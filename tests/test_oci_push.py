"""0007 Part A — OCI push (I17 two-tier gate, D2/D4/D9/D10) tests."""

from __future__ import annotations

import hashlib

import pytest

from lyra.oci_push import OciPushError, classify_path, is_append_only_superset, push, sha256_of_file
from tests.conftest import FakePar, FakeResponse

PREFIX = "https://objectstorage.example/p/x/n/y/b/lyra/o/data/"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def seed_local(root, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


class FakeParRW(FakePar):
    """FakePar + put() that records uploads; listings carry sha256 digests."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.puts: list[str] = []

    def put(self, url, **kwargs):
        self.puts.append(url)
        name = url[len(PREFIX):]
        data = kwargs.get("data", b"")
        self.objects[name] = data
        return FakeResponse(200)

    def _list(self, params: dict):
        if self.list_status != 200:
            return FakeResponse(self.list_status)
        names = sorted(self.objects)
        start = params.get("start")
        if start:
            names = [n for n in names if n > start]
        limit = int(params.get("limit", 1000))
        page = names[:limit]
        objects = [
            {
                "name": n,
                "size": len(self.objects[n]),
                "sha256": hashlib.sha256(self.objects[n]).hexdigest(),
            }
            for n in page
        ]
        next_start = page[-1] if len(names) > len(page) else None
        return FakeResponse(200, json_body={"objects": objects, "nextStartWith": next_start})


# --- classification unit tests ---------------------------------------------


@pytest.mark.parametrize(
    "rel,kind",
    [
        ("runs/eurusd/t1/r1/manifest.json", "immutable"),
        ("runs/eurusd/t1/r1/trades.parquet", "immutable"),
        ("strategies/fx/v01.yaml", "immutable"),
        ("strategies/fx/v12.yaml", "immutable"),
        ("strategies/fx/hypothesis.md", "append_only"),
        ("strategies/fx/lessons.md", "append_only"),
        ("strategies/fx/index/t1.json", "append_only"),
        ("alpha/features/fx/x.py", "immutable"),
        ("data/market/oanda/bronze/x.parquet", "immutable"),
        ("strategies/fx/notes.md", "unclassified"),
        ("strategies/fx/README.md", "unclassified"),
        ("strategies/fx/v01.yaml.bak", "unclassified"),
        ("strategies/fx/v01.yaml/evil", "unclassified"),
        ("strategies/v01.yaml", "unclassified"),
        ("README.md", "unclassified"),
    ],
)
def test_classify_matrix(rel, kind):
    assert classify_path(rel) == kind


def test_superset_line_granularity():
    assert is_append_only_superset("a\nb", "a\nb\nc")
    assert is_append_only_superset("", "anything")
    assert is_append_only_superset("\n\n", "x")
    assert is_append_only_superset("a\nb", "x\na\ny\nb")  # inserts allowed
    assert not is_append_only_superset("a\nb", "a\nc")
    assert not is_append_only_superset("a\nb", "b")
    assert not is_append_only_superset("x ", "x")  # whitespace differs (verbatim, C2)


def test_superset_reorder_rejected():
    """C2 tightening: a reorder (same set, different order) is NOT a
    legal append-only advance — old lines must be preserved in order."""
    assert not is_append_only_superset("line1\nline2", "line2\nline1")
    # but appending a line at the end is fine
    assert is_append_only_superset("line1\nline2", "line1\nline2\nline3")


# --- Part A 13-case matrix (0007 §5) ----------------------------------------


def test_push_immutable_new_uploads(tmp_path):
    seed_local(tmp_path, {"runs/d1/t1/r1/manifest.json": b'{"ok":1}'})
    t = FakeParRW(objects={})
    res = push(t, tmp_path, PREFIX)
    assert res.uploads == ["runs/d1/t1/r1/manifest.json"]
    assert t.puts and t.objects["runs/d1/t1/r1/manifest.json"] == b'{"ok":1}'


def test_push_immutable_same_sha_skips(tmp_path):
    content = b'{"ok":1}'
    seed_local(tmp_path, {"runs/d1/t1/r1/manifest.json": content})
    t = FakeParRW(objects={"runs/d1/t1/r1/manifest.json": content})
    res = push(t, tmp_path, PREFIX)
    assert res.skips == ["runs/d1/t1/r1/manifest.json"]
    assert res.uploads == []
    assert t.puts == []


def test_push_immutable_skip_with_realistic_md5_listing(tmp_path):
    # Regression (self-check 2026-11-10): real OCI PAR listings carry
    # name,size,md5(base64),timeModified — NOT sha256. Comparing a remote
    # md5 to a local sha256 (different digests) made every unchanged object
    # look like an immutable conflict, defeating I20 idempotent skips.
    from tests.conftest import FakePar, md5_b64

    content = b'{"ok":1}'
    seed_local(tmp_path, {"runs/d1/t1/r1/manifest.json": content})

    t = FakePar(objects={"runs/d1/t1/r1/manifest.json": content})
    t.puts = []

    def _put(url, **kwargs):
        t.puts.append(url)
        return FakeResponse(200)

    t.put = _put

    # listing is md5-only (no sha256 field) — realistic PAR shape
    remote = {
        "runs/d1/t1/r1/manifest.json": {
            "name": "runs/d1/t1/r1/manifest.json",
            "size": len(content),
            "md5": md5_b64(content),
            "timeModified": "2026-01-01T00:00:00Z",
        }
    }
    from lyra.oci_push import plan_push

    plan = plan_push(t, tmp_path, PREFIX, remote, top_levels=frozenset({"runs"}))
    assert [s.rel_path for s in plan.skips] == ["runs/d1/t1/r1/manifest.json"]
    assert plan.uploads == []
    assert plan.conflicts == []


def test_push_md5_listing_changed_still_conflict(tmp_path):
    # A genuinely different payload under a md5-only listing must still be
    # an immutable conflict — the md5 fix must not over-skip.
    from tests.conftest import FakePar, md5_b64

    remote_content = b"REMOTE"
    seed_local(tmp_path, {"runs/d1/t1/r1/manifest.json": b"LOCAL"})
    t = FakePar(objects={"runs/d1/t1/r1/manifest.json": remote_content})
    remote = {
        "runs/d1/t1/r1/manifest.json": {
            "name": "runs/d1/t1/r1/manifest.json",
            "size": len(remote_content),
            "md5": md5_b64(remote_content),
        }
    }
    from lyra.oci_push import plan_push

    plan = plan_push(t, tmp_path, PREFIX, remote, top_levels=frozenset({"runs"}))
    assert [c.reason for c in plan.conflicts] == ["immutable-sha-conflict"]
    assert plan.uploads == [] and plan.skips == []


def test_push_immutable_conflict_fails(tmp_path):
    seed_local(tmp_path, {"runs/d1/t1/r1/manifest.json": b"LOCAL"})
    t = FakeParRW(objects={"runs/d1/t1/r1/manifest.json": b"REMOTE"})
    with pytest.raises(OciPushError, match="immutable-sha-conflict"):
        push(t, tmp_path, PREFIX)
    assert t.puts == []  # fail-closed: nothing uploaded


def test_push_immutable_force_push_overrides(tmp_path):
    seed_local(tmp_path, {"runs/d1/t1/r1/manifest.json": b"LOCAL"})
    t = FakeParRW(objects={"runs/d1/t1/r1/manifest.json": b"REMOTE"})
    res = push(t, tmp_path, PREFIX, force_push=True)
    assert res.uploads == ["runs/d1/t1/r1/manifest.json"]
    assert t.objects["runs/d1/t1/r1/manifest.json"] == b"LOCAL"


def test_push_append_only_superset_ok(tmp_path):
    old = b"line1\nline2\n"
    new = b"line1\nline2\nline3\n"
    seed_local(tmp_path, {"strategies/d1/lessons.md": new})
    t = FakeParRW(objects={"strategies/d1/lessons.md": old})
    res = push(t, tmp_path, PREFIX)
    assert res.uploads == ["strategies/d1/lessons.md"]
    assert t.objects["strategies/d1/lessons.md"] == new


def test_push_append_only_regression_fails(tmp_path):
    old = b"line1\nline2\n"
    new = b"line1\nREWRITTEN\n"
    seed_local(tmp_path, {"strategies/d1/lessons.md": new})
    t = FakeParRW(objects={"strategies/d1/lessons.md": old})
    with pytest.raises(OciPushError, match="append-only-regression"):
        push(t, tmp_path, PREFIX)
    assert t.puts == []  # force_push cannot rescue this either
    with pytest.raises(OciPushError, match="append-only-regression"):
        push(t, tmp_path, PREFIX, force_push=True)


def test_push_unclassified_path_fails(tmp_path):
    seed_local(tmp_path, {"strategies/d1/notes.md": b"scratch"})
    t = FakeParRW(objects={})
    with pytest.raises(OciPushError, match="unclassified-path"):
        push(t, tmp_path, PREFIX)
    assert t.puts == []
    with pytest.raises(OciPushError, match="unclassified-path"):
        push(t, tmp_path, PREFIX, force_push=True)


def test_push_no_target_fails(tmp_path):
    seed_local(tmp_path, {"runs/d1/t1/r1/m.json": b"{}"})
    t = FakeParRW(objects={})
    with pytest.raises(OciPushError, match="no push target configured"):
        push(t, tmp_path, "")
    assert t.puts == []


def test_push_url_redacted_in_error(tmp_path):
    seed_local(tmp_path, {"runs/d1/t1/r1/m.json": b"X"})
    t = FakeParRW(objects={"runs/d1/t1/r1/m.json": b"Y"})

    secret = "SECRET-TOKEN-abc123xyz"
    url_with_token = PREFIX + f"?X-Oracle-Signature={secret}"
    with pytest.raises(OciPushError) as ei:
        push(t, tmp_path, url_with_token)
    msg = str(ei.value)
    assert secret not in msg
    assert "objectstorage.example" in msg


def test_push_dry_run_reports_no_upload(tmp_path):
    seed_local(tmp_path, {"runs/d1/t1/r1/new.json": b"NEW", "runs/d1/t1/r1/clash.json": b"LOCAL"})
    t = FakeParRW(objects={"runs/d1/t1/r1/clash.json": b"REMOTE"})
    res = push(t, tmp_path, PREFIX, dry_run=True)
    assert res.dry_run
    assert res.uploads == ["runs/d1/t1/r1/new.json"]
    assert any("clash.json" in c and "immutable-sha-conflict" in c for c in res.conflicts)
    assert t.puts == []
    assert "runs/d1/t1/r1/new.json" not in t.objects


def test_backup_is_push_of_changed(tmp_path):
    """`backup` = push of changed strategies + runs + a summary (R7 one-shot).

    CLI-level equivalence is covered by test_sync_alias_equals_backup;
    here we exercise the *composed* push (strategies + runs) that the CLI
    `backup` command performs.
    """
    seed_local(tmp_path, {"strategies/d1/lessons.md": b"l1\nl2\nl3\n", "runs/d1/t1/r1/m.json": b"{}"})
    t = FakeParRW(objects={"strategies/d1/lessons.md": b"l1\nl2\n"})
    res = push(t, tmp_path, PREFIX)
    assert sorted(res.uploads) == ["runs/d1/t1/r1/m.json", "strategies/d1/lessons.md"]


def _cli_has_command(name: str) -> bool:
    """A command exists if ``<name> --help`` succeeds (robust to
    typer/click internals)."""
    from typer.testing import CliRunner

    from lyra import cli

    out = CliRunner().invoke(cli.app, [name, "--help"])
    return out.exit_code == 0


def test_sync_alias_equals_backup():
    """`lyra sync` and `lyra backup` both exist and dispatch to the same
    `_push_all_roots` body (D10/O15)."""
    from lyra import cli

    assert _cli_has_command("backup")
    assert _cli_has_command("sync")

    # Both callbacks share the same parameter surface.
    import inspect

    by_fn = {c.callback.__name__: c.callback for c in cli.app.registered_commands}
    b_params = set(inspect.signature(by_fn["backup"]).parameters)
    s_params = set(inspect.signature(by_fn["sync_alias"]).parameters)
    assert b_params == s_params


def test_list_is_readonly():
    """`lyra list` is a read-only surface: it must exist, be distinct from
    push/backup, and must NOT accept --force-push or --dry-run (those are
    push-only knobs)."""
    from lyra import cli

    assert _cli_has_command("list")
    assert _cli_has_command("push")
    assert _cli_has_command("backup")

    import inspect

    list_cmd = next(c.callback for c in cli.app.registered_commands
                    if c.callback.__name__ == "list_cmd")
    param_names = set(inspect.signature(list_cmd).parameters)
    assert "force_push" not in param_names
    assert "dry_run" not in param_names
    assert "prefix" in param_names


# --- misc: sha256 helper ------------------------------------------------------


def test_sha256_of_file_roundtrip(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert sha256_of_file(p) == hashlib.sha256(b"abc").hexdigest()


# --- 0007 D7: canonical runs OCI path mapping ---------------------------------


def test_push_runs_maps_to_direction_track_runid(tmp_path, monkeypatch):
    """`push-runs` maps the local 0006 layout `runs/<name>/<date>/<run_id>/`
    to the canonical OCI path `runs/<direction>/<track_id>/<run_id>/` (D7/O2)."""
    import json as _json

    from typer.testing import CliRunner

    from lyra import cli

    # fake workspace: 0006 run artifacts (default root ~/.lyra/runs) + config
    ws = tmp_path / "ws"
    run_id = "abcdef1234567890"
    run_dir = ws / "runs" / "myrun" / "20261110" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "direction": "fx-trend",
        "spec_id": "b0",
        "artifacts": {},
    }
    (run_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")
    (run_dir / "metrics.json").write_text("{}", encoding="utf-8")
    (run_dir / "trades.parquet").write_bytes(b"PAR1")

    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"oci:\n  data_par_url: {PREFIX}\n"
        f"  strategies_par_url: {PREFIX}\n"
        "local:\n  workspace: ws\n  data: data\n",
        encoding="utf-8",
    )

    # stub the network transport with a fake that records put targets
    class Rec(FakeParRW):
        pass

    rec = Rec(objects={})
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)

    out = CliRunner().invoke(
        cli.app,
        ["push-runs", "fx-trend", "myrun", "--track", "alpha", "--config", str(cfg),
         "--runs-root", str(ws / "runs")],
    )
    assert out.exit_code == 0, out.output
    # canonical OCI path (0007 D7): runs/<direction>/<track_id>/<run_id>/
    rel = f"runs/fx-trend/alpha/{run_id}/manifest.json"
    assert rel in rec.objects, f"expected {rel} in {sorted(rec.objects)}"
    assert rec.objects[rel] == _json.dumps(manifest).encode()
    assert f"runs/fx-trend/alpha/{run_id}/trades.parquet" in rec.objects


def test_push_runs_direction_mismatch_fails(tmp_path, monkeypatch):
    import json as _json

    from typer.testing import CliRunner

    from lyra import cli

    ws = tmp_path / "ws"
    run_id = "ff00ff00ff00ff00"
    run_dir = ws / "runs" / "myrun" / "20261110" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        _json.dumps({"run_id": run_id, "direction": "other-dir"}), encoding="utf-8"
    )
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"oci:\n  data_par_url: {PREFIX}\n  strategies_par_url: {PREFIX}\n"
        "local:\n  workspace: ws\n  data: data\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_push_transport", lambda: FakeParRW(objects={}))
    out = CliRunner().invoke(
        cli.app,
        ["push-runs", "fx-trend", "myrun", "--track", "alpha", "--config", str(cfg),
         "--runs-root", str(ws / "runs")],
    )
    assert out.exit_code == 2
    assert "direction mismatch" in out.stderr


def test_out_of_scope_toplevel_skipped(tmp_path):
    """0007 research workspace files (tracks/, reviews/) are local-only and
    must be *skipped* by the push walk — distinct from unclassified files
    *inside* a scoped dir (which stay fail-closed)."""
    seed_local(tmp_path, {
        "strategies/d1/lessons.md": b"l1\nl2\n",
        "tracks/d1/alpha.json": b'{"track_id":"alpha"}',
        "reviews/synthesize-x.md": b"# report",
    })
    t = FakeParRW(objects={})
    res = push(t, tmp_path, PREFIX)
    assert res.uploads == ["strategies/d1/lessons.md"]
    assert "tracks/d1/alpha.json" not in t.objects
    assert "reviews/synthesize-x.md" not in t.objects


def test_top_levels_filter_excludes_data(tmp_path):
    """The one-shot push scopes itself to strategies/runs/alpha (R7); the
    raw data/ layer is not re-pushed by default."""
    seed_local(tmp_path, {
        "strategies/d1/lessons.md": b"l1\n",
        "data/market/x.parquet": b"RAW-BYTES",
        "runs/d1/t1/r1/m.json": b"{}",
    })
    t = FakeParRW(objects={})
    from lyra.oci_push import push as _push

    res = _push(t, tmp_path, PREFIX, top_levels=frozenset({"strategies", "runs", "alpha"}))
    assert res.uploaded_bytes > 0
    assert "data/market/x.parquet" not in t.objects
    assert "strategies/d1/lessons.md" in t.objects
    assert "runs/d1/t1/r1/m.json" in t.objects
    # without the filter, data/ would be in scope (I17 immutable)
    t2 = FakeParRW(objects={})
    res2 = _push(t2, tmp_path, PREFIX)
    assert "data/market/x.parquet" in t2.objects
    assert res2.uploaded_bytes > res.uploaded_bytes
