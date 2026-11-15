"""D6 (审查#128) — batch proposal bundle: one file the web-AI writes, the
coding-AI applies mechanically.

Shape (a single YAML file):

    version: 1
    generated_at: "2026-11-15"          # informational
    directions:
      - direction: fx-trend
        track: t1
        branch: v05                     # must be a NEW slug (immutable branches)
        driven_by_lesson: "L4"          # required for vNN (N>=2)
        parent: v01                     # optional; default = the v01 baseline
        strategy: |
          version: 1
          id: ...
          direction: fx-trend
          ...full strategy YAML...

The bundle is a PROPOSAL, not a command: ``apply_batch`` validates every
item **before** writing anything (stage 2), then adopts + optionally runs
each (stage 3/4). A single invalid item rejects the whole batch (nothing is
written), so the web-AI's "I proposed 3, 1 was bad" never becomes a
half-applied state on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class BatchError(Exception):
    """A batch file is malformed (not per-item — that is a per-item error)."""


@dataclass
class BatchItem:
    direction: str
    track: str
    branch: str
    driven_by_lesson: str | None
    parent: str | None
    hypothesis: str | None
    strategy_text: str          # the raw YAML block
    index: int = 0              # 0-based position in the bundle


@dataclass
class BatchResult:
    items: list[BatchItem] = field(default_factory=list)
    # stage 2: items that failed parse/compile (rejected — nothing written)
    invalid: list[tuple[BatchItem, str]] = field(default_factory=list)
    # stage 3: items that were adopted (path on disk)
    adopted: list[tuple[BatchItem, Path]] = field(default_factory=list)
    # stage 4: per-item run outcome (only when run=True)
    run_status: list[tuple[BatchItem, str, str]] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        return not self.invalid

    def summary_lines(self) -> list[str]:
        out = [
            "── batch summary ──────────────────────────────────────────────",
            f"{len(self.items)} proposed · "
            f"{len(self.adopted)} adopted · {len(self.invalid)} rejected"
            + (" · not run" if not self.run_status else ""),
        ]
        for it, err in self.invalid:
            out.append(f"  [INVALID] {it.direction}/{it.track}/{it.branch}: {err}")
        for it, p in self.adopted:
            out.append(f"  [OK]      {it.direction}/{it.track}/{it.branch} -> {p}")
        return out


def parse_batch(text: str) -> list[BatchItem]:
    """Parse a bundle file into items. Raises BatchError on malformed shape.

    Per-item *content* errors (invalid strategy YAML, unknown feature, …)
    are NOT raised here — those are detected in stage 2 (``apply_batch``)
    so that all items can be reported in one pass.
    """
    import yaml as _yaml
    data = _yaml.safe_load(text)
    if not isinstance(data, dict):
        raise BatchError("batch file root must be a mapping")
    if data.get("version") not in (1, None):
        raise BatchError(f"unsupported batch version {data.get('version')!r} (expected 1)")
    raw = data.get("directions")
    if not isinstance(raw, list) or not raw:
        raise BatchError("batch file must have a non-empty 'directions' list")
    items: list[BatchItem] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise BatchError(f"directions[{i}] must be a mapping")
        for required in ("direction", "track", "branch", "strategy"):
            if entry.get(required) in (None, ""):
                raise BatchError(
                    f"directions[{i}] is missing required field {required!r}"
                )
        items.append(BatchItem(
            direction=str(entry["direction"]),
            track=str(entry["track"]),
            branch=str(entry["branch"]),
            driven_by_lesson=(str(entry["driven_by_lesson"]).strip()
                              if entry.get("driven_by_lesson") else None),
            parent=(str(entry["parent"]).strip()
                    if entry.get("parent") else None),
            hypothesis=(str(entry["hypothesis"]).strip()
                        if entry.get("hypothesis") else None),
            strategy_text=str(entry["strategy"]),
            index=i,
        ))
    return items
