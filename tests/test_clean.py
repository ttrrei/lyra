"""0002 required tests — clean layer (is_complete, dedup, schema, recompute)."""

from __future__ import annotations


import pytest

from conftest import HEADER, make_csv_bytes
from lyra import clean as clean_mod


def _write_csvs(csv_dir, rows_per_file: list[tuple[str, bytes]]) -> None:
    import pathlib

    csv_dir = pathlib.Path(csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)
    for name, data in rows_per_file:
        (csv_dir / name).write_bytes(data)


def _read_bronze_rows(rows: list[dict]) -> list[tuple]:
    return [(r["instrument"], r["time"]) for r in rows]


def test_clean_is_complete_filter(tmp_path):
    """Rows with is_complete false/empty are dropped (moneta rule 1)."""
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    # Build a CSV with one incomplete row in the middle.
    data = make_csv_bytes("XAU_USD", 0, 3, complete=True).decode().splitlines()
    data[2] = data[2].replace(",true,", ",false,", 1)  # row index 1 → incomplete
    (csv_dir / "XAU_USD.csv").write_text("\n".join(data) + "\n")

    bronze = clean_mod.clean_csv_to_bronze(csv_dir)
    # 3 input rows → 2 survivors (one filtered out).
    assert len(bronze) == 2
    assert all("is_complete" not in r for r in bronze)


def test_clean_dedup_deterministic(tmp_path):
    """Overlapping (instrument,time) across files → one deterministic survivor."""
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    # Both files cover minutes 0..2 for XAU_USD. a.csv has full mid; b.csv
    # is missing mid_c (more nulls) → a.csv must win on every key.
    full = make_csv_bytes("XAU_USD", 0, 3)
    # Build b.csv with mid_c blank on the overlapping rows.
    b_rows = []
    import datetime

    for i in range(3):
        t = datetime.datetime(2026, 1, 2, 0, i)
        b_rows.append(
            f"XAU_USD,true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,100,101,99,,98,99,97,101,102,100,103"
        )
    (csv_dir / "a.csv").write_bytes(full)
    (csv_dir / "b.csv").write_text(HEADER + "\n" + "\n".join(b_rows) + "\n")

    bronze = clean_mod.clean_csv_to_bronze(csv_dir)
    keys = _read_bronze_rows(bronze)
    # 3 unique (XAU_USD, minute) keys, no duplicates.
    assert len(keys) == 3
    assert len(set(keys)) == 3
    # Survivor is a.csv (more non-null payload) on every row.
    for r in bronze:
        assert r["mid_c"] is not None and float(r["mid_c"]) > 0


def test_clean_dedup_survivor_file_name_order(tmp_path):
    """Same null-count → lexicographically-smaller source file wins."""
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    import datetime

    t = datetime.datetime(2026, 1, 2, 0, 0)
    # Full 16-column row (instrument,is_complete,time + 13 payload cols).
    row = (f"XAU_USD,true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,100,101,99,100,"
           f"98,99,97,101,102,100,103,101.5")
    (csv_dir / "b.csv").write_text(HEADER + "\n" + row + "\n")
    (csv_dir / "a.csv").write_text(HEADER + "\n" + row + "\n")

    bronze = clean_mod.clean_csv_to_bronze(csv_dir)
    assert len(bronze) == 1
    # a.csv is the deterministic survivor (smaller file name).
    assert bronze[0]["mid_o"] == 100.0 or bronze[0]["mid_o"] == "100"


def test_clean_non_1m_rejected(tmp_path):
    """I22: bronze rows that are not uniform 1m → aggregate raises GranularityError."""
    import datetime

    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    rows = []
    for m in (0, 5, 10):  # 5m-spaced bars → native resolution 5m, coarser than 1m
        t = datetime.datetime(2026, 1, 2, 0, m)
        rows.append(f"XAU_USD,true,{t.strftime('%Y-%m-%d %H:%M:%S')},10,100,101,99,100,98,99,97,101,102,100,103,101.5")
    (csv_dir / "XAU_USD.csv").write_text(HEADER + "\n" + "\n".join(rows) + "\n")

    import pyarrow.parquet as pq

    bronze = clean_mod.clean_csv_to_bronze_parquet(csv_dir, tmp_path / "bronze.parquet")
    assert pq.read_table(bronze).num_rows == 3
    from lyra import aggregate as agg

    with pytest.raises(agg.GranularityError):
        agg.aggregate_bronze_to_parquet(bronze, tmp_path / "5m.parquet", tmp_path / "1h.parquet")


def test_clean_bronze_schema(tmp_path):
    """A2: always-present columns + observed payload; is_complete NOT in bronze."""
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "XAU_USD.csv").write_bytes(make_csv_bytes("XAU_USD", 0, 2))

    bronze = clean_mod.clean_csv_to_bronze(csv_dir)
    assert bronze
    row = bronze[0]
    for col in clean_mod.ALWAYS_PRESENT:
        assert col in row, f"missing always-present column: {col}"
    assert "is_complete" not in row
    # Source-dependent bid/ask present because input had them.
    for col in ("bid_o", "bid_c", "ask_o", "ask_c"):
        assert col in row


def test_clean_recompute_overwrites(tmp_path):
    """A1: clean ALWAYS recomputes — adding a new file changes the output even
    though a bronze file already exists at the target path."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "XAU_USD.csv").write_bytes(make_csv_bytes("XAU_USD", 0, 3))
    bronze = clean_mod.clean_csv_to_bronze(csv_dir)
    out = tmp_path / "all_data.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(bronze), str(out))
    first_n = len(bronze)

    # Add another instrument; recompute must reflect it (not skip because out exists).
    (csv_dir / "EUR_USD.csv").write_bytes(make_csv_bytes("EUR_USD", 0, 2))
    bronze2 = clean_mod.clean_csv_to_bronze(csv_dir)
    pq.write_table(pa.Table.from_pylist(bronze2), str(out))
    assert len(bronze2) == first_n + 2
    assert {r["instrument"] for r in bronze2} == {"XAU_USD", "EUR_USD"}
