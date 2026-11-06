"""Shared fixtures: a fake OCI PAR transport + moneta-format CSV builder."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

HEADER = (
    "instrument,is_complete,time,volume,mid_o,mid_h,mid_l,mid_c,"
    "bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c"
)

PAR_PREFIX = "https://objectstorage.example/p/x/n/y/b/lyra/o/data/"


class FakeResponse:
    def __init__(self, status_code: int = 200, body: bytes = b"", json_body: dict | None = None):
        self.status_code = status_code
        self._body = body
        self._json = json_body
        self.ok = 200 <= status_code < 300

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


def md5_b64(data: bytes) -> str:
    """md5 as base64 — the encoding OCI PAR listings use."""
    return base64.b64encode(hashlib.md5(data).digest()).decode()


class FakePar:
    """A transport implementing ``oci_client.Transport`` against an in-memory
    PAR bucket. Records every request so tests can assert idempotent skips."""

    def __init__(self, objects: dict[str, bytes] | None = None, pages: int | None = None,
                 list_status: int = 200, download_status: int = 200, drop_md5: bool = False):
        self.objects = objects or {}
        self.pages = pages  # if set, split the listing into this many pages
        self.list_status = list_status
        self.download_status = download_status
        self.drop_md5 = drop_md5
        self.requests: list[str] = []

    def get(self, url: str, **kwargs):
        self.requests.append(url)
        if url.endswith("/"):  # prefix listing
            return self._list(kwargs.get("params") or {})
        name = url[len(PAR_PREFIX):]
        data = self.objects.get(name)
        if data is None or self.download_status != 200:
            return FakeResponse(self.download_status)
        return FakeResponse(200, body=data)

    def _list(self, params: dict):
        if self.list_status != 200:
            return FakeResponse(self.list_status)
        names = sorted(self.objects)
        start = params.get("start")
        if start:
            names = [n for n in names if n > start]
        limit = int(params.get("limit", 1000))
        if self.pages and len(names) > 1:
            # ceil: guarantees each page advances past at least one name.
            limit = max(1, -(-len(names) // self.pages))
        page = names[:limit]
        objects = [
            {"name": n, "size": len(self.objects[n]),
             **({} if self.drop_md5 else {"md5": md5_b64(self.objects[n])})}
            for n in page
        ]
        next_start = page[-1] if len(page) == limit and len(names) > len(page) else None
        return FakeResponse(200, json_body={"objects": objects, "nextStartWith": next_start})


def make_csv_bytes(instrument: str, start_minute: int, n_rows: int, complete: bool = True,
                   o: float = 100.0, vol: float = 10.0) -> bytes:
    """Moneta-format 1m CSV: ``time`` as UTC ISO ``YYYY-MM-DD HH:MM:SS``."""
    import datetime

    lines = [HEADER]
    for i in range(n_rows):
        t = datetime.datetime(2026, 1, 2, 0, 0) + datetime.timedelta(minutes=start_minute + i)
        # Physically valid quote: bid below mid, ask above mid, ask >= bid at
        # every point (0002 §3.4 DQ2). The original fixture had bid_l > ask_l
        # (impossible), which the data-quality gate correctly rejects.
        lines.append(
            f"{instrument},{str(complete).lower()},{t.strftime('%Y-%m-%d %H:%M:%S')},"
            f"{vol},{o + i},{o + i + 1},{o + i - 1},{o + i + 0.5},"
            f"{o + i - 0.2},{o + i + 0.8},{o + i - 0.8},{o + i + 0.2},"
            f"{o + i + 0.2},{o + i + 1.2},{o + i - 0.2},{o + i + 0.7}"
        )
    return ("\n".join(lines) + "\n").encode()


def make_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)


@pytest.fixture
def fake_par():
    return FakePar


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"
