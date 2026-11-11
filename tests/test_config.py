"""0002 boundary tests — config loading (B10 / reserved PAR slots)."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from lyra.config import (
    ConfigError,
    load_config,
    local_from_dict,
    oci_from_dict,
    resolve_data_root,
)


def test_pull_never_requires_push_par_slots(tmp_path):
    """The push PAR slots (0007) are RESERVED — `lyra pull` must work without them."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(textwrap.dedent(
        """
        oci:
          data_par_url: "https://objectstorage.example/p/x/n/y/b/lyra/o/data/"
        """
    ))
    data = load_config(cfg)
    oci = oci_from_dict(data)
    assert oci.data_par_url.startswith("https://")
    assert oci.strategies_par_url == ""   # absent → empty, not an error
    assert oci.features_par_url == ""
    assert oci.runs_par_url == ""


def test_data_par_url_required(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("oci: {}\n")
    with pytest.raises(ConfigError, match="data_par_url"):
        oci_from_dict(load_config(cfg))


def test_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError, match="config not found"):
        load_config(tmp_path / "nope.yml")


def test_resolve_data_root_precedence(tmp_path, monkeypatch):
    local = local_from_dict({})
    monkeypatch.delenv("LYRA_DATA_ROOT", raising=False)
    assert resolve_data_root(local) == pathlib.Path.home() / ".lyra" / "default" / "data"
    monkeypatch.setenv("LYRA_DATA_ROOT", str(tmp_path / "env"))
    assert resolve_data_root(local) == tmp_path / "env"
    # explicit flag wins over env
    assert resolve_data_root(local, str(tmp_path / "flag")) == tmp_path / "flag"
