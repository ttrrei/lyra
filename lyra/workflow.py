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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .features import FEATURE_VERSION
from .runner import _ENGINE_VERSION

#: I21 (D6, O13): the ONLY machine gate 0007 introduces.
MAX_ACTIVE_BRANCHES_PER_TRACK = 8

_BRANCH_RE = re.compile(r"^v\d+$")
_VNN_FILE_RE = re.compile(r"^v(\d+)\.yaml$")
_TRACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# 0007 D2: 分支文件命名 = vNN.yaml（I17 immutable 分类依据）。new-version
# 强制此格式，保证工具自己产出的分支文件可被 push 层分类为 immutable 并
# 推送（非 vNN 命名的手写策略文件仍按 fail-closed 分类为 unclassified，
# 需要作者自行归类，见 oci_push.classify_path 及 0007 决策稿 D2/D9）。
_BRANCH_NAME_RE = re.compile(r"^v\d+$")


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
        baseline["hypothesis_sha256"] = hashlib.sha256(hyp.read_bytes()).hexdigest()
    else:
        baseline["hypothesis_sha256"] = None

    catalog = workspace / "data" / "features" / "catalog.json"
    if catalog.exists():
        c = _load_json(catalog)
        baseline["feature_catalog_sha256"] = hashlib.sha256(catalog.read_bytes()).hexdigest()
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
    return workspace / "strategies" / direction / "index" / f"t{track_id}.json"


def _validate_track_id(track_id: str) -> None:
    if not _TRACK_ID_RE.match(track_id):
        raise WorkflowError(
            f"invalid track id {track_id!r} — use lowercase alnum/_/- (I18 fail-fast)"
        )


