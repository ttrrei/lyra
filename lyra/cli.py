"""Typer CLI (decision 0002 §3.1): one user entry — ``lyra pull``.

``lyra clean`` / ``lyra aggregate`` are **debug entries** into the same
internal steps ``lyra pull`` runs, for inspection while developing.
"""

from __future__ import annotations


import typer

from . import __version__, aggregate as agg, clean as clean_mod
from .config import (
    ConfigError,
    load_config,
    local_from_dict,
    oci_from_dict,
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
    root = resolve_data_root(local, data_root)
    return oci, root


@app.command()
def pull(
    config: str = typer.Option("config/config.yml", "--config", help="Path to config.yml"),
    data_root: str | None = typer.Option(None, "--data-root", help="Override the data root directory"),
) -> None:
    """Download raw archives (PAR, idempotent) then clean + aggregate (always recompute)."""
    try:
        oci, root = _load(config, data_root)
    except ConfigError as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    result = pipeline.run_pull(oci, root)
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

    _, root = _load(config, data_root)
    csv_dir = root / "raw_csv"
    if not csv_dir.exists():
        typer.secho(f"no raw_csv/ at {csv_dir} — run `lyra pull` first", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    out = root / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv_dir, out)
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

    _, root = _load(config, data_root)
    bronze = root / "all_data" / "all_data.parquet"
    if not bronze.exists():
        typer.secho(f"no bronze at {bronze} — run `lyra pull` first", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    p5 = root / "ohlcv_5m" / "ohlcv_5m.parquet"
    p1 = root / "ohlcv_1h" / "ohlcv_1h.parquet"
    agg.aggregate_bronze_to_parquet(bronze, p5, p1)
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
def version() -> None:
    """Print the installed Lyra version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
