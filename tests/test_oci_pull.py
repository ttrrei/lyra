"""0009 D2 — strategy/runs *download* (OCI → local) CLI loop tests.

Covers the OCI-authority pull half of the work loop:
  pull-strategy / pull-runs download a direction's objects from the PAR
  bucket into the canonical workspace layout (``~/.lyra/<ws>/strategies/<dir>``
  and ``~/.lyra/<ws>/runs/<dir>``), idempotently (I20 md5-skip), with a
  clean PAR-expiry failure path.
"""

from __future__ import annotations

from typer.testing import CliRunner

from lyra import cli
from tests.conftest import FakePar


def _write_cfg(tmp_path, par_url: str) -> str:
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"oci:\n"
        f"  data_par_url: {par_url}\n"
        f"  strategies_par_url: {par_url}\n"
        f"  runs_par_url: {par_url}\n"
        "local:\n  workspace: ws\n  data: data\n", encoding="utf-8")
    return str(cfg)


def test_pull_strategy_downloads_direction_only(tmp_path, monkeypatch):
    """pull-strategy downloads the requested direction's objects (incl.
    track-level subdirs) into ws/strategies/<dir>/, and does NOT touch other
    directions or the runs bucket."""
    from tests.conftest import PAR_PREFIX as P

    objects = {
        "strategies/fx-trend/v01.yaml": b"id: base\n",
        "strategies/fx-trend/t1/branch.yaml": b"id: b\n",
        "strategies/fx-trend/lessons.md": b"L1\n",
        "strategies/other/v01.yaml": b"other\n",  # different direction → excluded
        "runs/fx-trend/t1/r1/manifest.json": b"{}",  # runs bucket → excluded
    }
    rec = FakePar(objects=objects)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))

    out = CliRunner().invoke(
        cli.app,
        ["pull-strategy", "fx-trend", "--config", _write_cfg(tmp_path, P)],
    )
    assert out.exit_code == 0, out.output

    assert (ws / "strategies/fx-trend/v01.yaml").read_bytes() == b"id: base\n"
    assert (ws / "strategies/fx-trend/t1/branch.yaml").read_bytes() == b"id: b\n"
    assert (ws / "strategies/fx-trend/lessons.md").read_bytes() == b"L1\n"
    # other direction and runs must NOT be pulled by pull-strategy
    assert not (ws / "strategies/other/v01.yaml").exists()
    assert not (ws / "runs/fx-trend/t1/r1/manifest.json").exists()


def test_pull_runs_downloads_direction_only(tmp_path, monkeypatch):
    """pull-runs downloads the requested direction's runs into
    ws/runs/<dir>/, and does NOT touch the strategies bucket."""
    from tests.conftest import PAR_PREFIX as P

    objects = {
        "runs/fx-trend/t1/r1/manifest.json": b'{"ok":1}',
        "runs/fx-trend/t1/r1/trades.parquet": b"pq",
        "runs/other/t1/r1/manifest.json": b'{"other":1}',  # excluded
        "strategies/fx-trend/v01.yaml": b"id: base\n",  # strategies bucket → excluded
    }
    rec = FakePar(objects=objects)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))

    out = CliRunner().invoke(
        cli.app,
        ["pull-runs", "fx-trend", "--config", _write_cfg(tmp_path, P)],
    )
    assert out.exit_code == 0, out.output

    assert (ws / "runs/fx-trend/t1/r1/manifest.json").read_bytes() == b'{"ok":1}'
    assert (ws / "runs/fx-trend/t1/r1/trades.parquet").read_bytes() == b"pq"
    assert not (ws / "runs/other/t1/r1/manifest.json").exists()
    assert not (ws / "strategies/fx-trend/v01.yaml").exists()


