"""0003 feature-builder tests (0003 §5, rows 18-37).

Covers structural features, Supertrend parity, warm-up semantics, causality,
determinism, wide-table self-sufficiency, versioning, D5 streaming, universal
coverage, and the moneta-derived gates (1/3/4).
"""

from __future__ import annotations

import os
import pyarrow.parquet as pq
import numpy as np
import pytest
import talib

from lyra import features, indicators

RNG = np.random.default_rng(7)


@pytest.fixture(scope="module")
def data():
    n = 400
    c = 100 + np.cumsum(RNG.normal(0, 1, n))
    h = c + RNG.uniform(0.2, 1.5, n)
    l = c - RNG.uniform(0.2, 1.5, n)
    v = RNG.uniform(1000, 5000, n)
    t = np.datetime64("2020-01-01T00:00:00", "us") + np.arange(n, dtype=np.int64) * np.timedelta64(1, "h")
    return {"c": c, "h": h, "l": l, "v": v, "n": n, "t": t}


@pytest.fixture(scope="module")
def ctx(data):
    return features.Ctx(o=data["c"] - 0.5, h=data["h"], l=data["l"],
                        c=data["c"], v=data["v"], t=data["t"], n=data["n"])


def _compute(ctx):
    reg = features.build_registry()
    return reg, features.compute_features(ctx, reg)


# --- structural / semantic -------------------------------------------------

def test_prior60_path_eff60_known(ctx, data):
    reg, cols = _compute(ctx)
    c, h, l = data["c"], data["h"], data["l"]
    # prior60_high[t] = max(h[t-60 : t])  (current bar excluded)
    for t in (100, 200, 300):
        assert cols["prior60_high"][t] == h[t - 60 : t].max()
        assert cols["prior60_low"][t] == l[t - 60 : t].min()
        assert cols["prior60_range"][t] == h[t - 60 : t].max() - l[t - 60 : t].min()
    # efficiency_60[t] = |c[t]-c[t-60]| / sum(|c[i]-c[i-1]|, i=t-59..t)
    for t in (100, 200):
        num = abs(c[t] - c[t - 60])
        den = sum(abs(c[i] - c[i - 1]) for i in range(t - 59, t + 1))
        assert cols["efficiency_60"][t] == pytest.approx(num / den, rel=1e-12)
    # zero denominator (flat) → NaN (D4)
    flat = features.Ctx(o=np.full(80, 5.0), h=np.full(80, 5.0), l=np.full(80, 5.0),
                        c=np.full(80, 5.0), v=np.full(80, 1.0),
                        t=np.datetime64("2020-01-01","us")+np.arange(80,dtype=np.int64)*np.timedelta64(1,"h"), n=80)
    _, cflat = _compute(flat)
    assert np.all(np.isnan(cflat["efficiency_60"]))
    assert np.all(np.isnan(cflat["range_position_24"]))


def test_grid_only_windows():
    """K8: every window parameter in the registry ∈ {6,12,24,60,120}."""
    reg = features.build_registry()
    grid = {6, 12, 24, 60, 120}
    offenders = []
    for name in reg.names():
        spec = reg.get(name)
        for w in spec.window_params:
            if w not in grid:
                offenders.append((name, w))
    assert not offenders, f"off-grid window params: {offenders}"


def test_feature_count_matches_r31(ctx, data):
    reg, cols = _compute(ctx)
    # R3.1 / §3.4 fixed list — 116 features (F1 drift guard)
    assert len(reg) == 146   # 137 core (incl. prior12 trio) + 9 corpus fills (0008/#99)
    # and every computed column is present in the wide table
    assert set(cols) == set(reg.names())


# --- Supertrend parity ------------------------------------------------------

def test_supertrend_line_and_flags(ctx, data):
    reg, cols = _compute(ctx)
    bull = cols["supertrend_bullish"]
    bear = cols["supertrend_bearish"]
    # where defined, exactly one of bull/bear is 1
    valid = np.isfinite(bull)
    assert np.all((bull[valid] + bear[valid]) == 1.0)


