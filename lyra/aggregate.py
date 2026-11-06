"""Aggregate bronze 1m → 5m / 1h (moneta ``aggregate_ohlcv.py`` reference).

Decision 0002 §3.3 / I21 / I22:

* buckets on **UTC** boundaries via DuckDB ``time_bucket`` — the source
  timestamps are *interpreted as UTC* regardless of host timezone;
* open/close from the window's **first/last** 1m bar (``ARRAY_AGG(.. ORDER
  BY time)[1]`` / ``[n]``), high/low max/min, volume summed, and ``n_bars``
  truthfully flags partial windows (I21);
* **I22 foolproofing** — the input must be uniform 1m granularity per
  instrument; any other gap raises ``GranularityError``.
"""

from __future__ import annotations

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


def _make_bronze_table(connection: duckdb.DuckDBPyConnection, source_sql: str) -> None:
    """Build the working ``bronze`` table with explicit types.

    Input rows may arrive as CSV strings (in-memory path) or Parquet values
    (standalone path); casting here makes both paths behave identically.
    Naive timestamps are *interpreted as UTC* (I21) via ``AT TIME ZONE 'UTC'``
    so results never depend on the host timezone.
    """
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE bronze AS
        SELECT
            instrument::VARCHAR        AS instrument,
            time::TIMESTAMP           AS time,   -- naive UTC (I21)
            volume::DOUBLE            AS volume,
            mid_o::DOUBLE             AS mid_o,
            mid_h::DOUBLE             AS mid_h,
            mid_l::DOUBLE             AS mid_l,
            mid_c::DOUBLE             AS mid_c
        FROM {source_sql}
        """
    )


def _check_required(connection: duckdb.DuckDBPyConnection, label: str) -> None:
    cols = {r[0] for r in connection.execute("DESCRIBE bronze").fetchall()}
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise ValueError(f"{label} missing bronze column(s): {', '.join(missing)}")


def _validate_1m(connection: duckdb.DuckDBPyConnection) -> None:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT LAG(time) OVER (PARTITION BY instrument ORDER BY time) AS prev, time
            FROM bronze
        )
        WHERE prev IS NOT NULL AND time - prev <> INTERVAL '1 minute'
        """
    ).fetchone()
    if row and row[0]:
        raise GranularityError(
            f"I22 violation: input is not uniform 1m granularity "
            f"({row[0]} non-1m gap(s) found). Lyra aggregates from 1m bronze only."
        )


def _aggregate_interval(
    connection: duckdb.DuckDBPyConnection, interval_sql: str
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT
            instrument,
            time_bucket(INTERVAL '{interval_sql}', time)         AS time,
            (ARRAY_AGG(mid_o ORDER BY time))[1]                  AS mid_o,
            (ARRAY_AGG(mid_c ORDER BY time))[ARRAY_LENGTH(ARRAY_AGG(mid_c ORDER BY time))] AS mid_c,
            MAX(mid_h)                                            AS mid_h,
            MIN(mid_l)                                            AS mid_l,
            SUM(COALESCE(volume, 0))                              AS volume,
            COUNT(*)                                              AS n_bars
        FROM bronze
        GROUP BY instrument, time_bucket(INTERVAL '{interval_sql}', time)
        ORDER BY instrument, time_bucket(INTERVAL '{interval_sql}', time)
    """
    cursor = connection.execute(sql)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def aggregate_bronze_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Aggregate in-memory 1m bronze rows into ``{'ohlcv_5m': [...], 'ohlcv_1h': [...]}``.

    Shared by ``lyra pull`` and the standalone ``lyra aggregate`` step.
    """
    if not rows:
        raise ValueError("no bronze rows to aggregate")
    import pyarrow as pa

    # Normalize time to a string so a mixed input (datetime + str) cannot
    # break Arrow inference; ``_make_bronze_table`` casts it to TIMESTAMP.
    normalized = [{**r, "time": r["time"].isoformat(sep=" ") if hasattr(r.get("time"), "isoformat") else str(r["time"])} for r in rows]
    connection = duckdb.connect(":memory:")
    try:
        connection.register("bronze_rows", pa.Table.from_pylist(normalized))
        _make_bronze_table(connection, "bronze_rows")
        _check_required(connection, "bronze rows")
        _validate_1m(connection)
        return {label: _aggregate_interval(connection, sql) for label, sql in INTERVALS}
    finally:
        connection.close()


def aggregate_bronze(bronze_parquet: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Aggregate one bronze 1m Parquet file (standalone ``lyra aggregate`` step)."""
    path = Path(bronze_parquet)
    if not path.exists():
        raise FileNotFoundError(path)
    connection = duckdb.connect(":memory:")
    try:
        _make_bronze_table(connection, f"read_parquet({path.as_posix()!r})")
        _check_required(connection, path.name)
        _validate_1m(connection)
        return {label: _aggregate_interval(connection, sql) for label, sql in INTERVALS}
    finally:
        connection.close()
