"""0003 registry / alpha-loader tests (0003 §5, rows 1-4)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from lyra import features
from lyra.registry import RegistryError


def test_registry_core_names_unique():
    reg = features.build_registry()
    names = reg.names()
    assert len(names) == len(set(names))
    assert len(names) == 116, "R3.1 / §3.4 fixed list — count is a contract (F1)"


def test_registry_alpha_conflict_raises(tmp_path: Path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    (alpha / "zz.py").write_text(textwrap.dedent(
        """
        def register(reg):
            import numpy as np
            def _one(ctx, spec):
                return np.ones(ctx.n)
            reg.register("sma_24", _one, kind="value", unit="price",
                         warmup_bars=0, family="alpha", params={}, window_params=())
        """
    ))
    with pytest.raises((RegistryError, features.AlphaLoadError)):
        features.load_from(alpha)


def test_load_from_alpha_dir(tmp_path: Path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    (alpha / "zz.py").write_text(textwrap.dedent(
        """
        def register(reg):
            import numpy as np
            def _one(ctx, spec):
                return np.ones(ctx.n)
            reg.register("alpha_one", _one, kind="value", unit="price",
                         warmup_bars=0, family="alpha", params={}, window_params=())
        """
    ))
    reg = features.load_from(alpha)
    assert "alpha_one" in reg
    assert "sma_24" in reg  # core still present


def test_load_from_core_only_unchanged(tmp_path: Path):
    core = features.build_registry()
    reg = features.load_from(tmp_path / "no_such_dir")
    assert reg.names() == core.names()
    # I16: the core registry itself is untouched.
    assert len(core) == 116
