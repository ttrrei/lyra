"""OCI push layer (decision 0007 Part A — R7 + I17 two-tier rules).

Pushes local mirrors (strategies / runs / features / data) to their PAR
buckets with the 0007 D2 classification:

* **immutable** — ``runs/**``, ``strategies/**/vNN.yaml``, ``alpha/features/**``,
  ``data/**``: same path + same sha256 is an idempotent skip (I20); a
  different sha256 is a conflict unless ``--force-push`` (R7).
* **append-only** — ``strategies/**/hypothesis.md``, ``lessons.md``,
  ``strategies/**/index/*.json``: the new content must be a line superset of
  the remote content (new ⊇ old); a regression is always a conflict.
* **unclassified** — anything else is a fail-closed error (D9), never
  forceable.

``--dry-run`` plans without any upload. Push targets come from the 0002
reserved slots (``oci.strategies_par_url`` / ``oci.features_par_url``;
``runs``/``data`` reuse the prefix bucket or an explicit root URL). An
empty/unconfigured target is an error, never a silent skip (D4).

Transport: anything exposing ``get`` (listing, 0002-style) and ``put``
(upload). A transport without ``put`` fails with a clear error (C1: read-only
PAR cannot be pushed to; use a read/write PAR or SDK auth). PAR URLs are
always redacted in error messages (I19).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .oci_client import list_objects, redact_par_url

_CHUNK = 1 << 20

_VNN_RE = re.compile(r"^v\d+\.yaml$")


class PushTransport(Protocol):
    """A 0002-style ``get`` transport plus a ``put`` for uploads."""

    def get(self, url: str, **kwargs: Any) -> Any: ...

    def put(self, url: str, **kwargs: Any) -> Any: ...  # pragma: no cover


class OciPushError(RuntimeError):
    """A push planning/execution failure (fail-closed, I19-safe)."""


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_path(rel_path: str) -> str:
    """Classify a relative path per I17 (0007 D2).

    Returns ``"immutable"``, ``"append_only"`` or ``"unclassified"``.
    Append-only checks come first (they are specific file names inside
    ``strategies/**``); unclassified paths must be rejected by the caller
    (fail-closed — ``classify`` never guesses).
    """
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    if not parts:
        return "unclassified"
    top = parts[0]

    if top == "strategies":
        # strategies/<direction>/<file>
        if len(parts) >= 3:
            fname = parts[-1]
            if fname in ("hypothesis.md", "lessons.md"):
                return "append_only"
            if len(parts) >= 4 and parts[-2] == "index" and fname.endswith(".json"):
                return "append_only"
            if _VNN_RE.match(fname):
                return "immutable"
        return "unclassified"
    if top in ("runs", "data"):
        return "immutable"
    if top == "alpha" and len(parts) >= 2 and parts[1] == "features":
        return "immutable"
    return "unclassified"


def is_append_only_superset(old_text: str, new_text: str) -> bool:
    """True iff the non-empty lines of *old_text* appear in *new_text* **in
    their original order** (a line-subsequence), not merely as a set.

    0007 D2 / C2 tightening: "old content is preserved verbatim + only
    appending / paragraph-level extension allowed." A plain set-superset
    would wrongly accept a *reorder* (``line1\\nline2`` → ``line2\\nline1``)
    or a *rewrite* (``line1`` → ``line1'``); the subsequence check rejects
    both while still allowing inserts and appends at paragraph granularity.
    Empty lines in *old_text* are ignored; whitespace differences within a
    line are not ignored (verbatim, per C2).
    """
    new_lines = new_text.splitlines()
    i = 0  # pointer into new_lines
    for old_line in old_text.splitlines():
        if not old_line.strip():
            continue
        found = False
        while i < len(new_lines):
            if new_lines[i] == old_line:
                i += 1
                found = True
                break
            i += 1
        if not found:
            return False
    return True


@dataclass(frozen=True)
class UploadItem:
    rel_path: str
    local_sha256: str
    size: int
    kind: str  # "immutable" | "append_only"


@dataclass(frozen=True)
class ConflictItem:
    rel_path: str
    reason: str  # immutable-sha-conflict | append-only-regression | unclassified-path
    detail: str


@dataclass
class PushPlan:
    target_name: str
    uploads: list[UploadItem] = field(default_factory=list)
    skips: list[UploadItem] = field(default_factory=list)
    conflicts: list[ConflictItem] = field(default_factory=list)

    def to_report(self) -> dict[str, list[str]]:
        return {
            "upload": [u.rel_path for u in self.uploads],
            "skip": [s.rel_path for s in self.skips],
            "conflict": [f"{c.rel_path} ({c.reason})" for c in self.conflicts],
        }


@dataclass
class PushResult:
    target_name: str
    uploads: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    dry_run: bool = False
    uploaded_bytes: int = 0


#: I17-scoped top-level directories: the push *walk* skips any other top-level
#: directory (e.g. 0007's research workspace files ``tracks/``, ``reviews/``
#: which are local-only and never pushed). Unclassified *files* inside a
#: scoped directory are still fail-closed (D9) — the skip is per top-level
#: directory, not per file.
_SCOPED_TOP_LEVEL = frozenset({"strategies", "runs", "data", "alpha"})


def in_push_scope(rel_path: str) -> bool:
    """True iff *rel_path* is under an I17-scoped top-level directory."""
    top = rel_path.replace("\\", "/").split("/", 1)[0]
    return top in _SCOPED_TOP_LEVEL


def _url_for(base: str, rel_path: str) -> str:
    base = base if base.endswith("/") else base + "/"
    return base + rel_path.replace("\\", "/")


def list_remote_map(transport: PushTransport, par_url: str) -> dict[str, dict[str, Any]]:
    """Map object name (relative to the prefix) -> listing metadata."""
    objs = list_objects(transport, par_url)
    out: dict[str, dict[str, Any]] = {}
    for o in objs:
        name = str(o.get("name"))
        out[name] = o
    return out


def _remote_sha_or_md5(meta: Mapping[str, Any] | None) -> str | None:
    if not meta:
        return None
    for key in ("sha256", "eTag", "etag", "md5"):
        v = meta.get(key)
        if v:
            return str(v).strip().strip('"').lower()
    return None


def _download_remote_text(
    transport: PushTransport, par_url: str, rel_path: str
) -> str:
    """Fetch the current remote content (append-only regression check)."""
    url = _url_for(par_url, rel_path)
    try:
        resp = transport.get(url, timeout=120)
    except Exception as exc:  # noqa: BLE001 - surface as OciPushError
        raise OciPushError(f"fetching {rel_path} from {redact_par_url(par_url)} failed: {exc}") from exc
    if getattr(resp, "status_code", 200) >= 400:
        raise OciPushError(
            f"remote object {rel_path} ({redact_par_url(par_url)}) not readable: "
            f"HTTP {resp.status_code}"
        )
    body = b"".join(resp.iter_content(1 << 20))
    return body.decode("utf-8", errors="replace")


def check_remote_superset(
    transport: PushTransport, par_url: str, rel_path: str, new_text: str
) -> bool:
    """True iff the remote object (if any) is a line-subset of *new_text*."""
    old_text = _download_remote_text(transport, par_url, rel_path)
    return is_append_only_superset(old_text, new_text)


def push(
    transport: PushTransport,
    local_root: Path,
    par_url: str,
    *,
    force_push: bool = False,
    dry_run: bool = False,
    top_levels: frozenset[str] | None = None,
) -> PushResult:
    """Plan and (unless dry-run) upload one local root to its PAR bucket.

    Fail-closed: unclassified paths and append-only regressions are always
    errors; immutable sha conflicts need ``force_push`` (R7). An empty
    *par_url* is an error (D4 — never silently skip).
    """
    if not par_url:
        raise OciPushError(
            "no push target configured (oci.*_par_url empty) — set the PAR "
            "URL or auth_file in config.yml (0007 D4)"
        )
    if not hasattr(transport, "put"):
        raise OciPushError(
            f"transport has no put() — {redact_par_url(par_url)} is read-only; "
            "mount a read/write PAR or use SDK auth (0007 C1)"
        )

    remote_map = list_remote_map(transport, par_url)
    plan = plan_push(transport, local_root, par_url, remote_map,
                     top_levels=top_levels)
    if force_push and not dry_run:
        # R7: --force-push promotes immutable sha conflicts to uploads;
        # append-only regression / unclassified paths stay blocking.
        forced = [
            c for c in plan.conflicts if c.reason == "immutable-sha-conflict"
        ]
        plan.conflicts = [c for c in plan.conflicts if c not in forced]
        for c in forced:
            plan.uploads.append(
                UploadItem(c.rel_path, sha256_of_file(Path(local_root) / c.rel_path), 0, "immutable")
            )

    result = PushResult(target_name=plan.target_name, dry_run=dry_run)
    result.skips = [s.rel_path for s in plan.skips]
    if dry_run:
        result.uploads = [u.rel_path for u in plan.uploads]
        result.conflicts = [f"{c.rel_path} ({c.reason})" for c in plan.conflicts]
        return result

    # Fail-closed: any remaining conflict blocks the whole push.
    for conflict in plan.conflicts:
        raise OciPushError(
            f"push blocked at {redact_par_url(par_url)}: "
            f"{conflict.rel_path}: {conflict.reason} — {conflict.detail}"
        )

    for item in plan.uploads:
        data = (Path(local_root) / item.rel_path).read_bytes()
        url = _url_for(par_url, item.rel_path)
        try:
            resp = transport.put(url, data=data, timeout=300)
        except Exception as exc:  # noqa: BLE001
            raise OciPushError(f"upload of {item.rel_path} to {redact_par_url(par_url)} failed: {exc}") from exc
        status = getattr(resp, "status_code", 200)
        if status >= 400:
            raise OciPushError(
                f"upload of {item.rel_path} to {redact_par_url(par_url)} failed: HTTP {status}"
            )
        result.uploads.append(item.rel_path)
        result.uploaded_bytes += len(data)
    return result


def plan_push(
    transport: PushTransport | None,
    local_root: Path,
    par_url: str,
    remote_map: Mapping[str, Mapping[str, Any]],
    *,
    top_levels: frozenset[str] | None = None,
) -> PushPlan:
    """Classify every file under *local_root* and diff against *remote_map*.

    Never uploads — planning only (safe for dry-run and for the real push,
    which plans first and then uploads the ``uploads`` list). The
    append-only superset check against remote content is done via
    *transport* (required to verify an append-only file whose digest
    differs).
    """
    local_root = Path(local_root)
    plan = PushPlan(target_name=par_url)
    if not local_root.is_dir():
        return plan

    for path in sorted(p for p in local_root.rglob("*") if p.is_file()):
        rel = path.relative_to(local_root).as_posix()
        # Top-level directories outside I17 scope (e.g. local research
        # workspace files) are silently out of the push scope; the fail-closed
        # rule applies to unclassified *files inside* a scoped directory.
        if not in_push_scope(rel):
            continue
        top = rel.split("/", 1)[0]
        if top_levels is not None and top not in top_levels:
            continue
        kind = classify_path(rel)
        if kind == "unclassified":
            plan.conflicts.append(
                ConflictItem(rel, "unclassified-path", "path matches no I17 class (fail-closed)")
            )
            continue
        local_sha = sha256_of_file(path)
        size = path.stat().st_size
        meta = remote_map.get(rel)
        if meta is None:
            plan.uploads.append(UploadItem(rel, local_sha, size, kind))
            continue
        remote_digest = _remote_sha_or_md5(meta)
        if remote_digest is not None and remote_digest == local_sha:
            plan.skips.append(UploadItem(rel, local_sha, size, kind))
            continue
        if kind == "immutable":
            plan.conflicts.append(
                ConflictItem(
                    rel,
                    "immutable-sha-conflict",
                    f"remote digest {remote_digest or 'unknown'} != local sha256 {local_sha[:16]}…",
                )
            )
            continue
        # append-only: digest differs → verify superset against remote content
        if transport is None:
            # Planning without transport: treat as conflict (safe default;
            # callers with a transport never hit this).
            plan.conflicts.append(
                ConflictItem(rel, "append-only-regression", "cannot verify superset (no transport)")
            )
            continue
        new_text = path.read_text(encoding="utf-8", errors="replace")
        if check_remote_superset(transport, par_url, rel, new_text):
            plan.uploads.append(UploadItem(rel, local_sha, size, kind))
        else:
            plan.conflicts.append(
                ConflictItem(rel, "append-only-regression", "new content is not a superset of remote")
            )
    return plan
