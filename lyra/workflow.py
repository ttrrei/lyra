"""R12 interactive workflow (decision 0007 Part B).

Direction-scoped research organization on top of 0006 run artifacts:

* **tracks** — research *identity* (not execution identity, I18): a track
  freezes a read-only baseline snapshot (hypothesis hash + feature
  catalog/version + engine/compiler versions) at creation time.
* **active-branch cap** — **8 active branches per track** (I21, O13); the
  only machine gate 0007 introduces (D6). Tracks never crowd each other's
  quota (per-track counting).
* **context** — a single-file, track-scoped context package; ``context
  --track A`` never reads track B's drafts/lessons (I18 isolation).
* **new-version** — derive a branch template (``vNN.yaml`` skeleton with
  ``parent``/``driven_by_lesson`` placeholders, reusing 0004's provenance
  fields) and register it as active in the direction's index.
* **compare / merge / synthesize** — read-only evidence (I22): ``compare``
  reads 0006 ``metrics.json`` and emits an evidence table; ``merge`` only
  *adds* a candidate branch, never touching source branches; ``synthesize``
  writes a cross-track report under ``reviews/`` and nothing else.

Workspace layout (local; the canonical OCI layout is 0007 D7 and is handled
by the push side):

    strategies/<direction>/hypothesis.md
    strategies/<direction>/lessons.md
    strategies/<direction>/vNN.yaml
    strategies/<direction>/index/t<track>.json    (track's active branches)
    tracks/<direction>/<track_id>.json            (frozen baseline)
    runs/<name>/<YYYYMMDD>/<run_id>/metrics.json  (0006 artifacts)
    reviews/synthesize-<timestamp>.md
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .features import FEATURE_VERSION
from .runner import _ENGINE_VERSION

#: I21 (D6, O13): the ONLY machine gate 0007 introduces.
MAX_ACTIVE_BRANCHES_PER_TRACK = 8

# requirements R12: version tree — v01, v02a, v02b (same-generation siblings),
# v04ab (cross branch). Generation is v+number; sibling/cross suffixes are
# lowercase letters. The I17 classifier (oci_push._VNN_RE) must accept the
# same set, otherwise a branch the tool produces is unpushable (H5).
_BRANCH_RE = re.compile(r"^v\d+[a-z]*$")
_VNN_FILE_RE = re.compile(r"^v(\d+)[a-z]*\.yaml$")
_TRACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# O12 (user ruling): versioned branches may carry a variant ordinal suffix
# ``_1`` / ``_2`` (e.g. v04ab_1) — the parameter-variant series for one
# strategy. Letter suffixes (v02a/v04ab) remain the AI-identity axis.
_BRANCH_NAME_RE = re.compile(r"^v\d+[a-z]*(_\d+)?$")
# DEV-01 (UsageLastReview #2): a SINGLE generation parser. The old gate used
# `_VNN_FILE_RE` (no `(_\d+)?`), so a legal branch like `v02_1` (O12 variant
# suffix) passed `_BRANCH_NAME_RE` but was invisible to the lineage gate — a
# fail-OPEN bypass of both the v01-reservation and the parent/lesson
# requirements. This extracts the leading generation number from ANY name
# `_BRANCH_NAME_RE` accepts, so every legal branch is gated consistently.
_BRANCH_GEN_RE = re.compile(r"^v(\d+)")


def branch_generation(slug: str) -> int | None:
    """The generation (leading vNN number) of a branch slug, or ``None``.

    Recognizes exactly the names `_BRANCH_NAME_RE` accepts (``v02``, ``v02a``,
    ``v04ab_1`` …).  Returns the numeric generation so the lineage gate can
    treat ``v02_1`` the same as ``v02`` (N>=2 → gated) and ``v01_1`` the same
    as ``v01`` (N==1 → reserved baseline).
    """
    # P2-5: fullmatch — ``$`` in re.match still accepts a trailing newline.
    if not _BRANCH_NAME_RE.fullmatch(slug):
        return None
    m = _BRANCH_GEN_RE.match(slug)  # prefix match (no $ anchor) — stays .match
    return int(m.group(1)) if m else None
# direction/track/branch/run identifiers are single path components: no
# separators, no dot segments (H4 — a "../x" direction would escape the
# workspace root).
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_IDENT_BAD = ("..", ".")


class WorkflowError(RuntimeError):
    """A fail-closed workflow error (D9): duplicate IDs, cap overflow,
    missing direction, unresolvable baseline pieces."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _yaml_quote(value: str) -> str:
    """Render *value* as a single-quoted YAML scalar that always parses.

    H3 (2026-11-15): strategy YAML is generated with free-text audit fields
    (``driven_by_lesson``) that the author fills in. A bare string containing
    ``:`` ``<`` ``>`` or leading punctuation breaks YAML parsing and fails
    ``lyra validate``. Single-quoting (with embedded single-quotes doubled —
    the YAML 1.1 escape) keeps any lesson text valid and round-trips to the
    same string.
    """
    return "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Tracks (research identity, I18)
# ---------------------------------------------------------------------------


def _baseline_for_direction(workspace: Path, direction: str) -> dict[str, Any]:
    """Freeze the read-only baseline snapshot (综合稿 §9.1).

    Captures: hypothesis hash (if present), feature catalog/version, engine
    and compiler versions. Missing pieces are recorded as ``None`` (a
    direction without a hypothesis file yet is legal); nothing is invented.
    """
    d = workspace / "strategies" / direction
    if not d.is_dir():
        raise WorkflowError(f"unknown direction '{direction}': no strategies/{direction}/ at {d}")
    baseline: dict[str, Any] = {}

    hyp = d / "hypothesis.md"
    if hyp.exists():
        hbytes = hyp.read_bytes()
        baseline["hypothesis_sha256"] = hashlib.sha256(hbytes).hexdigest()
        # 0009 D1: freeze the FULL hypothesis text, not just its hash — the
        # frozen baseline must survive later edits to hypothesis.md
        # (overall-design review R1: hash-only "freezing" meant context
        # rendering silently drifted with the live file).
        baseline["hypothesis_snapshot"] = hbytes.decode("utf-8", errors="replace")
    else:
        baseline["hypothesis_sha256"] = None
        baseline["hypothesis_snapshot"] = None

    # M1 (batch2): the real feature catalog is the DuckDB file under the data
    # root (``lyra/catalog.py`` → ``<data_dir>/catalog.duckdb``), NOT the
    # ``data/features/catalog.json`` that the first draft referenced. Prefer
    # the real catalog; fall back to the (rare) JSON form.
    # M1 (batch2): the real feature catalog is the DuckDB file under the data
    # root (``lyra/catalog.py`` → ``<data_dir>/catalog.duckdb``), NOT the
    # ``data/features/catalog.json`` that the first draft referenced. Prefer
    # the real catalog; fall back to the (rare) JSON form.
    real_catalog = None
    from .catalog import default_catalog_path

    for _dd in (workspace / "data", workspace):
        _cp = default_catalog_path(_dd)
        if _cp.is_file():
            real_catalog = _cp
            break
    if real_catalog is not None:
        baseline["feature_catalog_sha256"] = hashlib.sha256(real_catalog.read_bytes()).hexdigest()
        baseline["feature_catalog_entry"] = str(real_catalog)
    else:
        legacy = workspace / "data" / "features" / "catalog.json"
        if legacy.exists():
            c = _load_json(legacy)
            baseline["feature_catalog_sha256"] = hashlib.sha256(legacy.read_bytes()).hexdigest()
            baseline["feature_catalog_entry"] = c if isinstance(c, (dict, list)) else None
        else:
            baseline["feature_catalog_sha256"] = None
            baseline["feature_catalog_entry"] = None
    baseline["feature_version"] = FEATURE_VERSION

    # Execution-rule versions (D5 attribution).
    baseline["engine_version"] = _ENGINE_VERSION
    try:
        from . import compiler

        baseline["compiler_version"] = getattr(compiler, "COMPILER_VERSION", None)
    except Exception:  # pragma: no cover - defensive: version constant moved
        baseline["compiler_version"] = None
    return baseline


def track_path(workspace: Path, direction: str, track_id: str) -> Path:
    return workspace / "tracks" / direction / f"{track_id}.json"


def track_index_path(workspace: Path, direction: str, track_id: str) -> Path:
    """Track event log (JSONL, append-only under I17).

    Each line is an independent event record. State transitions (activate /
    prune) APPEND a new line — never rewrite earlier lines — so the file is
    a verbatim line-superset of every previous version and therefore pushable
    (批次2-H10: the old mutable ``{"active": [...]}`` snapshot broke the
    append-only gate on the first fork/prune).

    RED-02 (UsageLastReview #2): this is the SINGLE choke point through which
    every read/write path helper builds a workspace-relative path (read_index_
    events, _track_active, get_track, _append_index_event, prune_branch, …).
    Validate direction + track_id HERE, and assert the resolved path stays
    inside the workspace tree — so an untrusted "../outside", "a/b", "." or
    absolute direction/track can never escape the workspace at ANY boundary,
    not just the CLI layer.
    """
    validate_ident(direction, "direction")
    _validate_track_id(track_id)
    p = workspace / "strategies" / direction / "index" / f"t{track_id}.jsonl"
    # Containment: the resolved path must remain under the resolved workspace.
    root = Path(workspace).resolve()
    resolved = p.resolve()
    if root != resolved and root not in resolved.parents:
        raise WorkflowError(
            f"track index path escapes the workspace: {resolved!r} is not "
            f"under {root!r}")
    return p


