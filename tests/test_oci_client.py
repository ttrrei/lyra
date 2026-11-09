"""0002 required tests — OCI PAR client layer (I19/I20 + pagination)."""

from __future__ import annotations

import io
import zipfile

import pytest

from conftest import PAR_PREFIX, FakePar, make_csv_bytes, md5_b64
from lyra import oci_client


def _zip_bytes(instrument: str = "XAU_USD", n: int = 4) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{instrument}.csv", make_csv_bytes(instrument, 0, n))
    return buf.getvalue()





def test_oci_list_pagination(fake_par, tmp_path):
    """Three objects, server splits into 2 pages → client reassembles all."""
    objects = {f"z{i}.zip": _zip_bytes() for i in range(3)}
    client = FakePar(objects=objects, pages=2)
    result = oci_client.list_objects(client, PAR_PREFIX)
    names = [o["name"] for o in result]
    assert names == ["z0.zip", "z1.zip", "z2.zip"]
    # Two listing requests (page 2 cursor = last name of page 1 = "z0.zip").
    assert len(client.requests) == 2


def test_oci_download_idempotent_md5(fake_par, tmp_path):
    """I20: a local file matching the remote md5 (base64) is NOT re-downloaded."""
    data = _zip_bytes()
    client = FakePar(objects={"a.zip": data})
    first = oci_client.sync_par(client, PAR_PREFIX, tmp_path)
    assert len(first) == 1
    requests_before = len(client.requests)
    assert requests_before == 2  # 1 list + 1 download

    again = oci_client.sync_par(client, PAR_PREFIX, tmp_path)
    assert len(again) == 1
    assert len(client.requests) == requests_before + 1  # only the re-list


def test_oci_download_md5_mismatch(fake_par, tmp_path):
    """I20: local file whose md5 does NOT match the listed md5 must be
    re-downloaded, and the result must be the (new) served bytes."""
    served = b"SERVED-CONTENT-BBBB"
    # Bucket lists an md5 that matches *served*; the local file holds old
    # bytes → the client must treat it as stale and re-download.
    client = FakePar(objects={"a.zip": served})
    (tmp_path / "a.zip").write_bytes(b"STALE-LOCAL-CONTENT")
    before = len(client.requests)
    out = oci_client.sync_par(client, PAR_PREFIX, tmp_path)
    assert [p.name for p in out] == ["a.zip"]
    assert (tmp_path / "a.zip").read_bytes() == served
    assert len(client.requests) > before  # a download request was issued

    # Contrast: once the local file matches the listed md5, no download.
    before2 = len(client.requests)
    oci_client.sync_par(client, PAR_PREFIX, tmp_path)
    assert len(client.requests) == before2 + 1  # only the re-list


def test_oci_unsafe_name_rejected(tmp_path):
    """Path traversal must be rejected even if a listing emits one."""
    client = FakePar(objects={"a.zip": _zip_bytes()})
    evil = {"name": "../evil.zip", "size": 10, "md5": md5_b64(b"x")}
    with pytest.raises(oci_client.ParObjectError, match="unsafe"):
        oci_client.download_object(client, PAR_PREFIX, "../evil.zip", tmp_path, evil)
    assert not (tmp_path.parent / "evil.zip").exists()
    # A legal name containing '..' as a substring is fine.
    ok = {"name": "EUR..USD.zip", "size": len(b"y"), "md5": md5_b64(b"y")}
    client2 = FakePar(objects={"EUR..USD.zip": b"y"})
    p = oci_client.download_object(client2, PAR_PREFIX, "EUR..USD.zip", tmp_path, ok)
    assert p.name == "EUR..USD.zip"


def test_oci_size_match_is_not_a_content_proof(tmp_path):
    """R1: when the remote lists no verifiable digest (md5 dropped), a size
    match must NOT be treated as content identity — the object is re-downloaded
    so a same-length new revision cannot keep serving stale local data."""
    old = b"old-content-x"
    new = b"new-content-y"  # different content, same length
    client = FakePar(objects={"a.zip": new}, drop_md5=True)
    target = tmp_path / "a.zip"
    target.write_bytes(old)  # local file has the *same size* but stale content

    result = oci_client.download_object(client, PAR_PREFIX, "a.zip", tmp_path,
                                        {"name": "a.zip", "size": len(new)})
    # Must have re-downloaded, so the local bytes now match the served content.
    assert result == target
    assert target.read_bytes() == new
    # The re-download proves no size-based skip occurred.
    assert any("a.zip" in r for r in client.requests)


def test_par_expiry_diagnostic(tmp_path):
    """401/403/404 must raise ParExpiredError with the redacted O5 message."""
    client = FakePar(objects={"a.zip": _zip_bytes()}, list_status=403)
    with pytest.raises(oci_client.ParExpiredError) as excinfo:
        oci_client.list_objects(client, PAR_PREFIX)
    msg = str(excinfo.value)
    assert "403" in msg
    assert "expired" in msg
    # I19: the signed URL must not leak.
    assert "token" not in msg and PAR_PREFIX not in msg
    assert "objectstorage.example" in msg

    # Download path: listing ok, object 404.
    client2 = FakePar(objects={"a.zip": _zip_bytes()}, download_status=404)
    with pytest.raises(oci_client.ParExpiredError):
        oci_client.sync_par(client2, PAR_PREFIX, tmp_path)


def test_par_url_redacted_in_logs():
    """I19: host + first two path segments only, query string dropped."""
    url = (
        "https://objectstorage.ap-x.oraclecloud.com/p/abc123/n/lyra/b/bkt/o/data/"
        "XAU_USD.zip?Expires=123&Signature=SECRET-SIG"
    )
    redacted = oci_client.redact_par_url(url)
    # I19: host + first two path segments; signed query and deep path dropped.
    assert redacted == "https://objectstorage.ap-x.oraclecloud.com/p/abc123"
    assert "SECRET-SIG" not in redacted
    assert "XAU_USD" not in redacted
    assert "Expires" not in redacted


def test_sync_par_skips_directory_markers(fake_par, tmp_path):
    """Names ending in '/' (directory markers) are not downloaded."""
    objects = {"a.zip": _zip_bytes(), "sub/": b""}
    client = FakePar(objects=objects)
    out = oci_client.sync_par(client, PAR_PREFIX, tmp_path)
    assert [p.name for p in out] == ["a.zip"]
