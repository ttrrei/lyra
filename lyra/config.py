"""Config loading (decision 0002 §3.1 / B10).

Real values live in ``config/config.yml`` (gitignored); the repo ships only
``config/config_example.yml``. The loader reads whatever ``config_path`` is
given and validates the subset 0002 needs. ``lyra pull`` must never require
the push PAR slots to be present (they are reserved for 0007).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class OandaConfig:
    """OANDA API access for the gap/backfill tool (0002 §3.5).

    ``api_token`` is a secret — it lives only in the gitignored
    ``config/config.yml`` and is never committed (moneta's convention).
    Absent/empty token means "OANDA backfill is not configured"; the
    OCI-PAR pull pipeline is unaffected.
    """

    api_token: str = field(default="", repr=False)  # secret: never in repr/log (批次08-D5)
    host: str = "api-fxpractice.oanda.com"
    # "MBA" = mid + bid + ask components (matches the bronze schema).
    price: str = "MBA"
    granularity: str = "M1"


@dataclass(frozen=True)
class DatabackendConfig:
    """DuckDB resource limits (D3, batch-7).

    ``memory_limit`` is applied as ``SET max_memory`` on every pipeline
    connection and ``tmp`` (resolved under the data root) as
    ``SET temp_directory``, so a low-RAM machine spills to disk instead of
    being OOM-killed. ``threads`` is applied the same way (optional).
    """

    memory_limit: str = "16GB"
    threads: int | None = None
    tmp: str = "tmp"


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


def databackend_from_dict(data: dict) -> DatabackendConfig:
    """Parse the optional ``databackend`` section (D3, batch-7).

    Absent/invalid sections fall back to sane defaults (DuckDB's own default
    is 80% of host RAM — we keep that default memory_limit conservative by
    NOT setting it when the user did not configure one… but we DO set it to
    16GB as an explicit ceiling so a runaway query cannot eat 32GB+ on a
    64GB box).
    """
    db = data.get("databackend")
    if db is None:
        return DatabackendConfig()
    if not isinstance(db, dict):
        raise ConfigError("'databackend' must be a mapping")
    threads = db.get("threads")
    if threads is not None:
        try:
            threads = int(threads)
        except (TypeError, ValueError):
            raise ConfigError(f"databackend.threads must be an integer: {threads!r}")
    return DatabackendConfig(
        memory_limit=str(db.get("memory_limit", "16GB")),
        threads=threads,
        tmp=str(db.get("tmp", "tmp")),
    )


def oanda_from_dict(data: dict) -> OandaConfig:
    """Parse the optional ``oanda`` section (0002 §3.5).

    Absent section → a default ``OandaConfig`` with an empty token, so
    callers can uniformly check ``cfg.api_token`` to decide availability.
    """
    o = data.get("oanda")
    if o is None:
        return OandaConfig()
    if not isinstance(o, dict):
        raise ConfigError("'oanda' must be a mapping")
    return OandaConfig(
        api_token=str(o.get("api_token") or "").strip(),
        host=str(o.get("host", "api-fxpractice.oanda.com")),
        price=str(o.get("price", "MBA")).upper(),
        granularity=str(o.get("granularity", "M1")).upper(),
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
