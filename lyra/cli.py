"""Typer CLI (decision 0002 §3.1): one user entry — ``lyra pull``.

``lyra clean`` / ``lyra aggregate`` are **debug entries** into the same
internal steps ``lyra pull`` runs, for inspection while developing.
"""

from __future__ import annotations


import math
import os
import shutil
import sys
import tempfile
import typer
from typing import Any

import duckdb
import yaml as _yaml

from pathlib import Path

from . import __version__, aggregate as agg, clean as clean_mod
from .config import (
    ConfigError,
    databackend_from_dict,
    load_config,
    local_from_dict,
    oci_from_dict,
    oanda_from_dict,
    resolve_data_root,
)
from . import pipeline

app = typer.Typer(help="Lyra research framework — data pipeline (0002).")


def _load(
    config: str | None,
    data_root: str | None,
):
    config_path = config or "config/config.yml"
    data = load_config(config_path)
    oci = oci_from_dict(data)
    local = local_from_dict(data)
    db = databackend_from_dict(data)
    root = resolve_data_root(local, data_root)
    return oci, root, db


@app.command()
def pull(
    config: str = typer.Option("config/config.yml", "--config", help="Path to config.yml"),
    data_root: str | None = typer.Option(None, "--data-root", help="Override the data root directory"),
) -> None:
    """Download raw archives (PAR, idempotent) then clean + aggregate (always recompute)."""
    try:
        oci, root, db = _load(config, data_root)
    except ConfigError as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    result = pipeline.run_pull(oci, root, db=db)
    typer.secho(f"raw zips : {len(result.raw_zips)}", fg=typer.colors.GREEN)
    typer.secho(f"raw csvs : {len(result.raw_csvs)}", fg=typer.colors.GREEN)
    typer.secho(f"bronze   : {result.bronze_rows} rows -> {result.bronze_path}", fg=typer.colors.GREEN)
    typer.secho(f"ohlcv_5m : {result.bars_5m} bars -> {result.ohlcv_5m_path}", fg=typer.colors.GREEN)
    typer.secho(f"ohlcv_1h : {result.bars_1h} bars -> {result.ohlcv_1h_path}", fg=typer.colors.GREEN)


@app.command()
def clean(
    config: str = typer.Option("config/config.yml", "--config"),
    data_root: str | None = typer.Option(None, "--data-root"),
) -> None:
    """DEBUG: re-run the clean step over the existing raw_csv/ (writes bronze, overwrites)."""
    import duckdb as _duckdb

    _, root, db = _load(config, data_root)
    csv_dir = root / "raw_csv"
    if not csv_dir.exists():
        typer.secho(f"no raw_csv/ at {csv_dir} — run `lyra pull` first", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    out = root / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv_dir, out, root, db)
    n = int(
        _duckdb.connect(":memory:")
        .execute("SELECT COUNT(*) FROM read_parquet(?)", [str(out)])
        .fetchone()[0]
    )
    typer.secho(f"cleaned {n} bronze rows -> {out}", fg=typer.colors.GREEN)


