"""Typer CLI (decision 0002 §3.1): one user entry — ``lyra pull``.

``lyra clean`` / ``lyra aggregate`` are **debug entries** into the same
internal steps ``lyra pull`` runs, for inspection while developing.
"""

from __future__ import annotations


import typer

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
    typer.echo("")
    typer.echo(plan.sql)


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
    out: str | None = typer.Option(None, "--out", help="Artifact root (default ~/.lyra/runs; B13 out-of-repo)"),
    strict: bool = typer.Option(False, "--strict", help="Fail if any instrument failed (I16)"),
    financing_days: float | None = typer.Option(None, "--financing-days", help="Flat trading-day override for every trade (O17); default = per-trade calendar days"),
) -> None:
    """Run a strategy end-to-end (0006): signals -> trade engine -> metrics.

    Per-instrument evaluation (I7, no cross-instrument synthesis), R5 metrics,
    a reproducibility manifest (I5), and a report.  Trade-level research only
    (I9: no sizing / $ PnL / account equity).
    """
    from . import runner as runner_mod
    from . import strategy_schema as schema_mod

    reg = _registry_for(alpha_dir, config)
    try:
        result = runner_mod.run_strategy(
            strategy, data_dir, registry=reg, name=name, out_dir=out,
            strict=strict, financing_days=financing_days,
        )
    except schema_mod.SchemaError as exc:
        typer.secho(f"INVALID: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.secho(f"RUN FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"OK: run {result.run_id[:12]} -> {result.out_dir}",
                fg=typer.colors.GREEN)
    for inst in sorted(result.metrics):
        m = result.metrics[inst]
        typer.echo(f"  {inst}: {m['trade_count']} trades, "
                   f"annualized={m['annualized']}, win={m['win_rate']:.4f}")
    for f in result.instrument_failures:
        typer.secho(f"  {f['instrument']}: FAILED — {f['error']}",
                    fg=typer.colors.YELLOW)


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


@app.command()
def version() -> None:
    """Print the installed Lyra version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
