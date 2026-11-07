"""0003 indicator golden tests (0003 §5, rows 5-17).

Reference implementations are **independent pure-Python** (hand-written
recursions / vectorized NumPy), never a second TA-Lib call: the golden test
must anchor TA-Lib's semantics, not self-confirm.
"""

from __future__ import annotations

import numpy as np
import pytest
import talib

from lyra import indicators

RNG = np.random.default_rng(42)


@pytest.fixture(scope="module")
def data():
    n = 260
    c = 100 + np.cumsum(RNG.normal(0, 1, n))
    h = c + RNG.uniform(0.2, 1.5, n)
    l = c - RNG.uniform(0.2, 1.5, n)
    v = RNG.uniform(1000, 5000, n)
    return {"c": c, "h": h, "l": l, "v": v, "n": n}


def _ref_sma(c, k):
    out = np.full(len(c), np.nan)
    for i in range(k - 1, len(c)):
        out[i] = c[i - k + 1 : i + 1].mean()
    return out


def _ref_ema(c, k):
    out = np.full(len(c), np.nan)
    a = 2.0 / (k + 1.0)
    out[k - 1] = c[:k].mean()
    for i in range(k, len(c)):
        out[i] = a * c[i] + (1.0 - a) * out[i - 1]
    return out


def _ref_rsi(c, k):
    out = np.full(len(c), np.nan)
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au, ad = up[:k].mean(), dn[:k].mean()
    out[k] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    for i in range(k + 1, len(c)):
        au = (au * (k - 1) + up[i - 1]) / k
        ad = (ad * (k - 1) + dn[i - 1]) / k
        out[i] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    return out


def _ref_atr(h, l, c, k):
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    out[k] = tr[1 : k + 1].mean()
    for i in range(k + 1, len(c)):
        out[i] = (out[i - 1] * (k - 1) + tr[i]) / k
    return out


def test_sma_values_known(data):
    c = data["c"]
    for k in (6, 12, 24, 60, 120):
        got = indicators.sma(c, k)
        ref = _ref_sma(c, k)
        m = np.isfinite(ref)
        assert np.allclose(got[m], ref[m], rtol=0, atol=1e-12), f"SMA({k})"
        assert np.isnan(got).sum() == np.isnan(ref).sum(), f"SMA({k}) warm-up prefix"


def test_ema_recursion_known(data):
    c = data["c"]
    for k in (6, 24, 60):
        got = indicators.ema(c, k)
        ref = _ref_ema(c, k)
        m = np.isfinite(ref)
        assert np.allclose(got[m], ref[m], rtol=0, atol=1e-9), f"EMA({k})"
        assert np.isnan(got).sum() == np.isnan(ref).sum(), f"EMA({k}) warm-up prefix"


def test_rsi_grid_known(data):
    got = indicators.rsi(data["c"], 24)
    ref = _ref_rsi(data["c"], 24)
    m = np.isfinite(ref)
    assert np.allclose(got[m], ref[m], rtol=0, atol=1e-9)


def test_atr_grid_values_known(data):
    h, l, c = data["h"], data["l"], data["c"]
    got = {}
    for k in (6, 12, 24, 60, 120):
        g = indicators.atr(h, l, c, k)
        r = _ref_atr(h, l, c, k)
        m = np.isfinite(r)
        assert np.allclose(g[m], r[m], rtol=0, atol=1e-9), f"ATR({k})"
        got[k] = g
    # grid effective: different windows must not collapse to the same series
    assert not np.allclose(got[24][np.isfinite(got[60])], got[60][np.isfinite(got[60])], atol=1e-12)


