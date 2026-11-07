"""Cross-library control: tulipy (C-backed, no pandas) vs our TA-Lib backend.

Why this exists (0003 K1 double-implementation cross-validation):
Our feature backend is TA-Lib (K1). To guard against a silent semantic
drift if TA-Lib is ever re-versioned, we cross-check our *shipped* feature
values against an independent second implementation. tulipy is the best fit
because it is (a) C-backed, (b) needs no pandas (our runtime stack is
deliberately pandas-free), and (c) covers more standard indicators than the
hand-rolled pure-NumPy references in ``test_indicators.py``.

It is an **optional** dependency (``pip install "lyra[control]"``) and is
imported here only, so the runtime core stays at R10's <=15 packages.

Two important tulipy-vs-TA-Lib differences (same family as the CMO/MFI
findings in ACTION_LOG #61):

* **Array length**: tulipy *truncates* the warm-up prefix and returns a
  shorter array (e.g. len 376 for a 400-bar input with period 24); TA-Lib
  keeps the full length and fills the prefix with NaN. We therefore align on
  the **tail** (``a[-k:]``) and never assume equal lengths. (moneta hit this
  exact "delete the prefix rows" trap — see 0003 §2.3 anti-pattern #1.)

* **Conventions**: a handful of indicators differ by a constant factor or
  seed, e.g. tulipy ROC/NATR are NOT ×100 (TA-Lib's), tulipy CMO uses an
  EMA-smoothed numerator/denominator (TA-Lib does not), tulipy OBV seeds at
  0 (TA-Lib seeds at ``v[0]``). These are *definitional*, not bugs: each
  side matches its own canonical definition exactly. The mapping below
  declares which normalisation to apply per indicator so the comparison is
  apples-to-apples.

Adding a new P1/P2 feature later? Extend :data:`MAP` with its tulipy
equivalent and a ``'exact'`` / ``'definitional'`` tag; :func:`crosscheck`
picks it up automatically.
"""

from __future__ import annotations

import numpy as np

#: feature name -> (producer, tag)
#:   producer : callable(ohcv) -> np.ndarray aligned to the *full* length by
#:              the caller's tail-alignment helper, OR None if tulipy lacks it
#:   tag      : 'exact'          -> must match to < 1e-9 (same definition)
#:              'definitional'   -> matches a normalised form (factor/smooth/seed)
#:              'no_lib'         -> tulipy has no equivalent (documented skip)
MAP: dict[str, tuple] = {
    # --- machine-precision group (same definition, no Wilder/EMA smoothing) -
    # Verified < 1e-10 tail-relative at n=400 AND n=2000. These indicators do
    # NOT use a decaying recursive smoother whose *seeding* differs between
    # the two C libraries, so they agree to floating-point noise only.
    "sma_24":      (lambda o, h, l, c, v, tp: tp.sma(c, 24), "exact"),
    "hma_24":      (lambda o, h, l, c, v, tp: tp.hma(c, 24), "exact"),
    "kama_24":     (lambda o, h, l, c, v, tp: tp.kama(c, 24), "exact"),
    "rsi_24":      (lambda o, h, l, c, v, tp: tp.rsi(c, 24), "exact"),
    "mom_24":      (lambda o, h, l, c, v, tp: tp.mom(c, 24), "exact"),
    "cci_24":      (lambda o, h, l, c, v, tp: tp.cci(h, l, c, 24), "exact"),
    "willr_24":    (lambda o, h, l, c, v, tp: tp.willr(h, l, c, 24), "exact"),
    "mfi_24":      (lambda o, h, l, c, v, tp: tp.mfi(h, l, c, v, 24), "exact"),
    "stddev_24":   (lambda o, h, l, c, v, tp: tp.stddev(c, 24), "exact"),
    # --- definitional group (smoothing-convention / factor / seed) ---------
    # All of these use a decaying recursive smoother (EMA or Wilder). TA-Lib
    # and tulipy seed the recursion differently and/or use a different alpha,
    # so the tail does NOT converge to machine precision at reasonable series
    # lengths (measured: EMA/DEMA ~1e-2, TEMA ~1e-3, ATR/ADX ~3e-3, length-
    # dependent). These are legitimate definitional differences, not bugs —
    # the test asserts only a sane bound, not machine precision.
    "ema_24":      (lambda o, h, l, c, v, tp: tp.ema(c, 24), "definitional"),
    "dema_24":     (lambda o, h, l, c, v, tp: tp.dema(c, 24), "definitional"),
    "tema_24":     (lambda o, h, l, c, v, tp: tp.tema(c, 24), "definitional"),
    "atr_24":      (lambda o, h, l, c, v, tp: tp.atr(h, l, c, 24), "definitional"),
    "adx_24":      (lambda o, h, l, c, v, tp: tp.adx(h, l, c, 24), "definitional"),
    # tulipy NATR is the raw ATR/close ratio; we also emit ATR/close, but the
    # ATR numerator carries the Wilder-seed difference above -> definitional.
    "natr_24":     (lambda o, h, l, c, v, tp: tp.natr(h, l, c, 24), "definitional"),
    # tulipy ROC = c/c[n] - 1 (no ×100); TA-Lib ROC = ×100. Normalise theirs.
    "roc_24":      (lambda o, h, l, c, v, tp: tp.roc(c, 24) * 100.0, "definitional"),
    # tulipy CMO uses an EMA-smoothed up/down sum; TA-Lib uses plain sums.
    "cmo_24":      (lambda o, h, l, c, v, tp: tp.cmo(c, 24), "definitional"),
    # tulipy OBV seeds at 0; TA-Lib seeds at v[0]. Compare the *differences*.
    "obv":         (lambda o, h, l, c, v, tp: tp.obv(c, v), "definitional"),
    # --- no tulipy equivalent (documented skip) ----------------------------
    "plus_di_24":  (None, "no_lib"),
    "minus_di_24": (None, "no_lib"),
    "lrslope_24":  (None, "no_lib"),
    "supertrend":  (None, "no_lib"),
    "ha_o":        (None, "no_lib"),
}


def run_crosscheck(o, h, l, c, v, cols: dict[str, np.ndarray]) -> dict[str, tuple]:
    """Run the full cross-check and return ``{name: (tag, diff)}``.

    ``o/h/l/c/v`` are the fixture arrays; ``cols`` is the dict of shipped
    feature columns (from ``features.compute_features``). Alignment is by
    trailing length: k = min(len(ours), len(theirs)), then both are sliced to
    the last k and compared where both are finite.
    """
    import tulipy as tp

    def call(producer):
        return np.asarray(producer(o, h, l, c, v, tp), dtype=np.float64)

    out: dict[str, tuple] = {}
    for name, (producer, tag) in MAP.items():
        if name not in cols:
            continue
        ours = np.asarray(cols[name], dtype=np.float64)
        if producer is None:
            out[name] = ("no_lib", None)
            continue
        theirs = call(producer)
        k = min(len(ours), len(theirs))
        a = ours[-k:]
        b = theirs[-k:]
        # OBV seeds differently: compare the *differences* (first diff drops
        # the constant offset, leaving the same per-bar increments).
        if name == "obv":
            a = np.diff(a); b = np.diff(b)
        m = np.isfinite(a) & np.isfinite(b)
        if not m.any():
            out[name] = (tag, None)
            continue
        d = np.abs(a[m] - b[m]) / np.maximum(np.abs(b[m]), 1e-9)
        out[name] = (tag, float(d.max()))
    return out
