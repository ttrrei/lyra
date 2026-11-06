"""0002 required tests — aggregate layer (I21 UTC buckets, determinism)."""

from __future__ import annotations

import datetime


from conftest import HEADER
from lyra import aggregate as agg
from lyra import clean as clean_mod


def _bronze(tmp_path, minutes: list[int], instrument="XAU_USD"):
    """Contiguous 1m bars starting 10:00 UTC at minute offsets (0-based, ordered)."""
    import pathlib

    csv_dir = pathlib.Path(tmp_path) / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    base = datetime.datetime(2026, 1, 2, 10, 0)
    for i, _m in enumerate(minutes):
        t = base + datetime.timedelta(minutes=i)
        o = 100 + i
        rows.append(
            f"{instrument},true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,{o},{o + 1},{o - 1},{o + 0.5},"
            f"{o - 0.2},{o + 0.8},{o - 0.3},{o + 0.3},{o + 0.2},{o + 1.2},{o - 0.7},{o + 0.7}"
        )
    (csv_dir / f"{instrument}.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return clean_mod.clean_csv_to_bronze(csv_dir)


def test_aggregate_5m_1h_utc(tmp_path):
    """I21: buckets land on UTC boundaries; open/close = first/last bar in window."""
    bronze = _bronze(tmp_path, list(range(12)))  # 10:00..10:11
    result = agg.aggregate_bronze_rows(bronze)

    b5 = result["ohlcv_5m"]
    assert [str(r["time"])[:16] for r in b5] == [
        "2026-01-02 10:00",
        "2026-01-02 10:05",
        "2026-01-02 10:10",
    ]
    assert float(b5[0]["mid_o"]) == 100.0 and float(b5[0]["mid_c"]) == 104.5
    assert b5[0]["n_bars"] == 5
    assert b5[2]["n_bars"] == 2  # partial window 10:10..10:11

    b1 = result["ohlcv_1h"]
    assert len(b1) == 1
    assert b1[0]["n_bars"] == 12
    assert float(b1[0]["mid_o"]) == 100.0 and float(b1[0]["mid_c"]) == 111.5


def test_aggregate_deterministic(tmp_path):
    """I18: two runs over the same input produce row-identical 5m/1h output."""
    rows = _bronze(tmp_path, list(range(0, 130)))  # crosses several 5m + 1h boundaries
    r1 = agg.aggregate_bronze_rows(rows)
    r2 = agg.aggregate_bronze_rows(rows)
    assert r1["ohlcv_5m"] == r2["ohlcv_5m"]
    assert r1["ohlcv_1h"] == r2["ohlcv_1h"]
    # Same rows in a different order → same aggregate (bucketing is order-invariant).
    r3 = agg.aggregate_bronze_rows(list(reversed(rows)))
    assert r3["ohlcv_5m"] == r1["ohlcv_5m"]
    assert r3["ohlcv_1h"] == r1["ohlcv_1h"]


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
    bronze = clean_mod.clean_csv_to_bronze(csv_dir)
    result = agg.aggregate_bronze_rows(bronze)
    n_bars = sorted(r["n_bars"] for r in result["ohlcv_1h"])
    assert n_bars == [2, 2]