def read_index_events(workspace: Path, direction: str, track_id: str) -> list[dict[str, Any]]:
    """Parse the track event log; [] if absent or unreadable."""
    p = track_index_path(workspace, direction, track_id)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
            if isinstance(rec, dict):
                out.append(rec)
        except Exception:  # tolerate a truncated final line, never crash
            continue
    return out


def active_branches_of(events: list[dict[str, Any]]) -> list[str]:
    """Replay activate/prune events in order → current active branch list."""
    active: list[str] = []
    for e in events:
        op = e.get("op")
        if op == "create_track":
            active = list(e.get("active", []))  # seed (normally empty)
        elif op == "activate":
            b = e.get("branch")
            if b and b not in active:
                active.append(b)
        elif op == "prune":
            b = e.get("branch")
            if b in active:
                active.remove(b)
    return active


def _validate_track_id(track_id: str) -> None:
    # P2-5: fullmatch — ``$`` in re.match still accepts a trailing newline.
    if not _TRACK_ID_RE.fullmatch(track_id):
        raise WorkflowError(
            f"invalid track id {track_id!r} — use lowercase alnum/_/- (I18 fail-fast)"
        )


def validate_ident(ident: str, what: str = "identifier") -> None:
    """Single-path-component check for direction/track/branch/run ids (H4).

    Rejects separators, dot segments and empty names so a value like
    ``../outside`` or ``a/b`` can never escape the workspace root when
    joined into a file path.
    """
    # P2-5: fullmatch — ``$`` in re.match still accepts a trailing newline
    # ("abc\n"), which would become a hostile filename on disk.  This is the
    # shared choke point for direction/track/branch/run-name validation, so the
    # fix covers all of them at once.
    if not isinstance(ident, str) or not _IDENT_RE.fullmatch(ident) or ident in _IDENT_BAD:
        raise WorkflowError(
            f"invalid {what} {ident!r} — use a single path component "
            f"(alnum/_/-, no separators, no '.') "
        )


