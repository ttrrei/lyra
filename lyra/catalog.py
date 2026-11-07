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
# 0003 feature wide-table views (D1): view name -> features/<layer> dir.
_FEATURE_VIEWS: tuple[tuple[str, str], ...] = (
    ("features_5m", "features/ohlcv_5m"),
    ("features_1h", "features/ohlcv_1h"),
)

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

        D8 (batch-7): the data root is resolved to an **absolute** path before
        any view is registered, so views stay valid no matter which directory
        a later connection (0003, a notebook, a script) opens the catalog
        from. D1: the file path is embedded as a SQL single-quoted literal
        with the standard quote-doubling escape (control chars rejected).
        """
        root = Path(data_root).resolve()
        created: list[str] = []
        con = duckdb.connect(str(self.path))
        try:
            for view_name, sub in _LAYERS:
                parquet = root / sub
                if not parquet.exists():
                    continue
                # Safe: the subpath is from a fixed whitelist; the file path
                # is escaped before embedding in SQL.
                if not _SAFE_SUBPATH.match(sub):
                    raise ValueError(f"unsafe catalog subpath: {sub!r}")
                escaped = str(parquet).replace("'", "''")
                if any(ord(ch) < 0x20 for ch in str(parquet)):
                    raise ValueError(f"unsafe catalog path: {parquet!r}")
                con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{escaped}')"
                )
                created.append(view_name)
        finally:
            con.close()
        return created

    def upsert_feature_views(self, data_root: str | Path) -> list[str]:
        """Register the 0003 feature wide-table views (D1).

        ``features_5m`` / ``features_1h`` each read every
        ``<data_root>/features/<layer>/*.parquet`` via a single ``read_parquet``
        glob — one named entry point for the 0004 compiler regardless of how
        many instruments are present (K5: the data itself is authoritative).
        Layers with no Parquet files are skipped (partial runs register what
        exists, same rule as :meth:`upsert`).
        """
        root = Path(data_root).resolve()
        created: list[str] = []
        con = duckdb.connect(str(self.path))
        try:
            for view, sub in _FEATURE_VIEWS:
                files = sorted((root / sub).glob("*.parquet")) if (root / sub).is_dir() else []
                if not files:
                    continue
                escaped = str(root / sub / "*.parquet").replace("'", "''")
                con.execute(
                    f"CREATE OR REPLACE VIEW {view} AS "
                    f"SELECT * FROM read_parquet('{escaped}')"
                )
                created.append(view)
        finally:
            con.close()
        return created

    def views(self) -> list[dict[str, object]]:
        """List the registered views (name, column count, base file)."""
        if not self.path.exists():
            return []
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            # M4: include the 0003 feature views — they were created by
            # upsert_feature_views but never listed by views(), a contract
            # inconsistency. (The idempotency test only needs ordering, which
            # the fixed union preserves.)
            names = tuple(name for name, _sub in _LAYERS) + tuple(
                name for name, _sub in _FEATURE_VIEWS
            )
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


    def instruments(self) -> list[str]:
        """The distinct instruments present in bronze (D5, batch-7).

        0002's O14 deliverable as a live query: the authoritative instrument
        set is the data itself; this makes it a one-liner for 0003 and for
        humans. Returns [] if the catalog or bronze view is absent.
        """
        if not self.path.exists():
            return []
        con = duckdb.connect(str(self.path), read_only=True)
        try:
            rows = con.execute(
                "SELECT DISTINCT instrument FROM bronze ORDER BY instrument"
            ).fetchall()
            return [r[0] for r in rows]
        except duckdb.Error:
            # Bronze view present but its Parquet is missing/unreadable —
            # degrade to [] rather than raising, matching the docstring.
            return []
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
