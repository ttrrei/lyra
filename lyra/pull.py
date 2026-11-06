"""Pull: unpack OCI archives into a flat CSV directory (moneta-equivalent).

Decision 0002 §3.1: equivalent of moneta's ``extract_all_zips_to_csv`` —
recursively unzip every ``*.zip`` under the archive dir and place all CSVs
into a single flat directory, resolving name collisions with an ``_N``
suffix. Re-runs clear only the **top-level** CSVs they manage (sub-directories
are left alone: they may hold data from other sources).
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from typing import Iterator


def iter_zip_csvs(zips_dir: Path):
    """Yield ``(zip_path, zipinfo)`` for every CSV member of every zip.

    A member is a CSV if it has a ``.csv`` extension and is not a directory.
    """
    for zip_path in sorted(Path(zips_dir).rglob("*.zip")):
        with zipfile.ZipFile(zip_path, "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if Path(info.filename).suffix.lower() == ".csv":
                    yield zip_path, info


def unique_target(target_dir: Path, preferred_name: str) -> Path:
    """A non-colliding path under *target_dir* for *preferred_name*."""
    candidate = target_dir / preferred_name
    if not candidate.exists():
        return candidate
    stem = Path(preferred_name).stem
    suffix = Path(preferred_name).suffix
    counter = 1
    while True:
        candidate = target_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def clear_top_level_csvs(target_dir: Path) -> None:
    """Remove only top-level ``*.csv`` files in *target_dir* (not sub-dirs)."""
    if not target_dir.exists():
        return
    for child in target_dir.iterdir():
        if child.is_file() and child.suffix.lower() == ".csv":
            child.unlink()


def extract_zips_to_csv(
    zips_dir: str | Path,
    csv_dir: str | Path,
    *,
    clean_target: bool = True,
) -> list[Path]:
    """Extract every CSV from every zip into a flat *csv_dir*.

    Returns the sorted list of extracted file paths. Corrupt archives are
    skipped (a per-archive ``testzip`` check) rather than aborting the run.
    """
    source_dir = Path(zips_dir)
    target_dir = Path(csv_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if clean_target:
        clear_top_level_csvs(target_dir)

    extracted: list[Path] = []
    for zip_path, info in iter_zip_csvs(source_dir):
        with zipfile.ZipFile(zip_path, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                continue  # corrupt archive — skip, don't abort
            preferred = Path(info.filename).name
            dest = unique_target(target_dir, preferred)
            with archive.open(info) as src, dest.open("wb") as out:
                while True:
                    chunk = src.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            extracted.append(dest)
    return sorted(extracted, key=lambda p: p.as_posix())


def iter_flat_csvs(csv_dir: str | Path):
    """Yield every top-level ``*.csv`` path in *csv_dir* (sorted).

    The instrument is read from each row's ``instrument`` **column** (the
    authoritative source), never inferred from the file name — a collision
    suffix like ``EUR_USD_2.csv`` does not change the instrument.
    """
    target_dir = Path(csv_dir)
    if not target_dir.exists():
        return
    for child in sorted(target_dir.iterdir()):
        if child.is_file() and child.suffix.lower() == ".csv":
            yield child


def read_csv_rows(path: Path) -> Iterator[dict[str, object]]:
    """Read a CSV into a list of dicts (first row is the header)."""
    with path.open("r", newline="") as fh:
        yield from csv.DictReader(fh)
