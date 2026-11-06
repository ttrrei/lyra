"""Tests for the DuckDB catalog (0002 — external-table metadata layer)."""

from __future__ import annotations

import duckdb

import pytest

from lyra import aggregate as agg
from lyra import clean as clean_mod
from lyra.catalog import Catalog, default_catalog_path, upsert_views


def _make_data_root(tmp_path):
    """Build a tiny bronze + 5m + 1h tree under tmp_path."""
    csv = tmp_path / "raw"
    csv.mkdir()
    rows = [
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n",
        "X,2020-01-01T00:00:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:01:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:02:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:03:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:04:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:05:00Z,1,1,1,1,1,True\n",
    ]
    (csv / "a.csv").write_text("".join(rows))
    bronze = tmp_path / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    p5 = tmp_path / "ohlcv_5m" / "ohlcv_5m.parquet"
    p1 = tmp_path / "ohlcv_1h" / "ohlcv_1h.parquet"
    agg.aggregate_bronze_to_parquet(bronze, p5, p1)
    return bronze, p5, p1


def test_catalog_registers_all_views(tmp_path):
    _make_data_root(tmp_path)
    cat = upsert_views(tmp_path)
    views = {v["view"] for v in cat.views()}
    assert {"bronze", "ohlcv_5m", "ohlcv_1h"} <= views


def test_catalog_is_idempotent(tmp_path):
    _make_data_root(tmp_path)
    c1 = upsert_views(tmp_path)
    c2 = upsert_views(tmp_path)
    assert [v["view"] for v in c1.views()] == [v["view"] for v in c2.views()]


def test_catalog_queries_match_parquet(tmp_path):
    bronze, p5, _ = _make_data_root(tmp_path)
    upsert_views(tmp_path)
    cat = Catalog(default_catalog_path(tmp_path))
    con = duckdb.connect(str(cat.path), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM bronze").fetchone()[0]
        con_n = int(duckdb.connect(":memory:").execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(bronze)]).fetchone()[0])
        assert n == con_n
        n5 = con.execute("SELECT COUNT(*) FROM ohlcv_5m").fetchone()[0]
        assert n5 == int(duckdb.connect(":memory:").execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(p5)]).fetchone()[0])
    finally:
        con.close()


def test_catalog_missing_layers_skipped(tmp_path):
    # Only bronze present (no 5m/1h) -> catalog registers bronze only.
    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "a.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,1,1,1,1,True\n"
    )
    bronze = tmp_path / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    cat = upsert_views(tmp_path)
    views = {v["view"] for v in cat.views()}
    assert views == {"bronze"}


def test_catalog_path_is_outside_repo(tmp_path):
    cat = Catalog(default_catalog_path(tmp_path))
    # The catalog lives next to the data root, not in the repo.
    assert str(cat.path).endswith("catalog.duckdb")


def test_aggregate_streams_via_view_not_table(tmp_path, monkeypatch):
    """I18/I21: the aggregate must not materialize bronze into a TABLE.

    Patch the register helper to assert a VIEW (not TABLE) is created —
    the streaming / external-table property the user asked for.
    """
    created: list[str] = []
    real_register = agg._register_bronze

    def spy_register(connection, path):
        real_register(connection, path)
        rows = connection.execute(
            "SELECT view_name FROM duckdb_views() "
            "WHERE view_name = 'bronze'").fetchall()
        assert rows, "bronze must be registered as a VIEW (streaming), not a TABLE"
        created.append(path.name)

    monkeypatch.setattr(agg, "_register_bronze", spy_register)
    # Build a minimal 1m bronze in tmp_path.
    csv = tmp_path / "raw"
    csv.mkdir()
    # 120 valid 1m bars spanning 2 hours (I22: uniform 1m resolution).
    (csv / "a.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        + "".join(f"X,2020-01-01T{m // 60:02d}:{m % 60:02d}:00Z,1,1,1,1,1,True\n" for m in range(120))
    )
    bronze = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    agg.aggregate_bronze_to_parquet(bronze, tmp_path / "o5.parquet", tmp_path / "o1.parquet")
    assert created == ["b.parquet"]


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
