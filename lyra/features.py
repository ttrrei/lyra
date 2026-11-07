"""Feature builder core (decision 0003).

Turns the 0002 ``ohlcv_5m`` / ``ohlcv_1h`` aggregation layers into a
per-instrument feature wide table (K2: one self-sufficient Parquet per
timeframe × instrument), computing **every** feature in the R3.1 / §3.4
standard list with the K8 grid {6, 12, 24, 60, 120}.

Design decisions it enforces:

* **K1** — standard indicators all come from **TA-Lib** (C core); window /
  structural features are vectorized NumPy compositions. No numba, no
  DuckDB-side compute. :mod:`lyra.indicators` holds the one hand-written
  reference (Supertrend) used only as a golden cross-check.
* **K3** — the registry (:mod:`lyra.registry`) is a pure-Python dict of
  metadata cards ``(name, kind, unit, warmup_bars, family, params)``;
  ``warmup_bars`` is the data source for the F2 assertion.
* **K4 / F2** — warm-up emits **NULL** (never 0, never dropped rows). The
  only post-warm-up NaN/NULL allowed is a *defined zero denominator* (D4
  gate); anything else after warm-up is a bug (Gate 4 intercepts).
* **K5** — the same algorithm + parameters run for all 21 instruments; only
  the NULL warm-up length may differ (K5).
* **K6** — every ATR-normalized feature divides by ``atr_24`` (never a
  mixed basis, the nova anti-pattern).
* **D5** — the pipeline loops instrument-by-instrument; each round fetches
  only that instrument's rows, computes, writes, and releases (never loads
  all 21 into one DataFrame — OOM guard).
* **F4** — deterministic on the same input + version + numeric stack (pure
  functions of the input arrays; no clocks, no randomness in values).
* **I13** — any change to a feature's computation or parameters bumps
  :data:`FEATURE_VERSION`.

Price basis is the ``mid_*`` columns (the 0002 bronze/aggregate contract);
``open/high/low/close`` in the spec are semantic shorthands for
``mid_o/mid_h/mid_l/mid_c``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import indicators
from .registry import FeatureKind, Registry, RegistryError

# I13: any change to a registered feature's computation or parameters must
# bump this. 0003 shipped v0.8 (+1 over the v0.7 baseline) and v0.9 (+1), so
# the first implementation baseline is 2.
FEATURE_VERSION = 3

#: The K8 window grid (0003 K8, aligned to moneta ``catalogue.py``).
GRID = (6, 12, 24, 60, 120)

#: K6 — the single, uniform ATR-normalization denominator.
ATR_NORM = 24


@dataclass
class Ctx:
    """One instrument's input arrays (the compute context).

    All arrays are 1-D ``float64`` of equal length ``n`` and must be in
    ascending ``time`` order (the caller guarantees ``ORDER BY time``).
    """

    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    t: np.ndarray  # datetime64[us] (UTC) or int64 epoch-µs; used only for utc_hour
    n: int

    @property
    def atr24(self) -> np.ndarray:
        return indicators.atr(self.h, self.l, self.c, ATR_NORM)


def _sma(c, n): return indicators.sma(c, n)
def _ema(c, n): return indicators.ema(c, n)
def _dema(c, n): return indicators.dema(c, n)
def _tema(c, n): return indicators.tema(c, n)
def _hma(c, n): return indicators.hma(c, n)
def _kama(c, n): return indicators.kama(c, n)
def _atr(h, l, c, n): return indicators.atr(h, l, c, n)
def _rsi(c, n): return indicators.rsi(c, n)
def _natr(h, l, c, n): return indicators.natr(h, l, c, n)
def _roc(c, n): return indicators.roc(c, n)
def _cci(h, l, c, n): return indicators.cci(h, l, c, n)
def _willr(h, l, c, n): return indicators.willr(h, l, c, n)
def _mfi(h, l, c, v, n): return indicators.mfi(h, l, c, v, n)
def _cmo(c, n): return indicators.cmo(c, n)
def _mom(c, n): return indicators.mom(c, n)
def _stddev(c, n): return indicators.stddev(c, n)
def _lrslope(c, n): return indicators.lrslope(c, n)
def _obv(c, v): return indicators.obv(c, v)
def _macd(c, f, s, sig): return indicators.macd(c, f, s, sig)
def _stoch(h, l, c, fastk, slowd): return indicators.stoch(h, l, c, fastk, slowd)
def _bbands(c, n): return indicators.bbands(c, n)


def build_registry() -> Registry:
    """Build the core feature registry (R3.1 / §3.4) with compute bound (K3).

    The ``compute`` callables are ``(ctx, spec) -> np.ndarray`` for a single
    column. Multi-output indicators (MACD / STOCH / BBANDS / PSAR /
    Supertrend) are split into one spec per emitted column.
    """
    reg = Registry()

    def reg_value(name, family, warmup, params, window, compute, unit="price"):
        return reg.register(
            name, compute, kind=FeatureKind.VALUE, unit=unit,
            warmup_bars=warmup, family=family, params=params, window_params=window,
        )

    # --- simple grid families (K8) -----------------------------------------
    for n in GRID:
        reg_value(f"sma_{n}", "sma", n - 1, {"n": n}, (n,), lambda ctx, s: _sma(ctx.c, s.params["n"]))
        reg_value(f"ema_{n}", "ema", n - 1, {"n": n}, (n,), lambda ctx, s: _ema(ctx.c, s.params["n"]))
        reg_value(f"atr_{n}", "atr", n, {"n": n}, (n,), lambda ctx, s: _atr(ctx.h, ctx.l, ctx.c, s.params["n"]), unit="price")
        reg_value(f"rsi_{n}", "rsi", n, {"n": n}, (n,), lambda ctx, s: _rsi(ctx.c, s.params["n"]), unit="index[0,100]")
        reg_value(f"natr_{n}", "natr", n, {"n": n}, (n,), lambda ctx, s: _natr(ctx.h, ctx.l, ctx.c, s.params["n"]), unit="ratio")
        reg_value(f"roc_{n}", "roc", n, {"n": n}, (n,), lambda ctx, s: _roc(ctx.c, s.params["n"]), unit="ratio")

    # --- MACD (curated triplets, K8 exception) -----------------------------
    for (f, s, sig) in ((6, 12, 6), (6, 24, 6), (12, 60, 12)):
        tag = f"macd_{f}_{s}_{sig}"
        # warm-up is dominated by the slow EMA plus the chained signal EMA:
        # measured exactly = slow + fast - 2 (16/28/70 for the three triplets).
        warm = s + f - 2
        params = {"fast": f, "slow": s, "signal": sig}
        reg_value(f"{tag}_line", "macd", warm, params, (f, s, sig), lambda ctx, sp: _macd(ctx.c, sp.params["fast"], sp.params["slow"], sp.params["signal"])[0], unit="price")
        reg_value(f"{tag}_signal", "macd", warm, params, (f, s, sig), lambda ctx, sp: _macd(ctx.c, sp.params["fast"], sp.params["slow"], sp.params["signal"])[1], unit="price")
        reg_value(f"{tag}_hist", "macd", warm, params, (f, s, sig), lambda ctx, sp: _macd(ctx.c, sp.params["fast"], sp.params["slow"], sp.params["signal"])[2], unit="price")

    # --- STOCH (%K/%D pairs, in-grid) --------------------------------------
    for (fastk, slowd) in ((6, 6), (24, 12), (60, 24)):
        tag = f"stoch_{fastk}_{slowd}"
        # TA-Lib defers %K to align with %D: measured warm-up = fastk + slowd - 2.
        warm = fastk + slowd - 2
        params = {"fastk": fastk, "slowd": slowd}
        reg_value(f"{tag}_k", "stoch", warm, params, (fastk, slowd), lambda ctx, sp: _stoch(ctx.h, ctx.l, ctx.c, sp.params["fastk"], sp.params["slowd"])[0], unit="index[0,100]")
        reg_value(f"{tag}_d", "stoch", warm, params, (fastk, slowd), lambda ctx, sp: _stoch(ctx.h, ctx.l, ctx.c, sp.params["fastk"], sp.params["slowd"])[1], unit="index[0,100]")

    # --- BBANDS (%B + bandwidth, no raw bands) -----------------------------
    for n in (24, 60, 120):
        params = {"n": n, "nbdev": 2}
        reg_value(f"bband_pctb_{n}", "bbands", n - 1, params, (n,), lambda ctx, sp: _bbands(ctx.c, sp.params["n"])[0], unit="ratio")
        reg_value(f"bband_bw_{n}", "bbands", n - 1, params, (n,), lambda ctx, sp: _bbands(ctx.c, sp.params["n"])[1], unit="ratio")

    # --- ADX family (trend strength, 24/60) --------------------------------
    for n in (24, 60):
        # Measured NaN prefixes: ADX = 2n-1 (double Wilder smoothing);
        # PLUS_DI / MINUS_DI = n.
        reg_value(f"adx_{n}", "adx", 2 * n - 1, {"n": n}, (n,), lambda ctx, sp: indicators.adx(ctx.h, ctx.l, ctx.c, sp.params["n"]), unit="index[0,100]")
        reg_value(f"plus_di_{n}", "adx", n, {"n": n}, (n,), lambda ctx, sp: indicators.plus_di(ctx.h, ctx.l, ctx.c, sp.params["n"]), unit="index[0,100]")
        reg_value(f"minus_di_{n}", "adx", n, {"n": n}, (n,), lambda ctx, sp: indicators.minus_di(ctx.h, ctx.l, ctx.c, sp.params["n"]), unit="index[0,100]")

    # --- oscillators / flow (24/60) ----------------------------------------
    for n in (24, 60):
        reg_value(f"cci_{n}", "cci", n - 1, {"n": n}, (n,), lambda ctx, sp: _cci(ctx.h, ctx.l, ctx.c, sp.params["n"]), unit="index")
        reg_value(f"willr_{n}", "willr", n - 1, {"n": n}, (n,), lambda ctx, sp: _willr(ctx.h, ctx.l, ctx.c, sp.params["n"]), unit="index[-100,0]")
        reg_value(f"mfi_{n}", "mfi", n, {"n": n}, (n,), lambda ctx, sp: _mfi(ctx.h, ctx.l, ctx.c, ctx.v, sp.params["n"]), unit="index[0,100]")
        reg_value(f"cmo_{n}", "cmo", n, {"n": n}, (n,), lambda ctx, sp: _cmo(ctx.c, sp.params["n"]), unit="index[-100,100]")

    # --- OBV (slope, not absolute) -----------------------------------------
    reg_value("obv", "obv", 0, {}, (), lambda ctx, s: _obv(ctx.c, ctx.v), unit="cumulative_volume")
    reg_value("obv_slope_24", "obv", 24, {"n": 24}, (24,), lambda ctx, s: indicators.lrslope(_obv(ctx.c, ctx.v), 24), unit="volume")

    # --- regression slope / KAMA -------------------------------------------
    for n in (24, 60):
        reg_value(f"lrslope_{n}", "lrslope", n - 1, {"n": n}, (n,), lambda ctx, sp: _lrslope(ctx.c, sp.params["n"]), unit="price")
    reg_value("kama_24", "kama", 24, {"n": 24}, (24,), lambda ctx, s: _kama(ctx.c, 24), unit="price")

    # --- DEMA / TEMA / HMA / MOM / STDDEV / Z-Score (v0.9) ------------------
    for n in (6, 24, 60):
        reg_value(f"dema_{n}", "dema", 2 * n - 1, {"n": n}, (n,), lambda ctx, sp: _dema(ctx.c, sp.params["n"]), unit="price")
        reg_value(f"tema_{n}", "tema", 3 * n - 1, {"n": n}, (n,), lambda ctx, sp: _tema(ctx.c, sp.params["n"]), unit="price")
    for n in (24, 60):
        # HMA warm-up = 2·sqrt(n) rounded up, then n+1 (measured 26/65 → n+2 at 24, n+5 at 60; use the safe bound n+5).
        reg_value(f"hma_{n}", "hma", n + 5, {"n": n}, (n,), lambda ctx, sp: _hma(ctx.c, sp.params["n"]), unit="price")
    for n in (6, 24, 60):
        reg_value(f"mom_{n}", "mom", n, {"n": n}, (n,), lambda ctx, sp: _mom(ctx.c, sp.params["n"]), unit="price")
        reg_value(f"stddev_{n}", "stddev", n - 1, {"n": n}, (n,), lambda ctx, sp: _stddev(ctx.c, sp.params["n"]), unit="price")
        reg_value(
            f"zscore_{n}", "zscore", n - 1, {"n": n}, (n,),
            lambda ctx, sp: indicators.zscore(ctx.c, sp.params["n"]), unit="z",
        )

    # --- PSAR (direction flags; K8 exception: af/maximum are not windows) --
    reg_value("psar", "psar", 2, {"af": 0.02, "maximum": 0.2}, (), lambda ctx, s: indicators.sar(ctx.h, ctx.l), unit="price")
    reg.register(
        "psar_bullish", lambda ctx, s: _psar_dir(ctx, +1),
        kind=FeatureKind.STATE, unit="state", warmup_bars=2, family="psar",
        params={"af": 0.02, "maximum": 0.2}, window_params=(),
    )
    reg.register(
        "psar_bearish", lambda ctx, s: _psar_dir(ctx, -1),
        kind=FeatureKind.STATE, unit="state", warmup_bars=2, family="psar",
        params={"af": 0.02, "maximum": 0.2}, window_params=(),
    )

    # --- Supertrend (talib library impl; ATR window in-grid, mult explicit) -
    reg_value("supertrend", "supertrend", 24, {"atr_window": 24, "multiplier": 3.0}, (24,),
              lambda ctx, s: indicators.supertrend_line(ctx.h, ctx.l, ctx.c, 24, 3.0), unit="price")
    reg.register(
        "supertrend_bullish", lambda ctx, s: indicators.supertrend_bullish(ctx.h, ctx.l, ctx.c, 24, 3.0),
        kind=FeatureKind.STATE, unit="state", warmup_bars=24, family="supertrend",
        params={"atr_window": 24, "multiplier": 3.0}, window_params=(24,),
    )
    reg.register(
        "supertrend_bearish", lambda ctx, s: indicators.supertrend_bearish(ctx.h, ctx.l, ctx.c, 24, 3.0),
        kind=FeatureKind.STATE, unit="state", warmup_bars=24, family="supertrend",
        params={"atr_window": 24, "multiplier": 3.0}, window_params=(24,),
    )

    # --- Heikin Ashi (K7 self-implementation; TA-Lib has no HA — no window) -
    # Recursion converges in ~16 bars regardless of seed → warmup_bars=16.
    ha = lambda ctx: indicators.heikin_asi(ctx.o, ctx.h, ctx.l, ctx.c)
    reg.register(
        "ha_o", lambda ctx, s: ha(ctx)[0],
        kind=FeatureKind.VALUE, unit="price", warmup_bars=16, family="heikin_asi",
        self_implemented=True,
    )
    reg.register(
        "ha_h", lambda ctx, s: ha(ctx)[1],
        kind=FeatureKind.VALUE, unit="price", warmup_bars=16, family="heikin_asi",
        self_implemented=True,
    )
    reg.register(
        "ha_l", lambda ctx, s: ha(ctx)[2],
        kind=FeatureKind.VALUE, unit="price", warmup_bars=16, family="heikin_asi",
        self_implemented=True,
    )
    reg.register(
        "ha_c", lambda ctx, s: ha(ctx)[3],
        kind=FeatureKind.VALUE, unit="price", warmup_bars=16, family="heikin_asi",
        self_implemented=True,
    )

    # --- semantic (deterministic predicates on registered columns) ---------
    reg.register(
        "sma_cross_up_6_24", lambda ctx, s: _sma_cross(ctx, +1),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=24, family="semantic",
        params={"fast": 6, "slow": 24}, window_params=(6, 24),
    )
    reg.register(
        "sma_cross_down_6_24", lambda ctx, s: _sma_cross(ctx, -1),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=24, family="semantic",
        params={"fast": 6, "slow": 24}, window_params=(6, 24),
    )
    reg.register(
        "sma_alignment_6_24", lambda ctx, s: _sma_alignment(ctx),
        kind=FeatureKind.STATE, unit="state{-1,0,1}", warmup_bars=24, family="semantic",
        params={"fast": 6, "slow": 24}, window_params=(6, 24),
    )
    reg.register(
        "rsi_divergence_up", lambda ctx, s: _rsi_divergence(ctx, +1),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=48, family="semantic",
        params={"rsi": 24, "lookback": 24}, window_params=(24,),
    )
    reg.register(
        "rsi_divergence_down", lambda ctx, s: _rsi_divergence(ctx, -1),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=48, family="semantic",
        params={"rsi": 24, "lookback": 24}, window_params=(24,),
    )

    # --- structural (vectorized; prior windows exclude the current bar) ----
    for n in (24, 60):
        reg_value(f"prior{n}_high", "structural", n, {"n": n}, (n,), lambda ctx, sp: _prior_high(ctx, sp.params["n"]), unit="price")
        reg_value(f"prior{n}_low", "structural", n, {"n": n}, (n,), lambda ctx, sp: _prior_low(ctx, sp.params["n"]), unit="price")
        reg_value(f"prior{n}_range", "structural", n, {"n": n}, (n,), lambda ctx, sp: _prior_range(ctx, sp.params["n"]), unit="price")
    reg_value("prior24_range_pos", "structural", 24, {"n": 24}, (24,), lambda ctx, s: _prior_range_pos(ctx, 24), unit="ratio[0,1]")
    reg_value("prior24_width", "structural", 24, {"n": 24}, (24,), lambda ctx, s: _prior_width_atr(ctx, 24), unit="atr")
    reg.register(
        "breakout_up", lambda ctx, s: _breakout(ctx, +1, 24),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=24, family="structural",
        params={"n": 24}, window_params=(24,),
    )
    reg.register(
        "breakout_down", lambda ctx, s: _breakout(ctx, -1, 24),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=24, family="structural",
        params={"n": 24}, window_params=(24,),
    )
    reg.register(
        "failed_breakout_up", lambda ctx, s: _failed_breakout(ctx, +1, 24),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=24, family="structural",
        params={"n": 24}, window_params=(24,),
    )
    reg.register(
        "failed_breakout_down", lambda ctx, s: _failed_breakout(ctx, -1, 24),
        kind=FeatureKind.EVENT, unit="event", warmup_bars=24, family="structural",
        params={"n": 24}, window_params=(24,),
    )
    reg_value("shift6_atr", "structural", ATR_NORM, {"n": 6, "denom": "atr_24"}, (6,), lambda ctx, s: _shift6_atr(ctx), unit="atr")
    reg_value("bar_range_atr", "structural", ATR_NORM, {"denom": "atr_24"}, (ATR_NORM,), lambda ctx, s: _bar_range_atr(ctx), unit="atr")
    reg_value("rel_quote_activity", "structural", 24, {"n": 24}, (24,), lambda ctx, s: _rel_quote_activity(ctx, 24), unit="ratio")
    reg.register("utc_hour", lambda ctx, s: _utc_hour(ctx), kind=FeatureKind.VALUE,
                 unit="utc_hour[0,23]", warmup_bars=0, family="structural", params={}, window_params=())
    for n in (24, 60):
        reg_value(f"path_eff_{n}", "structural", n, {"n": n}, (n,), lambda ctx, sp: _path_eff(ctx, sp.params["n"]), unit="ratio[0,1]")

    return reg


# ---------------------------------------------------------------------------
# Column compute helpers (pure NumPy; ctx holds one instrument's arrays)
# ---------------------------------------------------------------------------

def _psar_dir(ctx: Ctx, sign: int) -> np.ndarray:
    """PSAR direction flag: 1 where the SAR slope test shows the given regime.

    sign=+1 → bullish (SAR falling), sign=−1 → bearish (SAR rising)."""
    sar = indicators.sar(ctx.h, ctx.l)
    d = indicators.sar_direction(ctx.h, ctx.l, sar)  # +1 up / -1 down / NaN
    out = np.where(d == sign, 1.0, 0.0)
    out[~np.isfinite(d)] = np.nan
    return out


def _sma_cross(ctx: Ctx, sign: int) -> np.ndarray:
    """SMA(6) crossing SMA(24) from the previous bar (causal, uses t-1)."""
    fast = _sma(ctx.c, 6)
    slow = _sma(ctx.c, 24)
    prev_fast = np.concatenate(([np.nan], fast[:-1]))
    prev_slow = np.concatenate(([np.nan], slow[:-1]))
    if sign > 0:
        hit = (fast > slow) & (prev_fast <= prev_slow)
    else:
        hit = (fast < slow) & (prev_fast >= prev_slow)
    out = np.where(hit, 1.0, 0.0)
    out[~np.isfinite(fast) | ~np.isfinite(slow) | ~np.isfinite(prev_fast) | ~np.isfinite(prev_slow)] = np.nan
    return out


def _sma_alignment(ctx: Ctx) -> np.ndarray:
    fast = _sma(ctx.c, 6)
    slow = _sma(ctx.c, 24)
    d = fast - slow
    out = np.sign(d)
    out[~np.isfinite(fast) | ~np.isfinite(slow)] = np.nan
    return out


def _rsi_divergence(ctx: Ctx, sign: int) -> np.ndarray:
    """Divergence over a fixed 24-bar lookback (causal predicate, D4-spec).

    ``up``   : price lower than 24 bars ago while RSI is higher  (bullish)
    ``down`` : price higher than 24 bars ago while RSI is lower  (bearish)
    A simple, deterministic predicate on the registered ``rsi_24`` column
    (no pivot search — the K7 self-implementation discipline applies; the
    exact formula is this contract card).
    """
    lb = 24
    rsi = _rsi(ctx.c, 24)
    c = ctx.c
    prev_c = np.full_like(c, np.nan); prev_c[lb:] = c[:-lb]
    prev_r = np.full_like(rsi, np.nan); prev_r[lb:] = rsi[:-lb]
    if sign > 0:
        hit = (c < prev_c) & (rsi > prev_r)
    else:
        hit = (c > prev_c) & (rsi < prev_r)
    out = np.where(hit, 1.0, 0.0)
    out[~np.isfinite(prev_c) | ~np.isfinite(prev_r) | ~np.isfinite(rsi)] = np.nan
    return out


def _prior_high(ctx: Ctx, n: int) -> np.ndarray:
    """max(high[t-n : t]) — the current bar is excluded (nova ``shift(1)``)."""
    return _rolling_extreme(ctx.h, n, np.nanmax)


def _prior_low(ctx: Ctx, n: int) -> np.ndarray:
    """min(low[t-n : t]) — the current bar is excluded (nova ``shift(1)``)."""
    return _rolling_extreme(ctx.l, n, np.nanmin)


def _prior_range(ctx: Ctx, n: int) -> np.ndarray:
    return _prior_high(ctx, n) - _prior_low(ctx, n)


def _prior_range_pos(ctx: Ctx, n: int) -> np.ndarray:
    """(close - prior_low) / prior_range ; denominator 0 -> NaN (D4)."""
    hi = _prior_high(ctx, n)
    lo = _prior_low(ctx, n)
    w = hi - lo
    out = np.full_like(ctx.c, np.nan)
    valid = w > 0
    out[valid] = (ctx.c[valid] - lo[valid]) / w[valid]
    return out


def _prior_width_atr(ctx: Ctx, n: int) -> np.ndarray:
    """prior_range / atr_24 (K6 normalization basis)."""
    w = _prior_range(ctx, n)
    atr = ctx.atr24
    out = np.full_like(ctx.c, np.nan)
    valid = np.isfinite(atr) & (atr > 0)
    out[valid] = w[valid] / atr[valid]
    return out


def _breakout(ctx: Ctx, sign: int, n: int) -> np.ndarray:
    hi = _prior_high(ctx, n)
    lo = _prior_low(ctx, n)
    valid = np.isfinite(hi) & np.isfinite(lo)
    if sign > 0:
        hit = ctx.c > hi
    else:
        hit = ctx.c < lo
    out = np.where(hit, 1.0, 0.0)
    out[~valid] = np.nan
    return out


def _failed_breakout(ctx: Ctx, sign: int, n: int) -> np.ndarray:
    """Wick swept outside the prior range but close returned inside (D4)."""
    hi = _prior_high(ctx, n)
    lo = _prior_low(ctx, n)
    valid = np.isfinite(hi) & np.isfinite(lo)
    if sign > 0:
        hit = (ctx.h > hi) & (ctx.c <= hi)
    else:
        hit = (ctx.l < lo) & (ctx.c >= lo)
    out = np.where(hit, 1.0, 0.0)
    out[~valid] = np.nan
    return out


def _shift6_atr(ctx: Ctx) -> np.ndarray:
    """|close - close.shift(6)| / atr_24 (K6); denominator 0 -> NaN (D4)."""
    diff = np.full_like(ctx.c, np.nan)
    diff[6:] = np.abs(ctx.c[6:] - ctx.c[:-6])
    atr = ctx.atr24
    out = np.full_like(ctx.c, np.nan)
    valid = np.isfinite(atr) & (atr > 0)
    out[valid] = diff[valid] / atr[valid]
    return out


def _bar_range_atr(ctx: Ctx) -> np.ndarray:
    """(high - low) / atr_24 (K6); denominator 0 -> NaN (D4)."""
    atr = ctx.atr24
    out = np.full_like(ctx.c, np.nan)
    valid = np.isfinite(atr) & (atr > 0)
    out[valid] = (ctx.h[valid] - ctx.l[valid]) / atr[valid]
    return out


def _rel_quote_activity(ctx: Ctx, n: int) -> np.ndarray:
    """volume / SMA(volume, n) — dimensionless, cross-instrument comparable.

    D4 zero-denominator contract: when the prior-n-bar activity baseline is 0
    (flat volume), the ratio is a *defined NULL* (NaN), not an error. This
    supersedes the ``×1e9`` in the v0.9 doc text, which contradicts the
    doc's own "dimensionless, cross-instrument comparable" rationale.
    """
    base = indicators.sma(ctx.v, n)
    out = np.full_like(ctx.v, np.nan)
    valid = np.isfinite(base) & (base > 0)
    out[valid] = ctx.v[valid] / base[valid]
    return out


def _utc_hour(ctx: Ctx) -> np.ndarray:
    """UTC hour of the bar *opening* instant (causal; known at close)."""
    t = ctx.t
    if t.dtype.kind == "M":
        return (t.astype("datetime64[h]").astype("int64") % 24).astype("float64")
    # int64 epoch-microseconds (UTC)
    us = t.astype("int64")
    sec_per_hour = 3_600_000_000
    return ((us // sec_per_hour) % 24).astype("float64")


def _path_eff(ctx: Ctx, n: int) -> np.ndarray:
    """|close - close.shift(n)| / sum(|Δclose|, n) ; denominator 0 -> NaN (D4).

    1 = unidirectional path, 0 = pure chop. (nova ``efficiency`` contract.)
    ``denom[t] = Σ_{i=t-n+1}^{t} |c[i]-c[i-1]|`` (rolling sum of abs-diff,
    matching nova ``close.diff().abs().rolling(n).sum()``).
    """
    c = ctx.c
    absdiff = np.abs(np.diff(c, prepend=np.nan))  # absdiff[0]=NaN, absdiff[i]=|c[i]-c[i-1]|
    denom = _rolling_sum(absdiff, n)
    num = np.full_like(c, np.nan)
    num[n:] = np.abs(c[n:] - c[:-n])
    out = np.full_like(c, np.nan)
    valid = np.isfinite(denom) & (denom > 0)
    out[valid] = num[valid] / denom[valid]
    return out


def _rolling_extreme(a: np.ndarray, n: int, fn) -> np.ndarray:
    """Rolling extreme over the prior ``n`` bars: ``out[t] = fn(a[t-n : t])``.

    The current bar ``a[t]`` is excluded (nova ``shift(1)`` convention).
    Bars ``t < n`` are NaN (insufficient prior bars → warm-up, F2/K4).
    Vectorized via ``sliding_window_view`` (O(n)).
    """
    out = np.full_like(a, np.nan)
    if len(a) < n:
        return out
    from numpy.lib.stride_tricks import sliding_window_view

    w = sliding_window_view(a, n)  # w[i] = a[i : i+n], i in [0, len-n]
    vals = fn(w, axis=1)           # out[t]=extreme over a[t-n:t] → w[t-n]
    out[n:] = vals[: len(a) - n]
    return out


def _rolling_sum(a: np.ndarray, n: int) -> np.ndarray:
    """Rolling sum of the last ``n`` elements ending at t (inclusive).

    ``out[t] = Σ_{i=t-n+1}^{t} a[i]``; NaN if any element in the window is
    NaN (propagation is correct here — it only affects the warm-up prefix).
    """
    out = np.full_like(a, np.nan)
    if len(a) < n:
        return out
    from numpy.lib.stride_tricks import sliding_window_view

    w = sliding_window_view(a, n)  # w[i] = a[i : i+n]
    out[n - 1:] = w.sum(axis=1)    # out[i+n-1] = Σ a[i..i+n-1]
    return out


# ---------------------------------------------------------------------------
# Public API used by the CLI / 0004 compiler
# ---------------------------------------------------------------------------

def core_registry() -> Registry:
    """The core R3.1 registry (cached)."""
    return build_registry()


def compute_features(ctx: Ctx, reg: Registry) -> dict[str, np.ndarray]:
    """Compute every registered column for one instrument (F4: pure/derived).

    Returns ``{column_name: 1-D float64 array}``. Raises on a registry name
    conflict (F5) — the registry build already guarantees uniqueness.
    """
    out: dict[str, np.ndarray] = {}
    for name in reg.names():
        spec = reg.get(name)
        col = spec.compute(ctx, spec)
        if not isinstance(col, np.ndarray):
            raise TypeError(f"{name}: compute must return an ndarray, got {type(col)}")
        if col.shape != (ctx.n,):
            raise ValueError(f"{name}: expected shape ({ctx.n},), got {col.shape}")
        out[name] = col
    return out


def feature_version_string(reg: Registry) -> str:
    """The reproducible version identifier written into Parquet metadata (D1).

    ``(FEATURE_VERSION, registry full param-set sha256, numeric-stack triple)``.
    TA-Lib's version is deliberately *excluded* (I13: a TA-Lib semantic change
    must bump FEATURE_VERSION, not sneak in via a version string).
    """
    import numpy as _np
    parts = []
    for name in reg.names():
        spec = reg.get(name)
        parts.append(f"{name}|{sorted(spec.params.items())}|{spec.warmup_bars}")
    payload = "\n".join(parts)
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    stack = f"py{_py_version()}/np{_np.__version__}"
    return f"feat-{FEATURE_VERSION}-{sha}-{stack}"


def _py_version() -> str:
    import platform
    return platform.python_version()


# ---------------------------------------------------------------------------
# Alpha extension point (R3.2) — load_from + name-conflict fail-fast (I15/I16)
# ---------------------------------------------------------------------------

class AlphaLoadError(ValueError):
    """An alpha feature module failed to load (fail-fast, not silent skip)."""


def load_from(directory: str | Path, core: Registry | None = None) -> Registry:
    """Load alpha features from ``directory`` onto a copy of the core registry.

    Contract (0003 §3.1 / R3.2):
    * scans ``directory`` for ``*.py``; each module must expose
      ``register(registry)`` — it calls ``registry.register(...)`` for its
      own features, attaching the contract card in the module docstring;
    * **fail-fast** (D7): any syntax error / missing dependency / exception in
      an alpha module raises :class:`AlphaLoadError` naming the file — it is
      NOT silently skipped (a silent skip would only explode at 0004 compile);
    * **F5**: an alpha name colliding with a core (or earlier alpha) name
      raises (no overwrite, no ``_2`` suffix);
    * **I16**: core never imports a concrete alpha module — only this loader
      does, and only when the caller passes a directory.

    Returns a new Registry (core entries + alpha entries); the passed ``core``
    is left untouched (I16: core registry identity is stable).
    """
    base = core or build_registry()
    out = Registry()
    # seed with the core (preserving names so alpha conflicts raise F5)
    for name in base.names():
        spec = base.get(name)
        out.register(
            spec.name, spec.compute, kind=spec.kind, unit=spec.unit,
            warmup_bars=spec.warmup_bars, family=spec.family, params=spec.params,
            window_params=spec.window_params,
        )
    d = Path(directory)
    if not d.exists():
        return out  # no alpha dir → core unchanged (I16; test_load_from_core_only_unchanged)
    for path in sorted(d.glob("*.py")):
        try:
            spec_mod = _import_alpha_module(path)
        except Exception as exc:  # noqa: BLE001 — fail-fast must name the file
            raise AlphaLoadError(f"failed to import alpha module {path}: {exc!r}") from exc
        if not hasattr(spec_mod, "register"):
            raise AlphaLoadError(f"alpha module {path} must expose a register(registry) function")
        try:
            spec_mod.register(out)
        except RegistryError:
            raise  # F5 name clash — propagate (already descriptive)
        except Exception as exc:  # noqa: BLE001
            raise AlphaLoadError(f"alpha register() in {path} raised: {exc!r}") from exc
    return out


def _import_alpha_module(path: Path):
    import importlib.util
    import sys

    # Unique per absolute path: two alpha dirs with the same file name
    # (e.g. ``zz.py`` in different tmp fixtures) must not share a module.
    name = f"lyra_alpha_{path.stem}_{hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:8]}"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise AlphaLoadError(f"cannot build import spec for {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Pipeline (D5 per-instrument streaming) — 0002 bronze/5m/1h → feature wide
# ---------------------------------------------------------------------------

#: The input OHLCV columns copied verbatim into the wide table (K2 self-sufficient).
INPUT_COLS = ("instrument", "time", "mid_o", "mid_h", "mid_l", "mid_c", "volume", "n_bars")


class FeaturesError(ValueError):
    """The feature pipeline could not run (missing input, empty instrument)."""


def build_instrument(
    con,
    instrument: str,
    minutes: int,
    reg: Registry,
) -> dict:
    """Fetch one instrument's rows, compute every feature column, return columns.

    D5: this is the per-instrument unit of work — only this instrument's rows
    are ever in memory. ``con`` is an open DuckDB connection to the data root;
    the query is ``SELECT ... FROM ohlcv_<minutes> WHERE instrument=? ORDER BY time``.
    """
    view = _MINUTES_TO_VIEW.get(minutes)
    if view is None:
        raise FeaturesError(
            f"unsupported minutes={minutes!r}; supported={sorted(_MINUTES_TO_VIEW)}"
        )
    rows = con.execute(
        f"SELECT instrument, time, mid_o, mid_h, mid_l, mid_c, volume, n_bars "
        f"FROM {view} WHERE instrument = ? ORDER BY time",
        [instrument],
    ).fetchnumpy()
    n = int(rows["mid_c"].shape[0])
    if n == 0:
        raise FeaturesError(f"instrument {instrument!r} has no rows in {view}")
    ctx = Ctx(
        o=rows["mid_o"].astype(np.float64),
        h=rows["mid_h"].astype(np.float64),
        l=rows["mid_l"].astype(np.float64),
        c=rows["mid_c"].astype(np.float64),
        v=rows["volume"].astype(np.float64),
        t=rows["time"],
        n=n,
    )
    cols = compute_features(ctx, reg)
    return {"n": n, "cols": cols, "input": rows}


def _build_table(instrument: str, built: dict, reg: Registry, version_str: str, minutes: int):
    """Assemble the self-sufficient wide Parquet table (K2: input cols + features)."""
    import pyarrow as pa

    n = built["n"]
    inp = built["input"]
    arrays: dict[str, Any] = {
        "instrument": np.full(n, instrument, dtype=object),
        "time": inp["time"],
        "mid_o": inp["mid_o"].astype(np.float64),
        "mid_h": inp["mid_h"].astype(np.float64),
        "mid_l": inp["mid_l"].astype(np.float64),
        "mid_c": inp["mid_c"].astype(np.float64),
        "volume": inp["volume"].astype(np.float64),
        "n_bars": inp["n_bars"],
    }
    for name in reg.names():
        arrays[name] = built["cols"][name].astype(np.float64)
    table = pa.table({k: pa.array(v) for k, v in arrays.items()})
    meta = {
        b"feature_version": str(FEATURE_VERSION).encode("utf-8"),
        b"version_string": version_str.encode("utf-8"),
        b"input_minutes": str(minutes).encode("utf-8"),
    }
    return table, meta


def write_parquet(table, meta: dict, path: Path) -> None:
    """Write the wide table to a single Parquet file (D1: no snapshot dir)."""
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    # Always overwrite (0002 A1: derived layers are recomputed, never cached).
    if path.exists():
        existing_meta = pq.read_schema(str(path)).metadata or {}
        merged = dict(existing_meta)
    else:
        merged = {}
    merged.update(meta)
    if merged:
        schema = table.schema.with_metadata(merged)
        table = table.cast(schema)
    pq.write_table(table, path)


def feature_path(data_root: str | Path, minutes: int, instrument: str) -> Path:
    """``<data_root>/features/<layer>/<instrument>.parquet`` (D1 single file).

    ``<layer>`` is ``5m`` or ``1h`` (matches the aggregate view name, 0003).
    """
    layer = _MINUTES_TO_VIEW.get(minutes)
    if layer is None:
        raise FeaturesError(
            f"unsupported minutes={minutes!r}; supported={sorted(_MINUTES_TO_VIEW)}"
        )
    return Path(data_root) / "features" / layer / f"{instrument}.parquet"


@dataclass
class FeatureRunResult:
    minutes: int
    instruments: list[str]
    total_rows: int
    paths: list[Path]
    version_string: str


#: minutes → aggregate view name (ohlcv_5m, ohlcv_1h).
_MINUTES_TO_VIEW: dict[int, str] = {5: "ohlcv_5m", 60: "ohlcv_1h"}


def list_instruments(con, view: str) -> list[str]:
    """Distinct instruments present in an ``ohlcv_<m>`` view (K5, authoritative)."""
    rows = con.execute(f"SELECT DISTINCT instrument FROM {view} ORDER BY instrument").fetchall()
    return [r[0] for r in rows]


def run_features(
    data_root: str | Path,
    minutes: int,
    reg: Registry | None = None,
    instruments: list[str] | None = None,
    con=None,
) -> FeatureRunResult:
    """Compute feature wide tables for every instrument (D5: per-instrument loop).

    * Input view is ``ohlcv_<minutes>`` (0002 aggregate contract).
    * ``instruments`` defaults to the authoritative set from the data itself
      (K5: same algorithm + params for all; only the NULL warm-up length may
      differ). Pass a subset to run a slice (debug).
    * Per-instrument streaming (D5): each round fetches one instrument's rows,
      computes, writes a single Parquet (D1: no ``<snapshot_id>`` dir), and
      releases — never all 21 in one DataFrame (OOM guard).
    * Idempotent: always recomputes and overwrites (0002 A1 derived-layer rule).
    """
    import duckdb

    root = Path(data_root)
    reg = reg or build_registry()
    view = _MINUTES_TO_VIEW.get(minutes)
    if view is None:
        raise FeaturesError(
            f"unsupported minutes={minutes!r}; supported={sorted(_MINUTES_TO_VIEW)}"
        )
    version_str = feature_version_string(reg)

    own_con = con is None
    if own_con:
        con = duckdb.connect()
        # Register the aggregate Parquet as the expected view name.
        parquet = Path(root) / view / f"{view}.parquet"
        if not parquet.exists():
            raise FeaturesError(f"missing {parquet} — run `lyra pull` (aggregate) first")
        # DDL cannot take prepared parameters — quote the path instead.
        quoted = str(parquet).replace("'", "''")
        con.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM read_parquet('{quoted}')")

    if instruments is None:
        instruments = list_instruments(con, view)
    if not instruments:
        raise FeaturesError(f"no instruments found in {view}")

    paths: list[Path] = []
    total_rows = 0
    for inst in instruments:
        built = build_instrument(con, inst, minutes, reg)
        table, meta = _build_table(inst, built, reg, version_str, minutes)
        out_path = feature_path(root, minutes, inst)
        write_parquet(table, meta, out_path)
        paths.append(out_path)
        total_rows += built["n"]
        del built  # release per-instrument working set (D5)

    if own_con:
        con.close()
    return FeatureRunResult(
        minutes=minutes,
        instruments=instruments,
        total_rows=total_rows,
        paths=paths,
        version_string=version_str,
    )
