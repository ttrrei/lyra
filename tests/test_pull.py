"""0002 required test — zip → flat CSV extraction (collision-safe)."""

from __future__ import annotations

import zipfile

import pytest

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


def _corrupt_zip(path, filename: str, payload: bytes) -> None:
    """Write a zip whose stored data byte is corrupted, so ``testzip()``
    deterministically reports a CRC mismatch (flip the first stored byte)."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr(filename, payload)
    raw = bytearray(buf.getvalue())
    # Local header (30 bytes) + filename = start of the stored payload; flip
    # its first byte so the CRC no longer matches.
    data_start = 30 + len(filename)
    raw[data_start] ^= 0xFF
    path.write_bytes(bytes(raw))


def test_pull_strict_fails_on_corrupt_archive_before_clear(tmp_path):
    """R2: strict mode must raise CorruptArchiveError *before* clearing the
    target, so prior good data is not wiped into an empty result. Legacy
    (non-strict) mode still skips the corrupt archive."""
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    # Pre-existing good data that a naive extract would wipe.
    good = csv_dir / "prior_good.csv"
    good.write_bytes(make_csv_bytes("XAU_USD", 0, 1))
    assert good.exists()

    zips = tmp_path / "zips"
    zips.mkdir()
    _corrupt_zip(zips / "bad.zip", "bad.csv", make_csv_bytes("XAU_USD", 0, 1))

    # strict: raises before clearing — prior good CSV survives untouched.
    with pytest.raises(pull.CorruptArchiveError):
        pull.extract_zips_to_csv(zips, csv_dir, clean_target=True, strict=True)
    assert good.exists()

    # legacy tolerant mode: skips the corrupt archive, clears target, yields [].
    out = pull.extract_zips_to_csv(zips, csv_dir, clean_target=True, strict=False)
    assert out == []