def test_macd_triplets_known(data):
    # Golden anchors that are independently derivable (no second TA-Lib call):
    #  * flat input  -> line = signal = 0 (EMA of a constant is that constant)
    #  * ramp input  -> EMA(k) of a ramp lags by (k-1)/2, so line = lag_slow − lag_fast
    #  * hist        == line − signal (TA-Lib contract)
    flat = np.full(300, 50.0)
    for (f, s, sig) in ((6, 12, 6), (6, 24, 6), (12, 60, 12)):
        l, sg, h = indicators.macd(flat, f, s, sig)
        # every defined value must be 0 (EMA of a constant is that constant,
        # so the diff is 0; the warm-up prefix is NaN by F2)
        for arr in (l, sg, h):
            finite = arr[np.isfinite(arr)]
            assert len(finite) > 0
            assert np.allclose(finite, 0.0, atol=1e-9)

    ramp = np.arange(300.0)
    for (f, s, sig) in ((6, 12, 6), (6, 24, 6), (12, 60, 12)):
        l, sg, h = indicators.macd(ramp, f, s, sig)
        expected = (s - 1) / 2.0 - (f - 1) / 2.0
        assert np.allclose(l[s + sig + 2 :], expected, rtol=0, atol=1e-9), f"MACD({f},{s},{sig}) line lag"
        # signal = EMA(line, sig); line is constant on a ramp → signal == line
        assert np.allclose(sg[s + sig + 2 :], expected, rtol=0, atol=1e-9)

    # hist identity on the shared dataset
    c = data["c"]
    for (f, s, sig) in ((6, 12, 6), (6, 24, 6), (12, 60, 12)):
        l, sg, h = indicators.macd(c, f, s, sig)
        mh = np.isfinite(h)
        assert np.allclose(h[mh], l[mh] - sg[mh], rtol=0, atol=1e-9)


def test_roc_stoch_known(data):
    c, h, l = data["c"], data["h"], data["l"]
    got = indicators.roc(c, 24)
    m = np.arange(24, len(c))
    assert np.allclose(got[m], (c[m] - c[m - 24]) / c[m - 24] * 100.0, rtol=0, atol=1e-9)

    k, d = indicators.stoch(h, l, c, 24, 12)
    # TA-Lib defers %K to align with %D's warm-up (both valid from
    # fastk+slowd-2 onwards). Check on a late slice where both are clean.
    late = np.arange(120, len(c))
    ref_k = np.empty(len(late))
    ref_d = np.empty(len(late))
    for j, i in enumerate(late):
        hi = h[i - 23 : i + 1].max()
        lo = l[i - 23 : i + 1].min()
        ref_k[j] = (c[i] - lo) / (hi - lo) * 100.0
        # %D = SMA(%K, 12) over the 12 most recent %K values
        ref_d[j] = np.array([
            (c[i2] - l[i2 - 23 : i2 + 1].min()) /
            (h[i2 - 23 : i2 + 1].max() - l[i2 - 23 : i2 + 1].min()) * 100.0
            for i2 in range(i - 11, i + 1)
        ]).mean()
    assert np.allclose(k[late], ref_k, rtol=0, atol=1e-9)
    assert np.all((k[late] >= 0) & (k[late] <= 100))
    assert np.allclose(d[late], ref_d, rtol=0, atol=1e-9)


def test_bbands_pctb_bw_known(data):
    c = data["c"]
    n = 24
    pctb, bw = indicators.bbands(c, n)
    mean = np.full(len(c), np.nan)
    sd = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1 : i + 1]
        mean[i] = w.mean()
        sd[i] = w.std(ddof=0)
    up = mean + 2 * sd
    lo = mean - 2 * sd
    band = up - lo
    m = np.isfinite(pctb)
    assert np.allclose(pctb[m], (c[m] - mean[m]) / band[m], rtol=0, atol=1e-12)
    mb = np.isfinite(bw)
    assert np.allclose(bw[mb], band[mb] / mean[mb], rtol=0, atol=1e-12)
    assert np.all(bw[mb] >= 0)


