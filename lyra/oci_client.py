"""OCI Object Storage Pre-Authenticated Request (PAR) client.

Decision 0002 §3.1: the download mechanism is inherited from moneta's
``pipeline/extract_oci.py`` but re-implemented independently (never imported).

Two properties are load-bearing here and are covered by tests:

* **Idempotency (I20)** — objects are listed with ``md5``; a local file that
  already matches the remote ``md5`` is skipped (no request issued). When a
  remote object has no ``md5`` we fall back to a ``size`` comparison.
* **URL redaction (I19)** — a full PAR URL (which embeds a signed token)
  must never leak into logs or exception messages.

The client is transport-injected: anything exposing ``.get(url, params=...,
stream=..., timeout=...)`` returning an object with ``.status_code``,
``.json()``, ``.raise_for_status()``, ``.iter_content()`` works. ``requests``
is the production transport; tests use a fake.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urljoin, urlparse

# --- constants ------------------------------------------------------------

_LIST_FIELDS = "name,size,md5,timeModified"
_DEFAULT_PAGE_SIZE = 1000
_CHUNK = 64 * 1024
_DOWNLOAD_TIMEOUT = 300
_LIST_TIMEOUT = 60
_REDACT_PATH_SEGMENTS = 2


class Transport(Protocol):
    """Minimal HTTP surface required by the client (``requests``-compatible)."""

    def get(self, url: str, **kwargs: Any) -> Any: ...  # pragma: no cover


class ParListError(RuntimeError):
    """Listing objects under a PAR prefix failed."""


class ParObjectError(RuntimeError):
    """Downloading a single object failed."""


class ParExpiredError(ParObjectError):
    """The PAR likely expired (HTTP 403/404); surfaces the O5 diagnostic."""


def redact_par_url(url: str) -> str:
    """Redact a PAR URL to ``scheme://host/<first two path segments>``.

    Keeps just enough to identify the bucket/prefix for humans while
    dropping the signed query string and the deep object path. (I19.)
    """
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    keep = segments[:_REDACT_PATH_SEGMENTS]
    path = "/" + "/".join(keep) if keep else "/"
    return f"{parsed.scheme or 'https'}://{parsed.netloc}{path}"


def _md5_of_file(path: Path) -> bytes | None:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.digest()


def _to_md5_hex(remote_md5: str) -> str | None:
    """Normalize a remote md5 to lowercase hex.

    PAR listings carry the digest as **base64 (24 chars)**; some HTTP Etags
    carry it as **hex (32 chars)**. Both are base64-decodable, so the hex
    form must be detected *first* — otherwise ``b64decode`` of a 32-char hex
    string yields 24 garbage bytes and the comparison can never match.
    """
    v = remote_md5.strip().strip('"')
    if len(v) == 32 and all(c in "0123456789abcdefABCDEF" for c in v):
        return v.lower()
    if len(v) in (24, 25):  # 24: standard; 25: base64 with one pad stripped
        # Base64 of the 16-byte md5 digest → decode gives the digest itself.
        try:
            import base64

            digest = base64.b64decode(v + "=" * (-len(v) % 4))
        except Exception:
            return None
        if len(digest) == 16:
            return digest.hex()
    return None


def _md5_matches(local: Path, remote_md5: str | None) -> bool:
    """Compare a local file's md5 to a remote md5 (base64 or hex form).

    Returns False when *remote_md5* is absent/undecodable — the caller then
    falls back to a size comparison (I20).
    """
    if not remote_md5:
        return False
    local = _md5_of_file(local)
    if local is None:
        return False
    remote_hex = _to_md5_hex(str(remote_md5))
    return remote_hex is not None and remote_hex == local.hex().lower()


def safe_relative_path(name: str, root: Path) -> Path | None:
    """Resolve *name* under *root* without allowing path traversal.

    Traversal is judged on path **components**, so a legitimate file name that
    merely contains ``..`` as a substring (e.g. ``EUR..USD.csv``) is accepted,
    while ``../evil``, absolute paths, and drive prefixes are rejected.
    (moneta's guard, re-implemented.)
    """
    cleaned = name.strip()
    if not cleaned or cleaned.startswith("/") or cleaned.startswith("\\"):
        return None
    parts = [p for p in cleaned.replace("\\", "/").split("/") if p]
    if any(part in (".", "..") for part in parts):
        return None
    if any(":" in part for part in parts):
        return None
    root_resolved = Path(root).resolve()
    candidate = root_resolved
    for part in parts:
        candidate = candidate / part
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    if resolved == root_resolved:
        return None
    return resolved


def _objects_from_page(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    batch = payload.get("objects", [])
    return [o for o in batch if isinstance(o, dict) and o.get("name")]


def list_objects(
    transport: Transport,
    par_prefix_url: str,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """List every object under a PAR *prefix* URL, handling pagination.

    Uses ``nextStartWith``; a ``seen_starts`` set guards against a
    server-provided cursor looping forever.
    """
    base = par_prefix_url if par_prefix_url.endswith("/") else par_prefix_url + "/"
    objects: list[dict[str, Any]] = []
    start: str | None = None
    seen: set[str] = set()

    while True:
        params: dict[str, Any] = {"fields": _LIST_FIELDS, "limit": page_size}
        if start:
            params["start"] = start
        response = transport.get(base, params=params, timeout=_LIST_TIMEOUT)
        if _is_expiry(response.status_code):
            raise ParExpiredError(
                f"PAR listing returned {response.status_code} for "
                f"{redact_par_url(base)} — the PAR may have expired (O5)."
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ParListError(
                f"PAR listing at {redact_par_url(base)} did not return JSON."
            ) from exc

        objects.extend(_objects_from_page(payload))

        next_start = payload.get("nextStartWith")
        if not next_start or next_start in seen:
            break
        seen.add(next_start)
        start = str(next_start)
    return objects


def _is_expiry(status_code: int) -> bool:
    return status_code in (401, 403, 404)


def _object_url(base: str, name: str) -> str:
    return urljoin(base, name)


def _is_local_up_to_date(local: Path, obj: Mapping[str, Any]) -> bool:
    """I20 idempotency: md5-first, size-fallback."""
    if not local.exists():
        return False
    remote_md5 = obj.get("md5")
    if remote_md5:
        return _md5_matches(local, str(remote_md5))
    remote_size = obj.get("size")
    if remote_size is not None:
        return local.stat().st_size == int(remote_size)
    # Nothing to compare on: re-download to be safe.
    return False


def download_object(
    transport: Transport,
    base: str,
    name: str,
    save_dir: Path,
    obj: Mapping[str, Any] | None = None,
) -> Path:
    """Download one object to *save_dir*/name (idempotent). Returns the path.

    Raises ``ParExpiredError`` on 401/403/404; ``ParObjectError`` otherwise.
    """
    target = safe_relative_path(name, save_dir)
    if target is None:
        raise ParObjectError(f"Refusing unsafe object name: {name!r}")
    target.parent.mkdir(parents=True, exist_ok=True)

    if obj is not None and _is_local_up_to_date(target, obj):
        return target  # idempotent skip — no request issued (I20)

    obj_url = _object_url(base, name)
    response = transport.get(obj_url, stream=True, timeout=_DOWNLOAD_TIMEOUT)
    if _is_expiry(response.status_code):
        raise ParExpiredError(
            f"PAR download returned {response.status_code} for "
            f"{redact_par_url(obj_url)} — the PAR may have expired (O5)."
        )
    if not response.ok:
        raise ParObjectError(
            f"Failed to download {redact_par_url(obj_url)}: {response.status_code}"
        )
    with target.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=_CHUNK):
            if chunk:
                handle.write(chunk)
    return target


def sync_par(
    transport: Transport,
    par_prefix_url: str,
    save_dir: str | Path,
) -> list[Path]:
    """List + download every object under *par_prefix_url* into *save_dir*.

    Idempotent (I20): objects whose local copy already matches are skipped.
    Returns the list of local file paths present after the sync.
    """
    save = Path(save_dir)
    base = par_prefix_url if par_prefix_url.endswith("/") else par_prefix_url + "/"
    objects = list_objects(transport, par_prefix_url)
    by_name = {str(o["name"]): o for o in objects}
    results: list[Path] = []
    for obj in objects:
        name = str(obj["name"]).strip()
        if not name or name.endswith("/"):
            continue  # skip directory markers
        results.append(download_object(transport, base, name, save, by_name.get(name)))
    results.sort(key=lambda p: p.as_posix())
    return results
