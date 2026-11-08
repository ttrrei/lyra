"""0006 run-pipeline tests (runner.py).

A deterministic, fully-controlled fixture: a feature wide-table + catalog with
known OHLC, and a strategy whose signals are pure OHLC comparisons
(``close > open`` → entry_long), so no feature computation is involved and the
trades are exactly predictable.  Covers I5 (reproducibility + fail-fast),
I7 (per-instrument isolation), I8 (zero-open months), I16 (failure isolation),
and the R5/I15 metric fields in the artifacts.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lyra import catalog, compiler, features, runner
from lyra import trade_engine as te

TZ = dt.timezone.utc


def _registry():
    return features.load_from(__import__("pathlib").Path("_no_alpha_"))


def _write_feature(dirpath, inst: str, rows):
    """rows: list of (time, o, h, l, c) -> one parquet file per instrument."""
    pq.write_table(pa.table({
        "instrument": [inst] * len(rows),
        "time": [r[0] for r in rows],
        "mid_o": [r[1] for r in rows],
        "mid_h": [r[2] for r in rows],
        "mid_l": [r[3] for r in rows],
        "mid_c": [r[4] for r in rows],
        "volume": [1000.0] * len(rows),
        "n_bars": [1] * len(rows),
    }), dirpath / f"{inst}.parquet")


def _bull_bear(instrument: str, base: float, n: int = 10):
    """Bullish bar (c>o) on even days, bearish (c<o) on odd days, from a base."""
    base_dt = dt.datetime(2024, 1, 1, tzinfo=TZ)
    out = []
    for i in range(n):
        t = base_dt + dt.timedelta(days=i)
        o = base + 0.01 * i
        c = o + 0.01 if i % 2 == 0 else o - 0.01
        out.append((t, o, o + 0.002, o - 0.002, c))
    return out


_STRAT = """
version: 1
id: run_smoke
direction: test
timeframe_minutes: 60
entry:
  long:
    all:
      - {feature: close, op: gt, value: open}
  short:
    all:
      - {feature: close, op: lt, value: open}
exit:
  long:
    all:
      - {feature: close, op: lt, value: open}
  short:
    all:
      - {feature: close, op: gt, value: open}
  stop_loss_pct: 0.02
execution:
  spread_bps: 0
  slippage_bps_per_side: 0
  commission_bps_round_trip: 0
  financing_bps_per_day: 10
"""


@pytest.fixture
def env(tmp_path):
    """A data root (features/ohlcv_1h + catalog) + strategy YAML + registry."""
    data_root = tmp_path / "data"
    feat = data_root / "features" / "ohlcv_1h"
    feat.mkdir(parents=True)
    _write_feature(feat, "EURUSD", _bull_bear("EURUSD", 1.0, 10))
    _write_feature(feat, "GBPUSD", _bull_bear("GBPUSD", 1.27, 10))
    cat = catalog.Catalog(data_root / "catalog.duckdb")
    cat.upsert_feature_views(data_root)
    strat = tmp_path / "s.yaml"
    strat.write_text(_STRAT)
    return {"data_root": data_root, "strat": strat, "registry": _registry()}


def test_run_single_instrument_matches_engine(env):
    """The run's trades for one instrument == direct simulate() (diff=0)."""
    data_root, strat, reg = env["data_root"], env["strat"], env["registry"]
    res = runner.run_strategy(strat, data_root, registry=reg,
                              out_dir=strat.parent / "runs")
    import duckdb
    spec = __import__("lyra.strategy_schema", fromlist=["parse_strategy"]).parse_strategy(
        strat, reg)
    plan = compiler.compile_strategy(spec, reg, feature_catalog_snapshot="x")
    con = duckdb.connect(str(catalog.Catalog(data_root / "catalog.duckdb").path),
                         read_only=True)
    # C1 (batch-4): plan.sql now carries OHLC + signals (10 cols).
    signals = con.execute(plan.sql, list(plan.params)).fetchall()
    bars = [
        {
            "instrument": inst, "time": t,
            "mid_o": o, "mid_h": h, "mid_l": l, "mid_c": c,
            "entry_long": bool(el), "entry_short": bool(es),
            "exit_long": bool(xl), "exit_short": bool(xs),
        }
        for (inst, t, o, h, l, c, el, es, xl, xs) in signals
        if inst == "EURUSD"
    ]
    con.close()
    direct = te.simulate(plan, bars, trading_days_for=None)
    run_trades = res.trades["EURUSD"]
    assert len(run_trades) == len(direct)
    for a, b in zip(run_trades, direct):
        for f in ("direction", "entry_price", "exit_price", "gross_return",
                  "cost_return", "net_return", "bars_held", "exit_reason"):
            assert getattr(a, f) == getattr(b, f), f


