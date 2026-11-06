"""Clean: flat CSVs → bronze 1m Parquet (moneta ``load_data.py`` semantics).

Decision 0002 §3.3 / A2 / A1. Three deterministic rules (batch-3 A1, S2):

1. **``is_complete`` filter** — rows where ``is_complete`` is falsy are
   dropped (``COALESCE(is_complete, FALSE) = TRUE``).
2. **Dedup on ``(instrument, time)``** — duplicates (e.g. a ``prices_*``
   backfill overlapping the main CSV) resolve to a single **deterministic
   survivor**: non-null *payload* column count (desc) → source file name →
   original row order.
3. **Bronze schema** — the union of input columns **minus** ``is_complete``
   (it is consumed by step 1 and would be true for every bronze row).

Determinism (I18) is the whole point: the survivor rule must be total and
reproducible, so two runs over the same inputs produce row-identical bronze.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pull import iter_flat_csvs, read_csv_rows

# Bronze always-present columns (0002 A2). ``is_complete`` is deliberately
# NOT among them — it is a clean input, not a bronze output.
ALWAYS_PRESENT = ("instrument", "time", "volume", "mid_o", "mid_h", "mid_l", "mid_c")
REQUIRED_INPUT = ("instrument", "time", "is_complete")
# Payload columns considered for survivor ranking (excludes the keys + filter).
PAYLOAD = ("volume", "mid_o", "mid_h", "mid_l", "mid_c",
           "bid_o", "bid_h", "bid_l", "bid_c",
           "ask_o", "ask_h", "ask_l", "ask_c")


class CleanInputError(ValueError):
    """A flat CSV is missing a required input column (0002 §3.3)."""


@dataclass
class Row:
    instrument: str
    time: str
    values: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    row_index: int = 0

    def nonnull_payload_count(self) -> int:
        return sum(1 for col in PAYLOAD if self.values.get(col) not in (None, ""))

    def survivor_key(self) -> tuple[int, str, int]:
        # Min key wins: fewest nulls first, then lexicographic file, then row.
        return (-self.nonnull_payload_count(), self.source_file, self.row_index)


def _truthy(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "t")
    return bool(value)


def _iter_rows(csv_dir: Path):
    for path in iter_flat_csvs(csv_dir):
        for index, raw in enumerate(read_csv_rows(path)):
            yield path.name, index, raw


def clean_csv_to_bronze(csv_dir: str | Path) -> list[dict[str, Any]]:
    """Apply the three clean rules and return bronze rows (list of dicts).

    The bronze column set is the union of ``ALWAYS_PRESENT`` and any payload
    columns actually seen, ordered deterministically; ``is_complete`` is
    dropped. Rows are ordered by ``(instrument, time)`` for reproducibility.
    """
    csv_dir = Path(csv_dir)
    survivors: dict[tuple[str, str], Row] = {}
    observed_payload: set[str] = set()

    for source_file, index, raw in _iter_rows(csv_dir):
        # Validate required columns exist on this file's header.
        present = {str(k) for k in raw.keys()}
        missing = [c for c in REQUIRED_INPUT if c not in present]
        if missing:
            raise CleanInputError(
                f"{source_file} is missing required column(s): {', '.join(missing)}"
            )

        if not _truthy(raw.get("is_complete")):
            continue  # rule 1: is_complete filter

        instrument = str(raw.get("instrument"))
        time = str(raw.get("time"))
        key = (instrument, time)

        values = {str(k): v for k, v in raw.items() if str(k) not in ("is_complete", "instrument", "time")}
        for col in PAYLOAD:
            if col in values:
                observed_payload.add(col)

        row = Row(instrument=instrument, time=time, values=values,
                  source_file=source_file, row_index=index)
        current = survivors.get(key)
        if current is None or row.survivor_key() < current.survivor_key():
            survivors[key] = row  # rule 2: deterministic survivor

    bronze_columns = list(ALWAYS_PRESENT)
    for col in sorted(observed_payload):
        if col not in bronze_columns:
            bronze_columns.append(col)

    bronze: list[dict[str, Any]] = []
    for (instrument, time) in sorted(survivors.keys()):
        row = survivors[(instrument, time)]
        record = {"instrument": instrument, "time": time}
        for col in bronze_columns:
            if col in ("instrument", "time"):
                continue
            record[col] = row.values.get(col)
        bronze.append(record)
    return bronze


def bronze_columns(bronze_rows: list[dict[str, Any]]) -> list[str]:
    """Deterministic bronze column order (0002 A2)."""
    if not bronze_rows:
        return list(ALWAYS_PRESENT)
    return list(bronze_rows[0].keys())


def bronze_json(rows: list[dict[str, Any]]) -> str:
    """A deterministic, human-readable serialization (for tests / previews)."""
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=2)
