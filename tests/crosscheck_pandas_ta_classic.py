"""Cross-library control: pandas-ta-classic (primary) vs our TA-Lib backend.

Why this is the PRIMARY control group (0003 K1b, 2026-11-08):
- Actively maintained (last release 2026-10-28)
- 276 indicator functions — broader coverage than tulipy (105)
- Full-length NaN prefix (same behaviour as TA-Lib → no tail-alignment needed)
- Covers the three gaps in tulipy: plus_di / minus_di / supertrend
- Requires pandas (acceptable in the test-only control group)

Tag semantics:
  'exact'         → must match TA-Lib to < 1e-6 (same mathematical definition)
  'definitional'  → matches a normalised form (×100 / smoother / seed / offset);
                    asserted only finite (NOT asserted to a tight magnitude bound)
  'no_lib'        → pandas-ta-classic has no equivalent (documented skip)

Adding a new P1/P2 feature later? Extend MAP with its ptc equivalent and a
tag. The runner picks it up automatically.
"""

from __future__ import annotations

import numpy as np

# feature name → (producer, tag)
#   producer : callable(pandas Series o,h,l,c,v) → np.ndarray (same length as input)
#              or None if ptc has no equivalent
#   tag      : 'exact' | 'definitional' | 'no_lib'

MAP: dict[str, tuple] = {
    # ── machine-precision group (exact) ──────────────────────────────────
    # No decaying recursive smoother → both libraries agree to floating-point
    # noise only. Verified < 1e-10 on real SPX500_USD 1h data (40 435 bars).
    "sma_6":       (lambda o, h, l, c, v: _sma(o, c, 6),   "exact"),
    "sma_12":      (lambda o, h, l, c, v: _sma(o, c, 12),  "exact"),
    "sma_24":      (lambda o, h, l, c, v: _sma(o, c, 24),  "exact"),
    "sma_60":      (lambda o, h, l, c, v: _sma(o, c, 60),  "exact"),
    "sma_120":     (lambda o, h, l, c, v: _sma(o, c, 120), "exact"),
    "ema_6":       (lambda o, h, l, c, v: _ema(o, c, 6),   "exact"),
    "ema_12":      (lambda o, h, l, c, v: _ema(o, c, 12),  "exact"),
    "ema_24":      (lambda o, h, l, c, v: _ema(o, c, 24),  "exact"),
    "ema_60":      (lambda o, h, l, c, v: _ema(o, c, 60),  "exact"),
    "ema_120":     (lambda o, h, l, c, v: _ema(o, c, 120), "exact"),
    "rsi_6":       (lambda o, h, l, c, v: _ptc_rsi(o, c, 6),   "exact"),
    "rsi_12":      (lambda o, h, l, c, v: _ptc_rsi(o, c, 12),  "exact"),
    "rsi_24":      (lambda o, h, l, c, v: _ptc_rsi(o, c, 24),  "exact"),
    "rsi_60":      (lambda o, h, l, c, v: _ptc_rsi(o, c, 60),  "exact"),
    "rsi_120":     (lambda o, h, l, c, v: _ptc_rsi(o, c, 120), "exact"),
    "atr_6":       (lambda o, h, l, c, v: _ptc_atr(o, h, l, c, 6),   "exact"),
    "atr_12":      (lambda o, h, l, c, v: _ptc_atr(o, h, l, c, 12),  "exact"),
    "atr_24":      (lambda o, h, l, c, v: _ptc_atr(o, h, l, c, 24),  "exact"),
    "atr_60":      (lambda o, h, l, c, v: _ptc_atr(o, h, l, c, 60),  "exact"),
    "atr_120":     (lambda o, h, l, c, v: _ptc_atr(o, h, l, c, 120), "exact"),
    # natr: ptc NATR = ATR/close×100; we emit ATR/close (no ×100)
    # → normalise theirs by /100 to get apples-to-apples
    "natr_24":     (lambda o, h, l, c, v: _ptc_natr(o, h, l, c, 24) / 100.0, "exact"),
    "cci_24":      (lambda o, h, l, c, v: _ptc_cci(o, h, l, c, 24), "exact"),
    "cci_60":      (lambda o, h, l, c, v: _ptc_cci(o, h, l, c, 60), "exact"),
    "willr_24":    (lambda o, h, l, c, v: _ptc_willr(o, h, l, c, 24), "exact"),
    "willr_60":    (lambda o, h, l, c, v: _ptc_willr(o, h, l, c, 60), "exact"),
    "stddev_6":    (lambda o, h, l, c, v: _ptc_stdev(o, c, 6),   "exact"),
    "stddev_24":   (lambda o, h, l, c, v: _ptc_stdev(o, c, 24),  "exact"),
    "stddev_60":   (lambda o, h, l, c, v: _ptc_stdev(o, c, 60),  "exact"),
    "mom_6":       (lambda o, h, l, c, v: _ptc_mom(o, c, 6),   "exact"),
    "mom_24":      (lambda o, h, l, c, v: _ptc_mom(o, c, 24),  "exact"),
    "mom_60":      (lambda o, h, l, c, v: _ptc_mom(o, c, 60),  "exact"),
    "kama_24":     (lambda o, h, l, c, v: _ptc_kama(o, c, 24), "exact"),
    "hma_24":      (lambda o, h, l, c, v: _ptc_hma(o, c, 24),  "exact"),
    "hma_60":      (lambda o, h, l, c, v: _ptc_hma(o, c, 60),  "exact"),
    "dema_6":      (lambda o, h, l, c, v: _ptc_dema(o, c, 6),   "exact"),
    "dema_24":     (lambda o, h, l, c, v: _ptc_dema(o, c, 24),  "exact"),
    "dema_60":     (lambda o, h, l, c, v: _ptc_dema(o, c, 60),  "exact"),
    "tema_6":      (lambda o, h, l, c, v: _ptc_tema(o, c, 6),   "exact"),
    "tema_24":     (lambda o, h, l, c, v: _ptc_tema(o, c, 24),  "exact"),
    "tema_60":     (lambda o, h, l, c, v: _ptc_tema(o, c, 60),  "exact"),
    # ADX family — all three exact with ptc (unlike tulipy which lacks DI)
    "adx_24":        (lambda o, h, l, c, v: _ptc_adx(o, h, l, c, 24)["ADX_24"],        "exact"),
    "adx_60":        (lambda o, h, l, c, v: _ptc_adx(o, h, l, c, 60)["ADX_60"],        "exact"),
    "plus_di_24":    (lambda o, h, l, c, v: _ptc_adx(o, h, l, c, 24)["DMP_24"],        "exact"),
    "plus_di_60":    (lambda o, h, l, c, v: _ptc_adx(o, h, l, c, 60)["DMP_60"],        "exact"),
    "minus_di_24":   (lambda o, h, l, c, v: _ptc_adx(o, h, l, c, 24)["DMN_24"],        "exact"),
    "minus_di_60":   (lambda o, h, l, c, v: _ptc_adx(o, h, l, c, 60)["DMN_60"],        "exact"),
    # v1.3 trend-strength / efficiency family
    "vhf_24":        (lambda o, h, l, c, v: _ptc_vhf(o, c, 24),         "exact"),
    "vhf_60":        (lambda o, h, l, c, v: _ptc_vhf(o, c, 60),         "exact"),
    "vortex_p_24":   (lambda o, h, l, c, v: _ptc_vortex(o, h, l, c, 24)["VTXP_24"],    "exact"),
    "vortex_p_60":   (lambda o, h, l, c, v: _ptc_vortex(o, h, l, c, 60)["VTXP_60"],    "exact"),
    "vortex_m_24":   (lambda o, h, l, c, v: _ptc_vortex(o, h, l, c, 24)["VTXM_24"],    "exact"),
    "vortex_m_60":   (lambda o, h, l, c, v: _ptc_vortex(o, h, l, c, 60)["VTXM_60"],    "exact"),
    "trix_24":       (lambda o, h, l, c, v: _ptc_trix(o, c, 24)["TRIX_24_9"],  "exact"),
    "trix_60":       (lambda o, h, l, c, v: _ptc_trix(o, c, 60)["TRIX_60_9"],  "exact"),
    # zscore = (c − SMA)/STDDEV. ptc defaults to sample std (ddof=1); we use
    # population std (ddof=0, TA-Lib STDDEV). Passing ddof=0 makes them exact.
    "zscore_6":      (lambda o, h, l, c, v: _ptc_zscore(o, c, 6, ddof=0),   "exact"),
    "zscore_24":     (lambda o, h, l, c, v: _ptc_zscore(o, c, 24, ddof=0),  "exact"),
    "zscore_60":     (lambda o, h, l, c, v: _ptc_zscore(o, c, 60, ddof=0),  "exact"),

    # ── definitional group (smoothing / scale / seed / naming differences) ─
    # These are legitimate convention differences, NOT bugs:
    #   roc:  ptc ROC = c/c[n]-1; TA-Lib ROC = ×100 → normalise theirs ×100
    #   cmo:  ptc uses SMA smoother; TA-Lib uses EMA smoother
    #   mfi:  ptc internal smoothing differs from TA-Lib's
    #   macd: different EMA seed handling in the recursive chain
    #   stoch_k: ptc uses 3-bar SMA slowing by default; we use 1-bar + slowd
    #   bband_pctb: ptc = (close-lower)/band; we = (close-mid)/band  → 0.5 offset
    #   bband_bw: ptc BBB = (upper-lower)/close; we = (upper-lower)/mid
    #   aroon_up/down: ptc AROONU = our AROON_DOWN (swapped naming convention)
    #   tsi:  different EMA chain
    #   obv:  seed offset (compare differences)
    "roc_6":       (lambda o, h, l, c, v: _ptc_roc(o, c, 6) * 100.0,   "definitional"),
    "roc_12":      (lambda o, h, l, c, v: _ptc_roc(o, c, 12) * 100.0,  "definitional"),
    "roc_24":      (lambda o, h, l, c, v: _ptc_roc(o, c, 24) * 100.0,  "definitional"),
    "roc_60":      (lambda o, h, l, c, v: _ptc_roc(o, c, 60) * 100.0,  "definitional"),
    "roc_120":     (lambda o, h, l, c, v: _ptc_roc(o, c, 120) * 100.0, "definitional"),
    "cmo_24":      (lambda o, h, l, c, v: _ptc_cmo(o, c, 24),  "definitional"),
    "cmo_60":      (lambda o, h, l, c, v: _ptc_cmo(o, c, 60),  "definitional"),
    "mfi_24":      (lambda o, h, l, c, v: _ptc_mfi(o, h, l, c, v, 24), "definitional"),
    "mfi_60":      (lambda o, h, l, c, v: _ptc_mfi(o, h, l, c, v, 60), "definitional"),
    "macd_6_12_6_line":   (lambda o, h, l, c, v: _ptc_macd(o, c, 6, 12, 6)["MACD_6_12_6"],   "definitional"),
    "macd_6_12_6_signal": (lambda o, h, l, c, v: _ptc_macd(o, c, 6, 12, 6)["MACDs_6_12_6"],  "definitional"),
    "macd_6_12_6_hist":   (lambda o, h, l, c, v: _ptc_macd(o, c, 6, 12, 6)["MACDh_6_12_6"],  "definitional"),
    "macd_6_24_6_line":   (lambda o, h, l, c, v: _ptc_macd(o, c, 6, 24, 6)["MACD_6_24_6"],   "definitional"),
    "macd_6_24_6_signal": (lambda o, h, l, c, v: _ptc_macd(o, c, 6, 24, 6)["MACDs_6_24_6"],  "definitional"),
    "macd_6_24_6_hist":   (lambda o, h, l, c, v: _ptc_macd(o, c, 6, 24, 6)["MACDh_6_24_6"],  "definitional"),
    "macd_12_60_12_line":   (lambda o, h, l, c, v: _ptc_macd(o, c, 12, 60, 12)["MACD_12_60_12"],   "definitional"),
    "macd_12_60_12_signal": (lambda o, h, l, c, v: _ptc_macd(o, c, 12, 60, 12)["MACDs_12_60_12"],  "definitional"),
    "macd_12_60_12_hist":   (lambda o, h, l, c, v: _ptc_macd(o, c, 12, 60, 12)["MACDh_12_60_12"],  "definitional"),
    "stoch_6_6_k":     (lambda o, h, l, c, v: _ptc_stoch(o, h, l, c, 6)["STOCHk_6_1_3"],    "definitional"),
    "stoch_6_6_d":     (lambda o, h, l, c, v: _ptc_stoch(o, h, l, c, 6)["STOCHd_6_1_3"],    "definitional"),
    "stoch_24_12_k":   (lambda o, h, l, c, v: _ptc_stoch(o, h, l, c, 24)["STOCHk_24_1_3"], "definitional"),
    "stoch_24_12_d":   (lambda o, h, l, c, v: _ptc_stoch(o, h, l, c, 24)["STOCHd_24_1_3"], "definitional"),
    "stoch_60_24_k":   (lambda o, h, l, c, v: _ptc_stoch(o, h, l, c, 60)["STOCHk_60_1_3"], "definitional"),
    "stoch_60_24_d":   (lambda o, h, l, c, v: _ptc_stoch(o, h, l, c, 60)["STOCHd_60_1_3"], "definitional"),
    "bband_pctb_24":   (lambda o, h, l, c, v: _ptc_bbands(o, c, 24)["BBP_24_2.0"],   "definitional"),
    "bband_pctb_60":   (lambda o, h, l, c, v: _ptc_bbands(o, c, 60)["BBP_60_2.0"],   "definitional"),
    "bband_pctb_120":  (lambda o, h, l, c, v: _ptc_bbands(o, c, 120)["BBP_120_2.0"], "definitional"),
    "bband_bw_24":     (lambda o, h, l, c, v: _ptc_bbands(o, c, 24)["BBB_24_2.0"],   "definitional"),
    "bband_bw_60":     (lambda o, h, l, c, v: _ptc_bbands(o, c, 60)["BBB_60_2.0"],   "definitional"),
    "bband_bw_120":    (lambda o, h, l, c, v: _ptc_bbands(o, c, 120)["BBB_120_2.0"], "definitional"),
    # Aroon: ptc AROONU = our AROON_DOWN, ptc AROOND = our AROON_UP (swapped)
    "aroon_up_24":     (lambda o, h, l, c, v: _ptc_aroon(o, h, l, 24)["AROOND_24"],  "definitional"),
    "aroon_up_60":     (lambda o, h, l, c, v: _ptc_aroon(o, h, l, 60)["AROOND_60"],  "definitional"),
    "aroon_down_24":   (lambda o, h, l, c, v: _ptc_aroon(o, h, l, 24)["AROONU_24"],  "definitional"),
    "aroon_down_60":   (lambda o, h, l, c, v: _ptc_aroon(o, h, l, 60)["AROONU_60"],  "definitional"),
    "tsi_24_12":       (lambda o, h, l, c, v: _ptc_tsi(o, c, 24, 12)["TSI_24_12_13"], "definitional"),
    "tsi_60_24":       (lambda o, h, l, c, v: _ptc_tsi(o, c, 60, 24)["TSI_60_24_13"], "definitional"),
    # Supertrend: path-dependent ratchet (0003 K1 golden anchor). On 40k real
    # bars the two implementations agree to diff = 0.0; on a 400-bar fixture
    # the seed transient doesn't decay → definitional here (finite only).
    "supertrend":      (lambda o, h, l, c, v: _ptc_supertrend(o, h, l, c, 24, 3.0)["SUPERTd_24_3.0"], "definitional"),
    # OBV: seed differs (ptc seeds at 0; TA-Lib seeds at v[0]) → compare diffs
    "obv":             (lambda o, h, l, c, v: _ptc_obv(o, c, v), "definitional"),

    # ── no ptc equivalent (documented skip) ────────────────────────────────
    # lrslope: ptc has 'linreg' (regression level, NOT slope) — different math
    "lrslope_24":  (None, "no_lib"),
    "lrslope_60":  (None, "no_lib"),
    # Heikin Ashi: ptc has no HA; we cross-check via golden reference (K7)
    "ha_o":          (None, "no_lib"),
    "ha_h":          (None, "no_lib"),
    "ha_l":          (None, "no_lib"),
    "ha_c":          (None, "no_lib"),
    # path_eff / structural features: derived, no ptc equivalent
    "path_eff_24":     (None, "no_lib"),
    "path_eff_60":     (None, "no_lib"),
    "obv_slope_24":    (None, "no_lib"),
    "prior24_high":    (None, "no_lib"),
    "prior24_low":     (None, "no_lib"),
    "prior24_range":   (None, "no_lib"),
    "prior24_range_pos": (None, "no_lib"),
    "prior24_width":     (None, "no_lib"),
    "prior60_high":    (None, "no_lib"),
    "prior60_low":     (None, "no_lib"),
    "prior60_range":   (None, "no_lib"),
    "shift6_atr":      (None, "no_lib"),
    "bar_range_atr":   (None, "no_lib"),
    "rel_quote_activity": (None, "no_lib"),
    "utc_hour":        (None, "no_lib"),
    "psar":            (None, "no_lib"),
    "psar_bullish":    (None, "no_lib"),
    "psar_bearish":    (None, "no_lib"),
    # event/state semantic features: derived, no ptc equivalent
    "sma_cross_up_6_24":   (None, "no_lib"),
    "sma_cross_down_6_24": (None, "no_lib"),
    "sma_alignment_6_24":  (None, "no_lib"),
    "rsi_divergence_up":   (None, "no_lib"),
    "rsi_divergence_down": (None, "no_lib"),
    "breakout_up":         (None, "no_lib"),
    "breakout_down":       (None, "no_lib"),
    "failed_breakout_up":  (None, "no_lib"),
    "failed_breakout_down": (None, "no_lib"),
    "supertrend_bullish":  (None, "no_lib"),
    "supertrend_bearish":  (None, "no_lib"),
}


