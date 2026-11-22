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


# ---- #137: feature-layer instrument coverage ------------------------------


def _write_aggregate(root: Path, instruments: list[str], view: str = "ohlcv_1h",
                     bars: int = 40) -> None:
    """Write a synthetic ``<root>/<view>/<view>.parquet`` aggregate."""
    from datetime import datetime, timedelta

    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    rng = np.random.default_rng(7)
    cols: dict[str, list] = {k: [] for k in (
        "instrument", "time", "mid_o", "mid_h", "mid_l", "mid_c", "volume", "n_bars")}
    for inst in instruments:
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, bars)))
        o = np.r_[c[0], c[:-1]]
        cols["instrument"] += [inst] * bars
        cols["time"] += [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(bars)]
        cols["mid_o"] += o.tolist()
        cols["mid_h"] += (np.maximum(o, c) * 1.001).tolist()
        cols["mid_l"] += (np.minimum(o, c) * 0.999).tolist()
        cols["mid_c"] += c.tolist()
        cols["volume"] += rng.integers(100, 1000, bars).tolist()
        cols["n_bars"] += [60] * bars
    (root / view).mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), root / view / f"{view}.parquet")


def _stub_features(root: Path, names: list[str], view: str = "ohlcv_1h") -> None:
    d = root / "features" / view
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.parquet").write_bytes(b"")


def test_layer_coverage_complete(tmp_path):
    from lyra import features

    _write_aggregate(tmp_path, ["AAA", "BBB", "CCC"])
    _stub_features(tmp_path, ["AAA", "BBB", "CCC"])
    (cov,) = features.layer_coverage(tmp_path)
    assert cov["layer"] == "ohlcv_1h" and cov["minutes"] == 60
    assert (cov["source"], cov["features"]) == (3, 3)
    assert cov["missing"] == [] and cov["extra"] == []


def test_layer_coverage_reports_missing_and_extra(tmp_path):
    from lyra import features

    _write_aggregate(tmp_path, ["AAA", "BBB", "CCC"])
    _stub_features(tmp_path, ["AAA", "ZZZ"])
    (cov,) = features.layer_coverage(tmp_path)
    assert cov["missing"] == ["BBB", "CCC"]
    assert cov["extra"] == ["ZZZ"]


def test_layer_coverage_skips_absent_layers(tmp_path):
    from lyra import features

    assert features.layer_coverage(tmp_path) == []            # nothing at all
    _write_aggregate(tmp_path, ["AAA"])
    assert features.layer_coverage(tmp_path) == []            # aggregate but no features/
    _stub_features(tmp_path, ["AAA"], view="ohlcv_5m")        # features/ohlcv_5m, no 5m aggregate
    assert features.layer_coverage(tmp_path) == []


def test_doctor_warns_when_feature_layer_was_truncated(tmp_path):
    """Reproduces #136: ``run_features`` for ONE instrument prunes the other
    instruments' files but rewrites a matching manifest, so the generation
    check still passes.  The coverage check must flag it (as a warning, exit 0)."""
    from lyra import features

    data = tmp_path / "data"
    _write_aggregate(data, ["SPX500_USD", "EUR_USD", "XAU_USD"], bars=1500)
    cfg = _write_config(tmp_path / "config.yml")
    reg = features.build_registry()
    args = ["doctor", "--config", str(cfg), "--data-dir", str(data)]

    features.run_features(data, 60, reg)
    ok = runner.invoke(app, args)
    assert ok.exit_code == 0, ok.output
    assert "PASS feature layers cover every instrument (ohlcv_1h: 3)" in ok.output

    features.run_features(data, 60, reg, instruments=["SPX500_USD"])   # the incident
    bad = runner.invoke(app, args)
    assert bad.exit_code == 0, bad.output                  # warning, not failure
    assert "WARN feature layer features/ohlcv_1h holds 1 of 3 instruments" in bad.output
    assert "EUR_USD" in bad.output and "XAU_USD" in bad.output
    assert "lyra features --minutes 60" in bad.output
    assert "PASS feature layers cover every instrument" not in bad.output
