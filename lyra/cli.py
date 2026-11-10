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
        # C2 (batch-4 review): the flat ``--financing-days`` scalar was
        # removed from the engine (it mischarged every trade the same day
        # count). The default is per-trade natural days; a real trading-day
        # calendar is a future enhancement (O17).
        result = runner_mod.run_strategy(
            strategy, data_dir, registry=reg, name=name, out_dir=out,
            strict=strict,
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
_BACKUP_TOP_LEVELS = frozenset({"strategies", "runs", "alpha"})


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


@app.command(name="push-strategy")
def push_strategy(
    direction: str = typer.Argument(..., help="Direction name, e.g. 'fx-trend'"),
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push a single direction's strategy folder (strategies/<direction>/)."""
    from .config import resolve_data_root

    oci, local = _cfg(config)
    root = resolve_data_root(local, None)
    local_root = root / "strategies" / direction
    if not local_root.is_dir():
        typer.secho(f"no strategies/{direction}/ at {local_root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    # Only push this direction's slice: wrap in a temp copy?  Simpler: push
    # the parent and filter uploads in the plan to this prefix.
    from . import oci_push

    url = oci.strategies_par_url
    if not url:
        typer.secho("no push target configured (oci.strategies_par_url empty)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    transport = _push_transport()
    remote_map = oci_push.list_remote_map(transport, url)
    plan = oci_push.plan_push(transport, root / "strategies", url, remote_map)

    prefix = direction + "/"
    plan.uploads = [i for i in plan.uploads if i.rel_path.startswith(prefix)]
    plan.skips = [s for s in plan.skips if s.rel_path.startswith(prefix)]
    plan.conflicts = [c for c in plan.conflicts if c.rel_path.startswith(prefix)]

    if dry_run:
        for k in ("upload", "skip", "conflict"):
            for v in plan.to_report()[k]:
                typer.echo(f"  {k}: {v}")
        return
    for c in plan.conflicts:
        typer.secho(f"conflict: {c.rel_path} ({c.reason})", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    for item in plan.uploads:
        data = (root / "strategies" / item.rel_path).read_bytes()
        full = url if url.endswith("/") else url + "/"
        try:
            resp = transport.put(full + item.rel_path, data=data, timeout=300)
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"upload {item.rel_path} failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        status = getattr(resp, "status_code", 200)
        if status >= 400:
            typer.secho(f"upload {item.rel_path}: HTTP {status}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        typer.echo(f"  pushed: {item.rel_path}")


@app.command(name="push-direction")
def push_direction(
    direction: str = typer.Argument(..., help="Direction name"),
    config: str = typer.Option("config/config.yml", "--config"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push an entire direction: its strategies/ + runs/ slices."""
    push_strategy(direction, config=config, force_push=force_push, dry_run=dry_run)


@app.command(name="push-runs")
def push_runs(
    direction: str = typer.Argument(..., help="Direction name (from the run manifest)"),
    run: str = typer.Argument(..., help="Local run name (runs/<name>/)"),
    track: str = typer.Option(..., "--track", help="Owning track (0007 D7: injected into the OCI path)"),
    config: str = typer.Option("config/config.yml", "--config"),
    runs_root: str | None = typer.Option(None, "--runs-root",
                                        help="Local runs root (default ~/.lyra/runs, matching 0006 run)"),
    force_push: bool = typer.Option(False, "--force-push"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Push one 0006 run to its canonical OCI path (0007 D7 / O2 ruling):

        runs/<direction>/<track_id>/<run_id>/

    direction comes from the 0006 manifest (validated against the argument);
    track_id is a 0007 research identity supplied via --track (the 0006
    manifest has no track — D7)."""
    import json as _json

    from . import oci_push

    oci, _local = _cfg(config)
    # 0006 `lyra run` defaults to ~/.lyra/runs (B13, no workspace in path);
    # --runs-root overrides for co-located setups.
    base = Path(runs_root).expanduser() if runs_root else Path.home() / ".lyra" / "runs"
    run_root = base / run
    manifest = None
    for m in sorted(run_root.glob("*/*/manifest.json")):  # <name>/<YYYYMMDD>/<run_id>/
        manifest = m
        break
    if manifest is None or not manifest.exists():
        typer.secho(f"no manifest.json under {run_root} — run the strategy first (0006)",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    mdata = _json.loads(manifest.read_text(encoding="utf-8"))
    mdir = mdata.get("direction")
    if mdir is not None and mdir != direction:
        typer.secho(
            f"direction mismatch: manifest says {mdir!r}, argument says {direction!r}",
            fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    run_id = str(mdata.get("run_id", manifest.parent.name))

    import shutil as _shutil
    import tempfile

    # staging layout must mirror the canonical OCI layout (0007 D7):
    #   runs/<direction>/<track_id>/<run_id>/<artifact>
    # because the I17 classifier treats the *top-level* token as the class
    # key (`runs/**` → immutable).
    staging = Path(tempfile.mkdtemp(prefix=f".lyra-push-runs-{run_id[:12]}-"))
    dest_dir = staging / "runs" / direction / track / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        for f in manifest.parent.iterdir():
            if f.is_file():
                _shutil.copy2(f, dest_dir / f.name)

        url = (oci.strategies_par_url or oci.data_par_url).rstrip("/")
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
        _shutil.rmtree(staging, ignore_errors=True)

    mode = "dry-run" if dry_run else "push"
    typer.secho(f"push-runs: {len(res.uploads)} upload, {len(res.skips)} skip, "
                f"{len(res.conflicts)} conflict  ({mode})", fg=typer.colors.GREEN)
    for c in res.conflicts:
        typer.secho(f"  conflict: {c}", fg=typer.colors.YELLOW)


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
        "runs": oci.strategies_par_url or oci.data_par_url,
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
    from .config import resolve_data_root

    _, local = _cfg(config)
    return resolve_data_root(local, None).parent  # ~/.lyra/<workspace>/


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
        result = workflow.compare_siblings(ws, direction, branch)
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"# compare — {direction}")
    for row in result["siblings"]:
        b = row["branch"]
        runs = row["runs"]
        best = row["best"]
        if best:
            typer.echo(f"  {b}: best net={best.get('net_return')} ann={best.get('annualized')} "
                       f"trades={best.get('trades')} (runs={len(runs)})")
        else:
            typer.echo(f"  {b}: (no runs)")


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


@app.command()
def version() -> None:
    """Print the installed Lyra version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