def archive_batch_attempt(workspace: Path, direction: str, track_id: str,
                          bundle_text: str, result_text: str) -> Path:
    """Write one private, monotonically numbered batch record in the workspace."""
    validate_ident(direction, "direction")
    validate_ident(track_id, "track")
    root = Path(workspace).resolve()
    folder = Path(workspace) / "research-batches" / direction / track_id
    resolved = folder.resolve()
    if root != resolved and root not in resolved.parents:
        raise WorkflowError(f"batch archive path escapes workspace: {resolved!r}")
    folder.mkdir(parents=True, exist_ok=True)
    resolved = folder.resolve()
    if root != resolved and root not in resolved.parents:
        raise WorkflowError(f"batch archive path escapes workspace: {resolved!r}")
    import os

    numbers = []
    for p in folder.glob("batch-*"):
        m = re.match(r"batch-(\d{4,})(?:\.|-)", p.name)
        if m:
            numbers.append(int(m.group(1)))
    number = max(numbers, default=0) + 1
    while True:
        stem = f"batch-{number:04d}"
        reservation = folder / f"{stem}.reserved"
        try:
            fd = os.open(reservation, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            break
        except FileExistsError:
            number += 1
    bundle_path = folder / f"{stem}.yaml"
    result_path = folder / f"{stem}-result.md"
    try:
        with bundle_path.open("x", encoding="utf-8") as fh:
            fh.write(bundle_text)
        with result_path.open("x", encoding="utf-8") as fh:
            fh.write(result_text)
    except Exception:
        # Keep the reservation so a partial archive can never be overwritten.
        raise
    reservation.unlink()
    return result_path


def create_track(workspace: Path, direction: str, track_id: str) -> dict[str, Any]:
    """Create a track and freeze its baseline (I18).

    Duplicate IDs fail fast — never overwrite, never auto-rename (D9 /
    综合稿 §9).
    """
    validate_ident(direction, "direction")
    _validate_track_id(track_id)
    tp = track_path(workspace, direction, track_id)
    if tp.exists():
        raise WorkflowError(
            f"track id already exists: {direction}/{track_id} — refusing to "
            f"overwrite (I18 fail-fast; create a new id instead)"
        )
    # H2 fix (2026-11-15): check ALL preconditions BEFORE writing any file.
    # Original code called _write_json(tp, record) before checking idx.exists(),
    # so on a synced machine the record was already written (with a re-frozen
    # baseline) by the time the error fired — silently destroying provenance.
    idx = track_index_path(workspace, direction, track_id)
    if idx.exists():
        raise WorkflowError(
            f"track index already exists for {direction}/{track_id} — "
            f"inconsistent state, refusing to clobber (I18 fail-fast)"
        )
    baseline = _baseline_for_direction(workspace, direction)
    record = {
        "direction": direction,
        "track_id": track_id,
        "created_at": _now_iso(),
        "active_branches": [],
        "baseline": baseline,
    }
    _write_json(tp, record)
    _append_index_event(workspace, direction, track_id,
                        {"op": "create_track", "direction": direction,
                         "track_id": track_id, "at": _now_iso()})
    return record


def _append_index_event(workspace: Path, direction: str, track_id: str,
                        event: dict[str, Any]) -> None:
    idx = track_index_path(workspace, direction, track_id)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def list_tracks(workspace: Path, direction: str) -> list[dict[str, Any]]:
    d = workspace / "tracks" / direction
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        rec = _load_json(p)
        out.append(rec)
    return out


def get_track(workspace: Path, direction: str, track_id: str) -> dict[str, Any]:
    # #131 (P0-4): fail-closed on path escapes before the path join — this
    # builds `workspace/tracks/<direction>/<track_id>.json` from caller input.
    validate_ident(direction, "direction")
    _validate_track_id(track_id)
    tp = track_path(workspace, direction, track_id)
    if not tp.exists():
        raise WorkflowError(f"unknown track: {direction}/{track_id}")
    return _load_json(tp)


def _track_active(workspace: Path, direction: str, track_id: str) -> list[str]:
    return active_branches_of(read_index_events(workspace, direction, track_id))


# ---------------------------------------------------------------------------
# Branch cap (I21 / D6 / O13) — the only 0007 machine gate
# ---------------------------------------------------------------------------


def count_active_branches(workspace: Path, direction: str, track_id: str) -> int:
    """Count active branches of *this track only* (per-track, I21)."""
    return len(_track_active(workspace, direction, track_id))


def enforce_branch_cap(workspace: Path, direction: str, track_id: str) -> None:
    n = count_active_branches(workspace, direction, track_id)
    if n >= MAX_ACTIVE_BRANCHES_PER_TRACK:
        raise WorkflowError(
            f"branch cap reached: track {direction}/{track_id} already has "
            f"{n} active branches (max {MAX_ACTIVE_BRANCHES_PER_TRACK}, I21) — "
            f"prune one explicitly before forking"
        )


def prune_branch(workspace: Path, direction: str, track_id: str, branch: str,
                 reason: str = "") -> None:
    """Explicitly drop a branch from the track's active list (cap relief).

    H10: appends a prune EVENT — earlier lines are never rewritten, so the
    JSONL stays a verbatim line-superset (I17 append-only) and the prune is
    pushable (the old snapshot rewrite was rejected by the gate).

    审查#128 D9.1: a ``reason`` (why this branch died) is recorded in the
    event so the digest's "tried" line can show ``pruned: <reason>`` — the
    next AI reads *why* a candidate was dropped, not just that it was.

    RED-02 (UsageLastReview #2): validate direction AND track_id here, not
    only in the CLI. This is a write boundary (``_append_index_event`` builds
    a path from all three); the CLI layer is defense-in-depth, not the
    authority.
    """
    validate_ident(direction, "direction")
    _validate_track_id(track_id)
    validate_ident(branch, "branch")
    if branch not in _track_active(workspace, direction, track_id):
        raise WorkflowError(f"branch {branch!r} is not active on track {track_id}")
    ev: dict[str, Any] = {"op": "prune", "branch": branch, "at": _now_iso()}
    if reason.strip():
        ev["reason"] = reason.strip()
    _append_index_event(workspace, direction, track_id, ev)


# ---------------------------------------------------------------------------
# new-version (branch derivation, reusing 0004 provenance fields)
# ---------------------------------------------------------------------------


def _parent_file(workspace: Path, direction: str, parent: str,
                 track: str | None = None) -> Path:
    """Resolve a parent branch to its strategy file.

    0009 D12: a parent may live in this track's directory (``<track>/vNN.yaml``)
    or at the direction level (the shared read-only baseline, e.g. ``v01.yaml``).
    """
    resolved = _branch_file(workspace, direction, parent, track)
    if resolved is not None:
        return resolved
    raise WorkflowError(f"parent branch '{parent}' not found under strategies/{direction}/")


def new_version(
    workspace: Path,
    direction: str,
    branch: str,
    *,
    track: str,
    parent: str | None = None,
    driven_by_lesson: str | None = None,
) -> Path:
    """Derive a new branch template (vNN.yaml skeleton) for *track*.

    Enforces the per-track 8-active cap (I21/D6). Reuses 0004's provenance
    fields ``parent``/``driven_by_lesson`` (0007 D8 reuse point). Duplicate
    branch IDs fail fast (D9) — never overwrite, never auto-rename.
    """
    # P2-5: fullmatch (re.match + $ still accepts a trailing newline).
    if not _BRANCH_NAME_RE.fullmatch(branch):
        raise WorkflowError(
            f"invalid branch name {branch!r} — branches are vNN with optional "
            f"lowercase sibling/cross suffix (v02a, v04ab) per requirements R12"
        )
    # M2 (审查#128): v01 is the direction-level shared read-only baseline —
    # a track must never own it (a candidate shadowing the baseline breaks
    # the common-ancestor contract). Candidates start at v02.
    # DEV-01 (UsageLastReview #2): use the single generation parser so the
    # `v01_1` variant is treated as generation 1 (reserved) here too,
    # consistent with the lineage gate — not just the plain `v01` file name.
    _gen = branch_generation(branch)
    if _gen is not None and _gen <= 1:
        raise WorkflowError(
            f"branch {branch} is the DIRECTION baseline generation (v01) and "
            f"is reserved — a track ({direction}/{track}) must not own it. "
            f"Start candidates at v02 (v02a/v02b/v02_1/…).")
    # NOTE (D7/D8): `new_version` is the *skeleton generator* — it may be
    # called before the author fills in `parent`/`driven_by_lesson` (the
    # template carries quoted placeholders that pass `lyra validate`). The
    # real lineage gate is `adopt_branch`/`submit`, which sees the final
    # strategy spec (see `_validate_new_branch_lineage`).
    validate_ident(direction, "direction")
    get_track(workspace, direction, track)  # must exist (I18 identity)
    if branch in _track_active(workspace, direction, track):
        raise WorkflowError(
            f"branch {branch!r} already exists on track {track} — duplicate id "
            f"(I18/D9 fail-fast: not overwriting, not auto-renaming)"
        )
    # 0009 D12 (H1): the duplicate check is track-scoped — a same-named
    # branch in ANOTHER track's directory is legal (each AI owns its own
    # branch sequence). Only this track's directory is exclusive. The
    # direction-level file is the shared read-only baseline and is never
    # written by new_version.
    track_dir = workspace / "strategies" / direction / track
    if (track_dir / f"{branch}.yaml").exists():
        raise WorkflowError(
            f"branch {branch!r} already exists on track {track} "
            f"(strategies/{direction}/{track}/{branch}.yaml) — duplicate id "
            f"(I18/D9 fail-fast: not overwriting, not auto-renaming)"
        )
    enforce_branch_cap(workspace, direction, track)

    slug = branch
    track_dir.mkdir(parents=True, exist_ok=True)
    target = track_dir / f"{slug}.yaml"  # duplicate already rejected above (D9)

    parent_slug = None
    if parent is not None:
        pfile = _parent_file(workspace, direction, parent, track)
        parent_slug = pfile.stem  # e.g. v03 or the branch slug

    # 审查 U2 (2026-11-14)：骨架必须 *通过 `lyra validate`* 才能被作者迭代。
    # 原模板三处非法：
    #   (1) `version: 0` —— version 是 *schema* 版本（strategy_schema.SCHEMA_VERSION=1），
    #       不是分支号；strategy_schema 强制 version == 1，故 0 直接触发
    #       "unsupported YAML schema version"，作者第一步就卡死。
    #   (2) 入场结构 `entry.long.feature:` 不是 parser 识别的形状，须为
    #       `entry.long.all: [{feature, op, value}]`（与 validate 通过的真实策略一致）。
    #   (3) `sma_20_above_sma_50` 未在任何 Registry 注册 → registry 检查失败。
    # 现改为：version=1 + 合法入场形状 + 用恒可解析的 OHLC 别名（close/open →
    # mid_c/mid_o，不依赖方向级特征注册），使骨架开箱即 validate 通过、可直接迭代。
    template_lines = [
        "# Lyra strategy — derived branch (0007 new-version)",
        f"# direction: {direction}",
        "# 骨架（0007 new-version）：已可通过 `lyra validate`。",
        "#   入场示例用 OHLC 别名 close/open（恒可解析）——请按你的假设改成真实",
        "#   特征/op/value（feature 必须是 Registry 已注册特征或 open/high/low/close）。",
        f"id: {slug}",
        f"direction: {direction}",
        "version: 1",
        "timeframe_minutes: 60",
        "entry:",
        "  long:",
        "    all:",
        "      - {feature: close, op: gt, value: open}   # TODO: 真实入场条件",
        "  short:",
        "    all:",
        "      - {feature: close, op: lt, value: open}   # TODO: 真实入场条件",
        "exit:",
        "  stop_loss_pct: 0.02",
        "execution:",
        "  spread_bps: 2",
    ]
    if parent_slug is not None:
        template_lines.append(f"parent: {parent_slug}")
        template_lines.append("parents:")
        template_lines.append(f"  - {parent_slug}")
    if driven_by_lesson is not None:
        template_lines.append(f'driven_by_lesson: {_yaml_quote(driven_by_lesson)}')
    elif parent_slug is not None:
        # R12 vNN≥2: placeholders required — the author fills them.
        # H3 fix (2026-11-15): the placeholder is a *quoted* string so the
        # generated skeleton parses as valid YAML (unquoted `<TODO: ...>` is a
        # YAML mapping error → `lyra validate` fails on the author's first run).
        template_lines.append(
            'driven_by_lesson: "TODO(必填): 用一句话写清这个分支由哪条教训驱动"'
        )
    target.write_text("\n".join(template_lines) + "\n", encoding="utf-8")

    # Register as active on the track: append ONE event line (H10 — the
    # JSONL keeps every earlier line verbatim, so it remains an I17
    # append-only file after every fork).
    rel = f"{track}/{slug}.yaml"  # path relative to strategies/<direction>/
    _append_index_event(workspace, direction, track, {
        "op": "activate", "branch": slug, "file": rel,
        "parent": parent_slug, "driven_by_lesson": driven_by_lesson,
        "at": _now_iso(),
    })

    # H1 (2026-11-15): the track record is a *frozen, immutable* baseline
    # snapshot (its provenance value). The active-branch state lives in the
    # append-only index JSONL (already written above), which is the real source
    # of truth that context()/enforce_branch_cap/active_branches read. The old
    # code re-wrote the record here to track `branches`, but (a) nothing ever
    # read that field, and (b) re-writing the frozen record made it mutable —
    # which would collide with the immutable OCI classification and, worse,
    # let a re-push after forking silently overwrite the baseline provenance.
    # So the record is written exactly once, in create_track, and left frozen.
    return target


# ---------------------------------------------------------------------------
# context (track-scoped, single-file package — I18 isolation)
# ---------------------------------------------------------------------------


def append_lesson(workspace: Path, direction: str, track_id: str, text: str) -> Path:
    """Append one lesson line to the track's lessons file (H6/I18 append-only).

    审查 #125 (web-AI loop): a lesson is the track's loop memory — the AI
    writes one back after each run so the *next* iteration's ``context``
    shows it. Append-only (I17-style, one line per lesson); no command could
    previously do this (it was a hand-edited file). The track must exist
    (I18 identity).
    """
    get_track(workspace, direction, track_id)  # must exist (I18 identity)
    # D8.2 (审查#128): a lesson is ONE line (the digest/context render the last
    # N lines as one entry each). Flatten embedded whitespace so a pasted
    # multi-line block cannot break the one-line-per-lesson invariant, strip
    # control characters, and cap length (a lesson that enters the next AI's
    # prompt is a data-in-prompt channel — keep it small and well-formed).
    text = " ".join(str(text).split())
    text = "".join(ch for ch in text if ch == " " or ch.isprintable())
    if len(text) > 300:
        text = text[:300].rstrip() + "…"
    if not text:
        raise WorkflowError("lesson text is empty — a lesson must say something")
    p = track_lessons_path(workspace, direction, track_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = _now_iso()[:19]
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    p.write_text(existing + f"{stamp}: {text}\n", encoding="utf-8")
    return p


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fallback_hypothesis(direction_dir: Path) -> str | None:
    """Fall back to the ``hypothesis:`` field in ``v01.yaml`` when no
    ``hypothesis.md`` exists (11/12 real directions have only the YAML field).
    Returns the text or ``None``."""
    v01 = direction_dir / "v01.yaml"
    if not v01.exists():
        return None
    try:
        import yaml as _y
        spec = _y.safe_load(v01.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    hyp = spec.get("hypothesis")
    return hyp.strip() if isinstance(hyp, str) and hyp.strip() else None


def _branch_ever_seen(events: list[dict[str, Any]], branch: str) -> bool:
    """True if *branch* was ever activated or pruned (slug already consumed)."""
    for e in events:
        if e.get("branch") == branch and e.get("op") in ("activate", "prune"):
            return True
    return False


def _validate_new_branch_lineage(workspace: Path, direction: str, track_id: str,
                                 branch: str, spec: Any) -> None:
    """M2 / R12 lineage gate, enforced at the ONE seam where a track branch is
    created (``adopt_branch``) — fail-closed, no exceptions.

    - **v01 is reserved** as the direction-level shared read-only baseline
      (``strategies/<direction>/v01.yaml``); a track must never own it.
      Rejecting it here means the direction baseline stays the common
      ancestor and a track's candidate can't silently shadow it.
    - **vNN (N>=2) must declare its provenance** (R12): a ``parent`` (or
      ``parents``) that resolves to the direction baseline (v01) or an existing
      track branch, AND a non-empty ``driven_by_lesson`` (a one-line pointer
      into lessons.md). No parent, or a parent naming a branch that doesn't
      exist, is rejected — you cannot fabricate a lineage by copying YAML.

    ``spec`` is the parsed ``StrategySpec`` (only ``.parents`` and
    ``.driven_by_lesson`` are read; typed ``Any`` to avoid a schema import
    cycle — ``parse_strategy`` guarantees both fields exist).
    """
    # DEV-01: use the SINGLE generation parser (covers v02_1, v04ab_1, …)
    # instead of `_VNN_FILE_RE` — the latter missed the O12 variant suffix and
    # let those slugs fail OPEN past both the reservation and provenance rules.
    n = branch_generation(branch)
    if n is None:
        return  # not a vNN slug (e.g. a direction-level slug) — nothing to gate
    if n <= 1:
        raise WorkflowError(
            f"branch {branch} is the DIRECTION baseline generation (v01) and "
            f"is reserved — a track (direction/{track_id}) must not own it. "
            f"Start this track's candidates at v02 (v02a/v02b/v02_1/…).")
    parents = tuple(getattr(spec, "parents", ()) or ())
    lesson = (getattr(spec, "driven_by_lesson", None) or "").strip()
    problems: list[str] = []
    if not parents:
        problems.append(
            f"a track branch vNN (v{n}) must declare its provenance: add "
            f"`parent: <父版本 slug>` (or `parents: [v01, …]`) — v01 is the "
            f"direction baseline, or an existing track branch.")
    else:
        for p in parents:
            # A valid parent resolves to the direction baseline (v01) or an
            # existing file on this track. Either must actually be present.
            baseline = workspace / "strategies" / direction / f"{p}.yaml"
            on_track = workspace / "strategies" / direction / track_id / f"{p}.yaml"
            if not (baseline.exists() or on_track.exists()):
                problems.append(
                    f"declared parent {p!r} does not exist as the direction "
                    f"baseline (strategies/{direction}/{p}.yaml) or on this "
                    f"track (strategies/{direction}/{track_id}/{p}.yaml).")
    if not lesson:
        problems.append(
            f"a track branch vNN (v{n}) must declare `driven_by_lesson:` — a "
            f"one-line pointer into lessons.md explaining what evidence drove "
            f"this candidate.")
    if problems:
        raise WorkflowError(
            f"branch {branch} on track {direction}/{track_id} rejected "
            f"(R12 lineage):\n  - " + "\n  - ".join(problems))


def adopt_branch(workspace: Path, direction: str, track_id: str, branch: str,
                 source_yaml: Path, spec: Any = None) -> Path:
    """Make the web-AI's strategy file the ACTUAL branch (审查 #125 gap #2,
    hardened by 审查#128 M1: **branch content is immutable**).

    A branch slug is a stable identity that historical runs point at
    (``run_meta.branch``). Overwriting ``v02a.yaml`` in place would silently
    change what those runs mean, and ``context`` would then show the new YAML
    next to the *old* runs — the AI would read stale evidence as current. So:

    - **new branch** → enforced against the 8-cap (I19), then the AI's
      (already-validated) YAML is written **atomically** (tmp + ``os.replace``)
      and one ``activate`` event is appended (I17 append-only).
    - **branch file already present, byte-identical** → **idempotent no-op**
      (same branch re-run; no write, no new event, no cap consumed).
    - **branch file already present, different bytes** → **fail-closed**: a
      branch is immutable; the AI must use a NEW branch slug (history is
      never mutated).
    - **slug already pruned** → **fail-closed**: slugs are never reused
      (a pruned branch is a historical record, not a reusable name).

    The cap check runs **only** for a genuinely new branch, so re-submitting
    an existing branch at 8/8 is allowed (it consumes no new slot).
    """
    # #131 (P0-4): fail-closed on ANY path-escape before the first path join.
    # This is the CORE write boundary — a bundle (or any caller) can pass an
    # arbitrary direction/track/branch, and `workspace / direction / track_id`
    # would otherwise let "../outside" or "a/b" escape the workspace.
    validate_ident(direction, "direction")
    _validate_track_id(track_id)
    get_track(workspace, direction, track_id)      # track must exist (I18)
    # P2-5: fullmatch (re.match + $ still accepts a trailing newline).
    if not _BRANCH_NAME_RE.fullmatch(branch):
        raise WorkflowError(f"invalid branch name '{branch}'")
    src = Path(source_yaml)
    if not src.exists():
        raise WorkflowError(f"source strategy file not found: {src}")
    track_dir = workspace / "strategies" / direction / track_id
    dest = track_dir / f"{branch}.yaml"

    # DEV-02/USER-01 (UsageLastReview #2): resolve the branch's CURRENT state
    # (active / pruned / orphan) BEFORE the idempotent no-op. The old order
    # checked `dest.exists()` + same-bytes first, so a PRUNED branch
    # re-submitted with identical bytes hit the no-op and returned "success"
    # while the branch stayed inactive — a silent false success. Now the
    # active/pruned state is authoritative.
    events = read_index_events(workspace, direction, track_id)
    active = active_branches_of(events)
    ever_seen = _branch_ever_seen(events, branch)

    if dest.exists():
        same = (_file_sha256(dest) == _file_sha256(src))
        if branch not in active:
            # The file is on disk but the branch is NOT currently active.
            # Either it was pruned (ever_seen) or it's an orphan (file written
            # but the activate event was never appended). Neither is a case for
            # a silent no-op.
            if ever_seen:
                raise WorkflowError(
                    f"branch {branch!r} was previously pruned on track "
                    f"{direction}/{track_id} — its slug is a historical record "
                    f"and can NOT be re-activated (even with identical content). "
                    f"Use a new branch slug (v02a → v02b)."
                )
            # orphan: file present, no activate/prune event — the previous
            # adopt's index append failed. Fail closed rather than silently
            # pretending it's active; the user must repair (see doctor).
            raise WorkflowError(
                f"branch {branch!r} file exists on track {direction}/{track_id} "
                f"but has NO activate event (orphan — a previous adopt wrote the "
                f"file but the index event was lost). It is NOT active. Use "
                f"`lyra doctor` to inspect, or register a new branch slug."
            )
        if same:
            # branch is active AND content is identical — idempotent no-op.
            # Safe to call repeatedly (no new cap slot, no new event).
            return dest
        raise WorkflowError(
            f"branch {branch!r} on track {direction}/{track_id} already exists "
            f"with different content — branches are IMMUTABLE (their historical "
            f"runs point at them). Do NOT overwrite: register a NEW branch slug "
            f"(e.g. v02a → v02b) with the changed strategy."
        )

    # --- slug consumed by a pruned branch (file already removed): reuse banned
    if ever_seen and branch not in active:
        raise WorkflowError(
            f"branch {branch!r} was previously pruned on track "
            f"{direction}/{track_id} — its slug is a historical record and can "
            f"NOT be re-activated. Use a new branch slug (v02a → v02b)."
        )

    # --- genuinely new branch: M2 lineage, then cap check + atomic write --
    _validate_new_branch_lineage(workspace, direction, track_id, branch, spec)
    enforce_branch_cap(workspace, direction, track_id)  # I19, fail-closed
    track_dir.mkdir(parents=True, exist_ok=True)
    # Atomic single-file write: tmp in the SAME dir + os.replace (no partial
    # file visible; a write that lands but whose index append fails is
    # detectable by doctor as an orphan YAML, never silent).
    content = src.read_text(encoding="utf-8")
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, dest)
    rel = f"{track_id}/{branch}.yaml"  # path relative to strategies/<direction>/
    _append_index_event(workspace, direction, track_id, {
        "op": "activate", "branch": branch, "file": rel,
        "source": str(src), "at": _now_iso(),
    })
    return dest


def track_lessons_path(workspace: Path, direction: str, track_id: str) -> Path:
    """Per-track lessons file (H6/I18: track A's context never reads track
    B's lessons; a shared direction-level lessons.md remains readable but is
    clearly labelled as shared)."""
    return workspace / "tracks" / direction / f"{track_id}.lessons.md"


def _branch_file(workspace: Path, direction: str, branch: str,
                 track: str | None = None) -> Path | None:
    """Resolve a branch to its YAML (0009 D12).

    Track-level layout: ``strategies/<direction>/<track>/<branch>.yaml``
    (track-owned, H1) takes precedence; the direction-level
    ``strategies/<direction>/<branch>.yaml`` remains the shared read-only
    baseline (e.g. the legacy v01) and is the fallback.
    """
    d = workspace / "strategies" / direction
    if track is not None:
        cand = d / track / f"{branch}.yaml"
        if cand.exists():
            return cand
    cand = d / f"{branch}.yaml"
    if cand.exists():
        return cand
    m = _VNN_FILE_RE.match(branch + ".yaml")
    if m:
        # legacy zero-padding variant (v1 -> v01.yaml)
        for root in (d / track, d) if track is not None else (d,):
            if not root.is_dir():
                continue
            for p in root.glob("*.yaml"):
                pm = _VNN_FILE_RE.match(p.name)
                if pm and int(pm.group(1)) == int(m.group(1)):
                    return p
    return None


def compute_cross_instrument_stats(run: dict[str, Any]) -> dict[str, Any]:
    """0014: Macro cross-instrument statistical summary for a strategy run.

    Pure in-memory projection over instruments and failures.
    - Universe denominator for profitable ratio = per_instrument keys ∪ instrument_failures
      (including zero-trade and failed instruments).
    - Medians: median_annualized, median_net_return, median_expectancy.
      Zero-trade instruments contribute 0.0 to annualized return.
    - Identifies worst-performing instrument by annualized return.
    - Tracks trade count sample size (<20 threshold) and completeness.
    """
    insts = run.get("instruments", [])
    failures = run.get("instrument_failures", [])
    inst_names = {i["instrument"] for i in insts if isinstance(i, dict) and "instrument" in i}
    fail_names = {f["instrument"] for f in failures if isinstance(f, dict) and "instrument" in f}
    universe = sorted(inst_names | fail_names)
    expected_count = len(universe)
    actual_count = len(inst_names)
    failure_count = len(fail_names)
    is_incomplete = (failure_count > 0) or (actual_count < expected_count)

    # profitable ratio: count(ann > 0) / len(universe)
    # 0014: denominator includes zero-trade and failed instruments
    profitable_count = sum(
        1 for i in insts
        if i.get("annualized") is not None and float(i["annualized"]) > 0.0
    )
    prof_ratio = (profitable_count / expected_count) if expected_count > 0 else 0.0

    ann_list: list[float] = []
    net_list: list[float] = []
    exp_list: list[float] = []
    worst_inst = None
    min_ann = float("inf")
    best_inst = None
    max_ann = float("-inf")
    total_trades = 0
    low_trade_count = 0

    for i in insts:
        tc = i.get("trade_count")
        tc_int = int(tc) if tc is not None else 0
        total_trades += tc_int
        if tc_int < 20:
            low_trade_count += 1

        ann = i.get("annualized")
        if ann is not None:
            ann_f = float(ann)
            ann_list.append(ann_f)
        elif tc_int == 0:
            ann_f = 0.0
            ann_list.append(ann_f)
        else:
            ann_f = None

        if ann_f is not None:
            if ann_f < min_ann:
                min_ann = ann_f
                worst_inst = {"instrument": i["instrument"], "annualized": ann_f}
            if ann_f > max_ann:
                max_ann = ann_f
                best_inst = {
                    "instrument": i["instrument"],
                    "annualized": ann_f,
                    "net_return": i.get("net_return"),
                    "trades": tc_int,
                }

        net = i.get("net_return")
        if net is not None:
            net_list.append(float(net))

        exp = i.get("expectancy")
        if exp is not None:
            exp_list.append(float(exp))

    median_ann = float(statistics.median(ann_list)) if ann_list else 0.0
    median_net = float(statistics.median(net_list)) if net_list else 0.0
    median_exp = float(statistics.median(exp_list)) if exp_list else 0.0

    return {
        "median_annualized": median_ann,
        "median_net_return": median_net,
        "median_expectancy": median_exp,
        "profitable_instrument_ratio": prof_ratio,
        "profitable_instruments_count": profitable_count,
        "expected_instruments_count": expected_count,
        "actual_instruments_count": actual_count,
        "failure_count": failure_count,
        "is_incomplete": is_incomplete,
        "worst_instrument": worst_inst,
        "best_single_instrument": best_inst,
        "total_trades": total_trades,
        "low_trade_instruments_count": low_trade_count,
    }


def render_digest(
    workspace: Path,
    direction: str,
    *,
    track: str | None = None,
    n_lessons: int = 3,
    standalone: bool = True,
    registry: Any | None = None,
) -> str:
    """A COMPACT (<~5KB) history digest of a direction/track (0014, 审查#128).

    ``render_context`` is the full self-contained package (hypothesis text,
    full YAML of every active branch, every run row). That is the right
    artifact for a coding AI that can open files — but a **web/chat AI**
    reading it in a chat window pays the full token cost every iteration.
    ``render_digest`` is the low-token view: one screen of *what this track
    is about*, *which branches are active*, and *what each has scored* —
    enough to decide "iterate / prune / try a new angle" without dumping a
    90KB report. Full detail is always one ``lyra context`` away.

    0014: Emits macro cross-instrument summary per branch (median_ann,
    median_net, median_exp, prof_ratio, worst instrument, trades sample size)
    and compresses per-instrument one-liners to keep an 8-branch pool <= ~5KB.

    Reads exactly the same sidecars/artifacts as ``render_context``; it is a
    projection of the same facts, not a second source of truth.
    """
    validate_ident(direction, "direction")
    d = workspace / "strategies" / direction
    # D-3 (UsageLastReview): when embedded in `digest --all`, use a level-2
    # heading (not a repeating H1) so the whole thing reads as one document.
    h = "##" if not standalone else "#"
    out: list[str] = [f"{h} digest — {direction}" + (f" / track {track}" if track else "")]

    # hypothesis — one line (the first non-empty line), not the full text
    hyp = d / "hypothesis.md"
    if hyp.exists():
        first = next((ln.strip() for ln in hyp.read_text(encoding="utf-8").splitlines()
                      if ln.strip()), "")
        # drop a leading '#' heading marker for brevity
        first = first.lstrip("# ").strip()
        out.append(f"hypothesis: {first[:160]}{'…' if len(first) > 160 else ''}")
    else:
        # fall back to the v01.yaml hypothesis field (11/12 real directions)
        fb = _fallback_hypothesis(d)
        if fb:
            out.append(f"hypothesis: {fb[:160]}{'…' if len(fb) > 160 else ''}  (from v01.yaml)")
        else:
            out.append("hypothesis: (none)")

    # D-3: the registered-feature count is GLOBAL (same for every direction),
    # so it's emitted once in the `digest --all` header (see cli.py) and only
    # repeated here in single-direction (standalone) mode.
    if standalone:
        from .features import build_registry
        feats = build_registry().names()
        out.append(f"features: {len(feats)} registered (FEATURE_VERSION={FEATURE_VERSION}) — "
                   f"see `lyra context {direction}` for the full list")

    tracks_list = list_tracks(workspace, direction)
    if track is not None:
        tracks_list = [t for t in tracks_list if t["track_id"] == track]
        if not tracks_list:
            raise WorkflowError(f"unknown track: {direction}/{track}")

    shared_lessons = d / "lessons.md"
    for t in tracks_list:
        tid = t["track_id"]
        active = _track_active(workspace, direction, tid)
        cap = MAX_ACTIVE_BRANCHES_PER_TRACK
        branch_signatures: dict[str, dict[str, Any]] = {}
        try:
            from .features import build_registry
            from .strategy_schema import parse_strategy, structural_signature
            reg = registry if registry is not None else build_registry()
            for branch_name in active:
                strategy_path = (workspace / "strategies" / direction / tid
                                 / f"{branch_name}.yaml")
                if not strategy_path.is_file():
                    strategy_path = workspace / "strategies" / direction / f"{branch_name}.yaml"
                if strategy_path.is_file():
                    spec = parse_strategy(str(strategy_path), reg)
                    branch_signatures[branch_name] = structural_signature(spec, reg)
        except Exception:
            # Alpha-only feature columns may be unavailable to the core digest;
            # signature hints are informative and must not break this read path.
            branch_signatures = {}
        out.append(f"\n## track {tid} — {len(active)}/{cap} active branches")
        for b in (active or ["(none)"]):
            runs = _runs_for_branch(workspace, direction, b, track=tid)
            if not runs:
                out.append(f"  {b}: (no runs yet)")
                continue
            last = runs[-1]
            insts = last.get("instruments", [])
            stats = compute_cross_instrument_stats(last)

            def _ann(v):
                try:
                    return f"{float(v):+.3f}"
                except (TypeError, ValueError):
                    return str(v)

            ann_str = _ann(stats["median_annualized"])
            net_str = _ann(stats["median_net_return"])
            exp_str = f"{stats['median_expectancy']:+.4f}"
            ratio_str = f"{stats['profitable_instruments_count']}/{stats['expected_instruments_count']}({stats['profitable_instrument_ratio'] * 100:.1f}%)"
            worst_str = (
                f"{stats['worst_instrument']['instrument']}({_ann(stats['worst_instrument']['annualized'])})"
                if stats["worst_instrument"]
                else "(none)"
            )
            inc_tag = " [INCOMPLETE]" if stats["is_incomplete"] else ""
            low_samp = f" <20={stats['low_trade_instruments_count']}" if stats['low_trade_instruments_count'] > 0 else ""
            out.append(
                f"  {b} [{len(runs)} run(s)]{inc_tag}: med_ann={ann_str} med_net={net_str} "
                f"med_exp={exp_str} prof_ratio={ratio_str} worst={worst_str} "
                f"trades={stats['total_trades']}{low_samp}"
            )
            inst_parts = " ".join(
                f"{i['instrument']}:{_ann(i.get('annualized'))}({i.get('trade_count', 0)})"
                for i in insts
            )
            out.append(f"    {inst_parts or '(no data)'}")
            own_sig = branch_signatures.get(b)
            peers = [(name, sig) for name, sig in branch_signatures.items()
                     if name != b]
            if own_sig and peers:
                from .strategy_schema import compare_structural_signatures
                ranked = [(name, compare_structural_signatures(own_sig, sig))
                          for name, sig in peers]
                rank = {"identical": 0, "parameter_only": 1,
                        "structural_change": 2}
                peer, relation = min(ranked, key=lambda row: rank[row[1]["classification"]])
                hint = (f"≈{peer}"
                        if relation["classification"] == "parameter_only"
                        else f"{relation['classification'][:3]}:{peer}")
                if relation["exit_structure_changed"]:
                    hint += "/exitΔ"
                out.append(f"   {hint}")
        # D9.3 (审查#128): pruned branches are where the track learned the
        # most — surface them (with the prune reason, if recorded) so the
        # next AI does not re-propose a dead end.
        events = read_index_events(workspace, direction, tid)
        pruned = []
        for e in reversed(events):  # most recent first
            if e.get("op") != "prune":
                continue
            reason = e.get("reason") or ""
            pruned.append(f"{e.get('branch')}" + (f" — {reason}" if reason else ""))
        if pruned:
            out.append("  pruned: " + " · ".join(pruned[:8]))
        t_lessons = track_lessons_path(workspace, direction, tid)
        if t_lessons.exists():
            lines = [ln for ln in t_lessons.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            for ln in lines[-max(1, n_lessons):]:
                out.append(f"  lesson: {ln}")
        if shared_lessons.exists():
            lines = [ln for ln in shared_lessons.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            for ln in lines[-max(1, n_lessons):]:
                out.append(f"  shared lesson: {ln}")

    out.append("\n→ full detail: `lyra context " + direction +
               (f" --track {track}" if track else "") + "`")
    return "\n".join(out) + "\n"


def render_context(
    workspace: Path,
    direction: str,
    *,
    track: str | None = None,
    n_lessons: int = 5,
) -> str:
    """Render the single-file context package (R12, self-contained per H6).

    The file must be enough for an AI to work on this track **without**
    opening anything else: full hypothesis text, the frozen baseline
    snapshot (feature version + catalog hash + engine/compiler versions),
    the feature list, every active branch's **full YAML**, per-track
    lessons (with the shared direction lessons clearly labelled), and the
    sibling run comparison. Track A's context never reads track B's
    drafts/lessons (I18).
    """
    validate_ident(direction, "direction")
    out: list[str] = [f"# context — {direction}"]
    out.append(f"generated_at: {_now_iso()}  (informational; context is not a push artifact)")
    d = workspace / "strategies" / direction

    # --- hypothesis: FULL text (not just a path/hash) + its hash ----------
    # 0009 D1 / R1: a track's baseline froze the hypothesis *text* at creation;
    # the context renders that frozen snapshot (not the live file) and flags
    # drift when the live file has since changed. Direction-level context
    # (no ``track``) still shows the live text, labelled as such.
    hyp = d / "hypothesis.md"
    live_text = hyp.read_text(encoding="utf-8").rstrip("\n") if hyp.exists() else None
    live_sha = hashlib.sha256(hyp.read_bytes()).hexdigest() if hyp.exists() else None

    tracks_list = list_tracks(workspace, direction)
    if track is not None:
        tracks_list = [t for t in tracks_list if t["track_id"] == track]
        if not tracks_list:
            raise WorkflowError(f"unknown track: {direction}/{track}")
        bl = tracks_list[0].get("baseline", {})
        snap = bl.get("hypothesis_snapshot")
        snap_sha = bl.get("hypothesis_sha256")
        out.append("\n## hypothesis (frozen at track creation)")
        if snap is None:
            out.append("(no hypothesis.md present when the track was created)")
            fb = _fallback_hypothesis(d)
            if fb:
                out.append("(baseline v01.yaml hypothesis — no frozen snapshot exists, shown for reference)")
                out.append("```")
                out.append(fb)
                out.append("```")
            if live_text is not None:
                out.append("(live file since created; shown for reference — NOT the frozen baseline)")
                out.append(f"(live sha256 {live_sha[:16]}…)")
                out.append("```")
                out.append(live_text)
                out.append("```")
        else:
            out.append(f"(frozen sha256 {str(snap_sha)[:16]}…)")
            if live_sha is not None and snap_sha is not None and live_sha != snap_sha:
                out.append("⚠ hypothesis has drifted since track creation — the frozen snapshot below is what this track's baseline references; the live file is shown separately for reference")
            out.append("```")
            out.append(snap.rstrip("\n"))
            out.append("```")
            if live_sha is not None and snap_sha is not None and live_sha != snap_sha:
                out.append("(live file, NOT the frozen baseline; sha256 "
                           f"{live_sha[:16]}…)")
                out.append("```")
                out.append(live_text)
                out.append("```")
    else:
        out.append("\n## hypothesis")
        if live_text is not None:
            out.append(f"(sha256 {live_sha[:16]}…; live file — no track selected, so this is not a frozen baseline)")
            out.append("```")
            out.append(live_text)
            out.append("```")
        else:
            fb = _fallback_hypothesis(d)
            if fb:
                out.append("(from baseline v01.yaml — no hypothesis.md present)")
                out.append("```")
                out.append(fb)
                out.append("```")
            else:
                out.append("(none)")

    # --- feature list (R12: context includes the feature list) ------------
    out.append("\n## features")
    from .features import build_registry
    feats = build_registry().names()
    out.append(f"FEATURE_VERSION={FEATURE_VERSION}; {len(feats)} registered features:")
    out.append(", ".join(feats))

    # --- T3: the grammar + a copyable valid template (the web-AI's guide) --
    # A web/chat AI (no filesystem, no coding) can only get its strategy
    # right if the context *tells it the shape*. Without this, it must guess
    # the YAML schema and learn the rules only through `lyra validate`
    # rejections. This section is the "how to write this file" reference the
    # assessment flagged as Tier-3, delivered via the very context the AI reads.
    out.extend([
        "",
        "## how to write a strategy (grammar + a valid template to copy)",
        "Write **one YAML file**, then run `lyra validate <file>` (and `lyra submit` to run it).",
        "The schema is strict: **unknown keys are rejected** (not ignored). Copy the template",
        "below and only change what you intend. Rules that matter:",
        "  * `timeframe_minutes` must be **5** (features_5m) or **60** (features_1h).",
        "  * `version` is the **YAML schema version** (always **1**) — not the direction version.",
        "  * Each condition is `{feature, op, value}` → meaning `(feature op value)`.",
        "    - `op` is one of: `eq, ne, gt, gte, lt, lte` (numeric features); `eq, ne` (boolean features).",
        "    - `value` is a **constant number** OR **another feature** (feature-vs-feature, e.g. `sma_6 > sma_24`).",
        "    - `feature` must be a name from the `## features` list above (or an OHLC alias: `open`/`high`/`low`/`close`).",
        "  * `entry` / `exit` take `long` and `short` sub-blocks; `long`/`short` is a condition-list under `all:` (AND) or `any:` (OR), or a single condition map.",
        "  * `stop_loss_pct: 0.02` is **mandatory** (the 2% hard stop, I3) — leave it at 0.02.",
        "  * `take_profit_pct` / `max_holding_bars` are optional.",
        "  * Do **not** invent keys, do **not** use Python/callbacks/SQL — only the structure below.",
        "  * **Branch / lineage (R12, fail-closed)**: `v01` is the direction baseline and is "
        "RESERVED — your candidates start at the first free slug after it (append a suffix, e.g. "
        "`a`/`b`, for siblings). A candidate branch (N≥2) MUST declare `parent:` (or "
        "`parents: [ … ]`) naming what it evolved from (the v01 baseline or an existing track "
        "branch) AND a one-line `driven_by_lesson:`. A branch is IMMUTABLE: to change a strategy, "
        "register a NEW slug — never overwrite an existing one.",
        "Template (validated against this registry — copy it as your starting point):",
        "```yaml",
        "version: 1",
        "id: my_strategy_1h",
        "direction: " + direction,
        "hypothesis: >-",
        "  One-sentence hypothesis: what edge you expect and why, and how it should express itself.",
        "timeframe_minutes: 60",
        "entry:",
        "  long:",
        "    all:",
        "      - {feature: rsi_6, op: lt, value: 30}",
        "      - {feature: sma_6, op: gt, value: sma_24}",
        "  short:",
        "    all:",
        "      - {feature: rsi_6, op: gt, value: 70}",
        "      - {feature: sma_6, op: lt, value: sma_24}",
        "exit:",
        "  long: {feature: rsi_6, op: gt, value: 55}",
        "  short: {feature: rsi_6, op: lt, value: 45}",
        "  stop_loss_pct: 0.02",
        "execution:",
        "  spread_bps: 2",
        "  slippage_bps_per_side: 0.2",
        # F-3: non-zero commission/financing so a fresh T3 strategy is costed
        # from the start (zero-cost backtests are silently optimistic).
        "  commission_bps_round_trip: 0.2",
        "  financing_bps_per_day: 0.1",
        "```",
        "If you're unsure a feature exists, use only names from the `## features` list — an",
        "unregistered feature makes `lyra validate` fail with a clean INVALID line.",
    ])

    shared_lessons = d / "lessons.md"
    for t in tracks_list:
        tid = t["track_id"]
        out.append(f"\n## track {tid}")
        bl = t.get("baseline", {})
        out.append(
            "baseline (frozen at track creation): "
            f"hypothesis_sha256={str(bl.get('hypothesis_sha256'))[:16]}…, "
            f"feature_version={bl.get('feature_version')}, "
            f"feature_catalog_sha256={str(bl.get('feature_catalog_sha256'))[:16]}…, "
            f"engine={bl.get('engine_version')}, compiler={bl.get('compiler_version')}"
        )

        # per-track lessons (H6/I18 isolation)
        t_lessons = track_lessons_path(workspace, direction, tid)
        out.append(f"\n### lessons (track {tid}, last {n_lessons})")
        if t_lessons.exists():
            lines = [ln for ln in t_lessons.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            for ln in lines[-max(1, n_lessons):]:
                out.append(f"- {ln}")
        else:
            out.append("(none)")
        if shared_lessons.exists():
            out.append("\n### lessons (shared direction-level, labelled)")
            lines = [ln for ln in shared_lessons.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            for ln in lines[-max(1, n_lessons):]:
                out.append(f"- {ln}")

        active = _track_active(workspace, direction, tid)
        out.append(f"\n### active branches: {', '.join(active) if active else '(none)'}")
        for b in active:
            bfile = _branch_file(workspace, direction, b, track=tid)
            if bfile is None:
                out.append(f"  - {b} (YAML missing)")
                continue
            # full YAML text (H6: not just the file name)
            rel = bfile.name
            try:
                rel = bfile.relative_to(workspace / "strategies" / direction).as_posix()
            except ValueError:
                pass
            out.append(f"#### {rel}")
            out.append("```yaml")
            out.append(bfile.read_text(encoding="utf-8").rstrip("\n"))
            out.append("```")
            # 0009 D12 (H1): track-scoped run reads — this track's evidence
            # only (a baseline branch shared from the direction level still
            # shows this track's own runs, never another track's).
            runs = _runs_for_branch(workspace, direction, b, track=tid)
            for r in runs:
                parts = "  ".join(
                    f"{i['instrument']}: trades={i['trade_count']} ann={i['annualized']} "
                    f"win={i['win_rate']} net={i['net_return']}"
                    for i in r.get("instruments", [])
                )
                out.append(f"  run {r['run_id'][:12]}  {parts or '(no per-instrument data)'}")
            if not runs:
                out.append("  (no runs yet)")
    return "\n".join(out) + "\n"


def _runs_for_branch(workspace: Path, direction: str, branch: str,
                     track: str | None = None) -> list[dict[str, Any]]:
    """Read 0006 run artifacts referencing this branch (read-only).

    0009 D2/D3: identity comes first from the CLI-written ``run_meta.json``
    sidecar (explicit direction + branch + track, immune to spec_id naming
    conventions); legacy runs without a sidecar fall back to the spec_id
    suffix match (H7 exact-match rule unchanged).

    0009 D12 (H1): when ``track`` is given, only runs attributed to that
    track (``run_meta.track_id``) are returned — track A's context never
    mixes in track B's runs. Without ``track`` (e.g. cross-track
    ``synthesize``) all matching runs are returned and each row carries its
    ``track_id`` for provenance.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    runs_root = workspace / "runs"
    if not runs_root.is_dir():
        return out
    for mf in sorted(runs_root.glob("*/*/*/metrics.json")):
        try:
            m = _load_json(mf)
        except Exception:
            continue
        spec = str(m.get("spec_id", ""))
        meta_path = mf.parent / "run_meta.json"
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = _load_json(meta_path)
            except Exception:
                meta = {}
            matched = (
                str(meta.get("direction", "")) == direction
                and (str(meta.get("branch", "")) == branch
                     or str(meta.get("branch", "")) == f"{branch}.yaml")
            )
        else:
            # legacy fallback: exact branch identity only (H7: "v1" must not
            # match spec v10)
            matched = (
                spec == branch
                or spec.endswith(f"/{branch}")
                or spec.endswith(f"/{branch}.yaml")
            )
        if not matched:
            continue
        per = m.get("per_instrument", {})
        if not per:
            continue
        per_list = [
            {"instrument": inst,
             "trade_count": v.get("trade_count"),
             "annualized": v.get("annualized"),
             "win_rate": v.get("win_rate"),
             "net_return": v.get("net_return"),
             "expectancy": v.get("expectancy")}
            for inst, v in sorted(per.items()) if isinstance(v, dict)
        ]
        run_id = str(m.get("run_id", mf.parent.name))
        if run_id in seen:
            continue
        seen.add(run_id)
        track_id = meta.get("track_id") if meta else None
        track_id = str(track_id) if track_id else None
        # H1: track-scoped reads filter by the sidecar's track_id. Legacy
        # runs (no sidecar) have no track — they are excluded from a
        # track-scoped read (a track's context is its own evidence only) and
        # kept for cross-track reads.
        if track is not None and track_id != track:
            continue
        out.append({
            "run_id": run_id,
            "direction": direction,
            "track_id": track_id,
            "spec_id": spec or None,
            "feature_snapshot_id": m.get("feature_snapshot_id"),
            # 0009 D13 (H2) & 0013: per-run data identity fields (judged in
            # compare_siblings; legacy runs carry None).
            "market_data_snapshot_id": m.get("market_data_snapshot_id"),
            "data_digest": m.get("data_digest"),
            "feature_version": m.get("feature_version"),
            "instruments": per_list,
            "instrument_failures": m.get("instrument_failures", []),
        })
    return out


# ---------------------------------------------------------------------------
# compare / merge / synthesize (read-only evidence, I22)
# ---------------------------------------------------------------------------


def _run_comparable_reason(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """0009 D13 (H2) amended by 0013: the reason two runs are NOT comparable,
    or None if they are comparable. Three independent identity dimensions —
    market_data_snapshot_id (OHLC market data identity, Decision 0013),
    feature_version (feature code generation), and feature_snapshot_id (feature
    registry snapshot). Any mismatch is a distinct reason (the first differing
    dimension is reported)."""
    if a.get("market_data_snapshot_id") is None or b.get("market_data_snapshot_id") is None:
        return "missing_market_data_snapshot_id"
    if a["market_data_snapshot_id"] != b["market_data_snapshot_id"]:
        return "market_data_snapshot_id"
    if a.get("feature_version") is None or b.get("feature_version") is None:
        return "missing_feature_version"
    if a["feature_version"] != b["feature_version"]:
        return "feature_version"
    sa, sb = a.get("feature_snapshot_id"), b.get("feature_snapshot_id")
    if sa is None or sb is None:
        return "missing_feature_snapshot"
    if sa != sb:
        return "feature_snapshot"
    return None


def compare_siblings(workspace: Path, direction: str, branches: list[str],
                     track: str | None = None) -> dict[str, Any]:
    """Read-only evidence table over sibling branches' 0006 metrics (I22/D8).

    Reads only; never writes any file.

    0009 D13 (H2) amended by 0013: comparability is judged per run-set on THREE
    identity dimensions — ``market_data_snapshot_id`` (underlying OHLC market
    data, 0013), ``feature_version`` (the feature-code generation), and
    ``feature_snapshot_id`` (the 0009 D3 snapshot digest). A run missing any
    field (legacy) is marked ``comparable=None`` (unknown — NOT presumed
    comparable) and counted in ``runs_without_data_identity``; runs with all
    fields present but differing across the set are ``comparable=False`` with
    a per-run ``incomparable_reason``.

    0014: Ranks branches by cross-instrument ``median_annualized`` descending
    instead of single-instrument best. Excludes incomparable runs/branches from
    ranking. Retains best single instrument as ``best_single_instrument``
    (aliased to ``best`` for backward compatibility). Computes top-level
    summary across comparable branches.
    """
    if len(branches) < 1:
        raise WorkflowError("compare needs at least one branch (use --siblings to pass 2+)")

    all_runs: list[dict[str, Any]] = []
    branch_runs: dict[str, list[dict[str, Any]]] = {}
    for b in branches:
        runs = _runs_for_branch(workspace, direction, b, track=track)
        branch_runs[b] = runs
        for r in runs:
            all_runs.append(r)

    # --- H2/0013: three-dimension per-run comparability -------------------------
    def _identity_ok(r: dict[str, Any]) -> bool:
        return (r.get("market_data_snapshot_id") is not None
                and r.get("feature_version") is not None
                and r.get("feature_snapshot_id") is not None)

    runs_without = sum(1 for r in all_runs if not _identity_ok(r))
    known = [r for r in all_runs if _identity_ok(r)]

    # Per-run judgment (pairwise against every other fully-identified run):
    #   - identity missing  -> comparable=None (unknown, never presumed True)
    #   - any peer differs  -> comparable=False + first differing dimension
    #   - all peers equal   -> comparable=True
    for r in all_runs:
        if not _identity_ok(r):
            r["comparable"] = None
            r["incomparable_reason"] = "unknown (missing identity field)"
            continue
        reason = None
        for other in all_runs:
            if other is r or not _identity_ok(other):
                continue
            reason = _run_comparable_reason(r, other)
            if reason is not None:
                break
        r["comparable"] = reason is None
        r["incomparable_reason"] = reason

    if not all_runs:
        comparable = None  # no runs at all
    else:
        # set-level verdict: any unknown run → cannot assert (None);
        # otherwise all runs must be mutually comparable.
        states = {r["comparable"] for r in all_runs}
        if None in states:
            comparable = None
        else:
            comparable = (states == {True})

    # --- 0014: per-branch evaluation and ranking by median_annualized -----------
    rows = []
    for b in branches:
        runs = branch_runs[b]
        best_across_all = None
        best_ann_across_all = float("-inf")
        for r in runs:
            for inst in r.get("instruments", []):
                ann = inst.get("annualized")
                if ann is not None and ann > best_ann_across_all:
                    best_across_all, best_ann_across_all = inst, ann

        comp_runs = [r for r in runs if r.get("comparable") is True]
        if comp_runs:
            rep_run = comp_runs[-1]
            stats = compute_cross_instrument_stats(rep_run)
            best_single = stats["best_single_instrument"] or best_across_all
            rows.append({
                "branch": b,
                "runs": runs,
                "is_comparable": True,
                "comparable_run": rep_run,
                "median_annualized": stats["median_annualized"],
                "median_net_return": stats["median_net_return"],
                "median_expectancy": stats["median_expectancy"],
                "profitable_instrument_ratio": stats["profitable_instrument_ratio"],
                "profitable_instruments_count": stats["profitable_instruments_count"],
                "expected_instruments_count": stats["expected_instruments_count"],
                "actual_instruments_count": stats["actual_instruments_count"],
                "failure_count": stats["failure_count"],
                "is_incomplete": stats["is_incomplete"],
                "worst_instrument": stats["worst_instrument"],
                "best_single_instrument": best_single,
                "best": best_single,
                "total_trades": stats["total_trades"],
                "low_trade_instruments_count": stats["low_trade_instruments_count"],
            })
        elif runs:
            last_run = runs[-1]
            stats = compute_cross_instrument_stats(last_run)
            reasons = [r.get("incomparable_reason") for r in runs if r.get("incomparable_reason")]
            reason_str = reasons[0] if reasons else "unknown"
            rows.append({
                "branch": b,
                "runs": runs,
                "is_comparable": False,
                "incomparable_reason": reason_str,
                "median_annualized": None,
                "median_net_return": None,
                "median_expectancy": None,
                "profitable_instrument_ratio": stats["profitable_instrument_ratio"],
                "profitable_instruments_count": stats["profitable_instruments_count"],
                "expected_instruments_count": stats["expected_instruments_count"],
                "actual_instruments_count": stats["actual_instruments_count"],
                "failure_count": stats["failure_count"],
                "is_incomplete": stats["is_incomplete"],
                "worst_instrument": stats["worst_instrument"],
                "best_single_instrument": stats["best_single_instrument"] or best_across_all,
                "best": stats["best_single_instrument"] or best_across_all,
                "total_trades": stats["total_trades"],
                "low_trade_instruments_count": stats["low_trade_instruments_count"],
            })
        else:
            rows.append({
                "branch": b,
                "runs": [],
                "is_comparable": False,
                "incomparable_reason": "no runs",
                "median_annualized": None,
                "median_net_return": None,
                "median_expectancy": None,
                "profitable_instrument_ratio": 0.0,
                "profitable_instruments_count": 0,
                "expected_instruments_count": 0,
                "actual_instruments_count": 0,
                "failure_count": 0,
                "is_incomplete": False,
                "worst_instrument": None,
                "best_single_instrument": None,
                "best": None,
                "total_trades": 0,
                "low_trade_instruments_count": 0,
            })

    comp_rows = [r for r in rows if r.get("is_comparable")]
    comp_rows.sort(
        key=lambda r: (r["median_annualized"] if r["median_annualized"] is not None else float("-inf")),
        reverse=True,
    )
    incomp_rows = [r for r in rows if not r.get("is_comparable")]
    sorted_rows = comp_rows + incomp_rows

    if comp_rows:
        anns = [r["median_annualized"] for r in comp_rows if r.get("median_annualized") is not None]
        ratios = [r["profitable_instrument_ratio"] for r in comp_rows if r.get("profitable_instrument_ratio") is not None]
        top_median_ann = float(statistics.median(anns)) if anns else None
        top_min_ann = min(anns) if anns else None
        top_median_ratio = float(statistics.median(ratios)) if ratios else None
        inc_count = sum(1 for r in comp_rows if r.get("is_incomplete"))
    else:
        top_median_ann = None
        top_min_ann = None
        top_median_ratio = None
        inc_count = sum(1 for r in rows if r.get("is_incomplete"))

    summary = {
        "median_annualized": top_median_ann,
        "min_annualized": top_min_ann,
        "median_profitable_ratio": top_median_ratio,
        "incomplete_count": inc_count,
    }

    return {
        "direction": direction,
        "track": track,
        "siblings": sorted_rows,
        "summary": summary,
        "comparable": comparable,
        "distinct_feature_generations": len({r["feature_snapshot_id"] for r in known}),
        "distinct_market_data_snapshots": len({r["market_data_snapshot_id"] for r in known}),
        "distinct_data_digests": len({r["data_digest"] for r in known}),
        "distinct_feature_versions": len({str(r["feature_version"]) for r in known}),
        "runs_without_data_identity": runs_without,
    }


def merge(
    workspace: Path,
    direction: str,
    parents: list[str],
    *,
    track: str,
    name: str | None = None,
) -> Path:
    """Add a merge candidate branch (I22/D8): *only adds*, source branches
    are byte-for-byte untouched.

    Reuses 0004's ``inherited`` provenance field. The synthesis of actual
    parameters is AI-authored later (0007 does not auto-synthesize).
    """
    if len(parents) < 2:
        raise WorkflowError("merge needs at least two parents (cross/synthesis)")
    validate_ident(direction, "direction")
    for p in parents:
        validate_ident(p, "parent branch")
    parent_shas: dict[str, str] = {}
    for p in parents:
        pfile = _parent_file(workspace, direction, p, track)  # fail fast if missing
        # C6: record the *sha256* of the source (audit chain must not depend
        # on the branch name surviving prunes).
        parent_shas[p] = hashlib.sha256(pfile.read_bytes()).hexdigest()
    # 0007 D2: merge candidates are vNN branches too (I17 immutable class).
    # Default to the next free vNN number; an explicit name must also be vNN.
    # 0009 D12: the free number is computed over this track's directory AND
    # the direction-level baseline set (the baseline is shared and read-only,
    # so a merge must not shadow it).
    d = workspace / "strategies" / direction
    track_dir = d / track
    if not name:
        existing: set[int] = set()
        for root in (track_dir, d):
            if not root.is_dir():
                continue
            for p in root.glob("*.yaml"):
                if not p.is_file():
                    continue
                m = _VNN_FILE_RE.match(p.name)
                if m:
                    existing.add(int(m.group(1)))
        n = 1
        while n in existing:
            n += 1
        name = f"v{n:02d}"
    slug = name
    # P2-5: fullmatch (re.match + $ still accepts a trailing newline).
    if not _BRANCH_NAME_RE.fullmatch(slug):
        raise WorkflowError(
            f"invalid merge name {slug!r} — branches are vNN with optional "
            f"lowercase suffix (requirements R12)"
        )
    get_track(workspace, direction, track)  # must exist (I18 identity)
    enforce_branch_cap(workspace, direction, track)

    track_dir.mkdir(parents=True, exist_ok=True)
    target = track_dir / f"{slug}.yaml"
    if target.exists():
        raise WorkflowError(f"merge target exists: {target} — refusing to overwrite (D9)")
    lines = [
        "# merge candidate (0007) — AI to synthesize parameters across parents",
        f"id: {slug}",
        f"direction: {direction}",
        # 审查 U2 (2026-11-14)：version 是 schema 版本（SCHEMA_VERSION=1），
        # 原 `version: 0` 非法；merge 候选骨架应与 new_version 一致用 1。
        "version: 1",
        "parents:",
    ]
    lines += [f"  - {p}" for p in parents]
    lines.append("inherited:")
    lines += [f"  - {p}" for p in parents]
    # C6: provenance by content hash (audit chain survives prunes/renames).
    lines.append("# parent_sha256 (0007 C6, provenance):")
    lines += [f"#   {p}: {parent_shas[p]}" for p in parents]
    # H3 fix (2026-11-15): quoted so the skeleton is valid YAML (unquoted
    # `<TODO: ...>` is a YAML mapping error).
    lines.append(
        'driven_by_lesson: "TODO(必填): 用一句话写清这个 merge 由哪些教训驱动"'
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Register: append one event line (H10 — keeps the JSONL append-only).
    rel = f"{track}/{slug}.yaml"  # path relative to strategies/<direction>/
    _append_index_event(workspace, direction, track, {
        "op": "activate", "branch": slug, "file": rel,
        "parent": None, "parents": list(parents),
        "driven_by_lesson": None, "at": _now_iso(),
    })
    return target


def synthesize(workspace: Path, direction: str) -> Path:
    """Cross-track synthesis report (I22): writes ONLY under ``reviews/`` —
    never to lessons/ or strategy files.

    Explicit user-triggered action (0007 D8: not automatic).
    """
    tracks = list_tracks(workspace, direction)
    if not tracks:
        raise WorkflowError(f"no tracks under {direction} to synthesize")
    lines = [
        f"# synthesize — {direction} (0007, read-only evidence)",
        f"generated_at: {_now_iso()}",
        "",
    ]
    for t in tracks:
        tid = t["track_id"]
        active = _track_active(workspace, direction, tid)
        lines.append(f"## track {tid}")
        for b in active:
            runs = _runs_for_branch(workspace, direction, b, track=tid)
            for r in runs:
                # 0009 D13 (H2): cross-track synthesis is EXPLICIT (I22) and
                # must carry per-run identity so readers can see which runs
                # are comparable and which track they came from.
                ident = (
                    f" track={r.get('track_id') or '?'} "
                    f"digest={str(r.get('data_digest'))[:8] or '?'} "
                    f"featver={r.get('feature_version') or '?'} "
                    f"cmp={r.get('comparable')}"
                )
                for i in r.get("instruments", []):
                    lines.append(
                        f"- {b}: run {r['run_id'][:12]}{ident} {i['instrument']} "
                        f"trades={i['trade_count']} ann={i['annualized']} "
                        f"win={i['win_rate']} net={i['net_return']}"
                    )
            if not runs:
                lines.append(f"- {b}: (no runs)")
    out = workspace / "reviews"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out / f"synthesize-{direction}-{stamp}.md"
    n = 2
    while target.exists():
        target = out / f"synthesize-{direction}-{stamp}-{n}.md"
        n += 1
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
