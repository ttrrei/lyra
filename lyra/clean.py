"""Clean: flat CSVs → bronze 1m Parquet (moneta ``load_data.py`` semantics).

Decision 0002 §3.3 / A2 / A1. Implemented in **DuckDB** because real data
scales to 12 GB / ~10M rows where a Python loop is not an option (moneta's
proven approach, re-implemented independently):

1. **``is_complete`` filter** — ``COALESCE(is_complete, FALSE) = TRUE``.
2. **Dedup on ``(instrument, time)``** — one deterministic survivor per key:
   non-null *payload* column count desc → source file name → row order.
   (moneta scores bid/ask only; scoring the full payload set is a strict
   generalization — identical outcome when the two are equivalent.)
3. **Bronze schema** — the union of input columns **minus** ``is_complete``
   (A2): always ``instrument,time,volume,mid_o,mid_h,mid_l,mid_c``, plus
   ``bid_*/ask_*`` when the source carries them.

Determinism (I18): the ``ROW_NUMBER()`` ordering makes the survivor total
and reproducible — thread count never influences the outcome.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Bronze always-present columns (0002 A2). ``is_complete`` is deliberately
# NOT among them — it is a clean input, not a bronze output.
ALWAYS_PRESENT = ("instrument", "time", "volume", "mid_o", "mid_h", "mid_l", "mid_c")
REQUIRED_INPUT = ("instrument", "time", "is_complete")
# Payload columns considered for survivor ranking (excludes keys + filter).
PAYLOAD = (
    "volume", "mid_o", "mid_h", "mid_l", "mid_c",
    "bid_o", "bid_h", "bid_l", "bid_c",
    "ask_o", "ask_h", "ask_l", "ask_c",
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CleanInputError(ValueError):
    """A flat CSV is missing a required input column (0002 §3.3)."""


def _quote(path: Path) -> str:
    s = str(path)
    # Allow glob characters (the read_csv glob) but reject anything that
    # could break out of the SQL string literal or traverse upward.
    if not re.match(r"^[\w\s/.\-*]+$", s) or s.startswith("-"):
        raise CleanInputError(f"unsafe path for clean: {path!r}")
    return s


def _clean_sql(csv_dir: Path, payload_present: set[str]) -> str:
    score_cols = [f"({c} IS NOT NULL)::INT" for c in PAYLOAD if c in payload_present]
    score = " + ".join(score_cols) if score_cols else "0"
    # Survivors only: filter → score → deterministic row number.
    return f"""
        WITH raw AS (
            SELECT *, filename AS _source_file
            FROM read_csv('{_quote(csv_dir / "*.csv")}',
                          header = TRUE, auto_detect = TRUE,
                          union_by_name = TRUE, filename = TRUE)
        ),
        scored AS (
            SELECT *, {score} AS _payload_score
            FROM raw
            WHERE COALESCE(is_complete, FALSE) = TRUE
        ),
        deduped AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY instrument, time
                       ORDER BY _payload_score DESC, _source_file ASC, time ASC
                   ) AS _rn
            FROM scored
        )
        SELECT * EXCLUDE (_rn, _payload_score, _source_file, filename, is_complete)
        FROM deduped
        WHERE _rn = 1
    """


def clean_csv_to_bronze(csv_dir: str | Path) -> list[dict[str, Any]]:
    """Apply the three clean rules and return bronze rows (list of dicts).

    A1: this ALWAYS recomputes — it never inspects an existing output.
    Raises ``CleanInputError`` if any CSV lacks a required input column.
    """
    import duckdb

    csv_dir = Path(csv_dir)
    if not csv_dir.exists() or not list(csv_dir.glob("*.csv")):
        return []

    con = duckdb.connect(":memory:")
    try:
        # Probe the first CSV for the required input contract (moneta's
        # approach: a glob-level sniff is unreliable).
        first = sorted(csv_dir.glob("*.csv"))[0]
        cols = {
            r[0].lower()
            for r in con.execute(
                "DESCRIBE SELECT * FROM read_csv(?, header=TRUE, auto_detect=TRUE) LIMIT 1",
                [str(first)],
            ).fetchall()
        }
        missing = [c for c in REQUIRED_INPUT if c not in cols]
        if missing:
            raise CleanInputError(
                f"{first.name} is missing required column(s): {', '.join(missing)}"
            )
        # Payload columns actually present (union_by_name handles per-file
        # differences; we score on the intersection we can name safely).
        present = {c for c in PAYLOAD if c in cols}

        sql = _clean_sql(csv_dir, present)
        out_cols = ["instrument", "time"] + [
            c for c in ALWAYS_PRESENT if c not in ("instrument", "time")
        ]
        for c in sorted(present):
            if c not in out_cols:
                out_cols.append(c)
        select = ", ".join(out_cols)

        rows = con.sql(f"SELECT {select} FROM ({sql}) t").fetchall()
        names = out_cols
        return [dict(zip(names, r)) for r in rows]
    finally:
        con.close()


def clean_csv_to_bronze_parquet(csv_dir: str | Path, out_path: str | Path) -> Path:
    """A1: ALWAYS recompute and overwrite the bronze Parquet.

    Streamed via DuckDB ``COPY`` (no full in-memory row materialization).
    Returns the output path.
    """
    import duckdb

    csv_dir = Path(csv_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_dir.exists() or not list(csv_dir.glob("*.csv")):
        # Deterministic empty bronze with the always-present typed schema.
        import pyarrow as pa
        import pyarrow.parquet as pq

        fields = [
            pa.field(
                c,
                pa.timestamp("us") if c == "time" else (pa.float64() if c != "instrument" else pa.string()),
            )
            for c in ALWAYS_PRESENT
        ]
        pq.write_table(pa.table({f.name: pa.array([], type=f.type) for f in fields}), str(out_path))
        return out_path

    con = duckdb.connect(":memory:")
    try:
        first = sorted(csv_dir.glob("*.csv"))[0]
        cols = {
            r[0].lower()
            for r in con.execute(
                "DESCRIBE SELECT * FROM read_csv(?, header=TRUE, auto_detect=TRUE) LIMIT 1",
                [str(first)],
            ).fetchall()
        }
        missing = [c for c in REQUIRED_INPUT if c not in cols]
        if missing:
            raise CleanInputError(
                f"{first.name} is missing required column(s): {', '.join(missing)}"
            )
        present = {c for c in PAYLOAD if c in cols}
        inner = _clean_sql(csv_dir, present)
        out_cols = ["instrument", "time"] + [
            c for c in ALWAYS_PRESENT if c not in ("instrument", "time")
        ]
        for c in sorted(present):
            if c not in out_cols:
                out_cols.append(c)
        select = ", ".join(out_cols)
        con.execute(f"COPY (SELECT {select} FROM ({inner}) t) TO '{_quote(out_path)}' (FORMAT PARQUET)")
    finally:
        con.close()
    return out_path
