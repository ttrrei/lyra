"""0009 D10 — lyra-doctor severity-level tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from lyra.cli import app

runner = CliRunner()


def _write_config(
    path: Path,
    *,
    data_par_url: str = "https://par.example/b/lyra/o/raw",
    features_par_url: str = "https://par.example/b/lyra/o/feats",
    strategies_par_url: str = "https://par.example/b/lyra/o/strats",
    runs_par_url: str = "https://par.example/b/lyra/o/runs",
) -> Path:
    path.write_text(textwrap.dedent(f"""
        oci:
          data_par_url: {data_par_url}
          features_par_url: {features_par_url}
          strategies_par_url: {strategies_par_url}
          runs_par_url: {runs_par_url}
        local:
          workspace: dw
          data: data
    """), encoding="utf-8")
    return path


def test_doctor_all_hard_checks_pass_exit_zero(tmp_path):
    """0009 D10 (H4): with a parseable config, core deps importable, and all
    four OCI slots set, doctor exits 0 — data-layer items are only warnings."""
    cfg = _write_config(tmp_path / "config.yml")
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "DOCTOR OK" in result.output
    # data-layer checks are warnings, not failures (no pull/build yet)
    assert "WARN" in result.output


def test_doctor_push_slots_empty_are_warnings_not_failures(tmp_path):
    """P1-4 (UsageFinalReview): the push-only OCI slots (features/strategies/
    runs) are documented as OPTIONAL — config.py says "`lyra pull` must never
    require the push PAR slots" and config_example.yml says "Leave a slot empty
    if that bucket is not configured yet".  A pull-only setup (only
    ``data_par_url`` set) must PASS doctor with the three push slots reported
    as WARNINGS, not hard failures."""
    cfg = _write_config(
        tmp_path / "config.yml",
        features_par_url="", strategies_par_url="", runs_par_url="",
    )
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "DOCTOR OK" in result.output
    # the three push slots are surfaced (as warnings), and the data slot passed
    assert "PASS config slot data_par_url set" in result.output
    for slot in ("features_par_url", "strategies_par_url", "runs_par_url"):
        assert slot in result.output


def test_doctor_data_slot_missing_hard_fails_exit_one(tmp_path):
    """P1-4 (UsageFinalReview): ``data_par_url`` is the ONLY slot ``lyra pull``
    needs, so it is the hard requirement.  A config missing it must still fail
    closed (unlike the push-only slots, which are warnings)."""
    cfg = _write_config(
        tmp_path / "config.yml",
        data_par_url="",  # the required slot missing
    )
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1, result.output
    assert "data_par_url" in result.output
    assert "FAIL" in result.output


def test_doctor_bad_config_hard_fails_exit_one(tmp_path):
    """0009 D10: an unparseable / slot-missing config is a HARD failure."""
    cfg = tmp_path / "config.yml"
    cfg.write_text("oci: {}", encoding="utf-8")  # data_par_url missing
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_doctor_missing_config_file_hard_fails(tmp_path):
    """0009 D10: a non-existent config path is a HARD failure."""
    result = runner.invoke(app, ["doctor", "--config", str(tmp_path / "nope.yml")])
    assert result.exit_code == 1
    assert "FAIL" in result.output
