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
- ``simulate(plan, bars, *, trading_days_for=None)`` takes **bars as a list
  of dicts** (``instrument/time/mid_*/entry_*/exit_*``) and returns
  ``Trade[]``
  whose net field is ``Trade.net_return``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
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
from .trade_engine import Trade, TradingDaysCounter, simulate

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
    # Resolve the Lyra source tree, not the caller's current directory.
    base = str(cwd or Path(__file__).resolve().parents[1])
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
                 instruments: Sequence[str],
                 feature_cols: Sequence[str] = ()) -> str:
    """Compact O(n) digest of the consumed (view, per-instrument OHLC
    + strategy-consumed feature columns).

    Feeds the manifest so a data perturbation changes ``run_id`` (I5).
    批次1-H2: feature columns that the strategy SQL actually reads are part
    of the consumed data — perturbing only a feature value (OHLC unchanged)
    must change the run identity.  O(n) over the bars actually consumed
    (light); deterministic for a fixed dataset.
    """
    cols = ", ".join([_q(c) for c in feature_cols])
    h = hashlib.sha256()
    h.update(view.encode("utf-8"))
    for inst in sorted(instruments):
        h.update(b"|inst=" + inst.encode("utf-8"))
        if cols:
            sel = f"SELECT time, mid_o, mid_h, mid_l, mid_c, {cols}"
        else:
            sel = "SELECT time, mid_o, mid_h, mid_l, mid_c"
        rows = con.execute(
            f"{sel} FROM {_q(view)} WHERE instrument = ? ORDER BY time",
            [inst],
        ).fetchall()
        h.update(str(len(rows)).encode("utf-8"))
        for r in rows:
            h.update(repr(r).encode("utf-8"))
    return h.hexdigest()


def market_data_snapshot_id(con: duckdb.DuckDBPyConnection, view: str,
                            instruments: Sequence[str]) -> str:
    """Compact O(n) digest of the underlying market data (view + instruments
    + OHLC columns: time, mid_o, mid_h, mid_l, mid_c). Does NOT include
    strategy-consumed feature columns (Decision 0013).

    Used for horizontal comparability: runs consuming different features
    over the exact same market data share this ID and are judged comparable.
    """
    return _data_digest(con, view, instruments, feature_cols=())


_market_data_snapshot_id = market_data_snapshot_id


def _feature_layer_for_view(view: str) -> str | None:
    """Map a Catalog strategy view to its physical feature layer dir.

    Strategy views are ``features_5m`` / ``features_1h`` (catalog.py:37-38);
    the Parquet layers they read from are ``ohlcv_5m`` / ``ohlcv_1h``.
    """
    return {"features_5m": "ohlcv_5m", "features_1h": "ohlcv_1h"}.get(view)


def _generation_present(data_dir: str | Path, view: str) -> bool:
    """0009 D6: does the layer backing ``view`` have a generation manifest
    under ``features/<layer>/``?"""
    from .features import GENERATION_FILENAME

    layer = _feature_layer_for_view(view)
    if layer is None:
        return False
    return (Path(data_dir) / "features" / layer / GENERATION_FILENAME).exists()


def _validate_generation_for_view(data_dir: str | Path, view: str) -> None:
    """0009 D4 (H3 fail-closed gate): verify the generation manifest for the
    feature layer the strategy reads is consistent (sha + manifest exact)
    BEFORE any bar is read. Raises ``FeaturesError`` if the layer is mixed
    or stale. A layer with no manifest at all is the legacy state — the D6
    digest already flags it as ``legacy`` and the run proceeds (matching the
    pre-D4 data that was computed before the gate existed); a manifest that
    IS present but inconsistent is a hard failure."""
    from . import features as feat

    layer = _feature_layer_for_view(view)
    if layer is None:
        return
    layer_dir = Path(data_dir) / "features" / layer
    if not layer_dir.is_dir() or not feat.read_generation(layer_dir):
        return  # legacy / not computed — not a mixed-generation hazard
    # Manifest exists → enforce it (fail-closed on any mismatch).
    feat._validate_layer(layer_dir)


