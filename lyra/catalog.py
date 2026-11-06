"""Persistent DuckDB catalog over the Parquet layers (0002, I18/I19).

User request (2026-11-06): use DuckDB as a *metadata* layer that references
the Parquet files (external tables) rather than re-opening raw Parquet globs
in every downstream tool. The catalog is a tiny persistent DuckDB database
holding ``CREATE VIEW`` definitions; the **data** stays in Parquet files
(I18 — Parquet files are the artifact, the catalog is only metadata).

The catalog lives OUTSIDE the repo (anti-footgun) and is never read by the
0007 push path (I19):

* ``~/.lyra/default/catalog.duckdb`` — the catalog itself (a few KB).

Registered views (created by :func:`upsert_views`):

* ``bronze``  → ``data/all_data/all_data.parquet`` (1m)
* ``ohlcv_5m`` → ``data/ohlcv_5m/ohlcv_5m.parquet``
* ``ohlcv_1h`` → ``data/ohlcv_1h/ohlcv_1h.parquet``

Downstream (0003 feature builder, 0005 trade engine) should query these views
instead of re-opening the Parquet files — one stable, named entry point, and
the Parquet files remain the single source of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

# (view_name, subpath under the data root). The subpath must match the
# on-disk layout produced by the pipeline (0002 §3).
_LAYERS: tuple[tuple[str, str], ...] = (
    ("bronze", "all_data/all_data.parquet"),
    ("ohlcv_5m", "ohlcv_5m/ohlcv_5m.parquet"),
    ("ohlcv_1h", "ohlcv_1h/ohlcv_1h.parquet"),
)

_SAFE_SUBPATH = re.compile(r"^[\w.\-/]+$")


@dataclass
class Catalog:
    """Handle to a persistent DuckDB catalog database.

    The catalog file is created on first use and is a small file (a few KB)
    containing only ``CREATE VIEW`` statements that point at the Parquet
    files. It is **not** the data; the Parquet files are (I18).
    """

    path: Path

    def upsert(self, data_root: str | Path) -> list[str]:
        """(Re)create the views for every layer found under ``data_root``.

        Missing Parquet files are skipped (so a partial pipeline run still
        registers whatever is present). Returns the list of view names that
        were created.
        """
        root = Path(data_root)
        created: list[str] = []
        con = duckdb.connect(str(self.path))
        try:
            for view_name, sub in _LAYERS:
                parquet = root / sub
                if not parquet.exists():
                    continue
                # Safe: the subpath is from a fixed whitelist; the file path
                # is validated before embedding in SQL.
                if not _SAFE_SUBPATH.match(sub):
                    raise ValueError(f"unsafe catalog subpath: {sub!r}")
                if not re.match(r"^[\w\s/.\-:~]+$", str(parquet)):
                    raise ValueError(f"unsafe catalog path: {parquet!r}")
                con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{parquet}')"
                )
                created.append(view_name)
        finally:
            con.close()
        return created

    def views(self) -> list[dict[str, object]]:
        """List the registered views (name, column count, base file)."""
        if not self.path.exists():
            return []
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            names = tuple(name for name, _sub in _LAYERS)
            placeholders = ", ".join("?" for _ in names)
            rows = con.execute(
                f"""
                SELECT schema_name, view_name
                FROM duckdb_views()
                WHERE view_name IN ({placeholders})
                ORDER BY view_name
                """,
                list(names),
            ).fetchall()
            return [{"schema": r[0], "view": r[1]} for r in rows]
        finally:
            con.close()


def default_catalog_path(data_dir: str | Path) -> Path:
    """Where the catalog lives: ``<data_dir>/catalog.duckdb``.

    Kept next to the data (not in the repo) per the anti-footgun rule.
    """
    return Path(data_dir) / "catalog.duckdb"


def upsert_views(data_root: str | Path, catalog: Catalog | None = None) -> Catalog:
    """Convenience: register all views from a data root, return the catalog.

    Used by the pipeline after ``aggregate`` and by downstream tools that
    want a stable named entry point to the data.
    """
    root = Path(data_root)
    cat = catalog or Catalog(default_catalog_path(root))
    cat.path.parent.mkdir(parents=True, exist_ok=True)
    cat.upsert(root)
    return cat