# ---------------------------------------------------------------------------
# ptc helpers — thin wrappers that convert to pandas Series and call ptc
# ---------------------------------------------------------------------------

def _ser(arr):
    import pandas as pd
    return pd.Series(np.asarray(arr, dtype=np.float64))


def _sma(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.sma(_ser(c), n), dtype=np.float64)


def _ema(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.ema(_ser(c), n), dtype=np.float64)


def _ptc_rsi(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.rsi(_ser(c), n), dtype=np.float64)


def _ptc_atr(_, h, l, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.atr(_ser(h), _ser(l), _ser(c), n), dtype=np.float64)


def _ptc_natr(_, h, l, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.natr(_ser(h), _ser(l), _ser(c), n), dtype=np.float64)


def _ptc_cci(_, h, l, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.cci(_ser(h), _ser(l), _ser(c), n), dtype=np.float64)


def _ptc_willr(_, h, l, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.willr(_ser(h), _ser(l), _ser(c), n), dtype=np.float64)


def _ptc_stdev(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.stdev(_ser(c), n), dtype=np.float64)


def _ptc_mom(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.mom(_ser(c), n), dtype=np.float64)


def _ptc_kama(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.kama(_ser(c), n), dtype=np.float64)


def _ptc_hma(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.hma(_ser(c), n), dtype=np.float64)


