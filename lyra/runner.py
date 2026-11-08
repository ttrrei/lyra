"""0006 — the run pipeline (`lyra run`).

Assembles 0004 (compiled signal SQL) + 0005 (per-bar trade engine) into a
reproducible, per-instrument evaluation with R5 metrics (0006 D4/I15), a
report, and a reproducibility manifest (D5/I5).  No sizing, no $ PnL, no
account equity (I9).  Per-instrument isolation (I16): each instrument is
processed in its own scope; one instrument's failure is recorded and does not
silently skew the others' completed aggregation.

Data model (0006 D3, verified against the real 0004/0005 contracts):
- ``compile_strategy(spec, registry) -> CompiledPlan`` whose ``sql`` is
  ``SELECT instrument, time, entry_long, entry_short, exit_long, exit_short
  FROM <view> ORDER BY instrument, time`` (one row per bar; booleans).
- The same ``<view>`` carries OHLC: ``mid_o/mid_h/mid_l/mid_c``.
- ``simulate(plan, bars, *, trading_days=None)`` takes **bars as a list of
  dicts** (``instrument/time/mid_*/entry_*/exit_*``) and returns ``Trade[]``
  whose net field is ``Trade.net_return``.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from . import compiler as compiler_mod
from . import features as features_mod
from . import metrics as metrics_mod
from . import strategy_schema as schema_mod
from .catalog import Catalog
from .trade_engine import Trade, simulate

_ENGINE_VERSION = "0006-v0.1"  # 0006 run-pipeline implementation version (manifest).


# ---------------------------------------------------------------------------
# Determinism helpers (D5/I5)
# ---------------------------------------------------------------------------

def _canonical(obj: Any) -> str:
    """Deterministic JSON (sorted keys, compact) for hashing (D5/I5)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(cwd: Path | None = None) -> str:
    """Short HEAD (+dirty marker).  Deterministic for a given tree state (M4)."""
    base = str(cwd) if cwd else None
    try:
        short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=base, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "no-git"
    try:
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=base, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        dirty = ""
    return f"{short}+dirty" if dirty else short


def _q(ident: str) -> str:
    """DuckDB identifier quoting (same safety rule as the 0004 compiler)."""
    if not ident or not all(ch.isalnum() or ch == "_" for ch in ident):
        raise ValueError(f"unsafe view identifier: {ident!r}")
    return '"' + ident + '"'