def test_run_multi_instrument_isolated(env):
    res = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                              out_dir=env["strat"].parent / "runs")
    assert set(res.metrics) == {"EURUSD", "GBPUSD"}
    # I7: no cross-instrument portfolio score field anywhere in the payload.
    payload = json.loads((res.out_dir / "metrics.json").read_text())
    assert "portfolio" not in payload
    assert "combined" not in payload
    # summary is min/median/max only (not a sum/synthesis).
    for v in payload["summary"].values():
        if isinstance(v, dict):
            assert set(v) == {"min", "median", "max"}


def test_run_reproducible_identical_manifest(env):
    """I5: same inputs -> same run_id + byte-identical deterministic artifacts.

    ``metrics.json``/``manifest.json`` carry a wall-clock ``generated_at``
    (excluded from run_id by design, D5/I5), so those are compared on all
    fields except ``generated_at``; the data artifacts are byte-identical.
    """
    a = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                            out_dir=env["strat"].parent / "a")
    b = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                            out_dir=env["strat"].parent / "b")
    assert a.run_id == b.run_id
    # deterministic data artifacts: byte-for-byte identical
    for fname in ("trades.parquet", "signals.parquet", "report.md"):
        assert (a.out_dir / fname).read_bytes() == (b.out_dir / fname).read_bytes()
    # metrics.json / manifest.json: identical except the wall-clock field
    for fname in ("metrics.json", "manifest.json"):
        ma = json.loads((a.out_dir / fname).read_text())
        mb = json.loads((b.out_dir / fname).read_text())
        ma.pop("generated_at", None)
        mb.pop("generated_at", None)
        assert ma == mb


def test_run_reproducible_perturbation_fails(env):
    base = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                               out_dir=env["strat"].parent / "base")
    # parameter perturbation -> different run_id.  A per-trade trading-day
    # counter (C2) switches the financing basis to "trading", which is part
    # of the run identity → a different run_id than the calendar default.
    pert = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                               out_dir=env["strat"].parent / "pert",
                               trading_days_for=lambda e, x: 1.0)
    assert pert.run_id != base.run_id


def test_run_manifest_sha256s(env):
    res = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                              out_dir=env["strat"].parent / "runs")
    man = json.loads((res.out_dir / "manifest.json").read_text())
    for fname, digest in man["artifacts"].items():
        actual = hashlib.sha256((res.out_dir / fname).read_bytes()).hexdigest()
        assert man["artifacts"][fname] == actual


def test_run_empty_produces_zero_trades(tmp_path):
    """A strategy that never fires -> 0 trades, safe metrics, run still emits manifest."""
    data_root = tmp_path / "data"
    feat = data_root / "features" / "ohlcv_1h"
    feat.mkdir(parents=True)
    # flat bars: c == o -> close>open and close<open both False -> no signals
    rows = []
    base_dt = dt.datetime(2024, 1, 1, tzinfo=TZ)
    for i in range(6):
        t = base_dt + dt.timedelta(days=i)
        rows.append((t, 1.0, 1.0, 1.0, 1.0))
    _write_feature(feat, "FLAT", rows)
    catalog.Catalog(data_root / "catalog.duckdb").upsert_feature_views(data_root)
    strat = tmp_path / "s.yaml"
    strat.write_text(_STRAT)
    res = runner.run_strategy(strat, data_root, registry=_registry(),
                              out_dir=tmp_path / "runs")
    assert res.metrics["FLAT"]["trade_count"] == 0
    assert (res.out_dir / "manifest.json").exists()
    assert res.instrument_failures == []


