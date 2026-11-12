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


def test_doctor_missing_oci_slot_hard_fails_exit_one(tmp_path):
    """0009 D10 (H4): all four OCI slots are HARD requirements — a config
    missing features/strategies/runs must fail closed, not warn-and-pass."""
    cfg = _write_config(
        tmp_path / "config.yml",
        features_par_url="", strategies_par_url="", runs_par_url="",
    )
    result = runner.invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    # each missing slot is reported as a failure
    for slot in ("features_par_url", "strategies_par_url", "runs_par_url"):
        assert slot in result.output


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
