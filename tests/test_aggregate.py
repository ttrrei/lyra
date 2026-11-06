"""0002 required tests — aggregate layer (I21 UTC buckets, determinism)."""

from __future__ import annotations

import datetime

import pytest

from conftest import HEADER
from lyra import aggregate as agg
from lyra import clean as clean_mod


def _bronze_parquet(tmp_path, minutes: list[int], instrument="XAU_USD"):
    """Contiguous 1m bars from 10:00 UTC; returns the bronze Parquet path."""
    import pathlib

    csv_dir = pathlib.Path(tmp_path) / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    base = datetime.datetime(2026, 1, 2, 10, 0)
    rows = []
    for i in range(len(minutes)):
        t = base + datetime.timedelta(minutes=i)
        o = 100 + i
        rows.append(
            f"{instrument},true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,{o},{o + 1},{o - 1},{o + 0.5},"
            f"{o - 0.2},{o + 0.8},{o - 0.3},{o + 0.3},{o + 0.2},{o + 1.2},{o - 0.7},{o + 0.7}"
        )
    (csv_dir / f"{instrument}.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    out = pathlib.Path(tmp_path) / "bronze.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv_dir, out)
    return out


def _read(parquet):
    import pyarrow.parquet as pq

    return pq.read_table(parquet).to_pylist()


def test_aggregate_5m_1h_utc(tmp_path):
    """I21: buckets land on UTC boundaries; open/close = first/last bar in window."""
    bronze = _bronze_parquet(tmp_path, list(range(12)))  # 10:00..10:11
    out5 = tmp_path / "5m.parquet"
    out1 = tmp_path / "1h.parquet"
    agg.aggregate_bronze_to_parquet(bronze, out5, out1)

    b5 = _read(out5)
    assert [str(r["time"])[:16] for r in b5] == [
        "2026-01-02 10:00",
        "2026-01-02 10:05",
        "2026-01-02 10:10",
    ]
    assert float(b5[0]["mid_o"]) == 100.0 and float(b5[0]["mid_c"]) == 104.5
    assert b5[0]["n_bars"] == 5
    assert b5[2]["n_bars"] == 2  # partial window 10:10..10:11

    b1 = _read(out1)
    assert len(b1) == 1
    assert b1[0]["n_bars"] == 12
    assert float(b1[0]["mid_o"]) == 100.0 and float(b1[0]["mid_c"]) == 111.5


def test_aggregate_deterministic(tmp_path):
    """I18: two runs over the same input produce row-identical 5m/1h output."""
    bronze = _bronze_parquet(tmp_path, list(range(130)))  # crosses 5m + 1h boundaries
    a5 = tmp_path / "a5.parquet"; a1 = tmp_path / "a1.parquet"
    b5 = tmp_path / "b5.parquet"; b1 = tmp_path / "b1.parquet"
    agg.aggregate_bronze_to_parquet(bronze, a5, a1)
    agg.aggregate_bronze_to_parquet(bronze, b5, b1)
    assert _read(a5) == _read(b5)
    assert _read(a1) == _read(b1)


def test_aggregate_partial_window_flag(tmp_path):
    """I21 n_bars: 11:58..12:01 → 1h windows split truthfully at the hour."""
    import pathlib

    csv_dir = pathlib.Path(tmp_path) / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (h, m) in enumerate([(11, 58), (11, 59), (12, 0), (12, 1)]):
        t = datetime.datetime(2026, 1, 2, h, m)
        o = 100 + i
        rows.append(
            f"XAU_USD,true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,{o},{o + 1},{o - 1},{o + 0.5},"
            f"{o - 0.2},{o + 0.8},{o - 0.3},{o + 0.3},{o + 0.2},{o + 1.2},{o - 0.7},{o + 0.7}"
        )
    (csv_dir / "XAU_USD.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    bronze = pathlib.Path(tmp_path) / "bronze.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv_dir, bronze)
    out1 = tmp_path / "1h.parquet"
    agg.aggregate_bronze_to_parquet(bronze, tmp_path / "5m.parquet", out1)
    n_bars = sorted(r["n_bars"] for r in _read(out1))
    assert n_bars == [2, 2]


def test_aggregate_non_1m_rejected(tmp_path):
    """I22: data whose *native resolution* is coarser than 1m (5m-spaced bars,
    min gap = 5m) must raise GranularityError."""
    import pathlib

    csv_dir = pathlib.Path(tmp_path) / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    # 5m-spaced bars only (0, 5, 10, 15) → min gap 5m → coarser than 1m.
    rows = []
    for m in (0, 5, 10, 15):
        t = datetime.datetime(2026, 1, 2, 10, m)
        o = 100 + m
        rows.append(
            f"XAU_USD,true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,{o},{o + 1},{o - 1},{o + 0.5},"
            f"{o - 0.2},{o + 0.8},{o - 0.3},{o + 0.3},{o + 0.2},{o + 1.2},{o - 0.7},{o + 0.7}"
        )
    (csv_dir / "XAU_USD.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    bronze = pathlib.Path(tmp_path) / "bronze.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv_dir, bronze)
    with pytest.raises(agg.GranularityError):
        agg.aggregate_bronze_to_parquet(bronze, tmp_path / "5m.parquet", tmp_path / "1h.parquet")


def test_aggregate_gapped_1m_accepted(tmp_path):
    """I22 (refined): genuine 1m data WITH a market gap (0,1 then 5) is
    1m-resolution (min gap 1m) and MUST be accepted — gaps are legitimate.
    Real data has ~731k such gaps (closed market / no trade)."""
    import pathlib

    csv_dir = pathlib.Path(tmp_path) / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for m in (0, 1, 5, 6, 7):
        t = datetime.datetime(2026, 1, 2, 10, m)
        o = 100 + m
        rows.append(
            f"XAU_USD,true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,{o},{o + 1},{o - 1},{o + 0.5},"
            f"{o - 0.2},{o + 0.8},{o - 0.3},{o + 0.3},{o + 0.2},{o + 1.2},{o - 0.7},{o + 0.7}"
        )
    (csv_dir / "XAU_USD.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    bronze = pathlib.Path(tmp_path) / "bronze.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv_dir, bronze)
    # No GranularityError; the 5m window 10:05..10:09 holds only 3 bars.
    agg.aggregate_bronze_to_parquet(bronze, tmp_path / "5m.parquet", tmp_path / "1h.parquet")
    b5 = _read(tmp_path / "5m.parquet")
    by_time = {str(r["time"])[:16]: r for r in b5}
    assert by_time["2026-01-02 10:05"]["n_bars"] == 3  # 10:05,10:06,10:07