def _counter_fingerprint(trading_days_for: Any) -> str:
    """批次1-H2: behavioral fingerprint of the per-trade trading-day counter.

    Two run configurations that charge different financing (different
    counters) must not share a ``run_id``.  The fingerprint probes the
    counter with a fixed canonical pair (2024-01-01 → 2024-01-08, Monday
    start, crossing a weekend) and a same-day pair; the result values are
    part of the run identity.  Counters are anonymous callables so their
    *behavior* is the only stable identity available.
    """
    if trading_days_for is None:
        return "natural"
    import datetime as _dt

    # 0009 D5: a named/versioned counter self-identifies via
    # ``__lyra_identity__`` ("name/version"); the identity (not the behavior)
    # is what makes the fingerprint stable and meaningful.
    identity = getattr(trading_days_for, "__lyra_identity__", None)
    if identity and isinstance(identity, str) and identity.strip():
        return f"counter:{identity.strip()}"

    def _probe(a: _dt.datetime, b: _dt.datetime) -> str:
        try:
            v = trading_days_for(a, b)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("counter must return a number")
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv) or fv < 0:
                raise ValueError("counter returned an invalid day count")
            return repr(fv)
        except Exception as exc:  # a raising counter is also part of behavior
            return f"raised:{type(exc).__name__}"

    a = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)
    b = _dt.datetime(2024, 1, 8, tzinfo=_dt.timezone.utc)
    # No identity → behavior fingerprint only, explicitly labelled
    # "unidentified" (D5: two anonymous counters may collide here; an
    # identity-bearing counter never goes through this path).
    return f"counter:unidentified:{_probe(a, b)},{_probe(a, a)}"


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
    reused: bool = False


# ---------------------------------------------------------------------------
# Per-instrument bar assembly
# ---------------------------------------------------------------------------

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
    # P2-7 (UsageFinalReview): a zero-row result — or any run whose strategy
    # sets no stop / take-profit — must still emit a CONCRETE schema.  pa.table
    # infers column types from the VALUES, so an all-``None`` column produced a
    # ``null`` type (and an empty run produced an all-``null`` schema), which
    # downstream pd.read_parquet / DuckDB read as ``null`` columns — exactly the
    # case that most needs a stable contract.  We pin the explicit per-column
    # types uniformly (values are unchanged; only the declared type is forced),
    # so an empty run and a run with unset optional fields share one layout.
    schema_map = _TRADE_COL_TYPES if "direction" in columns else _SIGNAL_COL_TYPES
    arrays = [pa.array(data[c], type=pa.type_for_alias(schema_map.get(c, "string")))
              for c in columns]
    schema = pa.schema((c, a.type) for c, a in zip(columns, arrays))
    table = pa.Table.from_arrays(arrays, schema=schema)
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

def _load_complete_run(run_dir: Path, run_id: str, *,
                       require_run_meta: bool) -> RunResult:
    """Read a completed run only after validating its manifest checksums."""
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("run_id") != run_id:
            raise ValueError("manifest run_id does not match its directory")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            raise ValueError("manifest has no artifact checksum map")
        for name, expected in artifacts.items():
            path = run_dir / name
            if not path.is_file() or _sha256_file(path) != expected:
                raise ValueError(f"artifact {name!r} is missing or has a SHA mismatch")
        if require_run_meta:
            meta_path = run_dir / "run_meta.json"
            if not meta_path.is_file():
                raise ValueError("run_meta.json is missing")
            json.loads(meta_path.read_text(encoding="utf-8"))
        payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        if payload.get("run_id") != run_id:
            raise ValueError("metrics run_id does not match its directory")
        per_instrument = payload.get("per_instrument")
        if not isinstance(per_instrument, dict):
            raise ValueError("metrics has no per_instrument mapping")
        return RunResult(
            run_id=run_id,
            out_dir=run_dir,
            metrics=per_instrument,
            summary=payload.get("summary") or {},
            instrument_failures=payload.get("instrument_failures") or [],
            reused=True,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"existing run {run_id} is incomplete or invalid: {exc}") from exc


