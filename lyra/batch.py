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
    try:
        data = _yaml.safe_load(text)
    except _yaml.YAMLError as exc:  # #131 B5: no raw traceback on malformed YAML
        raise BatchError(
            f"bundle YAML parse error (fix the YAML syntax): {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise BatchError("batch file root must be a mapping")
    if data.get("version") not in (1, None):
        raise BatchError(f"unsupported batch version {data.get('version')!r} (expected 1)")
    # #131 (P0-2/P-3/B1): accept the three documented top-level key spellings so
    # a web-AI reading ai_readme.md (which shows `bundle:`) is not rejected by
    # the parser (which historically wanted `directions:`). First present wins.
    raw = None
    item_label = "directions"
    for key, label in (("bundle", "bundle"), ("directions", "directions"),
                       ("items", "items")):
        candidate = data.get(key)
        if isinstance(candidate, list):
            raw = candidate
            item_label = label
            break
    if raw is None:
        present = [k for k in ("bundle", "directions", "items") if k in data]
        raise BatchError(
            "batch file must have a non-empty item list under 'bundle', "
            f"'directions' or 'items' (found keys: {present or 'none'})"
        )
    if not raw:
        raise BatchError(f"the '{item_label}' list must not be empty")
    items: list[BatchItem] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise BatchError(f"{item_label}[{i}] must be a mapping")
        for required in ("direction", "track", "branch", "strategy"):
            if entry.get(required) in (None, ""):
                raise BatchError(
                    f"{item_label}[{i}] is missing required field {required!r}"
                )
        strategy_raw = entry["strategy"]
        if isinstance(strategy_raw, str):
            strategy_text = strategy_raw
        elif isinstance(strategy_raw, dict):
            # #131 (P-4/B7): a web-AI very naturally writes `strategy:` as a
            # nested mapping. str(dict) would store a Python repr (None->'None',
            # real newlines escaped, backslashes doubled). Normalise with a
            # round-trip-safe YAML dump so the stored text is lossless.
            strategy_text = _yaml.safe_dump(strategy_raw, sort_keys=False,
                                            allow_unicode=True)
        else:
            raise BatchError(
                f"{item_label}[{i}].strategy must be a YAML block string or a "
                f"mapping (got {type(strategy_raw).__name__})"
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
            strategy_text=strategy_text,
            index=i,
        ))
    return items
