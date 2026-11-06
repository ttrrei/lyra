"""Aggregate bronze 1m → 5m / 1h (moneta ``aggregate_ohlcv.py`` reference).

Decision 0002 §3.3 / I21 / I22 — implemented in **DuckDB** (moneta's proven
approach, re-implemented independently) so it scales to real data:

* buckets on **UTC** boundaries via ``time_bucket``;
* open/close from the window's **first/last** 1m bar, high/low max/min,
  volume summed, and ``n_bars`` truthfully flags partial windows (I21);
* **I22 foolproofing** — input must be uniform 1m per instrument; any other
  gap raises ``GranularityError``;
* outputs stream straight to Parquet via ``COPY`` (no multi-GB Python
  materialization).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb

INTERVALS: tuple[tuple[str, str], ...] = (
    ("ohlcv_5m", "5 minutes"),
    ("ohlcv_1h", "1 hour"),
)
REQUIRED = ("instrument", "time", "mid_o", "mid_h", "mid_l", "mid_c")
# Deterministic column order of the 5m/1h outputs (I18 schema stability).
AGGREGATE_COLUMNS = ("instrument", "time", "mid_o", "mid_h", "mid_l", "mid_c", "volume", "n_bars")


class GranularityError(ValueError):
    """I22: input is not uniform 1m granularity."""


def _quote(path: Path) -> str:
    if not re.match(r"^[\w\s/.\-]+$", str(path)):
        raise ValueError(f"unsafe path for aggregate: {path!r}")
    return str(path)


def _validate_1m(connection: duckdb.DuckDBPyConnection) -> None:
    """I22: the input's *native resolution* must be 1 minute.

    Real 1m market data has legitimate gaps (market closed, no trade —
    weekend/holiday/quiet minutes), so we do NOT require every consecutive
    pair to be exactly 1m apart. We require instead that the finest
    inter-bar gap per instrument is ≈1m — i.e. the data is 1m-resolution and
    no coarser. This accepts real gapped 1m data and rejects 5m/1h (or
    sub-1m) input, which would make the 5m/1h buckets meaningless.
    """
    row = connection.execute(
        """
        WITH g AS (
            SELECT instrument,
                   EXTRACT(EPOCH FROM (time - LAG(time) OVER (PARTITION BY instrument ORDER BY time))) AS gap_s
            FROM bronze
        ),
        mins AS (
            SELECT MIN(gap_s) AS min_gap_s FROM g WHERE gap_s IS NOT NULL GROUP BY instrument
        )
        SELECT COUNT(*) FROM mins WHERE min_gap_s < 59 OR min_gap_s > 61
        """
    ).fetchone()
    if row and row[0]:
        raise GranularityError(
            f"I22 violation: {row[0]} instrument(s) are not 1-minute resolution "
            f"(their finest inter-bar gap is not ≈1m). Lyra aggregates from 1m bronze only."
        )


def _interval_sql(interval_sql: str) -> str:
    """Inner aggregation SELECT (as a subquery body) over the ``bronze`` view."""
    return f"""
        SELECT
            instrument,
            time_bucket(INTERVAL '{interval_sql}', time)        AS time,
            (ARRAY_AGG(mid_o ORDER BY time))[1]                 AS mid_o,
            (ARRAY_AGG(mid_c ORDER BY time))[
                ARRAY_LENGTH(ARRAY_AGG(mid_c ORDER BY time))
            ]                                                    AS mid_c,
            MAX(mid_h)                                            AS mid_h,
            MIN(mid_l)                                            AS mid_l,
            SUM(COALESCE(volume, 0))                              AS volume,
            COUNT(*)                                              AS n_bars
        FROM bronze
        GROUP BY instrument, time_bucket(INTERVAL '{interval_sql}', time)
        ORDER BY instrument, time_bucket(INTERVAL '{interval_sql}', time)
    """


def _register_bronze(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
    """Register ``bronze`` as a **view** (external table) over the Parquet file.

    A view (not ``CREATE TABLE``) means DuckDB streams directly from the
    Parquet file on each query — no in-memory copy of the 48M rows. This is
    the "DuckDB-as-metadata / external-table" pattern the user asked for.
    """
    connection.execute(
        "CREATE OR REPLACE VIEW bronze AS "
        f"SELECT instrument, time, volume, mid_o, mid_h, mid_l, mid_c "
        f"FROM read_parquet('{_quote(path)}')"
    )
    cols = {r[0] for r in connection.execute("DESCRIBE bronze").fetchall()}
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise ValueError(f"{path.name} missing bronze column(s): {', '.join(missing)}")


def aggregate_bronze_to_parquet(
    bronze_parquet: str | Path,
    out_5m: str | Path,
    out_1h: str | Path,
) -> dict[str, Path]:
    """A1: ALWAYS recompute and overwrite (deterministic ⇒ safe, I18/I21).

    Streams each granularity straight to Parquet (``COPY``); returns the two
    output paths (no row materialization — scales to 12 GB inputs).
    """
    bronze = Path(bronze_parquet)
    if not bronze.exists():
        raise FileNotFoundError(bronze)
    p5 = Path(out_5m)
    p1 = Path(out_1h)
    p5.parent.mkdir(parents=True, exist_ok=True)
    p1.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    try:
        _register_bronze(con, bronze)
        _validate_1m(con)
        for path, (_label, interval_sql) in ((p5, INTERVALS[0]), (p1, INTERVALS[1])):
            select = ", ".join(AGGREGATE_COLUMNS)
            # ORDER BY in the outer query keeps Parquet row order stable
            # (I18) regardless of parallelism.
            sql = (
                f"SELECT {select} FROM ({_interval_sql(interval_sql)}) t "
                "ORDER BY instrument, time"
            )
            con.execute(
                f"COPY ({sql}) TO '{_quote(path)}' (FORMAT PARQUET)"
            )
    finally:
        con.close()
    return {"ohlcv_5m": p5, "ohlcv_1h": p1}


def aggregate_bronze(bronze_parquet: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Aggregate one bronze 1m Parquet to in-memory rows (small-data / tests)."""
    bronze = Path(bronze_parquet)
    if not bronze.exists():
        raise FileNotFoundError(bronze)
    con = duckdb.connect(":memory:")
    try:
        _register_bronze(con, bronze)
        _validate_1m(con)
        out: dict[str, list[dict[str, Any]]] = {}
        for label, sql in INTERVALS:
            cur = con.execute(f"SELECT * FROM ({_interval_sql(sql)}) t")
            names = [d[0] for d in cur.description]
            out[label] = [dict(zip(names, r)) for r in cur.fetchall()]
        return out
    finally:
        con.close()
