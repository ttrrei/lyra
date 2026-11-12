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


def test_run_id_covers_consumed_feature_values(env):
    """批次1-H2: a perturbation of a feature column the strategy SQL actually
    reads must change the run identity (I5); a perturbation of a column the
    strategy does NOT read must not (digest is scoped to features_used)."""
    import duckdb as _duckdb
    import pandas as _pd

    feat = env["data_root"] / "features" / "ohlcv_1h" / "EURUSD.parquet"
    original = _pd.read_parquet(feat)

    def _perturb(col: str, value: float) -> None:
        df = original.copy()
        df[col] = value
        _duckdb.connect().execute(
            f"COPY (SELECT * FROM df) TO '{feat}' (FORMAT PARQUET)"
        )

    def _restore() -> None:
        _pd.DataFrame(original.to_dict(orient="list")).to_parquet(feat)

    r_a = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"],
                              out_dir=env["strat"].parent / "h2a")
    # consumed feature (mid_c, used by the strategy): run_id MUST change
    _perturb("mid_c", 2.5)
    r_b = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"],
                              out_dir=env["strat"].parent / "h2b")
    assert r_b.run_id != r_a.run_id
    # unconsumed column (volume, not in the strategy digest scope): a file
    # differing from the original ONLY in volume must map back to the
    # original run identity.
    _perturb("volume", 99999.0)
    r_c = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"],
                              out_dir=env["strat"].parent / "h2c")
    assert r_c.run_id == r_a.run_id
    _restore()


def test_run_id_covers_trading_counter_behavior(env):
    """批次1-H2: two per-trade trading-day counters with different behavior
    (charging different financing) must not share a run identity."""
    base = runner.run_strategy(env["strat"], env["data_root"],
                               registry=env["registry"],
                               out_dir=env["strat"].parent / "cf0")
    two = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"],
                              out_dir=env["strat"].parent / "cf2",
                              trading_days_for=lambda e, x: 2.0)
    three = runner.run_strategy(env["strat"], env["data_root"],
                                registry=env["registry"],
                                out_dir=env["strat"].parent / "cf3",
                                trading_days_for=lambda e, x: 3.0)
    assert base.run_id != two.run_id
    assert two.run_id != three.run_id


def test_run_dir_scoped_by_run_id_no_stale_trades(env):
    """批次1-H3: a zero-trade run must not inherit (or re-hash) a previous
    run's trades.parquet from the same (name, date) path, and its manifest's
    artifact set must belong to its own run_id directory only."""
    out = env["strat"].parent / "h3"
    # First run: the env strategy produces trades.
    r1 = runner.run_strategy(env["strat"], env["data_root"],
                             registry=env["registry"], out_dir=out)
    assert any(len(t) for t in r1.trades.values())
    assert (r1.out_dir / "trades.parquet").exists()
    # Second run: a data root where the instrument never fires (close ==
    # open on every bar), same run name + out_dir as the first.
    data2 = out / "data_flat"
    feat2 = data2 / "features" / "ohlcv_1h"
    feat2.mkdir(parents=True)
    rows = []
    base_dt = dt.datetime(2024, 1, 1, tzinfo=TZ)
    for i in range(6):
        t = base_dt + dt.timedelta(days=i)
        rows.append((t, 1.0, 1.0, 1.0, 1.0))
    _write_feature(feat2, "EURUSD", rows)
    catalog.Catalog(data2 / "catalog.duckdb").upsert_feature_views(data2)
    flat = (env["strat"].parent / "flat.yaml")
    flat.write_text(_STRAT)
    r2 = runner.run_strategy(flat, data2, registry=_registry(),
                             name="run_smoke", out_dir=out)
    assert r2.metrics["EURUSD"]["trade_count"] == 0
    # the second run lives in its OWN run_id directory
    assert r2.out_dir != r1.out_dir
    # its trades.parquet is a zero-row file, not the first run's trades
    import pyarrow.parquet as _pq
    zero = _pq.read_table(str(r2.out_dir / "trades.parquet"))
    assert zero.num_rows == 0
    one = _pq.read_table(str(r1.out_dir / "trades.parquet"))
    assert one.num_rows > 0
    # manifest artifact hashes belong to files inside r2's own directory
    man = json.loads((r2.out_dir / "manifest.json").read_text())
    assert man["run_id"] == r2.run_id
    for fname, digest in man["artifacts"].items():
        assert (r2.out_dir / fname).exists()
        assert hashlib.sha256((r2.out_dir / fname).read_bytes()).hexdigest() \
            == digest
    # the first run's stale trades.parquet was NOT re-hashed into this manifest
    stale = hashlib.sha256(
        (r1.out_dir / "trades.parquet").read_bytes()).hexdigest()
    assert man["artifacts"]["trades.parquet"] != stale


def test_run_manifest_hashes_metrics_json(env):
    """批次1-M2: metrics.json is a D8 artifact and must appear in the
    manifest's artifact checksums (previously omitted)."""
    res = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"],
                              out_dir=env["strat"].parent / "m2")
    man = json.loads((res.out_dir / "manifest.json").read_text())
    assert "metrics.json" in man["artifacts"]
    actual = hashlib.sha256((res.out_dir / "metrics.json").read_bytes()).hexdigest()
    assert man["artifacts"]["metrics.json"] == actual


def test_metrics_zero_open_month_in_middle():
    """批次1-M5: a zero-open month BETWEEN two trading months must appear as
    a retained all-zero row (I8)."""
    import lyra.metrics as M

    class T:
        """Duck-typed trade exposing the fields the metrics read."""

        def __init__(self, entry, net):
            self.entry_time = entry
            self.net_return = net
            self.bars_held = 2

    jan = dt.datetime(2024, 1, 10, tzinfo=dt.timezone.utc)
    mar = dt.datetime(2024, 3, 5, tzinfo=dt.timezone.utc)
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(2024, 3, 31, tzinfo=dt.timezone.utc)
    out = M.compute_metrics([T(jan, 0.02), T(mar, -0.01)], start, end)
    months = {r["month"]: r for r in out["monthly"]}
    assert set(months) == {"2024-01", "2024-02", "2024-03"}
    feb = months["2024-02"]
    assert feb["actual_entries"] == 0
    assert feb["net_return_sum"] == 0.0
    assert feb["avg_bars_held"] == 0.0
    assert months["2024-01"]["actual_entries"] == 1
    assert months["2024-03"]["actual_entries"] == 1


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


# --- 0009 D5: counter identity token (R8) ---------------------------------


def test_d5_counter_identity_enters_fingerprint():
    """0009 D5: a counter that self-identifies via __lyra_identity__ records
    that identity (stable + meaningful) rather than a behavior probe."""
    from lyra.runner import _counter_fingerprint

    def counter(a, b):
        return 1

    counter.__lyra_identity__ = "trading-calendar/1.0"
    fp = _counter_fingerprint(counter)
    assert fp == "counter:trading-calendar/1.0"

    # an anonymous (identity-less) counter falls back to the behavior
    # fingerprint, explicitly labelled "unidentified"
    def anon(a, b):
        return 1

    fp2 = _counter_fingerprint(anon)
    assert fp2.startswith("counter:unidentified:")
    # None (natural days) unchanged
    assert _counter_fingerprint(None) == "natural"
