"""Pure-Numpy indicator primitives (decision 0003 K1 / §2.3 adoptions 1-2).

Two responsibilities:

1. **Standard indicators** — thin, deterministic wrappers over **TA-Lib**
   (the C core is the reference implementation for both prior generations,
   moneta ``library/*`` and nova ``features.py``). Each wrapper returns 1-D
   ``float64`` arrays of the input length, NaN where undefined (warm-up).
   No pandas / duckdb / framework imports — the NumPy-in / NumPy-out boundary
   (moneta ``library/__init__`` convention) keeps the math unit-testable and
   independently versionable.

2. **The one hand-written reference** — :func:`supertrend_reference` is the
   canonical path-dependent Supertrend construction (moneta
   ``library/supertrend.py`` / nova ``indicators.py``, identical). It is **not**
   used in production (K1 switched production to ``talib.SUPERTREND``); it
   exists as the *golden cross-anchor* for the parity test (K1 dual-library
   parity) so a future TA-Lib version that silently changes semantics is
   caught (``test_supertrend_parity_vs_reference``).

Determinism (F4): every function is a pure function of its inputs; no clocks,
no randomness, no global state. Same input + same TA-Lib build ⇒ bitwise
identical output on the same platform.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import talib

__all__ = [
    "sma", "ema", "dema", "tema", "hma", "kama",
    "atr", "natr", "rsi", "roc", "cci", "willr", "mfi", "cmo",
    "mom", "stddev", "lrslope", "obv", "macd", "stoch", "bbands",
    "adx", "plus_di", "minus_di", "sar", "sar_direction",
    "supertrend_line", "supertrend_bullish", "supertrend_bearish",
    "supertrend_reference", "zscore",
]


# ---------------------------------------------------------------------------
# Simple grid families
# ---------------------------------------------------------------------------

def sma(c: np.ndarray, n: int) -> np.ndarray:
    return talib.SMA(np.asarray(c, dtype=np.float64), timeperiod=n)


def ema(c: np.ndarray, n: int) -> np.ndarray:
    return talib.EMA(np.asarray(c, dtype=np.float64), timeperiod=n)


def dema(c: np.ndarray, n: int) -> np.ndarray:
    return talib.DEMA(np.asarray(c, dtype=np.float64), timeperiod=n)


def tema(c: np.ndarray, n: int) -> np.ndarray:
    return talib.TEMA(np.asarray(c, dtype=np.float64), timeperiod=n)


def hma(c: np.ndarray, n: int) -> np.ndarray:
    return talib.HMA(np.asarray(c, dtype=np.float64), timeperiod=n)


def kama(c: np.ndarray, n: int) -> np.ndarray:
    return talib.KAMA(np.asarray(c, dtype=np.float64), timeperiod=n)


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    """Wilder-smoothed ATR (the K6 normalization basis is ``atr_24``)."""
    return talib.ATR(h, l, c, timeperiod=n)


def natr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    """NATR = ATR / close (dimensionless volatility scale).

    Computed as ``atr / close`` directly — **not** ``talib.NATR`` — because
    TA-Lib's NATR multiplies by 100, while the 0003 contract (R3.1 +
    ``test_natr_consistency``) specifies the clean ratio ``atr_W == atr_W/close``.
    Zero close is impossible (positive prices); a zero ATR (all-flat) is a
    legitimate 0.0 NATR.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return talib.ATR(h, l, c, timeperiod=n) / np.asarray(c, dtype=np.float64)


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    return talib.RSI(np.asarray(c, dtype=np.float64), timeperiod=n)


def roc(c: np.ndarray, n: int) -> np.ndarray:
    return talib.ROC(np.asarray(c, dtype=np.float64), timeperiod=n)


