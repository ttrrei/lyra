"""Typer CLI (decision 0002 §3.1): one user entry — ``lyra pull``.

``lyra clean`` / ``lyra aggregate`` are **debug entries** into the same
internal steps ``lyra pull`` runs, for inspection while developing.
"""

from __future__ import annotations


import os
import shutil
import sys
import tempfile
import typer

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


def _write_run_meta(strategy_path: Path, run_dir: Path,
                    track: str | None) -> None:
    """0009 D2: identity sidecar for a finished run.

    ``{direction, branch, track_id, spec_id, strategy_path, run_id}`` — the
    R12 workflow (``_runs_for_branch`` / ``compare_siblings``) reads this
    first, so run→direction/branch/track attribution no longer depends on
    spec_id naming conventions.
    """
    import json as _json

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
    branch = (strategy_path.name[:-5]
              if strategy_path.name.endswith(".yaml")
              else strategy_path.name)
    run_id = None
    try:
        manifest = _json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        run_id = manifest.get("run_id")
    except Exception:
        run_id = run_dir.name  # run_dir is already run_id-scoped
    payload = {
        "direction": direction,
        "branch": branch,
        "track_id": track,
        "spec_id": spec_id,
        "strategy_path": str(strategy_path),
        "run_id": run_id,
    }
    (run_dir / "run_meta.json").write_text(
        _json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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

    # 0009 D2 (M4): run_meta.json is the R12 identity source — a run the
    # workflow cannot attribute is broken, so a sidecar write failure must
    # fail the command (not warn-and-succeed). The run itself already
    # succeeded and its artifacts are on disk; the failure is attribution.
    try:
        _write_run_meta(Path(strategy), Path(result.out_dir), track)
    except Exception as exc:
        typer.secho(
            f"RUN OK but FAILED to write run_meta.json "
            f"({result.out_dir}): {exc} — this run will not be attributable "
            "by the R12 workflow (context/compare).",
            fg=typer.colors.RED, err=True,
        )
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
    # reject unexpected files: only manifest-listed artifacts + manifest.json
    expected_files = set(artifacts) | {"manifest.json"}
    extra = [f.name for f in run_dir.iterdir() if f.is_file() and f.name not in expected_files]
    if extra:
        typer.secho(f"unexpected files in run dir: {sorted(extra)} — refusing (H8)",
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
            shutil.copy2(run_dir / name, dest_dir / name)
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
    prefix_url = f"{base}{prefix}/"
    keep_prefix = f"{prefix}/{direction}/"
    transport = _push_transport()
    try:
        objects = oci_client.list_objects(transport, prefix_url)
    except oci_client.ParExpiredError as exc:
        typer.secho(f"pull: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    selected = [o for o in objects
                if str(o.get("name", "")).startswith(keep_prefix)]
    if not selected:
        typer.secho(
            f"pull: no {prefix}/{direction}/ objects under "
            f"{oci_client.redact_par_url(prefix_url)}", fg=typer.colors.YELLOW,
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
    direction: str = typer.Argument(..., help="Direction name, e.g. 'fx-trend'"),
    config: str = typer.Option("config/config.yml", "--config"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="List what would be downloaded; do not fetch"),
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
    try:
        workflow.validate_ident(direction, "direction")
    except workflow.WorkflowError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    root = _workspace(config)
    _pull_direction(
        prefix="strategies",
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
        best = row["best"]
        if best:
            typer.echo(f"  {b}: best net={best.get('net_return')} ann={best.get('annualized')} "
                       f"trades={best.get('trades')} (runs={len(runs)})")
        else:
            typer.echo(f"  {b}: (no runs)")
    # 0009 D13 (H2): the comparability verdict + why (per-run identity).
    verdict = result.get("comparable")
    label = {True: "COMPARABLE", False: "NOT COMPARABLE",
             None: "UNKNOWN (missing identity fields)"}[verdict]
    typer.echo(f"comparable: {label}  "
               f"(data_digests={result['distinct_data_digests']}, "
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
    config parsing + OCI slot presence.
    Warnings (exit 0, WARN count printed): catalog/views presence,
    feature-generation integrity (D4 gate), one compile smoke.
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
        # D10: all four OCI slots are HARD requirements (a config missing any
        # of them cannot run full OCI sync/backup, so doctor must fail closed,
        # not degrade to a warning).
        for slot in ("data_par_url", "features_par_url",
                     "strategies_par_url", "runs_par_url"):
            val = getattr(oci, slot, None)
            if val:
                typer.echo(f"PASS config slot {slot} set")
            else:
                failures.append(
                    f"config slot {slot} not set (required for OCI sync/backup)"
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
