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
    """
    return workspace / "strategies" / direction / "index" / f"t{track_id}.jsonl"


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
    if not _TRACK_ID_RE.match(track_id):
        raise WorkflowError(
            f"invalid track id {track_id!r} — use lowercase alnum/_/- (I18 fail-fast)"
        )


def validate_ident(ident: str, what: str = "identifier") -> None:
    """Single-path-component check for direction/track/branch/run ids (H4).

    Rejects separators, dot segments and empty names so a value like
    ``../outside`` or ``a/b`` can never escape the workspace root when
    joined into a file path.
    """
    if not isinstance(ident, str) or not _IDENT_RE.match(ident) or ident in _IDENT_BAD:
        raise WorkflowError(
            f"invalid {what} {ident!r} — use a single path component "
            f"(alnum/_/-, no separators, no '.') "
        )


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
    baseline = _baseline_for_direction(workspace, direction)
    record = {
        "direction": direction,
        "track_id": track_id,
        "created_at": _now_iso(),
        "active_branches": [],
        "baseline": baseline,
    }
    _write_json(tp, record)
    # Track event log (JSONL, append-only class per I17 — H10: a JSONL of
    # independent event lines is a verbatim line-superset of its prior
    # versions, so re-pushing after new events is always allowed).
    idx = track_index_path(workspace, direction, track_id)
    if idx.exists():
        raise WorkflowError(
            f"track index already exists for {direction}/{track_id} — "
            f"inconsistent state, refusing to clobber (I18 fail-fast)"
        )
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


def prune_branch(workspace: Path, direction: str, track_id: str, branch: str) -> None:
    """Explicitly drop a branch from the track's active list (cap relief).

    H10: appends a prune EVENT — earlier lines are never rewritten, so the
    JSONL stays a verbatim line-superset (I17 append-only) and the prune is
    pushable (the old snapshot rewrite was rejected by the gate).
    """
    validate_ident(branch, "branch")
    if branch not in _track_active(workspace, direction, track_id):
        raise WorkflowError(f"branch {branch!r} is not active on track {track_id}")
    _append_index_event(workspace, direction, track_id,
                        {"op": "prune", "branch": branch, "at": _now_iso()})


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
            f"invalid branch name {branch!r} — branches are vNN with optional "
            f"lowercase sibling/cross suffix (v02a, v04ab) per requirements R12"
        )
    validate_ident(direction, "direction")
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

    # Register as active on the track: append ONE event line (H10 — the
    # JSONL keeps every earlier line verbatim, so it remains an I17
    # append-only file after every fork).
    _append_index_event(workspace, direction, track, {
        "op": "activate", "branch": slug, "file": target.name,
        "parent": parent_slug, "driven_by_lesson": driven_by_lesson,
        "at": _now_iso(),
    })

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


def track_lessons_path(workspace: Path, direction: str, track_id: str) -> Path:
    """Per-track lessons file (H6/I18: track A's context never reads track
    B's lessons; a shared direction-level lessons.md remains readable but is
    clearly labelled as shared)."""
    return workspace / "tracks" / direction / f"{track_id}.lessons.md"


def _branch_file(workspace: Path, direction: str, branch: str) -> Path | None:
    d = workspace / "strategies" / direction
    cand = d / f"{branch}.yaml"
    if cand.exists():
        return cand
    m = _VNN_FILE_RE.match(branch + ".yaml")
    if m:
        # legacy zero-padding variant (v1 -> v01.yaml)
        for p in d.glob("*.yaml"):
            pm = _VNN_FILE_RE.match(p.name)
            if pm and int(pm.group(1)) == int(m.group(1)):
                return p
    return None


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
            out.append("(no hypothesis present when the track was created)")
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
            out.append("(none)")

    # --- feature list (R12: context includes the feature list) ------------
    out.append("\n## features")
    from .features import build_registry
    feats = build_registry().names()
    out.append(f"FEATURE_VERSION={FEATURE_VERSION}; {len(feats)} registered features:")
    out.append(", ".join(feats))

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
            bfile = _branch_file(workspace, direction, b)
            if bfile is None:
                out.append(f"  - {b} (YAML missing)")
                continue
            # full YAML text (H6: not just the file name)
            out.append(f"#### {bfile.name}")
            out.append("```yaml")
            out.append(bfile.read_text(encoding="utf-8").rstrip("\n"))
            out.append("```")
            runs = _runs_for_branch(workspace, direction, b)
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


def _runs_for_branch(workspace: Path, direction: str, branch: str) -> list[dict[str, Any]]:
    """Read 0006 run artifacts referencing this branch (read-only).

    0009 D2/D3: identity comes first from the CLI-written ``run_meta.json``
    sidecar (explicit direction + branch + track, immune to spec_id naming
    conventions); legacy runs without a sidecar fall back to the spec_id
    suffix match (H7 exact-match rule unchanged).
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
             "net_return": v.get("net_return")}
            for inst, v in sorted(per.items()) if isinstance(v, dict)
        ]
        run_id = str(m.get("run_id", mf.parent.name))
        if run_id in seen:
            continue
        seen.add(run_id)
        track_id = meta.get("track_id") if meta else None
        out.append({
            "run_id": run_id,
            "direction": direction,
            "track_id": str(track_id) if track_id else None,
            "spec_id": spec or None,
            "feature_snapshot_id": m.get("feature_snapshot_id"),
            "instruments": per_list,
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
    all_snapshot_ids: list[str | None] = []
    for b in branches:
        runs = _runs_for_branch(workspace, direction, b)
        # best = highest per-instrument net_return across the run's instruments
        best = None
        for r in runs:
            all_snapshot_ids.append(r.get("feature_snapshot_id"))
            for inst in r.get("instruments", []):
                if best is None or (inst.get("net_return") or -1) > (best.get("net_return") or -1):
                    best = inst
        rows.append({"branch": b, "runs": runs, "best": best})
    # 0009 D3 / R9: comparability is a property of the DATA, not of the
    # strategy — runs over different feature generations (different
    # feature_snapshot_id) are not directly comparable. Runs without a
    # digest (legacy) are conservatively marked incomparable too.
    known = [s for s in all_snapshot_ids if s]
    if not known:
        comparable = None  # no data to judge (e.g. no runs at all)
    elif len(set(known)) > 1:
        comparable = False
    else:
        comparable = True
    incomparable_runs = sum(1 for s in all_snapshot_ids if s not in known)
    return {
        "direction": direction,
        "siblings": rows,
        "comparable": comparable,
        "distinct_feature_generations": len(set(known)),
        "runs_without_data_identity": incomparable_runs,
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
        raise WorkflowError(
            f"invalid merge name {slug!r} — branches are vNN with optional "
            f"lowercase suffix (requirements R12)"
        )
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

    # Register: append one event line (H10 — keeps the JSONL append-only).
    _append_index_event(workspace, direction, track, {
        "op": "activate", "branch": slug, "file": target.name,
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
            runs = _runs_for_branch(workspace, direction, b)
            for r in runs:
                for i in r.get("instruments", []):
                    lines.append(
                        f"- {b}: run {r['run_id'][:12]} {i['instrument']} "
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