def cci(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    return talib.CCI(h, l, c, timeperiod=n)


def willr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    return talib.WILLR(h, l, c, timeperiod=n)


def mfi(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray, n: int) -> np.ndarray:
    return talib.MFI(h, l, c, v, timeperiod=n)


def cmo(c: np.ndarray, n: int) -> np.ndarray:
    return talib.CMO(np.asarray(c, dtype=np.float64), timeperiod=n)


def mom(c: np.ndarray, n: int) -> np.ndarray:
    """Absolute n-bar momentum: close − close[n]."""
    return talib.MOM(np.asarray(c, dtype=np.float64), timeperiod=n)


def stddev(c: np.ndarray, n: int) -> np.ndarray:
    return talib.STDDEV(np.asarray(c, dtype=np.float64), timeperiod=n)


def lrslope(c: np.ndarray, n: int) -> np.ndarray:
    """LINEARREG_SLOPE (per-bar regression slope of close over n bars)."""
    return talib.LINEARREG_SLOPE(np.asarray(c, dtype=np.float64), timeperiod=n)


def obv(c: np.ndarray, v: np.ndarray) -> np.ndarray:
    return talib.OBV(np.asarray(c, dtype=np.float64), v)


# ---------------------------------------------------------------------------
# Multi-output families (split into one array per column by the caller)
# ---------------------------------------------------------------------------

def macd(c: np.ndarray, fast: int, slow: int, signal: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(line, signal, hist) — TA-Lib MACD; hist == line − signal."""
    return talib.MACD(np.asarray(c, dtype=np.float64), fast, slow, signal)


def stoch(h, l, c, fastk: int, slowd: int) -> Tuple[np.ndarray, np.ndarray]:
    """(%K, %D). slowk_ma=1 (SMA of length 1) keeps %K unsmoothed; %D is the
    slowd-bar mean of %K — the in-grid (fastk, slowd) pairing from §3.4."""
    return talib.STOCH(h, l, c, fastk, 1, 0, slowd, 0)


def bbands(c: np.ndarray, n: int) -> Tuple[np.ndarray, np.ndarray]:
    """(percent_b, bandwidth) — the dimensionless BBANDS forms only.

    ``%B = (close − middle) / (upper − lower)``; ``bandwidth = (upper−lower)/middle``.
    The raw upper/lower bands are deliberately NOT returned (they carry a price
    unit and are not cross-instrument comparable — the §3.4 discipline).
    Zero band width (all-flat) → NaN on the defined-zero-denominator rule (D4).
    """
    upper, middle, lower = talib.BBANDS(np.asarray(c, dtype=np.float64), timeperiod=n, nbdevup=2.0, nbdevdn=2.0, matype=0)
    band = upper - lower
    with np.errstate(divide="ignore", invalid="ignore"):
        pctb = np.where(band > 0, (c - middle) / band, np.nan)
        bw = np.where(middle > 0, band / middle, np.nan)
    return pctb, bw


def adx(h, l, c, n: int) -> np.ndarray:
    return talib.ADX(h, l, c, timeperiod=n)


def plus_di(h, l, c, n: int) -> np.ndarray:
    return talib.PLUS_DI(h, l, c, timeperiod=n)


def minus_di(h, l, c, n: int) -> np.ndarray:
    return talib.MINUS_DI(h, l, c, timeperiod=n)


# ---------------------------------------------------------------------------
# PSAR (direction flags)
# ---------------------------------------------------------------------------

def sar(h: np.ndarray, l: np.ndarray, af: float = 0.02, maximum: float = 0.2) -> np.ndarray:
    """Parabolic SAR price line (K8 exception: af/maximum are factors, not windows)."""
    return talib.SAR(h, l, acceleration=af, maximum=maximum)


def sar_direction(h: np.ndarray, l: np.ndarray, sar_line: np.ndarray, af: float = 0.02, maximum: float = 0.2) -> np.ndarray:
    """+1 in an uptrend, −1 in a downtrend, NaN where the SAR line is NaN.

    Standard Parabolic SAR direction test (causal): while SAR is *rising* the
    market is in a downtrend (SAR above price, capping from the high); while
    SAR is *falling* it is in an uptrend (SAR below price, a trailing
    support). Derived purely from the SAR line's bar-to-bar movement, so no
    close reference is needed. Bar 0 has no prior SAR → NaN (warm-up).
    """
    sl = np.asarray(sar_line, dtype=np.float64)
    n = len(sl)
    d = np.full(n, np.nan)
    if n < 2:
        return d
    delta = np.full(n, np.nan)
    delta[1:] = sl[1:] - sl[:-1]
    d[1:] = np.where(delta[1:] < 0, 1.0, -1.0)
    d[~np.isfinite(sl)] = np.nan
    d[~np.isfinite(delta)] = np.nan
    return d


# ---------------------------------------------------------------------------
# Supertrend (talib production + hand-written golden reference)
# ---------------------------------------------------------------------------

def supertrend_line(h, l, c, atr_window: int = 24, multiplier: float = 3.0) -> np.ndarray:
    """The active Supertrend line from ``talib.SUPERTREND`` (K1 library impl)."""
    line, trend = talib.SUPERTREND(h, l, c, timeperiod=atr_window, multiplier=multiplier)
    return line


def _supertrend_trend(h, l, c, atr_window: int, multiplier: float) -> np.ndarray:
    """Direction from ``talib.SUPERTREND``: +1 uptrend / −1 downtrend / NaN warm-up."""
    _, trend = talib.SUPERTREND(h, l, c, timeperiod=atr_window, multiplier=multiplier)
    t = np.asarray(trend, dtype=np.float64)
    return np.where(t > 0, 1.0, -1.0)


def supertrend_bullish(h, l, c, atr_window: int = 24, multiplier: float = 3.0) -> np.ndarray:
    d = _supertrend_trend(h, l, c, atr_window, multiplier)
    out = np.where(d == 1.0, 1.0, 0.0)
    out[~np.isfinite(d)] = np.nan
    return out


def supertrend_bearish(h, l, c, atr_window: int = 24, multiplier: float = 3.0) -> np.ndarray:
    d = _supertrend_trend(h, l, c, atr_window, multiplier)
    out = np.where(d == -1.0, 1.0, 0.0)
    out[~np.isfinite(d)] = np.nan
    return out


def supertrend_reference(h, l, c, atr: np.ndarray, mult: float = 3.0) -> Tuple[np.ndarray, np.ndarray]:
    """Hand-written canonical Supertrend (moneta/nova reference, golden anchor).

    Path-dependent recursion: basic bands ``ub = hl2 + k·ATR``, ``lb = hl2 −
    k·ATR``; the **final** bands ratchet against the *previous* close (upper
    only moves down / when price closes above; lower only moves up / when price
    closes below); direction flips when the close crosses the active band.
    Reported line = the **active** band (lower in uptrends, upper in
    downtrends). Causal (bar t uses bars ≤ t). NaN where ``atr`` is NaN.

    Used ONLY as the cross-check anchor for ``talib.SUPERTREND`` (K1 parity);
    not a production path.
    """
    n = len(c)
    line = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    if not mult > 0:
        raise ValueError(f"Supertrend multiplier must be > 0, got {mult}")
    hl2 = (h + l) / 2.0
    ub = hl2 + mult * atr
    lb = hl2 - mult * atr
    fu = fl = np.nan
    d = 1.0
    started = False
    for t in range(n):
        if not np.isfinite(atr[t]):
            continue
        if not started:
            fu, fl, d, started = ub[t], lb[t], 1.0, True
        else:
            fu = ub[t] if (ub[t] < fu or c[t - 1] > fu) else fu
            fl = lb[t] if (lb[t] > fl or c[t - 1] < fl) else fl
            if d > 0:
                if c[t] < fl:
                    d = -1.0
            elif c[t] > fu:
                d = 1.0
        direction[t] = d
        line[t] = fl if d > 0 else fu
    return line, direction


# ---------------------------------------------------------------------------
# Derived (SMA + STDDEV composition)
# ---------------------------------------------------------------------------

def heikin_asi(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Heikin Ashi OHLC (K7 self-implementation — no library ships it).

    Recursive transform of the *observed* OHLC into smoothed (heikin) bars:

        ha_c[i] = (o[i] + h[i] + l[i] + c[i]) / 4
        ha_o[i] = (ha_o[i-1] + ha_c[i-1]) / 2       (seed: ha_o[0] = (o[0]+c[0])/2)
        ha_h[i] = max(h[i], ha_o[i], ha_c[i])
        ha_l[i] = min(l[i], ha_o[i], ha_c[i])

    No window parameter (window_params=()) → K8 grid guard N/A. The recursion
    converges in ~16 bars regardless of seed, so warmup_bars=16 is a safe
    lower bound for the F2 assertion. Path-dependent from the data head (K4).
    """
    o = np.asarray(o, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)
    l = np.asarray(l, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    n = len(c)
    ha_c = (o + h + l + c) / 4.0
    ha_o = np.empty(n)
    ha_o[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2.0
    ha_h = np.maximum(h, np.maximum(ha_o, ha_c))
    ha_l = np.minimum(l, np.minimum(ha_o, ha_c))
    return ha_o, ha_h, ha_l, ha_c


def zscore(c: np.ndarray, n: int) -> np.ndarray:
    """(close − SMA(close, n)) / STDDEV(close, n) — dimensionless price position.

    Zero denominator (N all-flat bars → rolling stddev 0) → NaN on the
    defined-zero-denominator rule (D4); never an error.
    """
    c = np.asarray(c, dtype=np.float64)
    mean = talib.SMA(c, timeperiod=n)
    sd = talib.STDDEV(c, timeperiod=n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(sd > 0, (c - mean) / sd, np.nan)
    return out