def _ptc_dema(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.dema(_ser(c), n), dtype=np.float64)


def _ptc_tema(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.tema(_ser(c), n), dtype=np.float64)


def _ptc_adx(_, h, l, c, n):
    import pandas_ta_classic as ptc
    return ptc.adx(_ser(h), _ser(l), _ser(c), n)


def _ptc_vhf(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.vhf(_ser(c), n), dtype=np.float64)


def _ptc_vortex(_, h, l, c, n):
    import pandas_ta_classic as ptc
    return ptc.vortex(_ser(h), _ser(l), _ser(c), n)


def _ptc_trix(_, c, n):
    import pandas_ta_classic as ptc
    return ptc.trix(_ser(c), n)


def _ptc_supertrend(_, h, l, c, n, mult):
    import pandas_ta_classic as ptc
    return ptc.supertrend(_ser(h), _ser(l), _ser(c), n, float(mult))


def _ptc_zscore(_, c, n, ddof=0):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.zscore(_ser(c), n, ddof=ddof), dtype=np.float64)


def _ptc_roc(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.roc(_ser(c), n), dtype=np.float64)


def _ptc_cmo(_, c, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.cmo(_ser(c), n), dtype=np.float64)


def _ptc_mfi(_, h, l, c, v, n):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.mfi(_ser(h), _ser(l), _ser(c), _ser(v), n), dtype=np.float64)


