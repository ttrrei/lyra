"""Config loading (decision 0002 §3.1 / B10).

Real values live in ``config/config.yml`` (gitignored); the repo ships only
``config/config_example.yml``. The loader reads whatever ``config_path`` is
given and validates the subset 0002 needs. ``lyra pull`` must never require
the push PAR slots to be present (they are reserved for 0007).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(ValueError):
    """The config file is missing or invalid for 0002."""


@dataclass(frozen=True)
class OciConfig:
    data_par_url: str
    # Reserved for 0007; may be empty/absent in 0002.
    strategies_par_url: str = ""
    features_par_url: str = ""
    auth_file: str = ""


@dataclass(frozen=True)
class LocalConfig:
    workspace: str = "default"
    data: str = "data"
    strategies: str = "strategies"
    runs: str = "runs"
    alpha: str = "alpha"
    tmp: str = "data/tmp"


def load_config(config_path: str | Path) -> dict:
    """Parse a YAML config file into a dict (raises ``ConfigError`` on problems)."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    with path.open("r") as fh:
        try:
            data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping: {path}")
    return data


def oci_from_dict(data: dict) -> OciConfig:
    oci = data.get("oci") or {}
    if not isinstance(oci, dict):
        raise ConfigError("'oci' must be a mapping")
    url = str(oci.get("data_par_url") or "").strip()
    if not url:
        raise ConfigError("oci.data_par_url is required for 0002")
    return OciConfig(
        data_par_url=url,
        strategies_par_url=str(oci.get("strategies_par_url") or ""),
        features_par_url=str(oci.get("features_par_url") or ""),
        auth_file=str(oci.get("auth_file") or ""),
    )


def local_from_dict(data: dict) -> LocalConfig:
    local = data.get("local") or {}
    if not isinstance(local, dict):
        raise ConfigError("'local' must be a mapping")
    return LocalConfig(
        workspace=str(local.get("workspace", "default")),
        data=str(local.get("data", "data")),
        strategies=str(local.get("strategies", "strategies")),
        runs=str(local.get("runs", "runs")),
        alpha=str(local.get("alpha", "alpha")),
        tmp=str(local.get("tmp", "data/tmp")),
    )


def resolve_data_root(local: LocalConfig, override: str | None = None) -> Path:
    """The directory holding ``raw_zips/ raw_csv/ all_data/ ohlcv_5m/ ohlcv_1h/``.

    Defaults to ``~/.lyra/<workspace>/<data>`` (B13 — outside the repo).
    ``--data-root`` or the ``LYRA_DATA_ROOT`` env var override for co-location.
    """
    if override:
        return Path(override).expanduser()
    env = os.environ.get("LYRA_DATA_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".lyra" / local.workspace / local.data