@app.command()
def aggregate(
    config: str = typer.Option("config/config.yml", "--config"),
    data_root: str | None = typer.Option(None, "--data-root"),
) -> None:
    """DEBUG: re-run the aggregate step over the existing bronze (overwrites 5m/1h)."""
    import duckdb as _duckdb

    _, root, db = _load(config, data_root)
    bronze = root / "all_data" / "all_data.parquet"
    if not bronze.exists():
        typer.secho(f"no bronze at {bronze} — run `lyra pull` first", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    p5 = root / "ohlcv_5m" / "ohlcv_5m.parquet"
    p1 = root / "ohlcv_1h" / "ohlcv_1h.parquet"
    agg.aggregate_bronze_to_parquet(bronze, p5, p1, root, db)
    n5, n1 = (
        _duckdb.connect(":memory:")
        .execute(
            "SELECT (SELECT COUNT(*) FROM read_parquet(?)), (SELECT COUNT(*) FROM read_parquet(?))",
            [str(p5), str(p1)],
        )
        .fetchone()
    )
    typer.secho(f"aggregated: {n5} 5m bars -> {p5}, {n1} 1h bars -> {p1}", fg=typer.colors.GREEN)


@app.command()
def catalog(
    config: str = typer.Option("config/config.yml", "--config"),
    data_root: str | None = typer.Option(None, "--data-root"),
    refresh: bool = typer.Option(False, "--refresh", help="Re-register views from the Parquet files"),
) -> None:
    """Show (or refresh) the DuckDB catalog views that reference the Parquet layers."""
    from .catalog import Catalog, default_catalog_path

    _, root, _db = _load(config, data_root)
    cat = Catalog(default_catalog_path(root))
    if refresh:
        from .catalog import upsert_views

        upsert_views(root, cat)
    views = cat.views()
    if not views:
        typer.secho(f"no catalog views at {cat.path} — run `lyra catalog --refresh` or `lyra pull`",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    for v in views:
        typer.secho(f"{v['view']:<10}", fg=typer.colors.GREEN)
    typer.echo(f"catalog file: {cat.path}")


@app.command()
def oanda(
    instrument: str = typer.Argument(..., help="OANDA instrument, e.g. GBP_USD"),
    from_t: str = typer.Option(..., "--from", help="UTC ISO-8601 start (inclusive)"),
    to: str = typer.Option(..., "--to", help="UTC ISO-8601 end (inclusive)"),
    config: str = typer.Option("config/config.yml", "--config"),
    data_root: str | None = typer.Option(None, "--data-root"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan without downloading"),
    force: bool = typer.Option(False, "--force", help="Re-fetch months that already have a CSV"),
) -> None:
    """Backfill / gap-fill a window of OANDA 1-min candles into raw_csv/<inst>/.

    Reads ``oanda.api_token`` from the config (a secret, never committed).
    After this, run ``lyra pull`` so clean+aggregate pick up the new CSVs.
    """
    from . import oanda as oanda_mod

    # 批次08 D6: a missing config file must not block a --dry-run preview —
    # fall back to OandaConfig defaults (no token needed for dry-run).
    try:
        data = load_config(config or "config/config.yml")
    except ConfigError:
        if dry_run:
            typer.secho(
                f"note: no readable config at {config!r}; using defaults "
                "(dry-run only — a real fetch needs oanda.api_token).",
                fg=typer.colors.YELLOW, err=True,
            )
            data = {}
        else:
            raise
    ocfg = oanda_from_dict(data)
    local = local_from_dict(data)
    root = resolve_data_root(local, data_root)
    csv_root = root / "raw_csv"

    if not ocfg.api_token and not dry_run:
        typer.secho(
            "oanda.api_token is empty — set it in config/config.yml (a secret, "
            "never committed). Use --dry-run to preview without a token.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)

    written = oanda_mod.backfill_window(
        csv_root,
        instrument,
        from_t,
        to,
        token=ocfg.api_token,
        host=ocfg.host,
        granularity=ocfg.granularity,
        price=ocfg.price,
        dry_run=dry_run,
        force=force,
    )
    typer.secho(f"wrote/resumed {len(written)} month CSV(s) under {csv_root}/{instrument}/",
                fg=typer.colors.GREEN)
    if not dry_run:
        typer.echo("next: run `lyra pull` to clean+aggregate the new CSVs.")


@app.command()
def features(
    config: str = typer.Option("config/config.yml", "--config"),
    data_root: str | None = typer.Option(None, "--data-root"),
    minutes: int = typer.Option(0, "--minutes", help="Timeframe: 5 or 60 (0 = both). 0003 K2: per-instrument wide tables."),
    instrument: str | None = typer.Option(None, "--instrument", help="Restrict to one instrument (debug); default = all in the data (K5)"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature directory (R3.2); default = config local.alpha (may be empty)"),
) -> None:
    """Compute the 0003 feature wide tables (always recompute + overwrite)."""
    from . import catalog as catmod
    from . import features as feat

    _, root, _db = _load(config, data_root)

    # Alpha extension point (R3.2 / I16): resolve from CLI or config, fall back
    # to an empty (non-existent) directory → core-only registry, unchanged (I16).
    if alpha_dir is None:
        try:
            data = load_config(config or "config/config.yml")
            local = local_from_dict(data)
            alpha_dir = getattr(local, "alpha", None) or ""
        except ConfigError:
            alpha_dir = ""
    alpha = Path(alpha_dir) if alpha_dir else Path(root) / "_no_alpha_dir_"
    reg = feat.load_from(alpha)

    frames = [5, 60] if minutes not in (5, 60) else [minutes]
    insts = [instrument] if instrument else None
    for m in frames:
        result = feat.run_features(root, m, reg, instruments=insts)
        typer.secho(f"features {m}m : {len(result.instruments)} instruments, "
                    f"{result.total_rows} rows → {result.paths[0].parent}", fg=typer.colors.GREEN)
        typer.echo(f"version_string = {result.version_string}")
    # D1: keep the named catalog entry points in sync with the new files.
    cat = catmod.upsert_views(root)
    made = cat.upsert_feature_views(root)
    if made:
        typer.echo(f"catalog views: {', '.join(made)}")


def _warn_zero_cost(plan: Any) -> None:
    """F-3 (UsageLastReview): warn (not block) when a strategy backtests with
    zero costs — such net returns are cost-free and optimistically biased.

    Spread/slippage are optional (a limit-order venue may genuinely have none),
    so the warning keys on the two near-universal costs: commission and
    financing.  Warning only — some research legitimately wants zero-cost
    signal quality, and this is a *review* concern, not a schema one.
    """
    zero = (float(plan.commission_bps_round_trip or 0.0) == 0.0
            and float(plan.financing_bps_per_day or 0.0) == 0.0)
    if zero:
        typer.secho(
            "WARN: zero-cost strategy (commission_bps_round_trip=0 AND "
            "financing_bps_per_day=0) — backtest net returns will be "
            "cost-free and optimistically biased. Set real bps before trusting "
            "the numbers.",
            fg=typer.colors.YELLOW, err=True)


@app.command()
def validate(
    strategy: str = typer.Argument(..., help="Path to a strategy YAML"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature directory (R3.2); default = config local.alpha (may be empty)"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Validate a strategy YAML (0004): schema + registry + timeframe + SQL codegen.

    Cheap pre-run check (0004 §3.1).  Does NOT execute the generated SQL.
    """
    from . import compiler as compiler_mod
    from . import strategy_schema as schema_mod

    reg = _registry_for(alpha_dir, config)
    try:
        spec = schema_mod.parse_strategy(strategy, reg)
        # M2 (batch-2 adversarial review): compile-stage errors
        # (e.g. an unregistered feature) surface as a clean INVALID line,
        # not a raw traceback.
        plan = compiler_mod.compile_strategy(spec, reg)
    except schema_mod.SchemaError as exc:
        typer.secho(f"INVALID: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # defensive: no raw tracebacks from malformed YAML
        typer.secho(f"INVALID: {type(exc).__name__}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"VALID: {spec.id} → view={spec.view} timeframe={spec.timeframe_minutes}m",
                fg=typer.colors.GREEN)
    typer.echo(f"features   : {', '.join(plan.features_used) or '(none)'}")
    typer.echo(f"stop_loss  : {plan.stop_loss_pct}  take_profit: {plan.take_profit_pct}")
    typer.echo(f"max_holding: {plan.max_holding_bars}  params: {list(plan.params)}")
    typer.echo(f"plan_hash  : {plan.plan_hash}")
    # F-3 (UsageLastReview): a zero-cost backtest is silently optimistic —
    # warn (don't block) so a reader/AI sees it before trusting the numbers.
    _warn_zero_cost(plan)


@app.command()
def compile(
    strategy: str = typer.Argument(..., help="Path to a strategy YAML"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature directory (R3.2)"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Compile a strategy YAML to past-only DuckDB signal SQL (0004 §3.1).

    Prints the SQL + bound parameters + summary for human inspection.  Does NOT
    execute the SQL or run the trade engine (0005).
    """
    from . import compiler as compiler_mod
    from . import strategy_schema as schema_mod

    reg = _registry_for(alpha_dir, config)
    try:
        spec = schema_mod.parse_strategy(strategy, reg)
        # M2 (batch-2 adversarial review): compile-stage errors are clean.
        plan = compiler_mod.compile_strategy(spec, reg)
    except schema_mod.SchemaError as exc:
        typer.secho(f"INVALID: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # defensive: no raw tracebacks from malformed YAML
        typer.secho(f"INVALID: {type(exc).__name__}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"-- strategy : {plan.strategy_id}")
    typer.echo(f"-- view     : {plan.view} ({plan.timeframe_minutes}m)")
    typer.echo(f"-- params   : {list(plan.params)}")
    typer.echo(f"-- stop     : {plan.stop_loss_pct}  tp: {plan.take_profit_pct}  mhb: {plan.max_holding_bars}")
    typer.echo(f"-- plan_hash: {plan.plan_hash}")
    _warn_zero_cost(plan)
    typer.echo("")
    typer.echo(plan.sql)


def _run_meta_payload(strategy_path: Path, track: str | None,
                      workspace_root: Path) -> dict[str, Any]:
    """Build the stable 0009 D2 attribution sidecar for a run.

    ``{direction, branch, track_id, spec_id, strategy_path, run_id}`` — the
    R12 workflow (``_runs_for_branch`` / ``compare_siblings``) reads this
    first, so run→direction/branch/track attribution no longer depends on
    spec_id naming conventions.
    """
    spec_id: object = None
    direction: object = None
    try:
        data = _yaml.safe_load(strategy_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            spec_id = data.get("id")
            direction = data.get("direction") or data.get("family")
    except Exception:
        pass
    # branch = the strategy file's own name (v01 / v04ab_1 / …); the R12
    # workflow's identity axis, NOT the spec id (directions_<name>).
    # 审查 #125 gap #5: this is now CORRECT end-to-end because ``submit`` adopts
    # the AI's strategy to the branch file (strategies/<dir>/<track>/v01.yaml)
    # BEFORE running it, so the filename IS the branch slug and the run is
    # attributable via run_meta (branch=v01, track_id=t_ai, spec_id=strategy id).
    # Running the AI's one-off file directly (``lyra run``) still attributes by
    # that file's name — use ``submit --track --branch`` for the canonical loop.
    branch = (strategy_path.name[:-5]
              if strategy_path.name.endswith(".yaml")
              else strategy_path.name)
    try:
        relative_strategy_path = os.path.relpath(
            strategy_path.resolve(), workspace_root.resolve(),
        )
    except (OSError, ValueError):
        relative_strategy_path = strategy_path.name
    payload = {
        "direction": direction,
        "branch": branch,
        "track_id": track,
        "spec_id": spec_id,
        "strategy_path": Path(relative_strategy_path).as_posix(),
    }
    return payload


def _fmt_num(v: Any, pct: bool = False) -> str:
    """Compact numeric formatter for the run digest (None → '—')."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isinf(f) or math.isnan(f):
        return "—"
    if pct:
        return f"{f * 100:.2f}%"
    return f"{f:.6g}"


def _print_run_digest(metrics: dict[str, dict[str, Any]],
                      instrument_failures: list[dict[str, Any]]) -> None:
    """审查#128 P0-1: the compact per-instrument decision table.

    The one thing a web-AI needs after a run — trades / annualized / win /
    net per instrument — without the ~90KB full report. Zero-trade months
    (annualized=None) render as '—', never a misleading 0.
    """
    hdr = f"{'instrument':<14}{'trades':>8}{'annualized':>12}{'win%':>9}{'net sum':>11}"
    typer.echo(hdr)
    typer.echo("─" * len(hdr))
    for inst in sorted(metrics):
        m = metrics[inst]
        typer.echo(
            f"{inst:<14}{m['trade_count']:>8}{_fmt_num(m.get('annualized')):>12}"
            f"{_fmt_num(m.get('win_rate'), pct=True):>9}{_fmt_num(m.get('net_return')):>11}"
        )
    for f in instrument_failures:
        typer.secho(f"  {f['instrument']}: FAILED — {f['error']}",
                    fg=typer.colors.YELLOW)


def _registry_for(alpha_dir: str | None, config: str):
    """Build the feature registry (core + optional alpha extension point, R3.2/I16)."""
    from . import features as feat
    from .config import ConfigError, load_config, local_from_dict

    if alpha_dir is None:
        try:
            data = load_config(config or "config/config.yml")
            local = local_from_dict(data)
            alpha_dir = getattr(local, "alpha", None) or ""
        except ConfigError:
            alpha_dir = ""
    alpha = Path(alpha_dir) if alpha_dir else Path("_no_alpha_dir_")
    return feat.load_from(alpha)


@app.command()
def run(
    strategy: str = typer.Argument(..., help="Path to a strategy YAML (0004)"),
    data_dir: str = typer.Option(..., "--data-dir", help="Data root with catalog.duckdb + feature Parquet (R6)"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature directory (R3.2); default = config local.alpha"),
    config: str = typer.Option("config/config.yml", "--config"),
    name: str | None = typer.Option(None, "--name", help="Run display name (default = strategy id)"),
    out: str | None = typer.Option(None, "--out", help="Artifact root (default <workspace>/runs; 0009 D2)"),
    strict: bool = typer.Option(False, "--strict", help="Fail if any instrument failed (I16)"),
    track: str | None = typer.Option(None, "--track", help="Research track id to attribute this run to (0009 D2 run_meta)"),
) -> None:
    """Run a strategy end-to-end (0006): signals -> trade engine -> metrics.

    Per-instrument evaluation (I7, no cross-instrument synthesis), R5 metrics,
    a reproducibility manifest (I5), and a report.  Trade-level research only
    (I9: no sizing / $ PnL / account equity).

    0009 D2: default artifact root is ``<workspace>/runs`` (0007 D7 canonical
    layout, same tree ``push-runs`` scans) instead of the legacy
    ``~/.lyra/runs``; a ``run_meta.json`` identity sidecar is written into
    the run directory so the R12 workflow can attribute the run to its
    direction / branch / track without relying on spec_id naming.
    """
    from . import runner as runner_mod
    from . import strategy_schema as schema_mod

    reg = _registry_for(alpha_dir, config)
    if out is None:
        ws = _workspace(config)
        out = str(ws / "runs")

    # M3 (审查#128): two tracks running the **same** YAML (same spec.id,
    # same data/runtime → same run_id) on the same day with no explicit
    # ``--name`` would produce the **same run_dir** (out/<spec.id>/<date>/<run_id>),
    # and the second track's ``run_meta.json`` would overwrite the first's
    # ``track_id`` — silently losing attribution. Fix: when ``--track`` is
    # set and ``--name`` is not, scope the run name by the track so each
    # track gets its own directory. An explicit ``--name`` always wins
    # (operator intent overrides auto-scoping).
    effective_name = name
    if effective_name is None and track is not None:
        try:
            _spec = schema_mod.parse_strategy(strategy, reg)
            effective_name = f"{_spec.id}__{track}"
        except Exception:
            pass  # will be caught by the schema check inside run_strategy

    try:
        # C2 (batch-4 review): the flat ``--financing-days`` scalar was
        # removed from the engine (it mischarged every trade the same day
        # count). The default is per-trade natural days; a real trading-day
        # calendar is a future enhancement (O17).
        result = runner_mod.run_strategy(
            strategy, data_dir, registry=reg, name=effective_name, out_dir=out,
            strict=strict,
            run_meta_payload=_run_meta_payload(
                Path(strategy), track, _workspace(config),
            ),
            require_run_meta=True,
            audit_log_path=_workspace(config) / "research-batches" / "run-executions.jsonl",
        )
    except schema_mod.SchemaError as exc:
        typer.secho(f"INVALID: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.secho(f"RUN FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except duckdb.Error as exc:
        # #132 (R-1/R-2): a first-use `submit`/`run` almost always hits a
        # duckdb.BinderException here (feature layer not yet computed), and
        # letting it escape prints a bare Rich traceback the AI cannot act on.
        # Surface the ACTUAL cause + the exact fix (the same hint `lyra doctor`
        # already knows), so the AI runs `lyra features` and retries. Genuinely
        # unexpected errors still propagate (this is the CLI boundary, not a
        # broad swallow).
        typer.secho(f"RUN FAILED: {exc}", fg=typer.colors.RED, err=True)
        typer.secho(
            "  Likely cause: the feature layer has not been computed for this "
            "data dir.\n"
            "  Fix: run `lyra features` (then `lyra catalog --refresh` if "
            "available), and retry with the SAME branch slug (the strategy is "
            "already valid and adopted — nothing to re-derive).\n"
            "  Verify with: `lyra doctor` (it reports feature-generation "
            "integrity).", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)

    # P1-3 (UsageFinalReview): with ``strict=False`` (the default), a run in
    # which EVERY instrument failed used to print green "OK: run …" and exit 0
    # — any automation wrapping `lyra run` would treat a total failure as
    # success.  When NO instrument produced metrics but some FAILED, this is a
    # hard failure: surface it as a clean non-zero exit (not a raw traceback).
    # A PARTIAL run (some instruments have metrics, others failed) deliberately
    # still returns, so ``submit``/``apply-batch`` can inspect
    # ``instrument_failures`` and report it as PARTIAL (exit 4) — that semantic
    # was fixed in #132 and is preserved.
    if result.instrument_failures and not result.metrics:
        names = ", ".join(f.get("instrument", "?") for f in result.instrument_failures)
        typer.secho(
            f"RUN FAILED: every instrument failed — {names}\n"
            "  No run was produced. Check the data/feature layer and the "
            "strategy's feature names (`lyra doctor`, `lyra features`).",
            fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if result.reused:
        typer.secho(f"reused existing run {result.run_id[:12]} -> {result.out_dir}",
                    fg=typer.colors.CYAN)
    else:
        typer.secho(f"OK: run {result.run_id[:12]} -> {result.out_dir}",
                    fg=typer.colors.GREEN)
    for inst in sorted(result.metrics):
        m = result.metrics[inst]
        typer.echo(f"  {inst}: {m['trade_count']} trades, "
                   f"annualized={m['annualized']}, win={m['win_rate']:.4f}")
    for f in result.instrument_failures:
        typer.secho(f"  {f['instrument']}: FAILED — {f['error']}",
                    fg=typer.colors.YELLOW)
    return result  # submit reads this to print the full report (gap #1)


@app.command(name="submit")
def submit(
    strategy: str = typer.Argument(..., help="Path to a strategy YAML (0004)"),
    data_dir: str = typer.Option(..., "--data-dir", help="Data root with catalog.duckdb + feature Parquet (R6)"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature directory (R3.2); default = config local.alpha"),
    config: str = typer.Option("config/config.yml", "--config"),
    name: str | None = typer.Option(None, "--name", help="Run display name (default = strategy id)"),
    out: str | None = typer.Option(None, "--out", help="Artifact root (default <workspace>/runs; 0009 D2)"),
    strict: bool = typer.Option(False, "--strict", help="Fail if any instrument failed (I16)"),
    track: str | None = typer.Option(None, "--track", help="Research track id to attribute this run to (0009 D2)"),
    branch: str | None = typer.Option(None, "--branch", help="Branch slug to register the strategy under (REQUIRED with --track, e.g. v04)."),
    report: str = typer.Option("digest", "--report", help="What to print after the run: digest (compact per-instrument table, default) | full (the whole report.md) | none (nothing; full is on disk)"),
) -> None:
    """One-step platform loop (H4 + 审查 #125 gaps #2/#5): validate -> adopt -> run.

    应用平台一步命令（web-AI 无 FS / 无 coding 闭环）：AI 写好 strategy YAML
    后，一条命令即完成"校验→(登记分支)→运行→完整报告"，无需再手工拆
    validate / new-version / track / context 多步。

    **阶段化、全程 fail-closed**：
    1. **校验先行**：INVALID 策略绝不进入引擎、也不登记任何分支（无半截状态）；
    2. **登记分支**（给了 ``--track`` 时）：把 AI 的 YAML 写为该 track 上该
       branch 的真实策略文件（gap #2：不再"骨架≠AI 策略"两个文件），并登记
       index（``--branch`` 是必需参数，见 D8.3）；
    3. **运行**：委托 ``run``（原样复用 --data-dir/--track/run_meta 语义）。
       run_meta 的 branch 记策略自身 ``id``（gap #5：不再按文件名猜），track
       记 ``--track`` —— 于是 ``context --track`` 能看到该分支的**真实策略 + 它的 run**。
    4. **完整报告**：打印该 run 的完整 report.md（gap #1：月表/跨品种读数直接
       进 stdout，AI 下一轮直接可看，不必再猜怎么读报告）。

    退出码：校验失败=1（不 run、不登记）；运行失败=1；成功=0。
    """
    from . import compiler as compiler_mod
    from . import strategy_schema as schema_mod
    from . import workflow as wf

    # Stage 1 — fail-closed validation (reuses validate's exact logic).
    reg = _registry_for(alpha_dir, config)
    try:
        spec = schema_mod.parse_strategy(strategy, reg)
        compiler_mod.compile_strategy(spec, reg)
    except schema_mod.SchemaError as exc:
        typer.secho(f"INVALID (not run): {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # defensive: no raw traceback for malformed YAML
        typer.secho(f"INVALID (not run): {type(exc).__name__}: {exc}",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"VALID: {spec.id} — proceeding", fg=typer.colors.GREEN)

    # Stage 2 — adopt as the track's branch (gap #2) when --track is given. The
    # run then targets the CANONICAL branch file, so its run_meta points at the
    # branch (not a one-off file). Fail-closed: a bad track/branch never runs.
    run_strategy_path = strategy
    if track is not None:
        # The branch slug must be explicit (v01/v02/…): the strategy's ``id``
        # (directions_<name>) is NOT a branch slug (0007 D2 identity), so we
        # fail-closed instead of silently adopting a non-slug branch name.
        if branch is None:
            typer.secho(
                "ERROR (not run): --track requires --branch <slug> (e.g. v01); "
                "the strategy's own id is not a branch slug.",
                fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        direction = spec.direction
        # #131 (self-check): a strategy YAML that omits BOTH `direction:` and
        # the legacy `family:` alias yields spec.direction=None, which previously
        # surfaced as the cryptic path-escape message "invalid direction None".
        # Fail with the ACTUAL cause and the fix, so a web-AI can self-correct
        # (do NOT guess from the file path — run_meta reads direction from the
        # file CONTENT, so a path-guess would silently corrupt attribution).
        if not direction:
            typer.secho(
                "ERROR (not run): the strategy YAML declares no direction — "
                "add a top-level `direction: <slug>` (or legacy `family: <slug>`) "
                "field (see the template in `lyra context <direction>`). "
                "Direction is required to place the branch and attribute the run.",
                fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        try:
            dest = wf.adopt_branch(_workspace(config), direction, track, branch,
                                   Path(strategy), spec)
        except wf.WorkflowError as exc:
            typer.secho(f"ERROR (not run): {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        typer.secho(f"adopted as {direction}/{track}/{branch} ({dest})",
                    fg=typer.colors.CYAN)
        run_strategy_path = str(dest)

    # Stage 3 — run end-to-end (delegates to the run command's logic).
    res = run(
        strategy=run_strategy_path, data_dir=data_dir, alpha_dir=alpha_dir,
        config=config, name=name, out=out, strict=strict, track=track,
    )

    # Stage 4 — surface the run result. 审查#128 P0-1 (report layering):
    # the full report.md for a 21-instrument run is ~90KB (~25k tokens) — a
    # web-AI paying that every iteration is exactly the token-burn the
    # low-token goal exists to avoid. Default to a COMPACT digest (the
    # per-instrument one-liner: trades / annualized / win / net) — the
    # decision signal. `--report full` still dumps the whole report.md; the
    # full report is ALWAYS on disk at res.out_dir/report.md regardless.
    if res is not None and report != "none":
        rpt = Path(res.out_dir) / "report.md"
        if report == "full":
            if rpt.exists():
                typer.secho("── full report (report.md) "
                            "────────────────────────────────", fg=typer.colors.CYAN)
                typer.echo(rpt.read_text(encoding="utf-8").rstrip())
        else:  # digest (default)
            typer.secho("── digest (per-instrument) "
                        "──────────────────────────────", fg=typer.colors.CYAN)
            try:
                _print_run_digest(res.metrics, res.instrument_failures)
            except Exception as exc:  # fall back to the full report if the digest is broken
                typer.secho(f"(digest unavailable: {exc} — printing full report)",
                            fg=typer.colors.YELLOW)
                if rpt.exists():
                    typer.echo(rpt.read_text(encoding="utf-8").rstrip())
        typer.echo(f"full report on disk: {Path(res.out_dir) / 'report.md'}  "
                   f"(re-print with `lyra report {res.out_dir}` or read the file)")


@app.command(name="apply-batch")
def apply_batch_cmd(
    batch_file: str = typer.Argument(..., help="Path to a batch bundle YAML (D6)"),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Data root (required with --run)"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature dir; default = config local.alpha"),
    config: str = typer.Option("config/config.yml", "--config"),
    run_it: bool = typer.Option(False, "--run", help="Also run each adopted branch (default: adopt only)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse + validate only; write NOTHING (the coding AI's preview)"),
) -> None:
    """Apply a multi-direction proposal bundle in one command (审查#128 D6).

    The web/chat AI writes ONE file (a ``directions:`` list, each item a
    direction/track/branch + full strategy YAML) and the coding-AI runs this
    — no hand-written per-file plumbing. Fail-closed, staged:

      1. **parse**  — malformed bundle → error, nothing else.
      2. **validate** — EVERY item is parsed + compiled. If ANY item is
         invalid, the WHOLE batch is rejected and no strategy branch is written — the
         web-AI's "3 proposed, 1 bad" never becomes a half-applied state.
      3. **adopt**  — each valid item becomes the track's branch (M1
         immutable: re-proposing an existing branch with different content
         is refused).
      4. **run**    — with ``--run``, each adopted branch is executed
         (a single run failure is recorded, the rest continue).

    ``--dry-run`` stops after stage 2 (the coding AI previews what would
    happen without touching the filesystem).
    """
    from . import batch as batch_mod
    from . import compiler as compiler_mod
    from . import strategy_schema as schema_mod
    from . import workflow as wf

    try:
        text = Path(batch_file).read_text(encoding="utf-8")
    except OSError as exc:
        typer.secho(f"ERROR: cannot read bundle: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    try:
        items = batch_mod.parse_batch(text)
    except batch_mod.BatchError as exc:
        typer.secho(f"ERROR (batch malformed): {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # P3: every research batch has one direction/track and 3–4 candidates.
    # Preserve a real rejected attempt when its archive target is identifiable.
    archive_target = (items[0].direction, items[0].track)
    archive_lines: list[str] = []

    def _archive_attempt() -> None:
        if dry_run:
            return
        try:
            path = wf.archive_batch_attempt(
                _workspace(config), archive_target[0], archive_target[1], text,
                "# Batch result\n\n" + "\n".join(archive_lines) + "\n")
            typer.echo(f"batch archive: {path}")
        except Exception as exc:
            typer.secho(f"WARN: batch archive could not be written: {exc}",
                        fg=typer.colors.YELLOW, err=True)

    reg = _registry_for(alpha_dir, config)
    ws = _workspace(config)
    tmp = tempfile.TemporaryDirectory()

    # --- Stage 2: validate ALL items first (all-or-nothing) --------------
    # Write every item to a temp path and parse+compile; collect ALL errors
    # before deciding. A single invalid item rejects the whole batch.
    #
    # #131 (P-5/B4): the bundle carries provenance at the ITEM level (parent /
    # driven_by_lesson / hypothesis) as a web-AI convenience. Previously those
    # fields were only used to feed the R12 gate and then DISCARDED — the file
    # written to disk had no lineage. Now ``_merged_strategy_text`` folds them
    # into the strategy text BEFORE adoption, so the on-disk branch file (and
    # the OCI copy) carries the full lineage, and the lineage gate reads the
    # SAME text that gets written (no drift between gate input and artifact).
    # This also normalises a mapping-form ``strategy:`` (P-4/B7) into lossless
    # YAML via safe_dump.
    def _merged_strategy_text(it: batch_mod.BatchItem) -> str:
        try:
            data = _yaml.safe_load(it.strategy_text)
        except Exception:
            data = None
        if not isinstance(data, dict):
            # Not a parseable mapping — leave the text as-is; stage-2's
            # parse_strategy will surface the real error.
            return it.strategy_text
        if it.parent:
            parents = list(data.get("parents") or [])
            if isinstance(data.get("parent"), str):
                parents.append(data["parent"])
                data.pop("parent", None)
            if it.parent not in parents:
                parents.append(it.parent)
            data["parents"] = parents
        if it.driven_by_lesson:
            data["driven_by_lesson"] = it.driven_by_lesson
        if it.hypothesis and not data.get("hypothesis"):
            data["hypothesis"] = it.hypothesis
        return _yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    resolved: list[tuple[batch_mod.BatchItem, Path, Any]] = []
    errors: list[tuple[batch_mod.BatchItem, str]] = []
    for it in items:
        p = Path(tmp.name) / f"item{it.index}.yaml"
        final_text = _merged_strategy_text(it)
        p.write_text(final_text, encoding="utf-8")
        try:
            spec = schema_mod.parse_strategy(str(p), reg)
            compiler_mod.compile_strategy(spec, reg)
            resolved.append((it, p, spec))
        except Exception as exc:  # SchemaError / compile error / any
            errors.append((it, f"{type(exc).__name__}: {exc}"))
    if errors:
        tmp.cleanup()
        archive_lines.extend([f"- Proposed: {len(items)}",
                              f"- Preflight rejected: {len(errors)}"])
        archive_lines.extend(f"- Rejected {it.direction}/{it.track}/{it.branch}: {err}"
                             for it, err in errors)
        archive_lines.append("- Adopted: 0")
        archive_lines.extend(["- Run counts: OK=0, PARTIAL=0, FAILED=0 (not started)",
                              "- Run IDs: none (preflight rejected)",
                              "- Branch decisions: pending author review"])
        for it, err in errors:
            typer.secho(f"[INVALID] {it.direction}/{it.track}/{it.branch}: {err}",
                        fg=typer.colors.RED, err=True)
        typer.secho("── batch summary ──────────────────────────────────────────",
                    fg=typer.colors.CYAN)
        typer.secho(f"0 adopted — {len(errors)} invalid of {len(items)}; no strategy "
                    "branches written (all-or-nothing, D6)", fg=typer.colors.RED)
        _archive_attempt()
        raise typer.Exit(code=1)

    # E1: compare normalized execution costs against the shared direction v01
    # and across all candidates. None and explicit zero are distinct here.
    cost_fields = ("spread_bps", "slippage_bps_per_side",
                   "commission_bps_round_trip", "financing_bps_per_day")
    cost_errors: list[tuple[batch_mod.BatchItem, str]] = []
    baseline_path = ws / "strategies" / archive_target[0] / "v01.yaml"
    try:
        if not baseline_path.is_file():
            raise FileNotFoundError(f"direction baseline not found: {baseline_path}")
        baseline_spec = schema_mod.parse_strategy(str(baseline_path), reg)
        baseline_costs = tuple(getattr(baseline_spec.execution, f) for f in cost_fields)
    except Exception as exc:
        baseline_costs = None
        cost_errors.append((items[0], f"cannot read/validate v01 cost baseline: {exc}"))
    candidate_costs = [tuple(getattr(spec.execution, f) for f in cost_fields)
                       for _it, _p, spec in resolved]
    if baseline_costs is not None:
        for (it, _p, _spec), costs in zip(resolved, candidate_costs):
            if costs != baseline_costs:
                diffs = [f"{name}: candidate={got!r}, baseline={want!r}"
                         for name, got, want in zip(cost_fields, costs, baseline_costs)
                         if got != want]
                cost_errors.append((it, "execution costs differ from shared v01 baseline; "
                                         "copy the four fields exactly (including omitted vs 0): "
                                         + "; ".join(diffs)))
        if candidate_costs and any(costs != candidate_costs[0]
                                   for costs in candidate_costs[1:]):
            cost_errors.append((items[0], "candidates in this batch have different execution "
                                         "cost fields; make all four values identical"))
    if not cost_errors and candidate_costs and all(
            value in (None, 0.0) for value in candidate_costs[0]):
        typer.secho("WARN: all four execution cost fields are zero or unset; "
                    "returns may be optimistically biased", fg=typer.colors.YELLOW,
                    err=True)

    # --- Stage 2.5: FULL preflight (all predictable failures, zero writes) --
    # #131 (P0-3 / P-6 / P-7 / P1-2 / B3 / B6-T10): move every check that can
    # be predicted from the bundle + current workspace state to BEFORE any
    # adopt writes — so `--dry-run` and a real apply share the SAME gate, and
    # "dry-run all VALID" can no longer be followed by "real apply half-fails".
    #  1. --run requires --data-dir (B6-T10: no longer adopted-then-errored)
    #  2. direction/track/branch are safe single path components (P0-4)
    #  3. track exists
    #  4. spec.direction == item.direction (P1-2 / B3: no cross-direction
    #     mis-file: the file lands in item.direction but run_meta uses
    #     spec.direction, which would corrupt per-direction attribution)
    #  5. lineage (parent resolves + driven_by_lesson non-empty, R12)
    #  6. per (direction, track) cap: count NEW branches (skip idempotent
    #     re-submits of an existing byte-identical file) (P-6 cap half-state)
    #  7. no duplicate (direction, track, branch) within the batch (P-7)
    if run_it and data_dir is None:
        tmp.cleanup()
        archive_lines.extend([f"- Proposed: {len(items)}", "- Preflight rejected: 1",
                              "- Rejected: --run requires --data-dir",
                              "- Adopted: 0",
                              "- Run counts: OK=0, PARTIAL=0, FAILED=0 (not started)",
                              "- Run IDs: none (--run rejected before adoption)",
                              "- Branch decisions: pending author review"])
        typer.secho("ERROR: --run requires --data-dir (checked before any "
                    "writes; nothing was adopted).", fg=typer.colors.RED, err=True)
        _archive_attempt()
        raise typer.Exit(code=2)

    def _branch_dest(it):
        return ws / "strategies" / it.direction / it.track / f"{it.branch}.yaml"

    pre_errors: list[tuple[batch_mod.BatchItem, str]] = []
    pre_errors.extend(cost_errors)
    candidate_analysis: list[str] = []
    active_specs: list[tuple[str, dict[str, Any]]] = []
    try:
        active_names = wf._track_active(ws, archive_target[0], archive_target[1])
    except Exception:
        active_names = []
    for active in active_names:
        active_path = (ws / "strategies" / archive_target[0] / archive_target[1]
                       / f"{active}.yaml")
        if not active_path.is_file():
            active_path = ws / "strategies" / archive_target[0] / f"{active}.yaml"
        try:
            active_spec = schema_mod.parse_strategy(str(active_path), reg)
            active_specs.append((active, schema_mod.structural_signature(active_spec, reg)))
        except Exception:
            continue
    for it, _p, spec in resolved:
        sig = schema_mod.structural_signature(spec, reg)
        complexity = schema_mod.ast_complexity(spec)
        relations = [(branch, schema_mod.compare_structural_signatures(sig, other))
                     for branch, other in active_specs]
        if relations:
            rank = {"identical": 0, "parameter_only": 1, "structural_change": 2}
            nearest_branch, nearest = min(
                relations, key=lambda pair: rank[pair[1]["classification"]])
            relation_text = f"{nearest['classification']} vs {nearest_branch}"
            if nearest["classification"] == "parameter_only":
                relation_text = f"≈param-variant of {nearest_branch}"
            if nearest["exit_structure_changed"]:
                relation_text += " (exit_structure_changed)"
        else:
            relation_text = "no active sibling baseline"
        candidate_analysis.append(
            f"{it.direction}/{it.track}/{it.branch}: {relation_text}; "
            f"complexity={complexity}")
    for it, p, spec in resolved:
        def _err(msg):
            pre_errors.append((it, msg))
        try:
            wf.validate_ident(it.direction, "direction")
            wf.validate_ident(it.track, "track")
            wf.validate_ident(it.branch, "branch")
            # P2-5: fullmatch (validate_ident already enforces this; kept for the
            # vNN-specific pattern message).
            if not wf._BRANCH_NAME_RE.fullmatch(it.branch):
                _err(f"branch {it.branch!r} must match the vNN slug pattern")
                continue
            wf.get_track(ws, it.direction, it.track)          # track must exist
            # DEV-03/RED-05 (UsageLastReview #2): the strategy YAML MUST declare
            # its own direction — do NOT let the outer item.direction stand in.
            # `spec.direction=None` (no `direction:` and no legacy `family:`)
            # used to pass this check silently, so the branch was placed under
            # item.direction but run_meta read direction from the (empty) file
            # → None, corrupting per-direction attribution. Fail-closed, matching
            # the single-`submit` path.
            if not spec.direction:
                _err(f"strategy YAML declares no direction — add a top-level "
                     f"`direction: {it.direction}` (or legacy `family:`); the "
                     f"outer item.direction cannot stand in for it")
                continue
            if spec.direction != it.direction:
                _err(f"item.direction={it.direction!r} but the strategy YAML "
                     f"declares direction={spec.direction!r} — they must match")
                continue
            wf._validate_new_branch_lineage(
                ws, it.direction, it.track, it.branch, spec)   # R12 lineage
        except wf.WorkflowError as exc:
            _err(str(exc))

    # per-track NEW-branch cap: a NEW branch is one whose dest file does not
    # already exist (idempotent re-submits of an existing file consume no slot)
    new_by_track: dict[tuple[str, str], int] = {}
    for it, p, spec in resolved:
        if not _branch_dest(it).exists():
            key = (it.direction, it.track)
            new_by_track[key] = new_by_track.get(key, 0) + 1
    for (dname, tid), n_new in new_by_track.items():
        if n_new == 0:
            continue
        try:
            # RED-02 (UsageLastReview #2): track_index_path now validates the
            # direction/track and asserts workspace containment, so a bad key
            # that slipped through the per-item preflight (which normally
            # catches it and exits) becomes a clean preflight error here
            # instead of an uncaught exception.
            cur = wf.count_active_branches(ws, dname, tid)
        except wf.WorkflowError as exc:
            for it, p, spec in resolved:
                if (it.direction, it.track) == (dname, tid):
                    pre_errors.append((it, str(exc)))
            continue
        if cur + n_new > wf.MAX_ACTIVE_BRANCHES_PER_TRACK:
            for it, p, spec in resolved:
                if (it.direction, it.track) == (dname, tid) and \
                        not _branch_dest(it).exists():
                    pre_errors.append((it, f"track {dname}/{tid} would exceed "
                        f"the {wf.MAX_ACTIVE_BRANCHES_PER_TRACK}-branch cap "
                        f"(currently {cur}, +{n_new} new) — prune one first"))
            break
    # duplicate (direction, track, branch) within the same bundle (P-7)
    seen_targets: set[tuple[str, str, str]] = set()
    for it, p, spec in resolved:
        tgt = (it.direction, it.track, it.branch)
        if tgt in seen_targets:
            pre_errors.append((it, f"duplicate target {it.direction}/"
                f"{it.track}/{it.branch} appears more than once in this batch"))
        seen_targets.add(tgt)

    if not 3 <= len(items) <= 4:
        pre_errors.append((items[0],
                           f"batch has {len(items)} candidates; expected 3–4"))
    if len({(it.direction, it.track) for it in items}) != 1:
        pre_errors.append((items[0],
                           "all candidates must share one direction and track"))

    if pre_errors:
        tmp.cleanup()
        archive_lines.extend([f"- Proposed: {len(items)}",
                              f"- Preflight rejected: {len(pre_errors)}"])
        archive_lines.extend(f"- Rejected {it.direction}/{it.track}/{it.branch}: {err}"
                             for it, err in pre_errors)
        archive_lines.append("- Adopted: 0")
        archive_lines.extend(["- Run counts: OK=0, PARTIAL=0, FAILED=0 (not started)",
                              "- Run IDs: none (preflight rejected)",
                              "- Branch decisions: pending author review"])
        for it, err in pre_errors:
            typer.secho(f"[INVALID] {it.direction}/{it.track}/{it.branch}: {err}",
                        fg=typer.colors.RED, err=True)
        typer.secho("── batch summary (preflight FAILED) ──────────────────────",
                    fg=typer.colors.CYAN)
        typer.secho(f"0 adopted — {len(pre_errors)} item(s) failed preflight of "
                    f"{len(items)}; no strategy branches written (all-or-nothing, D6)",
                    fg=typer.colors.RED)
        _archive_attempt()
        raise typer.Exit(code=1)

    if dry_run:
        typer.secho("── dry-run: all items VALID (parse + compile + preflight), "
                    "nothing written ──", fg=typer.colors.GREEN)
        for it, _p, _s in resolved:
            typer.echo(f"  would adopt {it.direction}/{it.track}/{it.branch}")
        for line in candidate_analysis:
            typer.echo(f"  signature: {line}")
        tmp.cleanup()
        return

    # --- Stage 3: adopt each (M1 immutable; preflight guarantees no
    #     predictable conflict remains, so a failure here is an unexpected
    #     I/O or concurrent-state change) ------
    adopted: list[tuple[batch_mod.BatchItem, Path]] = []
    for it, p, spec in resolved:
        try:
            dest = wf.adopt_branch(ws, it.direction, it.track, it.branch, p,
                                   spec)
        except wf.WorkflowError as exc:
            tmp.cleanup()
            archive_lines.extend([f"- Proposed: {len(items)}",
                                  f"- Adopted before failure: {len(adopted)}",
                                  f"- Adoption failure: {it.direction}/{it.track}/{it.branch}: {exc}"])
            archive_lines.extend(["- Run counts: OK=0, PARTIAL=0, FAILED=0 (not started)",
                                  "- Run IDs: none (adoption failed before run stage)",
                                  "- Branch decisions: pending author review"])
            _archive_attempt()
            # #131 (B2/P-6): honest messaging — preflight should have caught
            # every predictable conflict, so a failure here is unexpected
            # (I/O or concurrent-state change). Previously this printed
            # "batch rolled back" while the already-adopted items REMAINED on
            # disk; we now say exactly what happened.
            typer.secho("── batch summary (adopt FAILED) ───────────────────────",
                        fg=typer.colors.RED)
            for d in adopted:
                typer.echo(f"  [already adopted] {d[0].direction}/"
                           f"{d[0].track}/{d[0].branch}")
            typer.secho(f"[FAILED] {it.direction}/{it.track}/{it.branch}: {exc}",
                        fg=typer.colors.RED)
            typer.secho(f"{len(adopted)} of {len(items)} were adopted BEFORE "
                        f"this failure and REMAIN on disk (branches are "
                        f"immutable, so nothing was rolled back). Fix the "
                        f"failed item and re-run — the already-adopted ones "
                        f"are idempotent no-ops.", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        adopted.append((it, dest))

    # --- Stage 4: optional run (on the ADOPTED file → correct branch id) --
    # #131 (B6-T10): the --data-dir requirement was checked in stage 2.5
    # (before any writes), so it is guaranteed present here.
    run_ok = run_fail = run_partial = 0
    run_records: list[str] = []
    if run_it:
        for it, dest in adopted:
            try:
                res = run(strategy=str(dest), data_dir=data_dir, alpha_dir=alpha_dir,
                          config=config, name=None, out=None, strict=False, track=it.track)
                run_id = getattr(res, "run_id", None) if res is not None else None
                # DEV-04/RED-06 (UsageLastReview #2): `strict=False` means run()
                # returns a RunResult even when SOME instruments failed — and
                # previously the batch counted that as "run ok". Now a partial
                # run (any instrument_failures) is reported as PARTIAL with the
                # failing instruments, and drives a non-zero exit.
                n_fail = len(res.instrument_failures) if res is not None else 0
                if n_fail:
                    run_partial += 1
                    names = ", ".join(f.get("instrument", "?") for f in res.instrument_failures)
                    typer.secho(
                        f"  run {it.direction}/{it.track}/{it.branch}: PARTIAL — "
                        f"{len(res.metrics)} ok / {n_fail} instrument(s) FAILED: {names}",
                        fg=typer.colors.YELLOW)
                    run_records.append(
                        f"- Run {it.direction}/{it.track}/{it.branch}: PARTIAL; "
                        f"run_id={run_id or 'unavailable'}; failures={n_fail}")
                else:
                    run_ok += 1
                    typer.echo(f"  run {it.direction}/{it.track}/{it.branch}: ok")
                    run_records.append(
                        f"- Run {it.direction}/{it.track}/{it.branch}: OK; "
                        f"run_id={run_id or 'unavailable'}")
            except Exception as exc:  # B6-T11: typer.Exit OR any run error
                # #131 (B6-T11): run() raises typer.Exit (a SystemExit
                # subclass) or a plain exception; both were previously
                # mishandled — a SystemExit propagated and ABORTED the whole
                # batch, so only the first failure was seen. Now every item
                # runs independently and the batch summary always prints.
                run_fail += 1
                run_records.append(
                    f"- Run {it.direction}/{it.track}/{it.branch}: FAILED; "
                    f"run_id=none; reason={type(exc).__name__}: {exc}")
                typer.secho(f"  run {it.direction}/{it.track}/{it.branch}: "
                            f"FAILED ({type(exc).__name__}) — others continue",
                            fg=typer.colors.YELLOW)
    tmp.cleanup()
    run_note = (f" · {run_ok} run ok, {run_partial} partial, {run_fail} failed"
                if run_it else " · not run")

    # #131 (B6) + DEV-04 (UsageLastReview #2): the exit code must reflect the
    # true batch outcome — a hard failure (exit 3) or a *partial* run
    # (exit 4) must not masquerade as a clean exit.
    _warn = run_fail > 0 or run_partial > 0
    typer.secho("── batch summary ──────────────────────────────────────────",
                fg=typer.colors.GREEN if not _warn else typer.colors.YELLOW)
    for it, dest in adopted:
        typer.echo(f"  [OK] {it.direction}/{it.track}/{it.branch} -> {dest}")
    for line in candidate_analysis:
        typer.echo(f"  signature: {line}")
    typer.secho(f"{len(adopted)} adopted" + run_note,
                fg=typer.colors.GREEN if not _warn else typer.colors.YELLOW)
    archive_lines.extend([f"- Proposed: {len(items)}",
                          "- Preflight rejected: 0",
                          f"- Adopted: {len(adopted)}",
                          f"- Run counts: OK={run_ok}, PARTIAL={run_partial}, FAILED={run_fail}"])
    archive_lines.extend(f"- {it.direction}/{it.track}/{it.branch}: {dest}"
                         for it, dest in adopted)
    archive_lines.extend(f"- Signature: {line}" for line in candidate_analysis)
    archive_lines.extend(run_records or ["- Runs: not requested"])
    archive_lines.append("- Branch decisions: pending author review")
    _archive_attempt()
    if run_it and run_fail > 0:
        raise typer.Exit(code=3)
    if run_it and run_partial > 0:
        # partial: the run produced SOME results but not all instruments
        # completed — non-zero so an AI/human can't treat it as a clean pass.
        raise typer.Exit(code=4)


@app.command()
def report(
    run_dir: str = typer.Argument(..., help="Path to a run artifact dir (…/<name>/<date>)"),
) -> None:
    """Re-render an existing run's report.md from its artifacts (0006 D7).

    Read-only over the artifacts (metrics.json + manifest.json); does not
    re-run the engine or modify the data.
    """
    import json as _json
    d = Path(run_dir)
    mpath = d / "metrics.json"
    if not mpath.exists():
        typer.secho(f"no metrics.json in {d}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    payload = _json.loads(mpath.read_text(encoding="utf-8"))
    typer.echo(f"# {payload['spec_id']}  (run {payload['run_id'][:12]})")
    for inst in sorted(payload.get("per_instrument", {})):
        m = payload["per_instrument"][inst]
        typer.echo(f"  {inst}: {m['trade_count']} trades, "
                   f"annualized={m['annualized']}, win={m['win_rate']:.4f}, "
                   f"net={m['net_return']:.6f}, bars={m['avg_bars_held']}")
    typer.echo(f"(see {d / 'report.md'} for the full report)")


@app.command(name="exit-months")
def exit_months_cmd(
    run_dir: str = typer.Argument(..., help="Run artifact directory"),
) -> None:
    """Print read-only per-instrument diagnostics grouped by trade exit month."""
    import csv
    import sys
    from .diagnostics import exit_month_diagnostics
    try:
        rows = exit_month_diagnostics(Path(run_dir))
    except Exception as exc:
        typer.secho(f"ERROR: cannot build exit-month diagnostics: {exc}",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    fields = ["instrument", "exit_month", "exit_month_trade_count",
              "exit_month_net_return_sum", "exit_month_win_rate",
              "exit_month_avg_bars_held"]
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


# ---- 0007 Part A: OCI push / backup / list ---------------------------------


def _push_transport():
    """Lazily build a Transport with a real HTTP ``get`` (and, if available,
    ``put``). Tests never hit this path — they inject fakes."""
    import requests

    session = requests.Session()

    class _T:
        def get(self, url, **kw):
            return session.get(url, **kw)

        def put(self, url, **kw):
            return session.put(url, **kw)

    return _T()


def _cfg(config: str):
    data = load_config(config)
    oci = oci_from_dict(data)
    local = local_from_dict(data)
    return oci, local


#: One-shot `push`/`backup`/`sync` scope (R7): strategies + runs + alpha
#: features. The raw ``data/`` market layer is already persisted on OCI and
#: is not re-pushed by the one-shot command.
#:
#: H1 (2026-11-15): ``tracks/`` is in scope — the frozen track baseline
#: (``tracks/<dir>/<track>.json``) + per-track lessons (``.lessons.md``) are
#: the cross-machine loop memory (provenance + the AI-iteration lessons).
#: Without this, a fresh machine that pulled ``strategies/`` + ``runs/`` would
#: silently lose its track baseline and lessons, breaking the closed loop.
_BACKUP_TOP_LEVELS = frozenset({"strategies", "runs", "alpha", "tracks"})


def _push_all_roots(
    config: str,
    *,
    force_push: bool,
    dry_run: bool,
) -> None:
    """`push` / `backup` / `sync`: push the local workspace root (I17
    classification happens per-path on the *top-level* token:
    ``strategies/**``, ``runs/**``, ``alpha/features/**``, ``data/**``).

    The workspace root is the parent of ``strategies/`` (and of ``runs/``
    when co-located under it); the canonical OCI bucket prefix is
    ``oci.strategies_par_url`` (falls back to ``data_par_url``).
    """
    from . import oci_push
    from .config import resolve_data_root

    oci, local = _cfg(config)
    data_root = resolve_data_root(local, None)
    # workspace root = parent of the data dir (~/.lyra/<workspace>/), which
    # also holds strategies/ and runs/ for co-located setups.
    ws_root = data_root.parent

    url = (oci.strategies_par_url or oci.data_par_url).rstrip("/")
    if not url:
        typer.secho("no push target configured (oci.*_par_url empty)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    transport = _push_transport()
    try:
        res = oci_push.push(transport, ws_root, url,
                            force_push=force_push, dry_run=dry_run,
                            top_levels=_BACKUP_TOP_LEVELS)
    except oci_push.OciPushError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    mode = "dry-run" if dry_run else "push"
    typer.secho(
        f"{len(res.uploads)} upload, {len(res.skips)} skip, "
        f"{len(res.conflicts)} conflict  ({mode})",
        fg=typer.colors.GREEN,
    )
    for c in res.conflicts:
        typer.secho(f"  conflict: {c}", fg=typer.colors.YELLOW)

    # H9 (batch2): the default ``~/.lyra/runs`` (``lyra run`` output root)
    # is NOT under the workspace root, so the pass above never saw it.
    # Push it second, mapped under the immutable ``runs/`` prefix.
    #
    # Conflict-safety: an object already present on the remote at the *same*
    # rel path but with a different digest would raise an immutable-sha
    # conflict that blocks the whole pass. So we only stage a default-runs
    # file when its target rel path is NOT already in the remote map (a run
    # that was pushed through the canonical 4-level path is already covered
    # and is left alone here).
    from .runner import _default_out

    runs_root = Path(os.environ.get("LYRA_RUNS_ROOT", _default_out())).expanduser()
    if runs_root.is_dir():
        try:
            ws_resolved = ws_root.resolve()
        except OSError:
            ws_resolved = ws_root
        same_tree = (runs_root.resolve() == ws_resolved) or \
            str(runs_root).startswith(str(ws_resolved) + "/")
        if not same_tree:
            remote = oci_push.list_remote_map(transport, url.rstrip("/"))
            staging = Path(tempfile.mkdtemp(prefix=".lyra-push-runs-root-"))
            staged = 0
            for f in runs_root.rglob("*"):
                if not f.is_file():
                    continue
                rel = "runs/" + f.relative_to(runs_root).as_posix()
                if rel in remote:
                    continue  # already covered by a canonical push; don't conflict
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                staged += 1
            try:
                if staged:
                    res2 = oci_push.push(transport, staging, url,
                                         force_push=force_push, dry_run=dry_run)
                else:
                    res2 = None
            except oci_push.OciPushError as exc:
                typer.secho(f"push(default runs): {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            if res2 is not None:
                typer.secho(
                    f"default-runs: {len(res2.uploads)} upload, {len(res2.skips)} skip, "
                    f"{len(res2.conflicts)} conflict  ({mode})",
                    fg=typer.colors.GREEN,
                )
                for c in res2.conflicts:
                    typer.secho(f"  conflict: {c}", fg=typer.colors.YELLOW)
            else:
                typer.secho("default-runs: already covered by canonical push",
                            fg=typer.colors.GREEN)


@app.command(name="push")
def push(
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push", help="Allow immutable-sha overrides (R7)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan and report, do not upload"),
) -> None:
    """Push strategies + runs (+ features) to their PAR buckets per I17 rules."""
    _push_all_roots(config, force_push=force_push, dry_run=dry_run)


@app.command(name="backup")
def backup(
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """One-shot push of changed strategies + runs (R7)."""
    _push_all_roots(config, force_push=force_push, dry_run=dry_run)


@app.command("sync")
def sync_alias(
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Alias for `lyra backup` (D10/O15)."""
    _push_all_roots(config, force_push=force_push, dry_run=dry_run)


def _push_staging(
    config: str,
    staging_root: Path,
    *,
    force_push: bool,
    dry_run: bool,
    url: str | None = None,
) -> None:
    """Shared push path: push a staging dir through the I17-classifier push
    (batch2 H1: the plan is built from a root whose top-level token is the
    class key — `strategies/**` / `runs/**` — so scope never rejects
    direction-prefixed paths)."""
    from . import oci_push

    if not url:
        oci, _local = _cfg(config)
        url = (oci.strategies_par_url or oci.data_par_url).rstrip("/")
    if not url:
        typer.secho("no push target configured (oci.*_par_url empty)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    transport = _push_transport()
    try:
        res = oci_push.push(transport, staging_root, url.rstrip("/"),
                            force_push=force_push, dry_run=dry_run)
    except oci_push.OciPushError as exc:
        typer.secho(f"push: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    mode = "dry-run" if dry_run else "push"
    typer.secho(
        f"{len(res.uploads)} upload, {len(res.skips)} skip, "
        f"{len(res.conflicts)} conflict  ({mode})",
        fg=typer.colors.GREEN,
    )
    for c in res.conflicts:
        typer.secho(f"  conflict: {c.rel_path} ({c.reason})", fg=typer.colors.RED)


def _staging_slice(source_root: Path, direction: str, *, include_runs: bool) -> Path:
    """Copy one direction's strategies/ (+ runs/ when *include_runs*) slice
    into a temp staging root, keeping the canonical top-level tokens."""

    staging = Path(tempfile.mkdtemp(prefix=".lyra-push-dir-"))
    dstrat = staging / "strategies" / direction
    dstrat.mkdir(parents=True)
    # deep copy: the track-level layout nests strategies/<direction>/<track>/
    # <branch>.yaml, so a shallow file copy would silently drop them.
    for f in (source_root / "strategies" / direction).rglob("*"):
        if f.is_file():
            rel = f.relative_to(source_root / "strategies" / direction)
            dest = dstrat / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    if include_runs:
        src_runs = source_root / "runs" / direction
        if src_runs.is_dir():
            for f in src_runs.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(src_runs)
                    dest = staging / "runs" / direction / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
    # H1 (2026-11-15): carry this direction's track memory too (frozen
    # baseline + lessons) so a per-direction push — the command a web-AI loop
    # most naturally uses — doesn't silently strand the cross-machine loop
    # state that the full `lyra push` now includes.
    src_tracks = source_root / "tracks" / direction
    if src_tracks.is_dir():
        for f in src_tracks.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src_tracks)
                dest = staging / "tracks" / direction / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
    return staging


@app.command(name="push-strategy")
def push_strategy(
    direction: str = typer.Argument(..., help="Direction name, e.g. 'fx-trend'"),
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push a single direction's strategy folder (strategies/<direction>/).

    Reads from the canonical workspace root (``~/.lyra/<ws>/strategies/<dir>``),
    the same tree ``lyra run``/``context``/``new-version`` read and
    ``pull-strategy`` downloads into — not the data dir, so the download→work→
    upload loop stays on one path.
    """
    from . import workflow

    root = _workspace(config)
    local_root = root / "strategies" / direction
    if not local_root.is_dir():
        typer.secho(f"no strategies/{direction}/ at {local_root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        workflow.validate_ident(direction, "direction")
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    staging = _staging_slice(root, direction, include_runs=False)
    try:
        _push_staging(config, staging, force_push=force_push, dry_run=dry_run)
    finally:

        shutil.rmtree(staging, ignore_errors=True)


@app.command(name="push-direction")
def push_direction(
    direction: str = typer.Argument(..., help="Direction name"),
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push an entire direction: its strategies/ + runs/ slices (H1/H9).

    Reads from the canonical workspace root (``~/.lyra/<ws>/strategies/<dir>``
    and ``~/.lyra/<ws>/runs/<dir>``), matching ``lyra run`` output and
    ``pull-runs`` downloads — not the data dir."""
    from . import workflow

    root = _workspace(config)
    local_root = root / "strategies" / direction
    if not local_root.is_dir():
        typer.secho(f"no strategies/{direction}/ at {local_root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        workflow.validate_ident(direction, "direction")
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    # also include the direction's runs when they live under the workspace
    # root (co-located layout); ~/.lyra/runs is covered by push/backup.
    has_runs = (root / "runs" / direction).is_dir()
    staging = _staging_slice(root, direction, include_runs=has_runs)
    try:
        _push_staging(config, staging, force_push=force_push, dry_run=dry_run)
    finally:

        shutil.rmtree(staging, ignore_errors=True)


def _corpus_staging(temp_root: Path) -> Path:
    """Stage the local ``strategies/temp/`` candidate corpus under the
    canonical OCI shape ``strategies/corpus/<entry>/…`` (2026-11-14 裁决:
    temp 移出 git、内容进 OCI 标准策略库, 原稿在 nova).

    ``temp/<X>`` (nova_campaign/, moneta_s_series/, …) → ``corpus/<X>``.
    classify_path treats corpus candidates as immutable and corpus *.json
    indexes as append-only, so a re-push after 0010 triage appends verdicts.
    """
    staging = Path(tempfile.mkdtemp(prefix=".lyra-corpus-"))
    dest_root = staging / "strategies" / "corpus"
    dest_root.mkdir(parents=True)
    for entry in sorted(temp_root.iterdir()):
        dest = dest_root / entry.name
        if entry.is_dir():
            for f in entry.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(entry)
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest / rel)
        elif entry.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dest)
    return staging


@app.command(name="push-corpus")
def push_corpus(
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push the local ``strategies/temp/`` candidate corpus to OCI as
    ``strategies/corpus/<entry>/…`` (alpha candidate pool; originals in nova).

    Fails closed if the local ``strategies/temp/`` corpus is missing."""
    root = _workspace(config)
    temp_root = Path(__file__).resolve().parent.parent / "strategies" / "temp"
    # Prefer the workspace copy if it exists (canonical), else the repo-local
    # corpus (which is where the triage corpus is authored, per temp/README).
    ws_temp = root / "strategies" / "temp"
    if ws_temp.is_dir():
        temp_root = ws_temp
    if not temp_root.is_dir():
        typer.secho(
            f"no candidate corpus at {temp_root} — nothing to push",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)
    n_files = sum(1 for f in temp_root.rglob("*") if f.is_file())
    staging = _corpus_staging(temp_root)
    try:
        typer.secho(
            f"push-corpus: staging {n_files} files → strategies/corpus/…",
            fg=typer.colors.CYAN,
        )
        _push_staging(config, staging, force_push=force_push, dry_run=dry_run)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@app.command(name="push-runs")
def push_runs(
    direction: str = typer.Argument(..., help="Direction name (from the run manifest)"),
    run: str = typer.Argument(..., help="Local run name (runs/<name>/)"),
    track: str = typer.Option(..., "--track", help="Owning track (0007 D7: injected into the OCI path)"),
    config: str = typer.Option("config/config.yml", "--config"),
    runs_root: str | None = typer.Option(None, "--runs-root",
                                        help="Local runs root (default <workspace>/runs, matching `lyra run`; 0009 D2)"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push one 0006 run to its canonical OCI path (0007 D7 / O2 ruling):

        runs/<direction>/<track_id>/<run_id>/

    direction comes from the 0006 manifest (validated against the argument);
    track_id is a 0007 research identity supplied via --track (the 0006
    manifest has no track — D7)."""
    import hashlib as _hashlib
    import json as _json

    from . import oci_push, workflow

    oci, _local = _cfg(config)
    # identity tokens must be safe (H4: no `..`/absolute/separators in path)
    for tok, label in ((direction, "direction"), (run, "run"), (track, "track")):
        try:
            workflow.validate_ident(tok, label)
        except workflow.WorkflowError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)

    # 0009 D2: `lyra run` now defaults to <workspace>/runs (0007 D7 tree);
    # --runs-root overrides, and the legacy ~/.lyra/runs (pre-0009 runs)
    # stays reachable as a one-version compatibility fallback.
    if runs_root:
        bases = [Path(runs_root).expanduser()]
    else:
        ws = _workspace(config)
        bases = [ws / "runs", Path.home() / ".lyra" / "runs"]
    manifests: list[Path] = []
    for base in bases:
        found = sorted((base / run).glob("*/*/manifest.json"))  # <name>/<YYYYMMDD>/<run_id>/
        if found:
            manifests = found
            break
    if not manifests:
        searched = ", ".join(str(b / run) for b in bases)
        typer.secho(f"no manifest.json under {searched} — run the strategy first (0006)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    manifest = manifests[0]
    mdata = _json.loads(manifest.read_text(encoding="utf-8"))
    mdir = mdata.get("direction")
    if mdir is not None and mdir != direction:
        typer.secho(
            f"direction mismatch: manifest says {mdir!r}, argument says {direction!r}",
            fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    run_id = str(mdata.get("run_id", manifest.parent.name))
    try:
        workflow.validate_ident(run_id, "run_id (from manifest)")
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    # H8 (batch2): the manifest's artifact set + sha256 MUST be verified
    # before anything is staged — "push whatever files are there" is exactly
    # the gap this review flagged (fake/partial artifact runs could upload).
    artifacts = mdata.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        typer.secho("manifest has no 'artifacts' sha map — refusing to push (H8)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    run_dir = manifest.parent
    for name, expect in sorted(artifacts.items()):
        afile = run_dir / name
        if not afile.is_file():
            typer.secho(f"artifact '{name}' listed in manifest but missing on disk",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        actual = _hashlib.sha256(afile.read_bytes()).hexdigest()
        want = str(expect).strip().lower()
        if actual != want:
            typer.secho(
                f"artifact '{name}' sha256 mismatch (manifest={want} actual={actual}) — "
                f"refusing to push (H8)", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    # reject unexpected files: only manifest-listed artifacts + the known
    # sidecars (manifest.json + run_meta.json). 2026-11-14 审查 U1：`lyra run`
    # 之后总会写 run_meta.json（R12 identity sidecar, cli._write_run_meta），
    # 若不在白名单里，H8「unexpected files」守卫会把 *所有* 现代 run 一律拒推，
    # 回测产物 100% 推不上去。run_meta 是合法 sidecar，放行；H8 反假件保护不变。
    expected_files = set(artifacts) | {"manifest.json", "run_meta.json"}
    extra = [f.name for f in run_dir.iterdir() if f.is_file() and f.name not in expected_files]
    if extra:
        typer.secho(f"unexpected files in run dir: {sorted(extra)} — refusing (H8)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    # 保持 H8 强度：run_meta.json 是 lyra 机器生成的 JSON sidecar，若存在则
    # 必须是合法 JSON（非 JSON 说明被篡改/损坏，拒推而非把垃圾件推上桶）。
    _run_meta = run_dir / "run_meta.json"
    if _run_meta.is_file():
        try:
            _json.loads(_run_meta.read_text(encoding="utf-8"))
        except Exception as exc:
            typer.secho(
                f"run_meta.json is not valid JSON ({exc}) — refusing to push (H8)",
                fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)


    # staging layout must mirror the canonical OCI layout (0007 D7):
    #   runs/<direction>/<track_id>/<run_id>/<artifact>
    # because the I17 classifier treats the *top-level* token as the class
    # key (`runs/**` → immutable).
    staging = Path(tempfile.mkdtemp(prefix=".lyra-push-runs-"))
    dest_dir = staging / "runs" / direction / track / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        for name in sorted(expected_files):
            src = run_dir / name
            if not src.is_file():
                # run_meta.json is a post-run sidecar; a legacy run predating
                # _write_run_meta legitimately lacks it. (Required artifacts are
                # already verified present above; this only skips the optional
                # sidecar.)
                if name != "run_meta.json":
                    raise FileNotFoundError(
                        f"expected run file missing: {src} (name={name!r})"
                    )
                continue
            shutil.copy2(src, dest_dir / name)
        # H8: auditable provenance sidecar (track attribution is injected by
        # the push, not by the 0006 manifest — make it an artifact too).
        (dest_dir / "run_provenance.json").write_text(
            _json.dumps({
                "track_id": track,
                "direction": direction,
                "run_id": run_id,
                "manifest_run_id": run_id,
                "pushed_by": "lyra push-runs (0007 D7)",
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        url = (oci.runs_par_url or oci.strategies_par_url
               or oci.data_par_url).rstrip("/")
        if not url:
            typer.secho("no push target configured (oci.*_par_url empty)",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        transport = _push_transport()
        try:
            res = oci_push.push(transport, staging, url,
                                force_push=force_push, dry_run=dry_run)
        except oci_push.OciPushError as exc:
            typer.secho(f"push-runs: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    mode = "dry-run" if dry_run else "push"
    typer.secho(f"push-runs: {len(res.uploads)} upload, {len(res.skips)} skip, "
                f"{len(res.conflicts)} conflict  ({mode})", fg=typer.colors.GREEN)
    for c in res.conflicts:
        typer.secho(f"  conflict: {c}", fg=typer.colors.YELLOW)


def _pull_direction(
    prefix: str,
    par_url: str,
    save_root: Path,
    direction: str,
    *,
    dry_run: bool,
) -> None:
    """List one *par_url* bucket, keep only ``<prefix>/<direction>/**``
    objects, and download them into *save_root* (idempotent, I20).

    ``pull-strategy``/``pull-runs`` share this path: same canonical
    workspace layout, same md5-based idempotency, same PAR-expiry handling.
    """
    from . import oci_client

    # base keeps a trailing slash: download_object urljoins it with the
    # object name, and urljoin drops the last segment when the base is not
    # slash-terminated (…/data → …/strategies/…), corrupting the object URL.
    base = par_url.rstrip("/") + "/"
    keep_prefix = f"{prefix}/{direction}/"
    transport = _push_transport()
    try:
        objects = oci_client.list_objects(transport, base)
    except oci_client.ParExpiredError as exc:
        typer.secho(f"pull: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    selected = [o for o in objects
                if str(o.get("name", "")).startswith(keep_prefix)]
    if not selected:
        typer.secho(
            f"pull: no {prefix}/{direction}/ objects under "
            f"{oci_client.redact_par_url(base)}", fg=typer.colors.YELLOW,
        )
        return

    if dry_run:
        typer.secho(
            f"pull ({prefix}/{direction}): {len(selected)} object(s) would be "
            f"downloaded into {save_root}", fg=typer.colors.CYAN,
        )
        for o in selected:
            typer.secho(f"  would pull: {o['name']}", fg=typer.colors.CYAN)
        return

    pulled = skipped = 0
    for o in selected:
        name = str(o["name"]).strip()
        local_path = save_root / name
        already = (local_path.exists()
                   and oci_client._is_local_up_to_date(local_path, o))
        try:
            path = oci_client.download_object(
                transport, base, name, save_root, o,
            )
        except oci_client.ParExpiredError as exc:
            typer.secho(f"pull: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if already:
            skipped += 1
            typer.secho(f"  skip (up to date): {path.relative_to(save_root)}",
                        fg=typer.colors.CYAN)
        else:
            pulled += 1
            typer.secho(f"  pulled: {path.relative_to(save_root)}",
                        fg=typer.colors.GREEN)

    typer.secho(
        f"pull ({prefix}/{direction}): {pulled} pulled, {skipped} skip "
        f"into {save_root}", fg=typer.colors.GREEN,
    )


@app.command(name="pull-strategy")
def pull_strategy(
    direction: str | None = typer.Argument(None, help="Direction name, e.g. 'fx-trend' (omit with --all)"),
    config: str = typer.Option("config/config.yml", "--config"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="List what would be downloaded; do not fetch"),
    all_directions: bool = typer.Option(False, "--all",
                                        help="Pull EVERY known direction (local strategies/ or tracks/ folders)"),
) -> None:
    """Download a direction's strategies/ (``strategies/<direction>/**``)
    from the PAR bucket into the canonical workspace layout
    (``~/.lyra/<ws>/strategies/<direction>/``) — the same tree ``lyra run``/
    ``context``/``new-version`` read and ``push-strategy``/``push-direction``
    upload.

    Idempotent (I20): files whose local md5 already matches the remote digest
    are skipped. Re-running the pull before each session is the OCI-authority
    download half of the work loop.
    """
    from . import workflow

    oci, _local = _cfg(config)
    url = (oci.strategies_par_url or oci.data_par_url).rstrip("/")
    if not url:
        typer.secho(
            "no pull source configured (oci.strategies_par_url empty)",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)

    root = _workspace(config)
    if all_directions:
        # U-3 (UsageLastReview): `pull-strategy --all` — enumerate the known
        # directions (from the local strategies/ and tracks/ folders) and pull
        # each, so a fresh machine restores the whole research tree in one
        # command instead of naming every direction by hand.
        if direction is not None:
            typer.secho("give either a <direction> OR --all, not both",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        known: set[str] = set()
        for sub in ("strategies", "tracks"):
            base = root / sub
            if base.is_dir():
                for p in sorted(base.iterdir()):
                    # P2-5: fullmatch (re.match + $ still accepts a trailing
                    # newline in a hostile directory name).
                    if p.is_dir() and workflow._IDENT_RE.fullmatch(p.name) \
                            and p.name not in workflow._IDENT_BAD:
                        known.add(p.name)
        if not known:
            typer.echo("(no known directions locally — nothing to pull; "
                       "a completely fresh machine must name a direction explicitly)")
            return
        typer.echo(f"pulling {len(known)} known direction(s): "
                   f"{', '.join(sorted(known))}")
        for dname in sorted(known):
            _pull_direction(prefix="strategies", par_url=url, save_root=root,
                            direction=dname, dry_run=dry_run)
            _pull_direction(prefix="tracks", par_url=url, save_root=root,
                            direction=dname, dry_run=dry_run)
        return
    if direction is None:
        typer.secho("ERROR: give a <direction> argument, or --all.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        workflow.validate_ident(direction, "direction")
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    _pull_direction(
        prefix="strategies",
        par_url=url,
        save_root=root,
        direction=direction,
        dry_run=dry_run,
    )
    # H1 (2026-11-15): also restore the track memory (frozen baseline +
    # lessons) so a fresh machine can continue the loop — the same bucket the
    # push side wrote ``tracks/<direction>/**`` to. If the direction has no
    # tracks yet, _pull_direction reports "no … objects" and returns cleanly.
    _pull_direction(
        prefix="tracks",
        par_url=url,
        save_root=root,
        direction=direction,
        dry_run=dry_run,
    )


@app.command(name="pull-runs")
def pull_runs(
    direction: str = typer.Argument(..., help="Direction name"),
    config: str = typer.Option("config/config.yml", "--config"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="List what would be downloaded; do not fetch"),
) -> None:
    """Download a direction's runs/ (``runs/<direction>/**``) from the PAR
    bucket into the canonical workspace layout (``~/.lyra/<ws>/runs/<dir>``) —
    the same tree ``lyra run`` writes to and ``push-runs`` reads from.

    Idempotent (I20); see ``pull-strategy``.
    """
    from . import workflow

    oci, _local = _cfg(config)
    url = (oci.runs_par_url or oci.strategies_par_url
           or oci.data_par_url).rstrip("/")
    if not url:
        typer.secho(
            "no pull source configured (oci.runs_par_url empty)",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)
    try:
        workflow.validate_ident(direction, "direction")
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    root = _workspace(config)
    _pull_direction(
        prefix="runs",
        par_url=url,
        save_root=root,
        direction=direction,
        dry_run=dry_run,
    )


@app.command(name="list")
def list_cmd(
    prefix: str = typer.Option("strategies", "--prefix",
                               help="data|strategies|runs|features"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """List OCI objects under one prefix (read-only; no uploads)."""
    from . import oci_push

    oci, _local = _cfg(config)
    urls = {
        "strategies": oci.strategies_par_url,
        "features": oci.features_par_url,
        "runs": oci.runs_par_url or oci.strategies_par_url or oci.data_par_url,
        "data": oci.data_par_url,
    }
    url = urls.get(prefix)
    if not url:
        typer.secho(f"no PAR URL for prefix '{prefix}'", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    transport = _push_transport()
    try:
        objs = oci_push.list_remote_map(transport, url)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"list failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    for name in sorted(objs):
        meta = objs[name]
        size = meta.get("size", "?")
        typer.echo(f"{name}  ({size} B)")


# ---- 0007 Part B: R12 workflow --------------------------------------------


def _workspace(config: str) -> Path:
    """Workspace root resolution with a graceful fallback (审查#128 D7.1).

    Priority:
      1. ``--config`` file exists and parses → use its ``local`` section.
      2. Otherwise → ``LYRA_WORKSPACE`` env var (explicit workspace dir).
      3. Otherwise → ``LYRA_DATA_ROOT`` env var (its parent = the workspace).
      4. Otherwise → ``~/.lyra/default`` (a sane default; NOT an error).

    Workspace-only commands (tracks / context / digest / new-version /
    prune / lesson / …) must not hard-crash with a raw ``ConfigError``
    traceback just because ``config/config.yml`` is absent — that is the
    "pure ritual cost" the reviews flagged (D7: 11 commands, CI failures).
    """
    from .config import ConfigError, load_config, local_from_dict, resolve_data_root

    try:
        local = local_from_dict(load_config(config))
        return resolve_data_root(local, None).parent
    except ConfigError:
        env = os.environ.get("LYRA_WORKSPACE")
        if env:
            return Path(env).expanduser()
        env_root = os.environ.get("LYRA_DATA_ROOT")
        if env_root:
            return Path(env_root).expanduser().parent
        return Path.home() / ".lyra" / "default"


@app.command(name="tracks")
def tracks(
    direction: str = typer.Argument(..., help="Direction name"),
    create: str = typer.Option(None, "--create", help="Create a track with this id"),
    list: bool = typer.Option(False, "--list", help="List tracks in this direction"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Manage research tracks (I18 identity; 8-active-branch cap per track)."""
    from . import workflow

    ws = _workspace(config)
    if create is not None:
        try:
            rec = workflow.create_track(ws, direction, create)
        except workflow.WorkflowError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        bl = rec.get("baseline", {})
        typer.secho(
            f"created track {direction}/{create}: "
            f"hypothesis_sha={bl.get('hypothesis_sha256') and bl['hypothesis_sha256'][:12] + '…' or '(none)'} "
            f"feature_v={bl.get('feature_version')} engine={bl.get('engine_version')}",
            fg=typer.colors.GREEN,
        )
        return
    if list or create is None:
        tracks_list = workflow.list_tracks(ws, direction)
        if not tracks_list:
            typer.echo(f"(no tracks in {direction})")
        for t in tracks_list:
            active = workflow.count_active_branches(ws, direction, t["track_id"])
            typer.echo(f"  {t['track_id']}  active={active}/8  "
                       f"created={t.get('created_at', '?')}")
        return


@app.command(name="context")
def context_cmd(
    direction: str = typer.Argument(..., help="Direction name"),
    track: str = typer.Option(None, "--track", help="Scope to one track (I18 isolation)"),
    n_lessons: int = typer.Option(5, "--n-lessons", help="Max lessons to include"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Render the single-file context package for a direction (read-only)."""
    from . import workflow

    ws = _workspace(config)
    try:
        typer.echo(workflow.render_context(ws, direction, track=track, n_lessons=n_lessons))
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command(name="digest")
def digest_cmd(
    direction: str | None = typer.Argument(None, help="Direction name (omit with --all)"),
    track: str | None = typer.Option(None, "--track", help="Scope to one track (I18 isolation)"),
    all_directions: bool = typer.Option(False, "--all", help="Digest EVERY direction in a compact multi-direction view"),
    n_lessons: int = typer.Option(3, "--n-lessons", help="Max lessons to include"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Low-token history digest (审查#128 P0-2).

    One screen of *what this track is about*, *which branches are active*,
    and *what each has scored* — the decision view for a web/chat AI that
    must iterate on a small token budget. Full detail is ``lyra context``.

    Two forms:
      * ``lyra digest <direction> [--track T]`` — one direction (optionally
        one track).
      * ``lyra digest --all`` — every direction, compact: per direction a
        hypothesis line, active-branch count, and a one-line-per-branch
        score. The multi-AI mode-B entry point (one read → a synthesis view).
    """
    from . import workflow

    ws = _workspace(config)
    try:
        digest_registry = _registry_for(None, config)
    except Exception:
        digest_registry = None
    if all_directions:
        # #131 (P-1/P-2): a real multi-direction view, not a stub. The old
        # implementation (a) only listed track counts, and (b) used
        # `hypothesis.md` presence as the *existence test* for a direction —
        # silently dropping 11/12 real directions that only carry the
        # hypothesis in v01.yaml. Now we enumerate EVERY direction folder
        # (a folder with a v01.yaml, a hypothesis.md, or a track index is a
        # direction) and reuse `render_digest` — the SAME low-token renderer
        # the single-direction path uses — so each direction gets its
        # hypothesis (with the v01 fallback), per-branch scores, pruned
        # lines and lessons.
        strat_root = ws / "strategies"
        if not strat_root.is_dir():
            typer.echo("# digest — ALL directions (compact)")
            typer.echo("(no directions found)")
            return
        directions: list[str] = []
        skipped: list[tuple[str, str]] = []
        for p in sorted(strat_root.iterdir()):
            if not p.is_dir():
                continue
            is_dir = (p / "v01.yaml").exists() or (p / "hypothesis.md").exists() \
                or (p / "index").exists() or any(p.glob("*/*.yaml"))
            if not is_dir:
                skipped.append((p.name, "no v01.yaml / hypothesis.md / index / branch yaml"))
                continue
            # P2-5: fullmatch (re.match + $ still accepts a trailing newline).
            if not workflow._IDENT_RE.fullmatch(p.name) or p.name in workflow._IDENT_BAD:
                skipped.append((p.name, "not a valid direction identifier"))
                continue
            directions.append(p.name)
        # D-3 (UsageLastReview): a single H1 header for the whole view, a
        # corrected plural, the GLOBAL feature count printed once (not per
        # direction), and per-direction level-2 headings via standalone=False.
        typer.echo("# digest — ALL directions (compact)")
        plural = "direction" if len(directions) == 1 else "directions"
        typer.echo(f"({len(directions)} {plural}"
                   + (f", {len(skipped)} skipped" if skipped else "") + ")")
        try:
            from .features import build_registry as _build_registry
            _n_feats = len((digest_registry or _build_registry()).names())
            typer.echo(f"features: {_n_feats} registered "
                       f"(FEATURE_VERSION={workflow.FEATURE_VERSION}) — "
                       f"see `lyra context <direction>` for a direction's full list")
        except Exception:
            pass  # feature registry optional for the digest header
        if skipped:
            for name, why in skipped:
                typer.echo(f"  (skipped: {name} — {why})")
        # USER-04 (UsageLastReview #2): `--all --track T` must actually scope
        # each direction to T, not silently show every track. A direction that
        # has no such track is reported explicitly (not dropped or shown wrong).
        for dname in directions:
            try:
                typer.echo(workflow.render_digest(ws, dname, track=track,
                                                  n_lessons=n_lessons,
                                                  standalone=False,
                                                  registry=digest_registry))
            except workflow.WorkflowError as exc:
                if track is not None:
                    typer.secho(f"  (direction {dname}: no track {track!r} — "
                                f"skipped)", fg=typer.colors.YELLOW)
                else:
                    typer.secho(f"  (direction {dname}: {exc})",
                                fg=typer.colors.RED)
        return

    if direction is None:
        typer.secho("ERROR: give a <direction> argument, or --all.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        typer.echo(workflow.render_digest(ws, direction, track=track,
                                          n_lessons=n_lessons,
                                          registry=digest_registry))
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command(name="new-version")
def new_version_cmd(
    direction: str = typer.Argument(...),
    branch: str = typer.Option(..., "--branch", help="New branch slug"),
    track: str = typer.Option(..., "--track", help="Owning track (I21 cap scope)"),
    parent: str = typer.Option(None, "--from", help="Parent branch to derive from"),
    lesson: str = typer.Option(None, "--lesson", help="driven_by_lesson placeholder"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Derive a new branch template (enforces the per-track 8 cap, I21/D6)."""
    from . import workflow

    ws = _workspace(config)
    try:
        path = workflow.new_version(ws, direction, branch, track=track,
                                    parent=parent, driven_by_lesson=lesson)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"created branch: {path}", fg=typer.colors.GREEN)
    active = workflow.count_active_branches(ws, direction, track)
    typer.echo(f"  track {direction}/{track}: {active}/8 active")


@app.command(name="lesson")
def lesson(
    direction: str = typer.Argument(...),
    text: str = typer.Argument(...),
    track: str = typer.Option(..., "--track", help="Owning track (I18 identity)"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Append one lesson to the track's memory (审查 #125 gap #3).

    应用平台闭环里的"教训/下一步"：AI 看完一轮的 ``report`` 后，把一条结论
    （如 "v01 止损太松，v02 收紧 stop_loss_pct"）写回该 track 的 lessons
    文件（append-only，I17）。下一轮 ``context --track`` 会显示最近几条，
    让迭代带记忆、不重复犯同样的错。track 必须已存在（I18）；文本必须非空
    （fail-closed）。
    """
    from . import workflow

    ws = _workspace(config)
    try:
        path = workflow.append_lesson(ws, direction, track, text)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"lesson appended: {path}", fg=typer.colors.GREEN)
    typer.echo(f"  > {text}")


@app.command(name="prune")
def prune_cmd(
    direction: str = typer.Argument(...),
    branch: str = typer.Option(..., "--branch", help="Active branch slug to drop"),
    track: str = typer.Option(..., "--track", help="Owning track (I21 cap scope)"),
    reason: str = typer.Option("", "--reason", help="Why this branch was dropped (D9.1; shown in the digest's 'tried' line)"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Drop an active branch from a track's active list (relieve the 8-cap).

    审查 U3 (2026-11-14)：`workflow.prune_branch` 一直存在，但 CLI 无入口——
    8 分支配额耗尽后即死锁，无法回收。此命令接通该核心剪枝通道。剪枝是
    显式、追加事件式（H10 保留 append-only JSONL），绝不自动、绝不改名。
    """
    from . import workflow

    ws = _workspace(config)
    try:
        workflow.prune_branch(ws, direction, track, branch, reason=reason)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    active = workflow.count_active_branches(ws, direction, track)
    typer.secho(f"pruned branch {branch} from track {direction}/{track}",
                fg=typer.colors.GREEN)
    typer.echo(f"  track {direction}/{track}: {active}/8 active")


@app.command(name="compare")
def compare_cmd(
    direction: str = typer.Argument(...),
    siblings: bool = typer.Option(True, "--siblings/--no-siblings"),
    track: str = typer.Option(None, "--track"),
    branch: list[str] = typer.Option([], "--branch", help="Explicit branch list (repeatable)"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Read-only evidence table over sibling branches' 0006 metrics (I22/D8)."""
    from . import workflow

    ws = _workspace(config)
    if not branch and track:
        branch = workflow._track_active(ws, direction, track)
    if not branch:
        typer.secho("no branches to compare — pass --branch or --track",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    try:
        # 0009 D12/D13 (H1/H2): --track scopes the evidence to that track's
        # runs; without it, the comparison is direction-wide (explicit, all
        # tracks) and each run row still carries track + identity fields.
        result = workflow.compare_siblings(ws, direction, branch, track=track)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"# compare — {direction}" + (f" (track={track})" if track else ""))
    for row in result["siblings"]:
        b = row["branch"]
        runs = row["runs"]
        if not runs:
            typer.echo(f"  {b}: (no runs)")
            continue
        if not row.get("is_comparable"):
            reason = row.get("incomparable_reason") or "incomparable"
            typer.echo(f"  {b}: [EXCLUDED from ranking — {reason}] (runs={len(runs)})")
            continue
        ann = f"{row['median_annualized']:+.3f}"
        net = f"{row['median_net_return']:+.3f}"
        exp = f"{row['median_expectancy']:+.4f}"
        ratio = f"{row['profitable_instruments_count']}/{row['expected_instruments_count']} ({row['profitable_instrument_ratio'] * 100:.1f}%)"
        worst = row.get("worst_instrument")
        worst_str = f"{worst['instrument']} ({worst['annualized']:+.3f})" if worst else "(none)"
        best = row.get("best_single_instrument")
        best_str = (
            f"{best['instrument']} ann={best['annualized']:+.3f} (最好的一次，非综合分)"
            if best and best.get("annualized") is not None
            else "(none)"
        )
        inc = " [INCOMPLETE]" if row.get("is_incomplete") else ""
        typer.echo(f"  {b}{inc}: median_ann={ann} (net={net} exp={exp}) prof_ratio={ratio} "
                   f"worst={worst_str} [best_single: {best_str}] (runs={len(runs)})")

    sm = result.get("summary")
    if sm and sm.get("median_annualized") is not None:
        typer.echo(f"summary: median_ann={sm['median_annualized']:+.3f}, min_ann={sm['min_annualized']:+.3f}, "
                   f"median_prof_ratio={sm['median_profitable_ratio'] * 100:.1f}%, incomplete={sm['incomplete_count']}")
    # 0009 D13 (H2): the comparability verdict + why (per-run identity).
    verdict = result.get("comparable")
    label = {True: "COMPARABLE", False: "NOT COMPARABLE",
             None: "UNKNOWN (missing identity fields)"}[verdict]
    typer.echo(f"comparable: {label}  "
               f"(market_data_snapshots={result.get('distinct_market_data_snapshots', 0)}, "
               f"data_digests={result['distinct_data_digests']}, "
               f"feature_versions={result['distinct_feature_versions']}, "
               f"feature_generations={result['distinct_feature_generations']}, "
               f"runs_without_identity={result['runs_without_data_identity']})")
    for row in result["siblings"]:
        for r in row["runs"]:
            if r.get("comparable") is False:
                typer.secho(
                    f"  {row['branch']}: run {r['run_id'][:12]} incomparable — {r['incomparable_reason']}",
                    fg=typer.colors.YELLOW)
            elif r.get("comparable") is None:
                typer.secho(
                    f"  {row['branch']}: run {r['run_id'][:12]} unknown — {r['incomparable_reason']}",
                    fg=typer.colors.YELLOW)


@app.command(name="merge")
def merge_cmd(
    direction: str = typer.Argument(...),
    parents: list[str] = typer.Option(..., "--parents", help="Parent branches (>=2)"),
    track: str = typer.Option(..., "--track"),
    name: str = typer.Option(None, "--name", help="Candidate branch slug"),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Add a merge candidate branch — only adds, source branches untouched (I22)."""
    from . import workflow

    ws = _workspace(config)
    try:
        path = workflow.merge(ws, direction, parents, track=track, name=name)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"merge candidate created: {path}", fg=typer.colors.GREEN)


@app.command(name="synthesize")
def synthesize_cmd(
    direction: str = typer.Argument(...),
    config: str = typer.Option("config/config.yml", "--config"),
) -> None:
    """Cross-track synthesis report → reviews/ only (I22, read-only)."""
    from . import workflow

    ws = _workspace(config)
    try:
        path = workflow.synthesize(ws, direction)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"synthesis report: {path}", fg=typer.colors.GREEN)


#: 0009 D10: doctor severity levels — hard failures exit 1, warnings only
#: keep the exit code at 0 (doctor must stay usable as an environment
#: readiness probe before the user has run `lyra pull`).
_DOCTOR_MIN_PY = (3, 12)
_DOCTOR_MAX_PY = (3, 13)


@app.command(name="doctor")
def doctor(
    config: str = typer.Option("config/config.yml", "--config"),
    data_dir: str | None = typer.Option(None, "--data-dir", help="Data root to check (default: config local.data under ~/.lyra/<workspace>)"),
    strategy: str | None = typer.Option(None, "--strategy", help="A strategy YAML for the compile smoke check (default: bundled example)"),
    alpha_dir: str | None = typer.Option(None, "--alpha-dir", help="Alpha feature directory (default: config local.alpha)"),
) -> None:
    """Read-only environment self-check (0009 D10; R10 acceptance).

    Hard failures (exit 1): Python version policy, core dependency imports,
    config parsing + the ``data_par_url`` slot (the only slot ``lyra pull``
    needs).
    Warnings (exit 0, WARN count printed): the push-only OCI slots
    (features/strategies/runs) — optional for a pull-only setup (P1-4);
    catalog/views presence; feature-generation integrity (D4 gate); feature-
    layer instrument coverage vs the aggregates (#137); one compile smoke.
    """
    failures: list[str] = []
    warnings: list[str] = []

    # --- hard: python version ---------------------------------------------
    if not (_DOCTOR_MIN_PY <= sys.version_info[:2] < _DOCTOR_MAX_PY):
        failures.append(
            f"python {sys.version_info.major}.{sys.version_info.minor} outside "
            f"policy {'.'.join(map(str, _DOCTOR_MIN_PY))}–"
            f"{'.'.join(map(str, _DOCTOR_MAX_PY))} (exclusive)"
        )
    else:
        typer.echo(f"PASS python {sys.version.split()[0]} (policy >=3.12,<3.13)")

    # --- hard: core deps importable ----------------------------------------
    for mod, pkg in (("duckdb", "duckdb"), ("pyarrow", "pyarrow"),
                     ("pydantic", "pydantic"), ("yaml", "pyyaml"),
                     ("typer", "typer"), ("requests", "requests"),
                     ("numpy", "numpy"), ("talib", "TA-Lib")):
        try:
            __import__(mod)
            typer.echo(f"PASS import {pkg}")
        except Exception as exc:
            failures.append(f"core dependency {pkg} not importable: {exc}")

    # --- hard: config + OCI slots ------------------------------------------
    try:
        from .config import load_config, local_from_dict, oci_from_dict

        data = load_config(config)
        oci = oci_from_dict(data)
        local = local_from_dict(data)
        # P1-4 (UsageFinalReview): only ``data_par_url`` is a HARD requirement
        # — it is the ONLY slot ``lyra pull`` (first-use data download) needs.
        # The other three (features/strategies/runs) are PUSH-only slots and
        # are explicitly documented as optional: config.py says "`lyra pull`
        # must never require the push PAR slots" and config_example.yml says
        # "Leave a slot empty if that bucket is not configured yet".  Treating
        # them as hard failures made a pull-only setup FAIL doctor, contradicting
        # both docs.  A user who only wants data can now pass; a user who tries
        # to PUSH to an unconfigured bucket still gets an explicit error from
        # the push command itself (fail-closed there).
        data_val = getattr(oci, "data_par_url", None)
        if data_val:
            typer.echo("PASS config slot data_par_url set")
        else:
            failures.append(
                "config slot data_par_url not set (required for `lyra pull` "
                "and any OCI data sync)"
            )
        for slot in ("features_par_url", "strategies_par_url", "runs_par_url"):
            val = getattr(oci, slot, None)
            if val:
                typer.echo(f"PASS config slot {slot} set")
            else:
                warnings.append(
                    f"config slot {slot} not set — the matching push command "
                    f"(push-features/-strategy/-runs) will error explicitly; "
                    "safe to leave empty for a pull-only setup"
                )
        typer.echo("PASS config parses")
    except Exception as exc:
        failures.append(f"config unreadable at {config}: {exc}")
        local = None  # type: ignore[assignment]

    # --- warn: catalog + views ---------------------------------------------
    data_root = None
    if data_dir:
        data_root = Path(data_dir).expanduser()
    elif local is not None:
        from .config import resolve_data_root

        data_root = resolve_data_root(local, None)
    cat_file = Path(data_root) / "catalog.duckdb" if data_root is not None else None
    if cat_file is not None and cat_file.exists():
        try:
            from .catalog import Catalog

            views = {str(v.get("view")) for v in Catalog(cat_file).views()}
            have = views & {"bronze", "features_5m", "features_1h"}
            typer.echo(f"PASS catalog.duckdb present (views: {sorted(views) or 'none'})")
            if not have:
                warnings.append(
                    "catalog has no bronze/features views yet "
                    "(run `lyra pull` → `lyra features` → `lyra catalog`)"
                )
        except Exception as exc:
            warnings.append(f"catalog present but unreadable: {exc}")
    else:
        warnings.append(
            "no catalog.duckdb found "
            "(run `lyra pull` → `lyra features` → `lyra catalog`)"
        )

    # --- warn: feature generation integrity (D4) ----------------------------
    if data_root is not None and (data_root / "features").is_dir():
        try:
            from . import features as feat

            checked = feat.validate_generation(data_root)
            typer.echo(f"PASS feature generation consistent ({len(checked)} files)")
        except Exception as exc:
            warnings.append(f"feature generation check failed: {exc}")

        # Coverage (#137): the generation check above cannot see a layer that
        # was rebuilt for fewer instruments than its aggregate holds (#136).
        try:
            from . import features as feat

            coverage = feat.layer_coverage(data_root)
            bad = [c for c in coverage if c["missing"] or c["extra"]]
            for c in bad:
                if c["missing"]:
                    shown = ", ".join(c["missing"][:5])
                    more = len(c["missing"]) - 5
                    if more > 0:
                        shown += f", … +{more} more"
                    warnings.append(
                        f"feature layer features/{c['layer']} holds {c['features']} of "
                        f"{c['source']} instruments (missing: {shown}) — run "
                        f"`lyra features --minutes {c['minutes']}` to rebuild it"
                    )
                if c["extra"]:
                    warnings.append(
                        f"feature layer features/{c['layer']} has files for instruments "
                        f"not in the {c['layer']} aggregate: {', '.join(c['extra'][:5])} — "
                        f"run `lyra features --minutes {c['minutes']}`"
                    )
            if coverage and not bad:
                typer.echo("PASS feature layers cover every instrument ("
                           + ", ".join(f"{c['layer']}: {c['source']}" for c in coverage) + ")")
        except Exception as exc:
            warnings.append(f"feature layer coverage check failed: {exc}")

    # --- warn: compile smoke -------------------------------------------------
    try:
        reg = _registry_for(alpha_dir, config)
        s = strategy or _default_example_strategy()
        from . import compiler as compiler_mod
        from . import strategy_schema as schema_mod

        spec = schema_mod.parse_strategy(s, reg)
        plan = compiler_mod.compile_strategy(spec, reg, feature_catalog_snapshot="[]")
        typer.echo(f"PASS compile smoke ({spec.id} -> view {plan.view})")
    except Exception as exc:
        warnings.append(f"compile smoke failed: {exc}")

    if warnings:
        for w in warnings:
            typer.secho(f"WARN {w}", fg=typer.colors.YELLOW)
    if failures:
        for f in failures:
            typer.secho(f"FAIL {f}", fg=typer.colors.RED, err=True)
        typer.secho(f"DOCTOR FAILED: {len(failures)} failure(s), {len(warnings)} warning(s)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"DOCTOR OK: 0 failures, {len(warnings)} warning(s)",
                fg=typer.colors.GREEN)


def _default_example_strategy() -> str:
    """A strategy YAML for the compile smoke test.

    Prefers the repo's bundled example (``strategies/examples/*/v01.yaml``)
    when running from a source checkout; otherwise writes a minimal RSI
    strategy to a temp file so the smoke works from any install (0009 M3).
    """
    pkg_root = Path(__file__).resolve().parent.parent
    for cand in sorted((pkg_root / "strategies").glob("examples/*/v01.yaml")):
        return str(cand)
    # Fallback: an in-memory minimal strategy (registered features only).
    import tempfile
    fallback = (
        "version: 1\n"
        "id: doctor_smoke_rsi\n"
        "direction: mean_reversion\n"
        "timeframe_minutes: 60\n"
        "entry:\n"
        "  long:\n"
        "    all:\n"
        "      - {feature: rsi_12, op: lt, value: 30}\n"
        "exit:\n"
        "  long: {feature: rsi_12, op: gt, value: 55}\n"
        "  stop_loss_pct: 0.02\n"
        "execution:\n"
        "  spread_bps: 2\n"
        "  slippage_bps_per_side: 0.2\n"
        "  commission_bps_round_trip: 0\n"
        "  financing_bps_per_day: 0\n"
    )
    fd, path = tempfile.mkstemp(prefix="lyra_smoke_", suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(fallback)
    return path


@app.command()
def version() -> None:
    """Print the installed Lyra version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