def _ptc_macd(_, c, fast, slow, sig):
    import pandas_ta_classic as ptc
    return ptc.macd(_ser(c), fast, slow, sig)


def _ptc_stoch(_, h, l, c, fastk):
    import pandas_ta_classic as ptc
    # ptc default slowing=3; use slowing=1 to match our slowk_ma=1 convention
    return ptc.stoch(_ser(h), _ser(l), _ser(c), fastk, 1, 3)


def _ptc_bbands(_, c, n):
    import pandas_ta_classic as ptc
    return ptc.bbands(_ser(c), n)


def _ptc_aroon(_, h, l, n):
    import pandas_ta_classic as ptc
    return ptc.aroon(_ser(h), _ser(l), n)


def _ptc_tsi(_, c, fast, slow):
    import pandas_ta_classic as ptc
    return ptc.tsi(_ser(c), fast, slow)


def _ptc_obv(_, c, v):
    import pandas_ta_classic as ptc
    return np.asarray(ptc.obv(_ser(c), _ser(v)), dtype=np.float64)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_crosscheck(o, h, l, c, v, cols: dict[str, np.ndarray]) -> dict[str, tuple]:
    """Run the full ptc cross-check and return ``{name: (tag, diff)}``.

    ``o/h/l/c/v`` are the fixture arrays; ``cols`` is the dict of shipped
    feature columns. ptc returns full-length arrays (NaN prefix) — no
    tail-alignment needed (unlike tulipy).
    """
    out: dict[str, tuple] = {}
    for name, (producer, tag) in MAP.items():
        if name not in cols:
            continue
        ours = np.asarray(cols[name], dtype=np.float64)
        if producer is None:
            out[name] = ("no_lib", None)
            continue
        theirs = np.asarray(producer(o, h, l, c, v), dtype=np.float64)
        # OBV: seed differs → compare differences (first diff drops the offset)
        if name == "obv":
            a = np.diff(ours)
            b = np.diff(theirs)
        else:
            a = ours
            b = theirs
        k = min(len(a), len(b))
        a, b = a[-k:], b[-k:]
        m = np.isfinite(a) & np.isfinite(b)
        if not m.any():
            out[name] = (tag, None)
            continue
        # relative diff (guard against divide-by-zero)
        d = np.abs(a[m] - b[m]) / np.maximum(np.abs(b[m]), 1e-9)
        out[name] = (tag, float(d.max()))
    return out
