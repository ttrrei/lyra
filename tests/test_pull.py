"""0002 required test — zip → flat CSV extraction (collision-safe)."""

from __future__ import annotations

import zipfile

from conftest import make_csv_bytes
from lyra import pull


def _write_zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)


def test_pull_zip_to_flat_csv(tmp_path):
    """Two zips, one shared member name → flat CSV dir with _1 collision suffix."""
    zips = tmp_path / "zips"
    zips.mkdir()
    _write_zip(zips / "a.zip", {"XAU_USD.csv": make_csv_bytes("XAU_USD", 0, 3)})
    _write_zip(zips / "b.zip", {"XAU_USD.csv": make_csv_bytes("XAU_USD", 3, 3),
                                "EUR_USD.csv": make_csv_bytes("EUR_USD", 0, 2)})

    csv_dir = tmp_path / "csv"
    out = pull.extract_zips_to_csv(zips, csv_dir, clean_target=True)

    names = sorted(p.name for p in out)
    assert "EUR_USD.csv" in names
    # XAU_USD.csv appears twice → second one gets a _N suffix.
    assert sum(1 for n in names if n.startswith("XAU_USD")) == 2
    # No nested directories leaked into the flat target.
    assert all(p.parent == csv_dir for p in out)
    # Re-running (clean_target=True) clears stale top-level CSVs first, so the
    # final set is exactly the source set again (idempotent at this layer).
    out2 = pull.extract_zips_to_csv(zips, csv_dir, clean_target=True)
    assert sorted(p.name for p in out2) == names


def test_pull_instrument_from_column_not_filename(tmp_path):
    """The instrument is the CSV column value, never inferred from the file name."""
    zips = tmp_path / "zips"
    zips.mkdir()
    # A collision-suffixed file whose column says XAU_USD.
    _write_zip(zips / "a.zip", {"whatever.csv": make_csv_bytes("XAU_USD", 0, 1)})
    csv_dir = tmp_path / "csv"
    pull.extract_zips_to_csv(zips, csv_dir)
    import csv as _csv

    for p in csv_dir.glob("*.csv"):
        with p.open() as fh:
            row = next(_csv.DictReader(fh))
        assert row["instrument"] == "XAU_USD"