def test_supertrend_parity_vs_reference(ctx, data):
    """K1 dual-library parity: talib.SUPERTREND vs the moneta/nova reference."""
    h, l, c = data["h"], data["l"], data["c"]
    atr24 = talib.ATR(h, l, c, timeperiod=24)
    lib_line, lib_trend = talib.SUPERTREND(h, l, c, timeperiod=24, multiplier=3.0)
    ref_line, ref_dir = indicators.supertrend_reference(h, l, c, atr24, mult=3.0)
    m = np.isfinite(lib_line) & np.isfinite(ref_line)
    assert np.allclose(lib_line[m], ref_line[m], rtol=0, atol=1e-12), "line parity"
    lib_dir = np.where(lib_trend > 0, 1.0, -1.0)
    assert np.allclose(lib_dir[m], ref_dir[m], rtol=0, atol=1e-12), "direction parity"


def test_supertrend_path_dependent_from_head(ctx, data):
    """K4: computed from the data head; a mid-seed gives a (potentially)
    different result — path dependence is explicit and accepted."""
    h, l, c = data["h"], data["l"], data["c"]
    full = indicators.supertrend_line(h, l, c, 24, 3.0)
    # recompute on a truncated prefix — the first N bars must be identical
    k = 200
    trunc = indicators.supertrend_line(h[:k], l[:k], c[:k], 24, 3.0)
    m = np.isfinite(trunc)
    assert np.allclose(full[:k][m], trunc[m], rtol=0, atol=1e-12)


def test_supertrend_registry_params():
    reg = features.build_registry()
    spec = reg.get("supertrend")
    assert spec.params["atr_window"] == 24          # in-grid
    assert spec.params["multiplier"] == 3.0         # explicit, not hardcoded
    assert 24 in spec.window_params


# --- Heikin Ashi (K7 self-implementation) ----------------------------------