def _find_local_run(out_root: Path, run_name: str, run_id: str, *,
                    require_run_meta: bool) -> RunResult | None:
    """Find and validate a matching run across all UTC date directories."""
    named_root = out_root / run_name
    candidates = sorted(named_root.glob(f"*/{run_id}")) if named_root.is_dir() else []
    if not candidates:
        return None
    valid: list[RunResult] = []
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            raise RuntimeError(f"existing run {run_id} is incomplete or invalid: unsafe path")
        valid.append(_load_complete_run(candidate, run_id,
                                        require_run_meta=require_run_meta))
    fingerprints = []
    for result in valid:
        files = sorted(p for p in result.out_dir.rglob("*") if p.is_file())
        fingerprints.append({p.relative_to(result.out_dir).as_posix(): _sha256_file(p)
                             for p in files})
    if any(fp != fingerprints[0] for fp in fingerprints[1:]):
        paths = ", ".join(str(r.out_dir) for r in valid)
        raise RuntimeError(
            f"ambiguous existing run {run_id}: duplicate date directories have "
            f"different bytes ({paths}); preserve them and resolve manually"
        )
    return valid[0]


def _append_execution_audit(path: Path, result: RunResult, git_commit: str) -> None:
    """Best-effort local execution log, deliberately outside ``runs/``."""
    record = {
        "run_id": result.run_id,
        "run_path": str(result.out_dir),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "command_line": list(sys.argv),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"WARN: run execution audit could not be written: {exc}", file=sys.stderr)