def create_track(workspace: Path, direction: str, track_id: str) -> dict[str, Any]:
    """Create a track and freeze its baseline (I18).

    Duplicate IDs fail fast — never overwrite, never auto-rename (D9 /
    综合稿 §9).
    """
    _validate_track_id(track_id)
    tp = track_path(workspace, direction, track_id)
    if tp.exists():
        raise WorkflowError(
            f"track id already exists: {direction}/{track_id} — refusing to "
            f"overwrite (I18 fail-fast; create a new id instead)"
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
    # Track branch index (append-only class per I17).
    idx = track_index_path(workspace, direction, track_id)
    if idx.exists():
        raise WorkflowError(
            f"track index already exists for {direction}/{track_id} — "
            f"inconsistent state, refusing to clobber (I18 fail-fast)"
        )
    _write_json(idx, {"direction": direction, "track_id": track_id, "active": []})
    return record


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
    tp = track_path(workspace, direction, track_id)
    if not tp.exists():
        raise WorkflowError(f"unknown track: {direction}/{track_id}")
    return _load_json(tp)


def _track_active(workspace: Path, direction: str, track_id: str) -> list[str]:
    idx = track_index_path(workspace, direction, track_id)
    if not idx.exists():
        return []
    return list(_load_json(idx).get("active", []))


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


def prune_branch(workspace: Path, direction: str, track_id: str, branch: str) -> None:
    """Explicitly drop a branch from the track's active list (cap relief)."""
    idx = track_index_path(workspace, direction, track_id)
    if not idx.exists():
        raise WorkflowError(f"no track index for {direction}/{track_id}")
    data = _load_json(idx)
    active = data.get("active", [])
    if branch not in active:
        raise WorkflowError(f"branch {branch!r} is not active on track {track_id}")
    data["active"] = [b for b in active if b != branch]
    data["pruned"] = data.get("pruned", [])
    data["pruned"].append(branch)
    _write_json(idx, data)


# ---------------------------------------------------------------------------
# new-version (branch derivation, reusing 0004 provenance fields)
# ---------------------------------------------------------------------------


def _parent_file(workspace: Path, direction: str, parent: str) -> Path:
    """Resolve a parent branch to its strategy file."""
    if _BRANCH_RE.match(parent):
        candidate = workspace / "strategies" / direction / f"{parent}.yaml"
        if candidate.exists():
            return candidate
    # branch slug that is not a bare vNN → treat parent as a slug under the
    # direction folder (user naming), e.g. strategies/<direction>/<parent>.yaml
    candidate = workspace / "strategies" / direction / f"{parent}.yaml"
    if candidate.exists():
        return candidate
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
    if not _BRANCH_NAME_RE.match(branch):
        raise WorkflowError(
            f"invalid branch name {branch!r} — use lowercase alnum/_/- (fail-fast)"
        )
    get_track(workspace, direction, track)  # must exist (I18 identity)
    if branch in _track_active(workspace, direction, track):
        raise WorkflowError(
            f"branch {branch!r} already exists on track {track} — duplicate id "
            f"(I18/D9 fail-fast: not overwriting, not auto-renaming)"
        )
    d0 = workspace / "strategies" / direction
    if (d0 / f"{branch}.yaml").exists():
        raise WorkflowError(
            f"branch {branch!r} already exists (strategies/{direction}/{branch}.yaml) "
            f"— duplicate id (I18/D9 fail-fast: not overwriting, not auto-renaming)"
        )
    enforce_branch_cap(workspace, direction, track)

    d = workspace / "strategies" / direction
    d.mkdir(parents=True, exist_ok=True)
    slug = branch
    target = d / f"{slug}.yaml"  # duplicate already rejected above (D9)

    parent_slug = None
    if parent is not None:
        pfile = _parent_file(workspace, direction, parent)
        parent_slug = pfile.stem  # e.g. v03 or the branch slug

    template_lines = [
        "# Lyra strategy — derived branch (0007 new-version)",
        f"# direction: {direction}",
        f"id: {slug}",
        f"direction: {direction}",
        "version: 0",
        "timeframe_minutes: 60",
        "entry:",
        "  long:",
        "    feature: sma_20_above_sma_50",
        "exit:",
        "  long:",
        "    stop_loss_pct: 0.02",
        "execution:",
        "  stop_loss_pct: 0.02",
    ]
    if parent_slug is not None:
        template_lines.append(f"parent: {parent_slug}")
        template_lines.append("parents:")
        template_lines.append(f"  - {parent_slug}")
    if driven_by_lesson is not None:
        template_lines.append(f"driven_by_lesson: {driven_by_lesson}")
    elif parent_slug is not None:
        # R12 vNN≥2: placeholders required — the author fills them.
        template_lines.append("driven_by_lesson: <TODO: which lesson drove this branch>")
    target.write_text("\n".join(template_lines) + "\n", encoding="utf-8")

    # Register as active on the track (per-track index).
    idx = track_index_path(workspace, direction, track)
    data = _load_json(idx)
    active = data.get("active", [])
    if slug in active:
        raise WorkflowError(
            f"branch {slug!r} already active on track {track} — duplicate id "
            f"(I18 fail-fast)"
        )
    active.append(slug)
    data["active"] = active
    data.setdefault("created", []).append(
        {"branch": slug, "file": target.name, "parent": parent_slug,
         "driven_by_lesson": driven_by_lesson, "created_at": _now_iso()}
    )
    _write_json(idx, data)

    # Reflect in the track record as well (single source for context/synthesis).
    tp = track_path(workspace, direction, track)
    rec2 = _load_json(tp)
    rec2.setdefault("branches", {})[slug] = {
        "file": target.name,
        "parent": parent_slug,
        "driven_by_lesson": driven_by_lesson,
    }
    _write_json(tp, rec2)
    return target


# ---------------------------------------------------------------------------
# context (track-scoped, single-file package — I18 isolation)
# ---------------------------------------------------------------------------


def render_context(
    workspace: Path,
    direction: str,
    *,
    track: str | None = None,
    n_lessons: int = 5,
) -> str:
    """Render the single-file context package (R12).

    ``track`` given → strictly that track's hypothesis ref / lessons /
    active branches + *sibling* branch run summaries (read-only). Track A's
    context never reads track B's drafts/lessons (I18).
    """
    out: list[str] = [f"# context — {direction}"]
    d = workspace / "strategies" / direction

    hyp = d / "hypothesis.md"
    if hyp.exists():
        h = hashlib.sha256(hyp.read_bytes()).hexdigest()
        out.append(f"\n## hypothesis\n{hyp}  (sha256 {h[:16]}…)\n")
    else:
        out.append("\n## hypothesis\n(none)\n")

    lessons = d / "lessons.md"
    out.append(f"\n## lessons (last {n_lessons})")
    if lessons.exists():
        lines = [ln for ln in lessons.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        for ln in lines[-max(1, n_lessons):]:
            out.append(f"- {ln}")
    else:
        out.append("(none)")

    tracks = list_tracks(workspace, direction)
    if track is not None:
        tracks = [t for t in tracks if t["track_id"] == track]
        if not tracks:
            raise WorkflowError(f"unknown track: {direction}/{track}")

    for t in tracks:
        tid = t["track_id"]
        out.append(f"\n## track {tid}")
        active = _track_active(workspace, direction, tid)
        out.append(f"active branches: {', '.join(active) if active else '(none)'}")
        bl = t.get("baseline", {})
        if bl.get("feature_version") is not None:
            out.append(f"baseline: feature_version={bl.get('feature_version')}, "
                       f"engine={bl.get('engine_version')}")
        for b in active:
            bfile = d / f"{b}.yaml"
            if not bfile.exists():
                m = _VNN_FILE_RE.match(b + ".yaml")
                if m:
                    bfile = d / f"v{int(m.group(1)):02d}.yaml"
            if bfile.exists():
                y = bfile.read_text(encoding="utf-8")
                par = re.search(r"^parent:\s*(\S+)", y, flags=re.M)
                out.append(f"  - {b} → {bfile.name}"
                           + (f"  (parent: {par.group(1)})" if par else ""))
            # sibling/own run summaries from 0006 metrics (read-only)
            runs = _runs_for_branch(workspace, direction, b)
            for r in runs:
                out.append(f"    run {r['run_id'][:12]}  trades={r['trades']} "
                           f"ann={r.get('annualized')}  win={r.get('win_rate')}")
            if not runs:
                out.append("    (no runs yet)")
    return "\n".join(out) + "\n"


def _runs_for_branch(workspace: Path, direction: str, branch: str) -> list[dict[str, Any]]:
    """Read 0006 metrics.json artifacts referencing this branch (read-only)."""
    out: list[dict[str, Any]] = []
    runs_root = workspace / "runs"
    if not runs_root.is_dir():
        return out
    for mf in sorted(runs_root.glob("*/*/*/metrics.json")):
        try:
            m = _load_json(mf)
        except Exception:
            continue
        spec = str(m.get("spec_id", ""))
        if spec != branch and not spec.endswith(f"/{branch}") and branch not in spec:
            continue
        per = m.get("per_instrument", {})
        if not per:
            continue
        first = next(iter(per.values()))
        out.append({
            "run_id": m.get("run_id", mf.parent.name),
            "trades": first.get("trade_count"),
            "annualized": first.get("annualized"),
            "win_rate": first.get("win_rate"),
            "net_return": first.get("net_return"),
        })
    return out


# ---------------------------------------------------------------------------
# compare / merge / synthesize (read-only evidence, I22)
# ---------------------------------------------------------------------------


def compare_siblings(workspace: Path, direction: str, branches: list[str]) -> dict[str, Any]:
    """Read-only evidence table over sibling branches' 0006 metrics (I22/D8).

    Reads only; never writes any file.
    """
    if len(branches) < 1:
        raise WorkflowError("compare needs at least one branch (use --siblings to pass 2+)")
    rows = []
    for b in branches:
        runs = _runs_for_branch(workspace, direction, b)
        best = None
        for r in runs:
            if best is None or (r.get("net_return") or -1) > (best.get("net_return") or -1):
                best = r
        rows.append({"branch": b, "runs": runs, "best": best})
    return {"direction": direction, "siblings": rows}


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
    parent_shas: dict[str, str] = {}
    for p in parents:
        pfile = _parent_file(workspace, direction, p)  # fail fast if missing
        # C6: record the *sha256* of the source (audit chain must not depend
        # on the branch name surviving prunes).
        parent_shas[p] = hashlib.sha256(pfile.read_bytes()).hexdigest()
    # 0007 D2: merge candidates are vNN branches too (I17 immutable class).
    # Default to the next free vNN number; an explicit name must also be vNN.
    if not name:
        existing = {
            int(m.group(1))
            for m in (
                _VNN_FILE_RE.match(p.name)
                for p in (workspace / "strategies" / direction).glob("*.yaml")
                if p.is_file()
            )
            if m
        }
        n = 1
        while n in existing:
            n += 1
        name = f"v{n:02d}"
    slug = name
    if not _BRANCH_NAME_RE.match(slug):
        raise WorkflowError(f"invalid merge name {slug!r} — branches are vNN (0007 D2)")
    get_track(workspace, direction, track)  # must exist (I18 identity)
    enforce_branch_cap(workspace, direction, track)

    d = workspace / "strategies" / direction
    target = d / f"{slug}.yaml"
    if target.exists():
        raise WorkflowError(f"merge target exists: {target} — refusing to overwrite (D9)")
    lines = [
        "# merge candidate (0007) — AI to synthesize parameters across parents",
        f"id: {slug}",
        f"direction: {direction}",
        "version: 0",
        "parents:",
    ]
    lines += [f"  - {p}" for p in parents]
    lines.append("inherited:")
    lines += [f"  - {p}" for p in parents]
    # C6: provenance by content hash (audit chain survives prunes/renames).
    lines.append("# parent_sha256 (0007 C6, provenance):")
    lines += [f"#   {p}: {parent_shas[p]}" for p in parents]
    lines.append("driven_by_lesson: <TODO: lesson(s) motivating this merge>")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    idx = track_index_path(workspace, direction, track)
    data = _load_json(idx)
    active = data.get("active", [])
    if slug in active:
        raise WorkflowError(f"branch {slug!r} already active (I18 fail-fast)")
    active.append(slug)
    data["active"] = active
    _write_json(idx, data)
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
            runs = _runs_for_branch(workspace, direction, b)
            for r in runs:
                lines.append(
                    f"- {b}: run {r['run_id'][:12]} trades={r['trades']} "
                    f"ann={r.get('annualized')} win={r.get('win_rate')} "
                    f"net={r.get('net_return')}"
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
