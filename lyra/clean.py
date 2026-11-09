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


class DataQualityError(ValueError):
    """Bronze rows violate a data-quality invariant (0002 §3.4, DQ1–DQ3)."""


def open_limited_duckdb(
    db=None,
    data_root: str | Path | None = None,
):
    """Open an in-memory DuckDB with the resource limits from config (D3).

    Applies ``SET max_memory`` / ``SET threads`` (when provided) and
    ``SET temp_directory`` (``<data_root>/<databackend.tmp>``, created on
    demand) so a low-RAM machine spills to disk instead of being OOM-killed.
    Shared by clean and aggregate so every pipeline connection is bounded.
    """
    import duckdb

    con = duckdb.connect(":memory:")
    if db is not None:
        if db.memory_limit:
            con.execute(f"SET max_memory = '{db.memory_limit}'")
        if db.threads is not None:
            con.execute(f"SET threads = {int(db.threads)}")
    if data_root is not None:
        tmp_dir = Path(data_root) / (db.tmp if db is not None else "tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_str = str(tmp_dir).replace("'", "''")
        con.execute(f"SET temp_directory = '{tmp_str}'")
    return con


def _quote(path: Path) -> str:
    """SQL single-quoted string literal for a path/glob (D1/D7, batch-7).

    Windows-safe (accepts drive letters, backslashes, spaces — R8
    portability) and injection-safe: the only escape is the standard SQL
    rule of doubling a single quote (``'`` → ``''``); control characters
    are rejected outright so no quote can be smuggled in another way.
    """
    s = str(path)
    if any(ord(ch) < 0x20 for ch in s) or "\x7f" in s:
        raise CleanInputError(f"unsafe path for clean: {path!r}")
    return "'" + s.replace("'", "''") + "'"


def _union_columns(con, csv_dir: Path) -> set[str]:
    """Return the union of lower-cased column names across ALL CSVs in *csv_dir*.

    D1 fix (批次08): the previous first-file sniff missed bid/ask columns
    that exist only in later files (e.g. OANDA sub-directory backfill CSVs
    mixed with mid-only flat CSVs), silently dropping them from bronze and
    skipping DQ2 spread validation. A single ``union_by_name`` DESCRIBE over
    the recursive glob captures every file's columns in one query.
    """
    return {
        r[0].lower()
        for r in con.execute(
            f"DESCRIBE SELECT * FROM read_csv({_quote(csv_dir / '**/*.csv')}, "
            "header=TRUE, auto_detect=TRUE, union_by_name=TRUE)"
        ).fetchall()
    }


def _clean_input_columns(con, csv_dir: Path) -> set[str]:
    """Validate required input columns and return the payload-column set."""
    cols = _union_columns(con, csv_dir)
    missing = [c for c in REQUIRED_INPUT if c not in cols]
    if missing:
        raise CleanInputError(
            f"input CSVs are missing required column(s): {', '.join(missing)}"
        )
    return {c for c in PAYLOAD if c in cols}


def _quality_checks(present: set[str]) -> dict[str, str]:
    """Data-quality invariants applied to the deduped bronze candidates
    (0002 §3.4, DQ1–DQ3). Each value is a WHERE expression matching a
    *violating* row; NULL comparisons naturally exclude partial rows.

    Ported from nova's ``_validate`` (the middle of moneta→nova→lyra): the
    OHLC/spread/volume invariants moneta's data happens to satisfy, now made
    explicit so dirty input cannot silently flow into bronze. Only invariants
    whose columns the input actually carries are emitted — referencing an
    absent column would be a binder error under ``union_by_name``.

    批次08 D4: every check additionally rejects non-finite values (``NaN`` /
    ``Inf``) in the columns it covers — DuckDB three-valued logic makes
    ``NaN > x`` evaluate to NULL, so without explicit guards a NaN price
    silently passes DQ1/DQ2 (DQ3 already had the guard).
    """
    checks: dict[str, str] = {
        # DQ1: mid OHLC must be positive, finite, and internally consistent
        # (o,c ∈ [l,h]). The isfinite guard is NULL-safe: it applies only to
        # rows that DO carry the value (a union_by_name NULL-filled column is
        # legal partial input, not a violation).
        "mid_ohlc": (
            "mid_h < mid_l OR mid_h < mid_o OR mid_h < mid_c "
            "OR mid_l > mid_o OR mid_l > mid_c "
            "OR mid_o <= 0 OR mid_h <= 0 OR mid_l <= 0 OR mid_c <= 0 "
            "OR (mid_o IS NOT NULL AND NOT isfinite(mid_o)) "
            "OR (mid_h IS NOT NULL AND NOT isfinite(mid_h)) "
            "OR (mid_l IS NOT NULL AND NOT isfinite(mid_l)) "
            "OR (mid_c IS NOT NULL AND NOT isfinite(mid_c))"
        ),
        # DQ3: volume, when present, must be finite and non-negative.
        "bad_volume": "volume IS NOT NULL AND (volume < 0 OR NOT isfinite(volume))",
    }
    # DQ2: at every point where BOTH sides of a quote are present, ask ≥ bid.
    # Column-aware per point: a sub-clause is emitted only when both bid_<p>
    # and ask_<p> columns exist (referencing an absent column under
    # union_by_name would be a binder error). The per-clause NULL guard makes
    # partial rows safe. DQ2 is enabled if ANY point has a bid/ask pair — this
    # avoids the "all-or-nothing 8 columns" trap where a partial-quote input
    # (e.g. only bid_o/ask_o) would silently skip spread validation. Only a
    # genuinely quote-free input (no bid/ask column at all) omits DQ2.
    #
    # 批次08 D4 (cross-point): a bar whose *highest* ask is below its *lowest*
    # bid is physically impossible at ANY point in time, even when the input
    # only carries mismatched points (e.g. bid_l + ask_h). This is the one
    # safe bar-wide inference: ask_h < bid_l ⇒ for every t, ask_t ≤ ask_h <
    # bid_l ≤ bid_t, so the quote is inverted at every point. (The reverse
    # inequality, bid_h < ask_l, is LEGITIMATE — the ask can sit above the
    # bid across the whole bar — so it must not be flagged.)
    point_clauses = [
        f"bid_{p} IS NOT NULL AND ask_{p} IS NOT NULL AND ask_{p} < bid_{p} "
        f"AND isfinite(bid_{p}) AND isfinite(ask_{p})"
        for p in ("o", "h", "l", "c")
        if f"bid_{p}" in present and f"ask_{p}" in present
    ]
    bar_wide_clauses: list[str] = []
    if "ask_h" in present and "bid_l" in present:
        bar_wide_clauses.append(
            "ask_h IS NOT NULL AND bid_l IS NOT NULL AND ask_h < bid_l "
            "AND isfinite(ask_h) AND isfinite(bid_l)"
        )
    if point_clauses or bar_wide_clauses:
        checks["bad_spread"] = " OR ".join(point_clauses + bar_wide_clauses)
    return checks


def _assert_quality(con, inner_sql: str, present: set[str]) -> None:
    """Fail fast (0002 §3.4) if any deduped bronze candidate violates DQ1–DQ3.

    Counts violating rows per invariant and raises ``DataQualityError`` naming
    each offender with its count, so a corrupt source is loud, not silent.
    """
    checks = _quality_checks(present)
    expressions = ",".join(
        f"count(*) FILTER (WHERE {expr})" for expr in checks.values()
    )
    # fetchall() (not fetchone()) so the result is fully consumed before any
    # later query reuses the same connection — required for the list-of-dicts
    # path, which runs another query on this connection right after.
    (counts,) = con.execute(f"SELECT {expressions} FROM ({inner_sql}) t").fetchall()
    offenders = {name: int(count) for name, count in zip(checks, counts) if count}
    if offenders:
        raise DataQualityError(
            "bronze data-quality violations (0002 §3.4): "
            + ", ".join(f"{name}={n}" for name, n in offenders.items())
        )


def _clean_sql(csv_dir: Path, payload_present: set[str]) -> str:
    score_cols = [f"({c} IS NOT NULL)::INT" for c in PAYLOAD if c in payload_present]
    score = " + ".join(score_cols) if score_cols else "0"
    # R3: keys must be non-NULL and non-empty before dedup — otherwise a
    # blank instrument/time survives into bronze and later stages (feature
    # builder, strategy run) fail far from the data boundary.
    key_valid = (
        " AND instrument IS NOT NULL AND TRIM(instrument) <> ''"
        " AND time IS NOT NULL"
    )
    # R13: a content hash of the payload columns is the final tie-breaker.
    # Same file + same key + same payload score but different content is a
    # total (read-order-independent) and run-stable order, so the survivor
    # is deterministic (I18) even when no column distinguishes the rows.
    hash_cols = [c for c in PAYLOAD if c in payload_present]
    if hash_cols:
        # `||` string-concatenation joins the per-row payload values into one
        # deterministic content fingerprint (run-stable, total ordering).
        row_hash = "md5(" + " || '' || ".join(hash_cols) + ")"
    else:
        row_hash = "''::VARCHAR"
    # Survivors only: filter → score → deterministic row number.
    return f"""
        WITH raw AS (
            SELECT *, filename AS _source_file
            FROM read_csv({_quote(csv_dir / "**/*.csv")},
                          header = TRUE, auto_detect = TRUE,
                          union_by_name = TRUE, filename = TRUE)
        ),
        scored AS (
            SELECT *, {score} AS _payload_score
            FROM raw
            WHERE COALESCE(is_complete, FALSE) = TRUE{key_valid}
        ),
        hashable AS (
            SELECT *, {row_hash} AS _row_hash FROM scored
        ),
        deduped AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY instrument, time
                       ORDER BY _payload_score DESC, _source_file ASC,
                                time ASC, _row_hash ASC
                   ) AS _rn
            FROM hashable
        )
        SELECT * EXCLUDE (_rn, _payload_score, _row_hash, _source_file,
                         filename, is_complete)
        FROM deduped
        WHERE _rn = 1
    """


def clean_csv_to_bronze(
    csv_dir: str | Path,
    data_root: str | Path | None = None,
    db=None,
) -> list[dict[str, Any]]:
    """Apply the three clean rules and return bronze rows (list of dicts).

    A1: this ALWAYS recomputes — it never inspects an existing output.
    Raises ``CleanInputError`` if any CSV lacks a required input column.
    """
    csv_dir = Path(csv_dir)
    if not csv_dir.exists() or not list(csv_dir.rglob("*.csv")):
        return []

    con = open_limited_duckdb(db, data_root)
    try:
        # D1 fix (批次08): union column set over ALL CSVs, not just the first.
        present = _clean_input_columns(con, csv_dir)

        sql = _clean_sql(csv_dir, present)
        # Same fail-fast DQ gate as the Parquet path (0002 §3.4) — this
        # list-of-dicts entry must not be able to bypass validation.
        _assert_quality(con, sql, present)
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


def clean_csv_to_bronze_parquet(
    csv_dir: str | Path,
    out_path: str | Path,
    data_root: str | Path | None = None,
    db=None,
) -> Path:
    """A1: ALWAYS recompute and overwrite the bronze Parquet.

    Streamed via DuckDB ``COPY`` (no full in-memory row materialization).
    Returns the output path.
    """
    csv_dir = Path(csv_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_dir.exists() or not list(csv_dir.rglob("*.csv")):
        # D7 (batch-7): the empty path MUST use the same ``timestamp[us, tz=UTC]``
        # as the non-empty DuckDB path (TIMESTAMPTZ, I18 schema stability).
        import pyarrow as pa
        import pyarrow.parquet as pq

        fields = [
            pa.field(
                c,
                pa.timestamp("us", tz="UTC") if c == "time" else (pa.float64() if c != "instrument" else pa.string()),
            )
            for c in ALWAYS_PRESENT
        ]
        pq.write_table(pa.table({f.name: pa.array([], type=f.type) for f in fields}), str(out_path))
        return out_path

    con = open_limited_duckdb(db, data_root)
    try:
        # D1 fix (批次08): union column set over ALL CSVs, not just the first.
        present = _clean_input_columns(con, csv_dir)
        inner = _clean_sql(csv_dir, present)
        # Fail fast on dirty rows *before* writing bronze (0002 §3.4, DQ1–DQ3).
        _assert_quality(con, inner, present)
        out_cols = ["instrument", "time"] + [
            c for c in ALWAYS_PRESENT if c not in ("instrument", "time")
        ]
        for c in sorted(present):
            if c not in out_cols:
                out_cols.append(c)
        select = ", ".join(out_cols)
        con.execute(f"COPY (SELECT {select} FROM ({inner}) t) TO {_quote(out_path)} (FORMAT PARQUET)")
    finally:
        con.close()
    return out_path