def run_strategy(
    strategy_path: str | Path,
    data_dir: str | Path,
    *,
    registry: Any,
    name: str | None = None,
    out_dir: str | Path | None = None,
    strict: bool = False,
    trading_days_for: TradingDaysCounter | None = None,
    run_meta_payload: Mapping[str, Any] | None = None,
    require_run_meta: bool = False,
    audit_log_path: str | Path | None = None,
) -> RunResult:
    """Run one strategy end-to-end and write the 0006 run artifacts.

    - ``strategy_path``: the validated strategy YAML (0004).
    - ``data_dir``: the data root holding ``catalog.duckdb`` + feature Parquet
      (R6); the strategy's ``spec.view`` is read from it.
    - ``registry``: the 0004 feature registry (for parse/compile).
    - ``name``: run display name (defaults to the strategy id).
    - ``out_dir``: artifact root (defaults to ``~/.lyra/runs``; B13 out-of-repo).
    - ``strict``: raise if any instrument failed (I16); else record failures.
    - ``trading_days_for``: optional **per-trade** trading-day counter
      ``counter(entry_time, exit_time) -> float`` (D6/O17; ``None`` =
      per-trade natural/calendar days derived from bar timestamps, which is
      the default and the nova cross-check basis). The flat
      ``--financing-days`` scalar was removed (0004 C2, batch-4 review) — it
      mischarged every trade the same day count, so a real trading calendar
      must count each trade's held interval individually.
    """
    strategy_path = Path(strategy_path)
    data_dir = Path(data_dir)

    # 1) parse + compile (0004) ---------------------------------------------
    spec = schema_mod.parse_strategy(strategy_path, registry)
    cat = Catalog(data_dir / "catalog.duckdb")
    if not cat.path.exists():
        raise FileNotFoundError(
            f"catalog not found at {cat.path}; run `lyra features` first (R6)."
        )
    views_list = sorted(cat.views(), key=lambda d: str(d.get("view")))
    # 0009 D6: the snapshot is now a *data identity*, not just a name list —
    # it carries the 0009 D4 generation digest (per-file SHA256 map via
    # _generation.json) for the layer this strategy consumes. Absent
    # generation manifest (legacy data) → legacy marker, no full re-hash.
    feature_snapshot_id = features_mod.feature_snapshot_digest(data_dir)
    feature_catalog_snapshot = json.dumps(
        {
            "views": views_list,
            "feature_snapshot_digest": feature_snapshot_id,
            "digest_source": "generation_manifest" if _generation_present(data_dir, spec.view) else "legacy",
        },
        sort_keys=True, default=str,
    )
    plan = compiler_mod.compile_strategy(
        spec, registry, feature_catalog_snapshot=feature_catalog_snapshot,
    )

    # 0009 D4 (H3): fail-closed generation gate on the feature layer this
    # strategy reads, BEFORE any bar is read — a mixed/stale generation must
    # never be silently consumed into metrics or the run_id digest.
    _validate_generation_for_view(data_dir, spec.view)

    run_name = name or spec.id
    if name is not None:
        from .workflow import validate_ident
        validate_ident(run_name, "run name")
    output_root = Path(out_dir) if out_dir else _default_out()

    # Compute run identity before strategy SQL and simulation. This is the
    # point where a complete local cache hit can skip the backtest.
    identity_con = duckdb.connect(str(cat.path), read_only=True)
    try:
        identity_instruments = [r[0] for r in identity_con.execute(
            f"SELECT DISTINCT instrument FROM {_q(spec.view)} ORDER BY instrument"
        ).fetchall()]
        market_data_id = market_data_snapshot_id(
            identity_con, spec.view, identity_instruments,
        )
        data_digest = _data_digest(
            identity_con, spec.view, identity_instruments,
            feature_cols=plan.features_used,
        )
    finally:
        identity_con.close()
    run_id = _compute_run_id(
        strategy_yaml_bytes=strategy_path.read_bytes(),
        plan_hash=plan.plan_hash,
        feature_version=features_mod.FEATURE_VERSION,
        compiler_version=plan.compiler_version,
        engine_version=_ENGINE_VERSION,
        duckdb_version=duckdb.__version__,
        params=_params_dict(plan),
        trading_days_basis="trading" if trading_days_for else "calendar",
        counter_fingerprint=_counter_fingerprint(trading_days_for),
        data_digest=data_digest,
        feature_snapshot_digest=feature_snapshot_id,
        schema_version=spec.version,
        spec_id=spec.id,
        direction=spec.direction,
    )
    cached = _find_local_run(output_root, run_name, run_id,
                             require_run_meta=require_run_meta)
    if cached is not None:
        if strict and cached.instrument_failures:
            raise RuntimeError(
                "run failed on "
                + ", ".join(f["instrument"] for f in cached.instrument_failures)
            )
        return cached

    # 2) signal SQL + per-instrument OHLC (I16 isolation) --------------------
    con = duckdb.connect(str(cat.path), read_only=True)
    try:
        # C1 (batch-4): plan.sql now projects OHLC + signals, so the signal
        # rows carry everything simulate() needs — no second OHLC query.
        signals = con.execute(plan.sql, list(plan.params)).fetchall()
        bars_by_inst: dict[str, list[dict[str, Any]]] = {}
        for (inst, t, o, h, l, c, el, es, xl, xs) in signals:
            bars_by_inst.setdefault(inst, []).append({
                "instrument": inst, "time": t,
                "mid_o": o, "mid_h": h, "mid_l": l, "mid_c": c,
                "entry_long": bool(el), "entry_short": bool(es),
                "exit_long": bool(xl), "exit_short": bool(xs),
            })
        signal_instruments = sorted(bars_by_inst)
        if signal_instruments != identity_instruments:
            raise RuntimeError(
                "catalog instrument set changed while computing run identity; "
                "refusing to publish a run with a stale run_id"
            )
        instruments = identity_instruments

        # 3) per-instrument simulate + metrics (I7: never aggregate across) --
        result = RunResult(run_id=run_id, out_dir=output_root,
                           instrument_failures=[])
        for inst in instruments:
            try:
                bars = bars_by_inst[inst]
                result.bars_by_instrument[inst] = bars
                trades = simulate(plan, bars, trading_days_for=trading_days_for)
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

    finally:
        con.close()
    result.run_id = run_id

    # 5) write artifacts -----------------------------------------------------
    run_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    # 批次1-H3: every run gets its own run_id-scoped directory.  Reusing a
    # (name, date) directory across different run_ids would let a zero-trade
    # re-run inherit (and re-hash) a previous run's trades.parquet; scoping by
    # run_id makes each artifact set self-contained and verifiable against its
    # own manifest.
    run_dir = output_root / run_name / run_date / run_id
    if run_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing run directory: {run_dir}")
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".lyra-run-{run_id[:12]}-",
                                     dir=run_dir.parent) as temp:
        staged = Path(temp) / "run"
        staged.mkdir()
        _write_artifacts(staged, plan, spec, result, run_id, trading_days_for,
                         feature_catalog_snapshot, data_digest=data_digest,
                         market_data_snapshot_id=market_data_id)
        if run_meta_payload is not None:
            meta = dict(run_meta_payload)
            if meta.get("run_id") not in (None, run_id):
                raise RuntimeError("run_meta_payload has a different run_id")
            meta["run_id"] = run_id
            _write_json(meta, staged / "run_meta.json")
        try:
            os.rename(staged, run_dir)
        except OSError as exc:
            raise RuntimeError(
                f"could not publish run without overwriting {run_dir}: {exc}"
            ) from exc
    result.out_dir = run_dir
    if audit_log_path is not None:
        _append_execution_audit(Path(audit_log_path), result, _git_commit())

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
    trading_days_basis: str,
    counter_fingerprint: str,
    data_digest: str,
    feature_snapshot_digest: str,
    schema_version: int,
    spec_id: str,
    direction: str | None,
) -> str:
    """Deterministic run identity (D5/I5): everything the output depends on,
    except ``generated_at`` (wall clock) — that is excluded so identical inputs
    always map to the same ``run_id``.

    批次1-H2: ``counter_fingerprint`` captures the behavioral identity of the
    per-trade trading-day counter (two different counters must not share a
    run identity), and ``data_digest`` covers the strategy-consumed feature
    values, not just OHLC.
    """
    payload = {
        "strategy_yaml_sha256": _sha256_bytes(strategy_yaml_bytes),
        "spec_id": spec_id,
        "direction": direction,
        "schema_version": schema_version,
        "plan_hash": plan_hash,
        "params": params,
        "trading_days_basis": trading_days_basis,
        "counter_fingerprint": counter_fingerprint,
        "feature_version": feature_version,
        "compiler_version": compiler_version,
        "engine_version": engine_version,
        "duckdb_version": duckdb_version,
        "data_digest": data_digest,
        "feature_snapshot_digest": feature_snapshot_digest,
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

# P2-7 (UsageFinalReview): explicit per-column Parquet types.  ``pa.table``
# infers column types from the VALUES — so a zero-row result produced an all-
# ``null`` schema, and downstream ``pd.read_parquet`` / DuckDB read ``null``
# columns instead of the concrete types.  Pinning the schema guarantees a
# stable, concrete layout even when a run produces no rows.  Time columns are
# iso-string (they are converted by ``_iso`` before the array is built).
_TRADE_COL_TYPES = {
    "instrument": "string",
    "direction": "int64",
    "signal_time": "string",
    "entry_time": "string",
    "exit_time": "string",
    "entry_price": "float64",
    "exit_price": "float64",
    "exit_reason": "string",
    "bars_held": "int64",
    "gross_return": "float64",
    "cost_return": "float64",
    "net_return": "float64",
    "stop_price": "float64",
    "take_profit_price": "float64",
}
_SIGNAL_COL_TYPES = {
    "instrument": "string",
    "time": "string",
    "entry_long": "bool",
    "entry_short": "bool",
    "exit_long": "bool",
    "exit_short": "bool",
}


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


def _stop_trigger_rate(trades: list[Any]) -> float:
    """F-1: fraction of an instrument's trades stopped out (stop_loss/stop_gap).

    Lets a reader see at a glance whether the 2% stop was inactive (0%) or the
    main exit path, per instrument.  ``0.0`` when the instrument has no trades.
    """
    if not trades:
        return 0.0
    stops = sum(1 for t in trades
                if getattr(t, "exit_reason", None) in ("stop_loss", "stop_gap"))
    return stops / len(trades)


def _write_report(path: Path, metrics_payload: dict[str, Any], *,
                  git_commit: str | None = None) -> None:
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
    lines.append(f"- git commit: `{git_commit or metrics_payload.get('git_commit', '—')}`")
    # R5 "日期" = the data window (deterministic); execution time is local audit data.
    lines.append(f"- date: {win.get('start', '—')} → {win.get('end', '—')} "
                 "(data window)")
    basis = metrics_payload.get("trading_days_basis") or "calendar"
    lines.append("- financing day basis: " + ("trading days" if basis == "trading" else "calendar/natural days (default; R4/O15 trading-day basis is a future enhancement)"))
    costs = metrics_payload.get("costs_bps")
    if costs is not None:
        # F-3: the actual cost model applied, so a zero-cost backtest is
        # visible (and warn-able) rather than silently optimistic.
        # P0 (UsageFinalReview): an unspecified cost field is ``None`` (not 0)
        # — ``costs.get(k, 0.0)`` does NOT cover a present-but-None value, so
        # ``float(None)`` raised TypeError and the whole report crashed, leaving
        # the run without report.md / manifest.json.  _num() treats None as 0.
        def _num(v: Any) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        zero = all(_num(costs.get(k)) == 0.0
                   for k in ("commission_round_trip", "financing_per_day",
                             "spread", "slippage_per_side"))
        lines.append("- **cost model (bps):** commission_round_trip="
                     f"{_num(costs.get('commission_round_trip'))}, "
                     f"financing_per_day={_num(costs.get('financing_per_day'))}, "
                     f"spread={_num(costs.get('spread'))}, "
                     f"slippage_per_side={_num(costs.get('slippage_per_side'))}"
                     + ("  ⚠ **ALL ZERO — net returns are cost-free and optimistically biased**"
                        if zero else ""))
    # FIN-03 (UsageLastReview #2): disclose the quote model so a reader never
    # mistakes a mid+synthetic-spread backtest for a real bid/ask fill model.
    lines.append("- quote model: mid OHLC ± fixed spread_bps "
                 "(bid/ask branch exists in the engine but is NOT wired to the "
                 "runner feed — treat fills as a research assumption)")
    lines.append("- scope: trade-level per-instrument research — no sizing, "
                 "leverage, margin, account HWM/drawdown, or portfolio model "
                 "(I9)")
    if metrics_payload.get("instrument_failures"):
        lines.append("- **instrument failures:**")
        for f in metrics_payload["instrument_failures"]:
            lines.append(f"  - {f['instrument']}: {f['error']}")
    lines.append("")
    lines.append("## Per-instrument metrics (R5; no CAGR/HWM/Sharpe/Sortino — I9)")
    lines.append("")
    lines.append("| instrument | trades | net sum | annualized | win% | expectancy | avg bars held | stop% | low-sample |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    stop_rates = metrics_payload.get("stop_trigger_rate", {})
    for inst in sorted(metrics_payload["per_instrument"]):
        m = metrics_payload["per_instrument"][inst]
        # F-2 (cheap): a low-sample flag so readers don't over-trust a 3-trade
        # "win rate".  Threshold 20 is a conventional small-sample marker.
        low_sample = int(m.get("trade_count", 0)) < 20
        stop_rate = stop_rates.get(inst)
        stop_cell = (f"{stop_rate:.3f}" + (" (inactive)" if stop_rate == 0.0 else "")
                     if stop_rate is not None else "—")
        lines.append(
            f"| {inst} | {m['trade_count']} | {_fmt(m.get('net_return'))} | "
            f"{_fmt(m.get('annualized'))} | {m['win_rate']:.4f} | "
            f"{m['expectancy']:.6f} | {_fmt(m.get('avg_bars_held'))} | "
            f"{stop_cell} | {'⚠ <20 trades' if low_sample else ''} |"
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
    trading_days_for: TradingDaysCounter | None,
    feature_snapshot_id: str | None,
    data_digest: str | None = None,
    market_data_snapshot_id: str | None = None,
) -> None:

    # 批次1-M2: D8 lists signals.parquet + trades.parquet as required run
    # artifacts; even a zero-row result must emit them (with the fixed schema)
    # so downstream consumers can rely on a stable file layout.  批次1-H3:
    # the caller writes into a run_id-scoped directory, so an empty re-run
    # can never leave a stale trades.parquet from a previous run behind.
    sig_rows = _signals_rows(result)
    _write_parquet(sig_rows, run_dir / "signals.parquet",
                   _SIGNAL_COLUMNS, _TIME_COLS_SIGNAL)

    trade_rows = _trades_rows(result)
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
        "trading_days_basis": "trading" if trading_days_for else "calendar",
        "instruments": sorted(result.metrics),
        "window": window,
        "feature_snapshot_id": feature_snapshot_id,
        # 0009 D13 (H2) & 0013: per-run data identity — market_data_snapshot_id
        # (OHLC values, 0013 comparability) + data_digest (consumed features,
        # reproducibility) + feature_version (feature-code generation).
        "market_data_snapshot_id": market_data_snapshot_id,
        "data_digest": data_digest,
        "feature_version": features_mod.FEATURE_VERSION,
        "per_instrument": {i: result.metrics[i] for i in sorted(result.metrics)},
        "summary": summary,
        "instrument_failures": result.instrument_failures,
        # F-3 (UsageLastReview): the ACTUAL cost model applied, surfaced in the
        # report so a reader never silently trusts a zero-cost backtest.
        "costs_bps": {
            "commission_round_trip": plan.commission_bps_round_trip,
            "financing_per_day": plan.financing_bps_per_day,
            "spread": plan.spread_bps,
            "slippage_per_side": plan.slippage_bps_per_side,
        },
        # F-1: per-instrument stop trigger-rate (fraction stopped out), so a
        # 0% instrument is visibly "stop inactive" rather than an unnoticed bug.
        "stop_trigger_rate": {
            inst: _stop_trigger_rate(result.trades[inst])
            for inst in sorted(result.trades)
        },
    }
    # metrics.json is fully deterministic (I5): no wall-clock field.
    # 批次1-M2: metrics.json is a key consumed artifact — it IS hashed into
    # the manifest checksums (previously omitted, so tamper/corruption of the
    # primary output was undetectable).
    _write_json(metrics_payload, run_dir / "metrics.json")

    # report.md (R5) — deterministic (no wall-clock inside; I5 byte-repro).
    _write_report(run_dir / "report.md", metrics_payload, git_commit=git_commit)

    # manifest.json (D5/I5): written LAST so it can hash the other artifacts.
    manifest = {
        "run_id": run_id,
        "spec_id": spec.id,
        "direction": spec.direction,
        "schema_version": spec.version,
        "view": plan.view,
        "timeframe_minutes": plan.timeframe_minutes,
        "params": _params_dict(plan),
        "trading_days_basis": "trading" if trading_days_for else "calendar",
        "plan_hash": plan.plan_hash,
        "features_used": sorted(plan.features_used),
        "feature_snapshot_id": feature_snapshot_id,
        "feature_version": features_mod.FEATURE_VERSION,
        "market_data_snapshot_id": market_data_snapshot_id,
        "data_digest": data_digest,
        "compiler_version": plan.compiler_version,
        "engine_version": _ENGINE_VERSION,
        "duckdb_version": duckdb.__version__,
        "git_commit": git_commit,
        "window": window,
        "instrument_failures": result.instrument_failures,
        "artifacts": {},
    }
    # 批次1-M2: hash ALL D8 artifacts (incl. metrics.json); they were all
    # unconditionally written above, so existence is expected — fail closed
    # if one is missing rather than silently skipping its checksum.
    for fname in ("signals.parquet", "trades.parquet", "metrics.json",
                  "report.md"):
        p = run_dir / fname
        if not p.exists():
            raise RuntimeError(
                f"run artifact {fname!r} was not written; refusing to emit a "
                f"manifest with an incomplete artifact set (D8/M2)"
            )
        manifest["artifacts"][fname] = _sha256_file(p)
    _write_json(manifest, run_dir / "manifest.json")