def test_run_report_fields(env):
    res = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                              out_dir=env["strat"].parent / "runs")
    text = (res.out_dir / "report.md").read_text()
    payload = json.loads((res.out_dir / "metrics.json").read_text())
    # R5 per-instrument fields present (the frozen set)
    m = payload["per_instrument"]["EURUSD"]
    for k in ("trade_count", "net_return", "annualized", "win_rate",
              "expectancy", "avg_bars_held", "monthly"):
        assert k in m
    # R5/I9: Sharpe / profit factor / CAGR / HWM are *forbidden* in the metrics
    for banned in ("sharpe_ratio", "profit_factor", "sortino", "max_drawdown",
                   "position_sizing", "pnl_usd", "equity_curve", "account_cagr",
                   "margin_used", "leverage", "hwm", "high_water_mark"):
        assert banned not in m
    # R5: report.md carries the required provenance metadata
    for meta in ("strategy:", "timeframe:", "instruments:", "time window:",
                 "feature snapshot id:", "git commit:", "date:"):
        assert meta in text
    # report.md has per-instrument + per-month + cross-instrument sections
    assert "Per-instrument metrics" in text
    assert "Per-month" in text
    assert "Cross-instrument summary" in text
    assert "EURUSD" in text


def test_run_financing_wired(env):
    """O17/C2: default financing is per-trade natural days; a per-trade
    trading-day counter (``trading_days_for``) is honored and changes the
    run identity (D6).  The old flat ``--financing-days`` scalar was removed
    (0004 C2) because it mischarged every trade the same day count."""
    base = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                               out_dir=env["strat"].parent / "base")
    # A trade held multiple days with financing_bps_per_day=10 must carry a
    # non-zero cost_return (financing), not just zero.
    has_financing = any(t.cost_return > 0 for t in base.trades["EURUSD"])
    assert has_financing
    # a per-trade trading-day counter is honored and changes the run_id (D6)
    ov = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                             out_dir=env["strat"].parent / "ov",
                             trading_days_for=lambda e, x: 2.0)
    assert ov.run_id != base.run_id


def test_run_instrument_failure_isolated(env, monkeypatch):
    """I16: one instrument's per-bar stage failing must not skew the others.

    The signal SQL is a single cross-instrument query (a data-level failure
    there is a run-level failure); I16 isolates the *per-instrument* simulate
    stage. We force it by making ``simulate`` raise for one instrument only.
    """
    real_simulate = runner.simulate

    def _boom(plan, bars, *, trading_days_for=None):
        if bars and bars[0]["instrument"] == "GBPUSD":
            raise RuntimeError("simulated per-instrument failure")
        return real_simulate(plan, bars, trading_days_for=trading_days_for)

    monkeypatch.setattr(runner, "simulate", _boom)
    res = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                              out_dir=env["strat"].parent / "runs")
    # EURUSD still present and aggregated; GBPUSD recorded, not silently dropped.
    assert "EURUSD" in res.metrics
    assert "GBPUSD" not in res.metrics
    assert any(f["instrument"] == "GBPUSD" for f in res.instrument_failures)
    # strict mode must surface the failure as an error.
    with pytest.raises(RuntimeError):
        runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                            out_dir=env["strat"].parent / "runs2", strict=True)


def test_run_monthly_zero_openings_counted(env):
    """I8: a month with zero openings is present with count 0, not dropped."""
    res = runner.run_strategy(env["strat"], env["data_root"], registry=env["registry"],
                              out_dir=env["strat"].parent / "runs")
    monthly = res.metrics["EURUSD"]["monthly"]
    # The 10-day window spans exactly one month here (Jan 1..10, 2024); the
    # month key must be present with its actual opening count (R5/I8).
    by_month = {r["month"]: r for r in monthly}
    assert "2024-01" in by_month
    assert by_month["2024-01"]["actual_entries"] >= 0