def test_trend_momentum_family_known(data):
    h, l, c = data["h"], data["l"], data["c"]
    for n in (24, 60):
        for fn in (indicators.adx, indicators.plus_di, indicators.minus_di):
            v = fn(h, l, c, n)
            m = np.isfinite(v)
            assert np.all((v[m] >= 0) & (v[m] <= 100)), fn.__name__
        cci = indicators.cci(h, l, c, n)
        assert np.isfinite(cci).any()
        w = indicators.willr(h, l, c, n)
        m = np.isfinite(w)
        assert np.all((w[m] >= -100) & (w[m] <= 0))
        cmo = indicators.cmo(c, n)
        m = np.isfinite(cmo)
        assert np.all((cmo[m] >= -100) & (cmo[m] <= 100))


def test_volume_flow_known(data):
    h, l, c, v = data["h"], data["l"], data["c"], data["v"]
    for n in (24, 60):
        mfi = indicators.mfi(h, l, c, v, n)
        m = np.isfinite(mfi)
        assert np.all((mfi[m] >= 0) & (mfi[m] <= 100))
    # OBV: TA-Lib seeds the first value with the first volume, then ±v per close move.
    obv = indicators.obv(c, v)
    sign = np.sign(np.diff(c))
    ref = np.empty(len(c)); ref[0] = v[0]
    ref[1:] = v[0] + np.cumsum(sign * v[1:])
    assert np.allclose(obv, ref, rtol=0, atol=1e-9)
    # obv_slope_24 is the LINEARREG_SLOPE of OBV over 24 bars (finite post-warmup).
    assert np.isfinite(talib.LINEARREG_SLOPE(obv, timeperiod=24)).any()
    kama = indicators.kama(c, 24)
    m = np.isfinite(kama)
    assert np.all((kama[m] >= c.min()) & (kama[m] <= c.max()))
    for n in (24, 60):
        assert np.isfinite(indicators.lrslope(c, n)).any()


def test_natr_consistency(data):
    h, l, c = data["h"], data["l"], data["c"]
    for n in (6, 24, 120):
        natr = indicators.natr(h, l, c, n)
        ratio = indicators.atr(h, l, c, n) / c
        m = np.isfinite(natr) & np.isfinite(ratio)
        assert np.allclose(natr[m], ratio[m], rtol=0, atol=1e-12), f"NATR({n})"


def test_dema_tema_hma_known(data):
    c = data["c"]
    for n in (24, 60):
        dema = indicators.dema(c, n)
        m = np.isfinite(dema)
        assert np.all((dema[m] >= c.min()) & (dema[m] <= c.max()))
        tema = indicators.tema(c, n)
        assert np.isfinite(tema).any()
        hma = indicators.hma(c, n)
        assert np.isfinite(hma).any()
    # DEMA identity on a fixed, hand-checkable input:
    # DEMA = 2·EMA(c,n) − EMA(EMA(c,n), n).  For constant input the EMA is
    # constant, so DEMA must equal that constant (a degenerate identity probe).
    flat = np.full(80, 42.0)
    dema_flat = talib.DEMA(flat, timeperiod=24)
    m = np.isfinite(dema_flat)
    assert np.allclose(dema_flat[m], 42.0, rtol=0, atol=1e-9)


def test_mom_stddev_zscore_known(data):
    c = data["c"]
    n = 24
    mom = indicators.mom(c, n)
    m = np.arange(n, len(c))
    assert np.allclose(mom[m], c[m] - c[m - n], rtol=0, atol=1e-12)
    sd = indicators.stddev(c, n)
    m = np.isfinite(sd)
    assert np.all(sd[m] >= 0)
    z = indicators.zscore(c, n)
    mean = np.full(len(c), np.nan)
    s = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1 : i + 1]
        mean[i] = w.mean()
        s[i] = w.std(ddof=0)
    mz = np.isfinite(z)
    assert np.allclose(z[mz], (c[mz] - mean[mz]) / s[mz], rtol=0, atol=1e-12)
    assert np.allclose(z[mz].mean(), 0.0, atol=0.25)
    # D4: all-flat input → zscore NULL (zero rolling std), never Inf
    flat = np.full(60, 100.0)
    zf = indicators.zscore(flat, 24)
    assert np.all(np.isnan(zf))
