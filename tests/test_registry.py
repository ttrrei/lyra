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
    assert len(names) == 146, "R3.1 / §3.4 fixed list — count is a contract (F1)"


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
    assert len(core) == 146


def test_resolve_column_unknown_hint_suggests_close_match():
    """#130: unknown-feature error should suggest a close registered name
    (did-you-mean) so a web-AI knows a valid feature exists near its guess."""
    from lyra.strategy_schema import _resolve_column
    from lyra.features import build_registry
    reg = build_registry()
    # "return_6" is not registered (real one is return_6_atr)
    try:
        _resolve_column("return_6", reg, file="x.yaml", yaml_path="entry.long.all[0]")
        raise AssertionError("expected SchemaError")
    except Exception as e:
        msg = str(e)
        assert "unknown feature" in msg
        assert "return_6_atr" in msg, f"expected did-you-mean hint, got: {msg}"


def test_resolve_column_unknown_generic_hint():
    """#130: a name with no close match gets the 'lyra context' hint."""
    from lyra.strategy_schema import _resolve_column
    from lyra.features import build_registry
    reg = build_registry()
    try:
        _resolve_column("zzz_totally_bogus_qq", reg, file="x.yaml", yaml_path="p")
        raise AssertionError("expected SchemaError")
    except Exception as e:
        msg = str(e)
        assert "unknown feature" in msg
        assert "lyra context" in msg, f"expected context hint, got: {msg}"