def _data_digest(con: duckdb.DuckDBPyConnection, view: str,
                 instruments: Sequence[str]) -> str:
    """Compact O(n) digest of the consumed (view, per-instrument OHLC).

    Feeds the manifest so a data perturbation changes ``run_id`` (I5).  O(n)
    over the bars actually consumed (light); deterministic for a fixed dataset.
    """
    h = hashlib.sha256()
    h.update(view.encode("utf-8"))
    for inst in sorted(instruments):
        h.update(b"|inst=" + inst.encode("utf-8"))
        rows = con.execute(
            f"SELECT time, mid_o, mid_h, mid_l, mid_c FROM {_q(view)} "
            f"WHERE instrument = ? ORDER BY time", [inst],
        ).fetchall()
        h.update(str(len(rows)).encode("utf-8"))
        for r in rows:
            h.update(repr(r).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    run_id: str
    out_dir: Path
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    trades: dict[str, list[Trade]] = field(default_factory=dict)
    bars_by_instrument: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    instrument_failures: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-instrument bar assembly
# ---------------------------------------------------------------------------

def _bars_for_instrument(
    con: duckdb.DuckDBPyConnection,
    view: str,
    instrument: str,
    signal_rows: Mapping[Any, tuple[bool, bool, bool, bool]],
) -> list[dict[str, Any]]:
    """Fetch an instrument's OHLC bars and attach the 0004 boolean signals.

    ``signal_rows`` maps ``time -> (entry_long, entry_short, exit_long,
    exit_short)``; the 0004 signal SQL emits one row per bar, so every bar
    resolves (missing -> all-FALSE, i.e. no entry/exit that bar).
    """
    rows = con.execute(
        f"SELECT time, mid_o, mid_h, mid_l, mid_c FROM {_q(view)} "
        f"WHERE instrument = ? ORDER BY time", [instrument],
    ).fetchall()
    bars: list[dict[str, Any]] = []
    for t, o, h_, l, c in rows:
        sig = signal_rows.get(t, (False, False, False, False))
        bars.append({
            "instrument": instrument,
            "time": t,
            "mid_o": o, "mid_h": h_, "mid_l": l, "mid_c": c,
            "entry_long": bool(sig[0]), "entry_short": bool(sig[1]),
            "exit_long": bool(sig[2]), "exit_short": bool(sig[3]),
        })
    return bars


# ---------------------------------------------------------------------------
# Artifact writers (deterministic row order; created-at excluded from run_id)
# ---------------------------------------------------------------------------

def _iso(x: Any) -> str:
    if isinstance(x, datetime):
        return x.isoformat(sep=" ")
    return str(x)


def _write_parquet(rows: Sequence[Mapping[str, Any]], path: Path,
                   columns: list[str], time_cols: set[str]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    data = {c: [r.get(c) for r in rows] for c in columns}
    for c in columns:
        if c in time_cols:
            data[c] = [_iso(v) for v in data[c]]
    table = pa.table({c: data[c] for c in columns})
    pq.write_table(table, path, compression="snappy")


def _json_safe(obj: Any) -> Any:
    """Coerce inf/NaN to None so the artifact stays valid JSON (H5)."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _write_json(obj: Any, path: Path) -> None:
    path.write_text(
        json.dumps(_json_safe(obj), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n", encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_strategy(
    strategy_path: str | Path,
    data_dir: str | Path,
    *,
    registry: Any,
    name: str | None = None,
    out_dir: str | Path | None = None,
    strict: bool = False,
    financing_days: float | None = None,
) -> RunResult:
    """Run one strategy end-to-end and write the 0006 run artifacts.

    - ``strategy_path``: the validated strategy YAML (0004).
    - ``data_dir``: the data root holding ``catalog.duckdb`` + feature Parquet
      (R6); the strategy's ``spec.view`` is read from it.
    - ``registry``: the 0004 feature registry (for parse/compile).
    - ``name``: run display name (defaults to the strategy id).
    - ``out_dir``: artifact root (defaults to ``~/.lyra/runs``; B13 out-of-repo).
    - ``strict``: raise if any instrument failed (I16); else record failures.
    - ``financing_days``: optional flat trading-day override for every trade
      (D6/O17; ``None`` = per-trade calendar days from bar timestamps).
    """
    strategy_path = Path(strategy_path)
    data_dir = Path(data_dir)

    # 1) parse + compile (0004) ---------------------------------------------
    spec = schema_mod.parse_strategy(strategy_path, registry)
    cat = Catalog(data_dir / "catalog.duckdb")
    if not cat.path.exists():
        raise FileNotFoundError(
            f"catalog not found at {cat.path}; run `lyra build` first (R6)."
        )
    feature_catalog_snapshot = json.dumps(
        sorted(cat.views(), key=lambda d: str(d.get("view"))),
        sort_keys=True, default=str,
    )
    plan = compiler_mod.compile_strategy(
        spec, registry, feature_catalog_snapshot=feature_catalog_snapshot,
    )

    # 2) signal SQL + per-instrument OHLC (I16 isolation) --------------------
    con = duckdb.connect(str(cat.path), read_only=True)
    try:
        signals = con.execute(plan.sql, list(plan.params)).fetchall()
        sig_by_inst: dict[str, dict[Any, tuple[bool, bool, bool, bool]]] = {}
        for (inst, t, el, es, xl, xs) in signals:
            sig_by_inst.setdefault(inst, {})[t] = (
                bool(el), bool(es), bool(xl), bool(xs),
            )
        instruments = sorted(sig_by_inst)

        # 3) per-instrument simulate + metrics (I7: never aggregate across) --
        result = RunResult(run_id="", out_dir=Path(out_dir) if out_dir
                           else _default_out(), instrument_failures=[])
        for inst in instruments:
            try:
                bars = _bars_for_instrument(con, plan.view, inst,
                                            sig_by_inst[inst])
                result.bars_by_instrument[inst] = bars
                trades = simulate(plan, bars, trading_days=financing_days)
                result.trades[inst] = trades
                if bars:
                    start_t, end_t = bars[0]["time"], bars[-1]["time"]
                else:
                    start_t = end_t = None
                result.metrics[inst] = metrics_mod.compute_metrics(
                    trades, start_t, end_t,
                )
            except Exception as exc:  # I16: record; do not silently skew others
                result.instrument_failures.append({
                    "instrument": inst,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        # 4) reproducibility manifest inputs (D5/I5; computed while conn open)
        data_digest = _data_digest(con, plan.view, instruments)
    finally:
        con.close()

    run_id = _compute_run_id(
        strategy_yaml_bytes=strategy_path.read_bytes(),
        plan_hash=plan.plan_hash,
        feature_version=features_mod.FEATURE_VERSION,
        compiler_version=plan.compiler_version,
        engine_version=_ENGINE_VERSION,
        duckdb_version=duckdb.__version__,
        params=_params_dict(plan),
        trading_days_override=financing_days,
        data_digest=data_digest,
        schema_version=spec.version,
        spec_id=spec.id,
        direction=spec.direction,
    )
    result.run_id = run_id

    # 5) write artifacts -----------------------------------------------------
    run_name = name or spec.id
    run_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    run_dir = Path(result.out_dir) / run_name / run_date
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_artifacts(run_dir, plan, spec, result, run_id, financing_days,
                     feature_catalog_snapshot)
    result.out_dir = run_dir

    if strict and result.instrument_failures:
        raise RuntimeError(
            "run failed on "
            + ", ".join(f["instrument"] for f in result.instrument_failures)
        )
    return result


def _default_out() -> Path:
    return Path.home() / ".lyra" / "runs"


def _params_dict(plan: Any) -> dict[str, Any]:
    return {
        "stop_loss_pct": plan.stop_loss_pct,
        "take_profit_pct": plan.take_profit_pct,
        "max_holding_bars": plan.max_holding_bars,
        "spread_bps": plan.spread_bps,
        "slippage_bps_per_side": plan.slippage_bps_per_side,
        "commission_bps_round_trip": plan.commission_bps_round_trip,
        "financing_bps_per_day": plan.financing_bps_per_day,
    }


def _compute_run_id(
    *,
    strategy_yaml_bytes: bytes,
    plan_hash: str,
    feature_version: int,
    compiler_version: str,
    engine_version: str,
    duckdb_version: str,
    params: dict[str, Any],
    trading_days_override: float | None,
    data_digest: str,
    schema_version: int,
    spec_id: str,
    direction: str | None,
) -> str:
    """Deterministic run identity (D5/I5): everything the output depends on,
    except ``generated_at`` (wall clock) — that is excluded so identical inputs
    always map to the same ``run_id``."""
    payload = {
        "strategy_yaml_sha256": _sha256_bytes(strategy_yaml_bytes),
        "spec_id": spec_id,
        "direction": direction,
        "schema_version": schema_version,
        "plan_hash": plan_hash,
        "params": params,
        "trading_days_override": trading_days_override,
        "feature_version": feature_version,
        "compiler_version": compiler_version,
        "engine_version": engine_version,
        "duckdb_version": duckdb_version,
        "data_digest": data_digest,
    }
    return _sha256_bytes(_canonical(payload).encode("utf-8"))


# ---------------------------------------------------------------------------
# Artifact output (D8 layout: signals / trades / metrics / report / manifest)
# ---------------------------------------------------------------------------

_TRADE_COLUMNS = [
    "instrument", "direction", "signal_time", "entry_time", "exit_time",
    "entry_price", "exit_price", "exit_reason", "bars_held",
    "gross_return", "cost_return", "net_return",
    "stop_price", "take_profit_price",
]
_SIGNAL_COLUMNS = ["instrument", "time", "entry_long", "entry_short",
                   "exit_long", "exit_short"]
_TIME_COLS_TRADE = {"signal_time", "entry_time", "exit_time"}
_TIME_COLS_SIGNAL = {"time"}


def _trades_rows(result: RunResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for inst in sorted(result.trades):
        for t in result.trades[inst]:
            d = t.__dict__.copy()
            rows.append({c: d.get(c) for c in _TRADE_COLUMNS})
    return rows


def _signals_rows(result: RunResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for inst in sorted(result.bars_by_instrument):
        for b in result.bars_by_instrument[inst]:
            rows.append({
                "instrument": b["instrument"],
                "time": b["time"],
                "entry_long": b["entry_long"], "entry_short": b["entry_short"],
                "exit_long": b["exit_long"], "exit_short": b["exit_short"],
            })
    rows.sort(key=lambda r: (r["instrument"], _iso(r["time"])))
    return rows


def _median(vals: list[float]) -> float:
    vals = sorted(vals)
    n = len(vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def _fmt(x: Any) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return "inf" if math.isinf(x) else f"{x:.6f}"
    return str(x)


def _write_report(path: Path, metrics_payload: dict[str, Any]) -> None:
    """R5 report: strategy name, timeframe, instruments, time window, feature
    snapshot id, git commit, date; per-instrument metrics (no CAGR/HWM/Sharpe/
    Sortino — R5/I9); per-month rows (I8: zero-open months kept as 0).

    The ``date`` line is the *data* window (deterministic) — R5's "日期" is the
    studied period, not the wall-clock run time.  The wall-clock generation
    stamp lives only in ``manifest.json``/``metrics.json`` (excluded from the
    I5 byte-reproducibility contract).
    """
    lines: list[str] = []
    lines.append(f"# Run report — {metrics_payload['spec_id']}")
    lines.append("")
    lines.append(f"- run_id: `{metrics_payload['run_id']}`")
    lines.append(f"- strategy: {metrics_payload['spec_id']}")
    lines.append(f"- direction: {metrics_payload['direction']}")
    lines.append(f"- timeframe: {metrics_payload['timeframe_minutes']}m "
                 f"(view {metrics_payload['view']})")
    lines.append("- instruments: "
                 + ", ".join(metrics_payload.get("instruments", [])))
    win = metrics_payload.get("window") or {}
    lines.append(f"- time window: {win.get('start', '—')} → {win.get('end', '—')}")
    lines.append(f"- feature snapshot id: `{metrics_payload.get('feature_snapshot_id', '—')}`")
    lines.append(f"- git commit: `{metrics_payload.get('git_commit', '—')}`")
    # R5 "日期" = the data window (deterministic); wall-clock is in manifest.
    lines.append(f"- date: {win.get('start', '—')} → {win.get('end', '—')} "
                 "(data window; generation time in manifest.json)")
    td = metrics_payload.get("trading_days_override")
    lines.append("- financing days: "
                 + ("per-trade calendar days" if td is None else f"flat {td}"))
    if metrics_payload.get("instrument_failures"):
        lines.append("- **instrument failures:**")
        for f in metrics_payload["instrument_failures"]:
            lines.append(f"  - {f['instrument']}: {f['error']}")
    lines.append("")
    lines.append("## Per-instrument metrics (R5; no CAGR/HWM/Sharpe/Sortino — I9)")
    lines.append("")
    lines.append("| instrument | trades | net sum | annualized | win% | expectancy | avg bars held |")
    lines.append("|---|---|---|---|---|---|---|")
    for inst in sorted(metrics_payload["per_instrument"]):
        m = metrics_payload["per_instrument"][inst]
        lines.append(
            f"| {inst} | {m['trade_count']} | {_fmt(m.get('net_return'))} | "
            f"{_fmt(m.get('annualized'))} | {m['win_rate']:.4f} | "
            f"{m['expectancy']:.6f} | {_fmt(m.get('avg_bars_held'))} |"
        )
    lines.append("")
    lines.append("## Per-month (actual openings; zero-open months kept — I8)")
    lines.append("")
    for inst in sorted(metrics_payload["per_instrument"]):
        m = metrics_payload["per_instrument"][inst]
        monthly = m.get("monthly", [])
        lines.append(f"### {inst}")
        lines.append("")
        lines.append("| month | openings | net sum | win% | avg bars held |")
        lines.append("|---|---|---|---|---|")
        for r in monthly:
            lines.append(
                f"| {r['month']} | {r['actual_entries']} | "
                f"{_fmt(r['net_return_sum'])} | {r['win_rate']:.4f} | "
                f"{_fmt(r['avg_bars_held'])} |"
            )
        lines.append("")
    lines.append("## Cross-instrument summary (min/median/max — NOT a portfolio, I7)")
    lines.append("")
    lines.append("| metric | min | median | max |")
    lines.append("|---|---|---|---|")
    for k, v in sorted(metrics_payload.get("summary", {}).items()):
        if isinstance(v, dict):
            lines.append(f"| {k} | {_fmt(v.get('min'))} | "
                         f"{_fmt(v.get('median'))} | {_fmt(v.get('max'))} |")
        else:
            lines.append(f"| {k} | — | — | — |")
    lines.append("")
    lines.append("*0006 trade-level research only (I9/R9): no sizing, no $ PnL, "
                 "no CAGR/HWM/Sharpe/Sortino.*")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _window(result: RunResult) -> dict[str, str]:
    """Study time window (min/max bar time across the run's instruments)."""
    start = end = None
    for bars in result.bars_by_instrument.values():
        if not bars:
            continue
        s, e = bars[0]["time"], bars[-1]["time"]
        start = s if start is None or s < start else start
        end = e if end is None or e > end else end
    return {"start": _iso(start) if start is not None else None,
            "end": _iso(end) if end is not None else None}


def _write_artifacts(
    run_dir: Path,
    plan: Any,
    spec: Any,
    result: RunResult,
    run_id: str,
    financing_days: float | None,
    feature_snapshot_id: str | None,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()

    # signals.parquet (per-bar signal matrix; deterministic instrument,time order)
    sig_rows = _signals_rows(result)
    if sig_rows:
        _write_parquet(sig_rows, run_dir / "signals.parquet",
                       _SIGNAL_COLUMNS, _TIME_COLS_SIGNAL)

    # trades.parquet (0005 output)
    trade_rows = _trades_rows(result)
    if trade_rows:
        _write_parquet(trade_rows, run_dir / "trades.parquet",
                       _TRADE_COLUMNS, _TIME_COLS_TRADE)

    # metrics.json: per-instrument (R5 set) + cross-instrument summary
    # (min/median/max — NOT synthesis, I7).
    metric_keys = ["net_return", "annualized", "win_rate", "expectancy",
                   "avg_bars_held", "trade_count"]
    summary: dict[str, Any] = {}
    for k in metric_keys:
        vals = [m[k] for m in result.metrics.values()
                if m.get(k) is not None
                and not (isinstance(m.get(k), float) and math.isinf(m.get(k)))]
        if vals:
            summary[k] = {"min": min(vals), "median": _median(vals),
                          "max": max(vals)}
        else:
            summary[k] = None
    result.summary = summary

    git_commit = _git_commit()
    window = _window(result)
    metrics_payload = {
        "run_id": run_id,
        "spec_id": spec.id,
        "direction": spec.direction,
        "view": plan.view,
        "timeframe_minutes": plan.timeframe_minutes,
        "trading_days_override": financing_days,
        "instruments": sorted(result.metrics),
        "window": window,
        "feature_snapshot_id": feature_snapshot_id,
        "git_commit": git_commit,
        "per_instrument": {i: result.metrics[i] for i in sorted(result.metrics)},
        "summary": summary,
        "instrument_failures": result.instrument_failures,
    }
    # metrics.json is fully deterministic (I5): no wall-clock field.  The
    # generation stamp lives only in manifest.json's ``generated_at``.  It is
    # NOT hashed into the manifest's artifact checksums for
    # reproducibility (I5): only the deterministic data artifacts
    # (trades/signals/report) and the run_id are the reproducibility contract.
    _write_json(metrics_payload, run_dir / "metrics.json")

    # report.md (R5) — deterministic (no wall-clock inside; I5 byte-repro).
    _write_report(run_dir / "report.md", metrics_payload)

    # manifest.json (D5/I5): written LAST so it can hash the other artifacts.
    manifest = {
        "run_id": run_id,
        "generated_at": generated_at,
        "spec_id": spec.id,
        "direction": spec.direction,
        "schema_version": spec.version,
        "view": plan.view,
        "timeframe_minutes": plan.timeframe_minutes,
        "params": _params_dict(plan),
        "trading_days_override": financing_days,
        "plan_hash": plan.plan_hash,
        "features_used": sorted(plan.features_used),
        "feature_snapshot_id": feature_snapshot_id,
        "feature_version": features_mod.FEATURE_VERSION,
        "compiler_version": plan.compiler_version,
        "engine_version": _ENGINE_VERSION,
        "duckdb_version": duckdb.__version__,
        "git_commit": git_commit,
        "window": window,
        "instrument_failures": result.instrument_failures,
        "artifacts": {},
    }
    for fname in ("signals.parquet", "trades.parquet", "report.md"):
        p = run_dir / fname
        if p.exists():
            manifest["artifacts"][fname] = _sha256_file(p)
    _write_json(manifest, run_dir / "manifest.json")
