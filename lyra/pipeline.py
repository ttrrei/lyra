"""Orchestration for ``lyra pull`` (decision 0002 §3.1 / A1).

Re-run semantics (batch-3 A1, the load-bearing part):

* **only the raw download layer is idempotent** (I20) — ``sync_par`` skips
  objects whose local copy already matches;
* **clean and aggregate ALWAYS recompute and overwrite** their outputs. If
  we skipped them when the output already existed, deleting or corrupting
  ``all_data.parquet`` would silently lose data — the raw skip would then
  mask it. Because bronze/5m/1h are deterministic functions of the raw data
  (I18), recomputing is cheap and always safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import aggregate as agg
from . import clean as clean_mod
from . import oci_client, pull
from .config import OciConfig


@dataclass(frozen=True)
class PullResult:
    raw_zips: list[Path]
    raw_csvs: list[Path]
    bronze_path: Path
    ohlcv_5m_path: Path
    ohlcv_1h_path: Path
    bronze_rows: int
    bars_5m: int
    bars_1h: int


def _write_parquet(rows: list[dict], path: Path, columns: tuple[str, ...] | None = None) -> Path:
    """Write rows as Parquet with a typed schema (time as TIMESTAMP, I18/I21).

    Column order is fixed by the caller (clean's deterministic bronze set, or
    the aggregate SELECT order), so schemas are stable across runs. Empty
    input writes a zero-row table with the same schema (no drift).
    """
    import duckdb

    cols = list(columns) if columns else (list(rows[0].keys()) if rows else ["instrument", "time"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        # Empty input: same typed schema as the non-empty path.
        _NUMERIC = {"volume", "mid_o", "mid_h", "mid_l", "mid_c", "bid_o", "bid_h",
                    "bid_l", "bid_c", "ask_o", "ask_h", "ask_l", "ask_c", "n_bars"}
        fields = [
            pa.field(
                c,
                pa.timestamp("us") if c == "time" else (pa.float64() if c in _NUMERIC else pa.string()),
            )
            for c in cols
        ]
        table = pa.table({c: pa.array([], type=f.type) for c, f in zip(cols, fields)})
    else:
        # Normalize time to a string so Arrow inference is uniform; DuckDB
        # casts it back to TIMESTAMP (naive UTC, I21) in the SELECT below.
        normalized = [
            {**r, "time": r["time"].isoformat(sep=" ") if hasattr(r.get("time"), "isoformat") else str(r["time"])}
            for r in rows
        ]
        cast_cols = [f"{c}::TIMESTAMP AS {c}" if c == "time" else c for c in cols]
        con = duckdb.connect(":memory:")
        try:
            con.register("rows", pa.Table.from_pylist(normalized))
            table = con.sql(f"SELECT {', '.join(cast_cols)} FROM rows").to_arrow_table()
        finally:
            con.close()
    pq.write_table(table, str(path))
    return path


def _build_requests_session():  # pragma: no cover - needs network
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=5, connect=5, read=5, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def run_pull(
    oci: OciConfig,
    data_root: str | Path,
    transport: oci_client.Transport | None = None,
) -> PullResult:
    """Execute the full ``lyra pull`` pipeline into *data_root*."""
    data_root = Path(data_root)
    zips_dir = data_root / "raw_zips"
    csv_dir = data_root / "raw_csv"
    bronze_path = data_root / "all_data" / "all_data.parquet"
    p5 = data_root / "ohlcv_5m" / "ohlcv_5m.parquet"
    p1 = data_root / "ohlcv_1h" / "ohlcv_1h.parquet"

    transport = transport if transport is not None else _build_requests_session()

    # 1) raw download — the ONLY idempotent layer (I20).
    raw_zips = oci_client.sync_par(transport, oci.data_par_url, zips_dir)

    # 2) flatten archives → CSVs (clears stale top-level CSVs first).
    raw_csvs = pull.extract_zips_to_csv(zips_dir, csv_dir, clean_target=True)

    # 3) clean — ALWAYS recompute (A1). Deterministic (I18).
    bronze_rows = clean_mod.clean_csv_to_bronze(csv_dir)

    # 4) aggregate — ALWAYS recompute (A1). I21/I22 enforced inside.
    if bronze_rows:
        agg_result = agg.aggregate_bronze_rows(bronze_rows)
    else:
        agg_result = {"ohlcv_5m": [], "ohlcv_1h": []}

    # 5) persist outputs (overwrite). Explicit column order ⇒ stable schema.
    bronze_cols = tuple(bronze_rows[0].keys()) if bronze_rows else clean_mod.ALWAYS_PRESENT
    bronze_out = _write_parquet(bronze_rows, bronze_path, columns=bronze_cols)
    out_5 = _write_parquet(agg_result["ohlcv_5m"], p5, columns=agg.AGGREGATE_COLUMNS)
    out_1 = _write_parquet(agg_result["ohlcv_1h"], p1, columns=agg.AGGREGATE_COLUMNS)

    return PullResult(
        raw_zips=raw_zips,
        raw_csvs=raw_csvs,
        bronze_path=bronze_out,
        ohlcv_5m_path=out_5,
        ohlcv_1h_path=out_1,
        bronze_rows=len(bronze_rows),
        bars_5m=len(agg_result["ohlcv_5m"]),
        bars_1h=len(agg_result["ohlcv_1h"]),
    )