def test_pull_strategy_is_idempotent(tmp_path, monkeypatch):
    """A second pull of unchanged objects issues no new download requests
    (I20 md5-skip) — re-pulling before each session is a no-op for matches."""
    from tests.conftest import PAR_PREFIX as P

    objects = {"strategies/fx-trend/v01.yaml": b"id: base\n"}
    rec = FakePar(objects=objects)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))
    cfg = _write_cfg(tmp_path, P)

    first = CliRunner().invoke(cli.app, ["pull-strategy", "fx-trend", "--config", cfg])
    assert first.exit_code == 0, first.output
    downloads_after_first = len([u for u in rec.requests if not u.endswith("/")])

    second = CliRunner().invoke(cli.app, ["pull-strategy", "fx-trend", "--config", cfg])
    assert second.exit_code == 0, second.output
    downloads_after_second = len([u for u in rec.requests if not u.endswith("/")])
    # the second run must not re-download the already-matching file
    assert downloads_after_second == downloads_after_first


def test_pull_strategy_survives_revised_remote(tmp_path, monkeypatch):
    """If the remote object bytes change (same name, same length → same size,
    different md5), the local file must be refreshed — a size-match alone must
    not mask a stale local copy (I20 / R6)."""
    from tests.conftest import PAR_PREFIX as P

    content = b"id: base\n"
    objects = {"strategies/fx-trend/v01.yaml": content}
    rec = FakePar(objects=objects)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))
    cfg = _write_cfg(tmp_path, P)

    first = CliRunner().invoke(cli.app, ["pull-strategy", "fx-trend", "--config", cfg])
    assert first.exit_code == 0, first.output
    assert (ws / "strategies/fx-trend/v01.yaml").read_bytes() == content

    # remote revises: same length, different bytes → md5 changes
    revised = b"id: new \n"  # len == len(content) == 9
    assert len(revised) == len(content)
    rec.objects["strategies/fx-trend/v01.yaml"] = revised

    second = CliRunner().invoke(cli.app, ["pull-strategy", "fx-trend", "--config", cfg])
    assert second.exit_code == 0, second.output
    assert (ws / "strategies/fx-trend/v01.yaml").read_bytes() == revised


def test_pull_strategy_empty_direction(tmp_path, monkeypatch):
    """A direction with no objects in the bucket reports 'no objects' and
    exits 0 (nothing to pull is not an error)."""
    from tests.conftest import PAR_PREFIX as P

    objects = {"strategies/other/v01.yaml": b"other\n"}  # not fx-trend
    rec = FakePar(objects=objects)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))

    out = CliRunner().invoke(
        cli.app,
        ["pull-strategy", "fx-trend", "--config", _write_cfg(tmp_path, P)],
    )
    assert out.exit_code == 0, out.output
    assert "no strategies/fx-trend" in out.output
    assert not (ws / "strategies").exists()


def test_pull_strategy_expired_par_fails_closed(tmp_path, monkeypatch):
    """A 401/403/404 listing (expired PAR, O5) must fail closed with a
    non-zero exit and an actionable message — never silently no-op."""
    from tests.conftest import PAR_PREFIX as P

    rec = FakePar(objects={"strategies/fx-trend/v01.yaml": b"x"}, list_status=403)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))

    out = CliRunner().invoke(
        cli.app,
        ["pull-strategy", "fx-trend", "--config", _write_cfg(tmp_path, P)],
    )
    assert out.exit_code != 0
    assert "expired" in out.output or "PAR" in out.output


def test_pull_strategy_dry_run_fetches_nothing(tmp_path, monkeypatch):
    """--dry-run lists what would be pulled but downloads no bytes."""
    from tests.conftest import PAR_PREFIX as P

    objects = {"strategies/fx-trend/v01.yaml": b"id: base\n"}
    rec = FakePar(objects=objects)
    monkeypatch.setattr(cli, "_push_transport", lambda: rec)
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setenv("LYRA_DATA_ROOT", str(ws / "data"))

    out = CliRunner().invoke(
        cli.app,
        ["pull-strategy", "fx-trend", "--dry-run",
         "--config", _write_cfg(tmp_path, P)],
    )
    assert out.exit_code == 0, out.output
    assert "would pull" in out.output
    assert not (ws / "strategies").exists()