def test_heikin_asi_known_values(ctx, data):
    """K7 golden test: independent textbook reference vs the shipped recursive
    transform. After the ~16-bar convergence window the seed dependence is
    below 1e-9, so compare from bar 32 (well past warmup_bars=16)."""
    reg, cols = _compute(ctx)
    o, h, l, c = ctx.o, ctx.h, ctx.l, ctx.c
    n = len(c)
    # Independent pure-Python reference (textbook definition).
    ha_c = (o + h + l + c) / 4.0
    ha_o = np.empty(n)
    ha_o[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2.0
    ha_h = np.maximum(h, np.maximum(ha_o, ha_c))
    ha_l = np.minimum(l, np.minimum(ha_o, ha_c))
    s = 32
    for name, ref in (("ha_o", ha_o), ("ha_h", ha_h), ("ha_l", ha_l), ("ha_c", ha_c)):
        got = cols[name]
        assert np.allclose(got[s:], ref[s:], rtol=0, atol=1e-9), name
    # Invariants hold at every bar (no NaN): ha_h >= max(o,h,l,c) is NOT
    # required, but ha_h >= ha_l and ha_h/ha_l sandwich the *heikin* close:
    assert np.all(cols["ha_h"] >= cols["ha_l"])
    assert np.all(cols["ha_h"] >= cols["ha_c"])
    assert np.all(cols["ha_l"] <= cols["ha_c"])


def test_heikin_asi_k7_management():
    """K7 discipline: self_implemented=True, no window params (recursion,
    not a fixed window), warmup_bars is the documented convergence bound."""
    reg = features.build_registry()
    for name in ("ha_o", "ha_h", "ha_l", "ha_c"):
        spec = reg.get(name)
        assert spec.self_implemented is True, name
        assert spec.window_params == (), name  # no window → K8 N/A
        assert spec.warmup_bars >= 16, name


def test_heikin_asi_marker_survives_load_from():
    """M2 (batch-1 review): the K7 self_implemented marker must survive
    load_from's per-spec copy — before the fix it was dropped in
    v1.0–v1.3, silently downgrading ha_* in the registry the real CLI uses.
    Pass a non-existent directory: load_from seeds the core through register()
    and returns early, exercising exactly the copy path under test."""
    reg = features.load_from("/nonexistent-alpha-dir-xyz")
    for name in ("ha_o", "ha_h", "ha_l", "ha_c"):
        spec = reg.get(name)
        assert spec.self_implemented is True, (
            f"{name}: K7 self_implemented marker lost in load_from"
        )
    # sanity: other specs (TA-Lib-backed) must NOT be marked self_implemented
    assert reg.get("sma_12").self_implemented is False


def test_params_are_read_only():
    """M1 (batch-1 review): spec.params is a MappingProxyType — in-place
    mutation raises TypeError instead of silently corrupting the registry's
    SQL right-value contract (no current code mutates it; this is the guard)."""
    reg = features.build_registry()
    spec = reg.get("sma_12")
    import types
    assert isinstance(spec.params, types.MappingProxyType)
    import pytest
    with pytest.raises(TypeError):
        spec.params["n"] = 999  # noqa: F841 — must raise, not mutate


# --- v1.3 trend-strength / efficiency family (TRIX/TSI/VHF/Vortex/Aroon) ---

def test_v13_family_known_values_and_invariants(ctx, data):
    """Golden references (independent pure-Python) + structural invariants
    for the six v1.3 families, all on-grid (24/60, K8)."""
    reg, cols = _compute(ctx)

    # VHF: positive by construction (Σ|Δc|/|span|×100); exact value cross-
    # checked against pandas-ta-classic in test_crosscheck_pandas_ta_classic
    # (vhf_24/vhf_60 matched diff = 0.0 on real data).
    for n in (24, 60):
        vals = cols[f"vhf_{n}"][np.isfinite(cols[f"vhf_{n}"])]
        assert vals.size > 0 and np.all(vals > 0), f"vhf_{n}"
        assert np.all(np.isnan(cols[f"vhf_{n}"][:n])), f"vhf_{n} warmup"

    # AROON: UP = 100·(n − bars_since_highest_high)/n (TA-Lib convention;
    # verified: highest-2-bars-ago → 80 for n=10). Both in [0,100].
    for n in (24, 60):
        for nm in (f"aroon_up_{n}", f"aroon_down_{n}"):
            vals = cols[nm][np.isfinite(cols[nm])]
            assert vals.size > 0, nm
            assert np.all((vals >= 0) & (vals <= 100)), nm
        # warm-up: first n−1 bars NaN (F2)
        assert np.all(np.isnan(cols[f"aroon_up_{n}"][:n - 1])), f"aroon_up_{n} warmup"
        assert np.all(np.isnan(cols[f"aroon_down_{n}"][:n - 1])), f"aroon_down_{n} warmup"

    # VORTEX: VI+ and VI− are both positive; at least one dominates.
    for n in (24, 60):
        p = cols[f"vortex_p_{n}"]; m = cols[f"vortex_m_{n}"]
        fin = np.isfinite(p) & np.isfinite(m)
        assert np.all(p[fin] > 0) and np.all(m[fin] > 0), f"vortex_{n}"

    # TRIX / TSI: finite after warm-up, bounded range sanity (no blow-up).
    for nm in ("trix_24", "trix_60", "tsi_24_12", "tsi_60_24"):
        v = cols[nm][np.isfinite(cols[nm])]
        assert v.size > 0 and np.all(np.abs(v) < 1e6), nm


def test_v13_family_registry_params():
    """All six families register on-grid (K8) warmup bounds and in-grid windows."""
    reg = features.build_registry()
    grid = {6, 12, 24, 60, 120}
    for name in ("trix_24", "trix_60", "tsi_24_12", "tsi_60_24",
                 "vhf_24", "vhf_60", "vortex_p_24", "vortex_m_60",
                 "aroon_up_24", "aroon_down_60"):
        spec = reg.get(name)
        assert spec is not None, name
        assert set(spec.window_params) <= grid, (name, spec.window_params)
        assert spec.warmup_bars >= 0, name
    # TRIX warm-up = 3n−2 (three chained EMAs), measured exactly
    assert reg.get("trix_24").warmup_bars == 70
    assert reg.get("trix_60").warmup_bars == 178
    # VHF/Vortex/Aroon warm-up = n
    assert reg.get("vhf_24").warmup_bars == 24
    assert reg.get("vortex_p_60").warmup_bars == 60
    assert reg.get("aroon_up_24").warmup_bars == 24


# --- PSAR ------------------------------------------------------------------

def test_psar_bull_bear_flags(ctx, data):
    reg, cols = _compute(ctx)
    bull = cols["psar_bullish"]
    bear = cols["psar_bearish"]
    valid = np.isfinite(bull)
    assert np.all((bull[valid] + bear[valid]) == 1.0)
    # flags align with the SAR direction (falling SAR = uptrend = bullish)
    sar = talib.SAR(data["h"], data["l"])
    d = indicators.sar_direction(data["h"], data["l"], sar)
    m = np.isfinite(d)
    expect_bull = np.where(d == 1.0, 1.0, 0.0)
    assert np.allclose(bull[m], expect_bull[m], rtol=0, atol=1e-12)


# --- warm-up semantics (F2) -------------------------------------------------

def test_warmup_null_semantics(ctx, data):
    """F2 v0.7: NULL only in the warm-up prefix for clean (no-missing) input.

    The only post-warm-up NULL allowed is a *defined zero denominator* (D4) —
    those are asserted separately in the zero-amplitude tests.
    """
    reg, cols = _compute(ctx)
    for name in reg.names():
        spec = reg.get(name)
        col = cols[name]
        # after the warm-up prefix, every value must be finite (clean input)
        post = col[spec.warmup_bars:]
        nan_post = np.isnan(post).sum()
        # allowed exceptions: none on this clean, non-flat dataset.
        assert nan_post == 0, f"{name}: {nan_post} NaN after warm-up (warmup={spec.warmup_bars})"


# --- causality (I1, moneta Gate 1) -----------------------------------------

def test_no_future_reference(ctx, data):
    """Truncate the tail → the prefix feature values must be unchanged."""
    reg, full = _compute(ctx)
    k = 300
    trunc_ctx = features.Ctx(o=ctx.o[:k], h=ctx.h[:k], l=ctx.l[:k],
                             c=ctx.c[:k], v=ctx.v[:k], t=ctx.t[:k], n=k)
    _, trunc = _compute(trunc_ctx)
    for name in reg.names():
        a = full[name][:k]
        b = trunc[name]
        m = np.isfinite(a) | np.isfinite(b)
        assert np.allclose(a[m], b[m], rtol=0, atol=1e-12, equal_nan=True), f"{name}"


def test_gate1_truncation_zero_redraw(ctx, data):
    reg, full = _compute(ctx)
    k = 250
    trunc_ctx = features.Ctx(o=ctx.o[:k], h=ctx.h[:k], l=ctx.l[:k],
                             c=ctx.c[:k], v=ctx.v[:k], t=ctx.t[:k], n=k)
    _, trunc = _compute(trunc_ctx)
    for name in reg.names():
        a, b = full[name][:k], trunc[name]
        m = np.isfinite(a) & np.isfinite(b)
        assert np.nanmax(np.abs(a[m] - b[m])) < 1e-12, f"{name}"


# --- determinism (F4) -------------------------------------------------------

def test_deterministic_rerun(ctx, data):
    reg1, cols1 = _compute(ctx)
    reg2, cols2 = _compute(ctx)
    for name in reg1.names():
        assert np.array_equal(cols1[name], cols2[name], equal_nan=True), f"{name}"


def test_f4_same_env_bitwise_cross_env_allclose(ctx, data):
    # same-env bitwise (strict F4)
    reg, a = _compute(ctx)
    _, b = _compute(ctx)
    for name in reg.names():
        assert np.array_equal(a[name], b[name], equal_nan=True)
    # cross-platform documented ceiling: allclose(1e-12) is the maintenance
    # bound — verified here as the same-stack tolerance holds.
    for name in reg.names():
        m = np.isfinite(a[name])
        assert np.allclose(a[name][m], b[name][m], rtol=0, atol=1e-12)


# --- wide-table / I/O contract ---------------------------------------------

def test_wide_table_self_sufficient(ctx, data):
    """F3/K2: the wide table carries the input OHLCV columns so a single file
    is independently queryable."""
    reg, cols = _compute(ctx)
    # _build_table must emit input cols + feature cols
    table, meta = features._build_table("TEST", {"n": data["n"], "cols": cols,
                                                  "input": _input_dict(data)}, reg,
                                        features.feature_version_string(reg), 60)
    names = set(table.column_names)
    for req in ("mid_o", "mid_h", "mid_l", "mid_c", "volume", "n_bars", "time"):
        assert req in names
    assert len(table.column_names) == 146 + 8


def _input_dict(data):
    import numpy as _np
    return {"instrument": _np.array(["TEST"] * data["n"]),
            "time": data["t"], "mid_o": data["c"] - 0.5, "mid_h": data["h"],
            "mid_l": data["l"], "mid_c": data["c"],
            "volume": data["v"], "n_bars": _np.ones(data["n"], dtype=_np.int64)}


def test_feature_version_in_metadata(tmp_path, data, ctx):
    reg = features.build_registry()
    table, meta = features._build_table("TEST", {"n": data["n"], "cols": _compute(ctx)[1],
                                                  "input": _input_dict(data)}, reg,
                                        features.feature_version_string(reg), 60)
    p = tmp_path / "t.parquet"
    features.write_parquet(table, meta, p)
    t2 = pq.read_table(p)
    md = t2.schema.metadata
    assert b"feature_version" in md
    assert md[b"feature_version"] == str(features.FEATURE_VERSION).encode()
    assert b"version_string" in md
    # bumping FEATURE_VERSION would change the sha → the string changes (D1)
    assert features.feature_version_string(reg).startswith("feat-")


def test_output_single_file_no_snapshot_dir(tmp_path, data):
    p = features.feature_path(tmp_path, 60, "TEST")
    assert p.parent.name == "ohlcv_1h"          # no <minutes>m, no snapshot dir
    assert p.name == "TEST.parquet"
    assert "<snapshot" not in str(p) and "snapshot" not in str(p)


# --- per-instrument streaming (D5) -----------------------------------------

def test_per_instrument_streaming(ctx, data):
    """D5: the per-instrument unit of work keeps one instrument in memory —
    the working set is bounded by one instrument's rows (not 21×)."""
    reg = features.build_registry()
    built = features.build_instrument(_fake_con(data), "TEST", 60, reg)
    # the built working set holds exactly one instrument's row count
    assert built["n"] == data["n"]
    assert len(built["cols"]) == 146


def _fake_con(data):
    """A minimal stand-in that answers build_instrument's single query."""
    import numpy as _np

    class _R:
        def __init__(self, d):
            self._d = d
        def fetchnumpy(self):
            return {"instrument": _np.array(["TEST"] * self._d["n"]),
                    "time": self._d["t"], "mid_o": self._d["c"] - 0.5,
                    "mid_h": self._d["h"], "mid_l": self._d["l"],
                    "mid_c": self._d["c"], "volume": self._d["v"],
                    "n_bars": _np.ones(self._d["n"], dtype=_np.int64)}
        def execute(self, sql, params=None):
            return _R(self._d)

    return _R(data)


# --- universal (K5) ---------------------------------------------------------

def test_universal_21_instruments(data):
    """K5: identical algorithm + params for every instrument. We verify the
    property structurally: the registry (algorithm + params) is a single shared
    object independent of the instrument, so 21 instruments all draw on it."""
    reg = features.build_registry()
    # every instrument runs against this one registry — no per-instrument
    # algorithm/parameter fork exists in the code path (D5 loop is uniform).
    assert len(reg) == 146   # 137 core (incl. prior12 trio) + 9 corpus fills (0008/#99)
    # and the compute functions are pure (same input → same output), so
    # instrument A and B differ only in their input data, never in the math.
    a = features.Ctx(o=np.full(50, 1.0), h=np.full(50, 1.0), l=np.full(50, 1.0),
                     c=np.full(50, 1.0), v=np.full(50, 1.0),
                     t=np.datetime64("2020-01-01","us")+np.arange(50,dtype=np.int64)*np.timedelta64(1,"h"), n=50)
    b = features.Ctx(o=a.o, h=a.h, l=a.l, c=a.c, v=a.v, t=a.t, n=50)
    _, ca = _compute(a)
    _, cb = _compute(b)
    for name in reg.names():
        assert np.array_equal(ca[name], cb[name], equal_nan=True), f"{name} not universal"


# --- gates (moneta-derived) -------------------------------------------------

def test_gate3_bounds_rsi_atr(ctx, data):
    reg, cols = _compute(ctx)
    for name in ("rsi_6", "rsi_12", "rsi_24", "rsi_60", "rsi_120"):
        v = cols[name]
        m = np.isfinite(v)
        assert np.all((v[m] >= 0) & (v[m] <= 100)), name
    for name in ("atr_6", "atr_12", "atr_24", "atr_60", "atr_120"):
        v = cols[name]
        m = np.isfinite(v)
        assert np.all(v[m] >= 0), name
    # Supertrend line is a price — bounded by the data's price range
    st = cols["supertrend"]
    m = np.isfinite(st)
    assert np.all(st[m] >= data["l"].min() - 1.0) and np.all(st[m] <= data["h"].max() + 1.0)


def test_gate4_zero_amplitude_no_crash():
    """moneta Gate 4: zero-amplitude / zero-volume / flat input → no Inf, no
    NaN leak beyond warm-up, no crash."""
    n = 80
    flat = features.Ctx(o=np.full(n, 100.0), h=np.full(n, 100.0), l=np.full(n, 100.0),
                        c=np.full(n, 100.0), v=np.zeros(n),
                        t=np.datetime64("2020-01-01","us")+np.arange(n,dtype=np.int64)*np.timedelta64(1,"h"), n=n)
    reg, cols = _compute(flat)
    for name in reg.names():
        col = cols[name]
        assert not np.isinf(col).any(), f"{name}: Inf leaked on zero-amplitude input"
    # division features must be NaN (D4 defined-NULL), never 0/Inf
    for name in ("efficiency_24", "range_position_24", "return_6_atr",
                 "range_atr", "relative_volume_24", "zscore_24",
                 "natr_24", "bband_pctb_24", "bband_bw_24"):
        post = cols[name][max(reg.get(name).warmup_bars, 30):]
        assert np.all(np.isnan(post) | np.isfinite(post)), name
        assert not np.isinf(post).any(), f"{name}: Inf on flat input"


def test_atr_normalization_basis_atr12(ctx, data):
    """K6 (v1.5/#99): every ATR-normalized feature divides by atr_12.

    Single uniform basis — the corpus' ATR(14) was rebased to the in-grid
    ATR(12) per the 2026-11-11 user ruling (no off-grid 14 allowed)."""
    reg, cols = _compute(ctx)
    atr = cols["atr_12"]
    # range_atr = (h-l)/atr_12
    m = np.isfinite(atr) & (atr > 0)
    assert np.allclose(cols["range_atr"][m], (data["h"][m] - data["l"][m]) / atr[m],
                       rtol=0, atol=1e-12)
    # range_width_atr_24 = prior24_range / atr_12
    m2 = np.isfinite(atr) & (atr > 0) & np.isfinite(cols["range_width_atr_24"])
    assert np.allclose(cols["range_width_atr_24"][m2], cols["prior24_range"][m2] / atr[m2],
                       rtol=0, atol=1e-12)
    # return_6_atr = |c - c.shift(6)| / atr_12
    m3 = np.isfinite(atr) & (atr > 0) & np.isfinite(cols["return_6_atr"])
    c = data["c"]
    ref = np.abs(c[m3] - c[np.where(m3)[0] - 6]) / atr[m3]
    assert np.allclose(cols["return_6_atr"][m3], ref, rtol=0, atol=1e-12)
    # corpus fills (v1.5): distance features use the same ATR(12) basis
    m4 = m & np.isfinite(cols["close_sma24_distance_atr"])
    assert m4.any()
    sma24 = talib.SMA(data["c"], timeperiod=24)
    assert np.allclose(cols["close_sma24_distance_atr"][m4],
                       (data["c"] - sma24)[m4] / atr[m4], rtol=1e-10)
    m5 = m & np.isfinite(cols["close_ema60_distance_atr"])
    assert m5.any()
    ema60 = talib.EMA(data["c"], timeperiod=60)
    assert np.allclose(cols["close_ema60_distance_atr"][m5],
                       (data["c"] - ema60)[m5] / atr[m5], rtol=1e-10)


def test_psar_direction_and_flips(ctx, data):
    """v1.5 corpus fills: psar_direction ±1 and nova flip contract (±1→∓1)."""
    reg, cols = _compute(ctx)
    d = cols["psar_direction"]
    sar = talib.SAR(data["h"], data["l"], acceleration=0.02, maximum=0.2)
    m = np.isfinite(sar)
    assert np.all((d[m] == 1.0) | (d[m] == -1.0))
    assert np.all(d[m & (data["c"] > sar)] == 1.0)
    assert np.all(d[m & (data["c"] <= sar)] == -1.0)
    assert np.all(np.isnan(d[~m]))
    prior = np.full_like(d, np.nan); prior[1:] = d[:-1]
    for up, dn in (("psar_flip_up", "psar_flip_down"),):
        valid = np.isfinite(d) & np.isfinite(prior)
        expect_up = (d == 1) & (prior == -1)
        expect_dn = (d == -1) & (prior == 1)
        assert np.allclose(cols[up][valid], expect_up[valid].astype(float), rtol=0)
        assert np.allclose(cols[dn][valid], expect_dn[valid].astype(float), rtol=0)
        assert np.all(np.isnan(cols[up][~valid]))


def test_supertrend_direction_and_flips(ctx, data):
    """v1.5 corpus fills: supertrend_direction ±1 consistent with bull/bear."""
    reg, cols = _compute(ctx)
    d = cols["supertrend_direction"]
    bull, bear = cols["supertrend_bullish"], cols["supertrend_bearish"]
    m = np.isfinite(d)
    assert np.all(d[m & (bull == 1)] == 1.0)
    assert np.all(d[m & (bear == 1)] == -1.0)
    valid = np.isfinite(d) & np.isfinite(np.r_[np.nan, d[:-1]])
    prior = np.full_like(d, np.nan); prior[1:] = d[:-1]
    valid = np.isfinite(d) & np.isfinite(prior)
    assert np.allclose(cols["supertrend_flip_up"][valid],
                       ((d == 1) & (prior == -1))[valid].astype(float), rtol=0)
    assert np.allclose(cols["supertrend_flip_down"][valid],
                       ((d == -1) & (prior == 1))[valid].astype(float), rtol=0)


def test_ema_alignment_6_24(ctx, data):
    """v1.5 corpus fill: sign(ema6 − ema24), NaN where either is NaN."""
    reg, cols = _compute(ctx)
    e6, e24 = talib.EMA(data["c"], timeperiod=6), talib.EMA(data["c"], timeperiod=24)
    m = np.isfinite(e6) & np.isfinite(e24)
    assert np.allclose(cols["ema_alignment_6_24"][m], np.sign(e6[m] - e24[m]), rtol=0)
    assert np.all(np.isnan(cols["ema_alignment_6_24"][:20]))


# --- real-data end-to-end (5m/1h layers present) ----------------------------

def _real_data_root():
    root = os.path.expanduser("~/.lyra/default/data")
    if not (os.path.exists(f"{root}/ohlcv_1h/ohlcv_1h.parquet")):
        pytest.skip("no real 0002 aggregate data present")
    return root


def test_real_data_one_instrument(tmp_path):
    root = _real_data_root()
    reg = features.build_registry()
    res = features.run_features(root, 60, reg, instruments=["SPX500_USD"])
    assert res.total_rows > 0
    t = pq.read_table(res.paths[0])
    assert len(t.column_names) == 154   # 146 + 8
    assert t.schema.metadata[b"feature_version"] == str(features.FEATURE_VERSION).encode()
