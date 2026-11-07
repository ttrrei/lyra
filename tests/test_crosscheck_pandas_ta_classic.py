"""0003 K1b cross-library control test: pandas-ta-classic (primary) vs our TA-Lib backend.

``pip install "lyra[control]"`` to enable; this module auto-skips otherwise.

The machine-precision group (tag ``exact``) is asserted to < 1e-6 — a hard
regression guard against a future TA-Lib semantic change. pandas-ta-classic
returns full-length arrays (NaN prefix), so — unlike tulipy — no
tail-alignment is needed.

The ``definitional`` group (MACD/ROC/CMO/MFI/STOCH/BBANDS/Aroon/TSI/OBV)
is legitimately different by smoothing convention / scale / naming
(see the MAP comments in ``crosscheck_pandas_ta_classic.py``); we assert
only finiteness for those.

``no_lib`` features (lrslope/heikin_asi/structural/semantic) have no ptc
equivalent and are cross-checked via the golden references in
``test_indicators.py`` instead.
"""

from __future__ import annotations

import numpy as np
import pytest

ptc = pytest.importorskip("pandas_ta_classic")  # optional: lyra[control]

from lyra import features  # noqa: E402
from crosscheck_pandas_ta_classic import run_crosscheck  # noqa: E402

RNG = np.random.default_rng(7)


@pytest.fixture(scope="module")
def ohcv():
    n = 400
    c = 100 + np.cumsum(RNG.normal(0, 1, n))
    h = c + RNG.uniform(0.2, 1.5, n)
    l = c - RNG.uniform(0.2, 1.5, n)
    v = RNG.uniform(1000, 5000, n)
    t = (np.datetime64("2020-01-01T00:00:00", "us")
         + np.arange(n, dtype=np.int64) * np.timedelta64(1, "h"))
    return {"o": c - 0.5, "h": h, "l": l, "c": c, "v": v, "t": t, "n": n}


@pytest.fixture(scope="module")
def cols(ohcv):
    ctx = features.Ctx(o=ohcv["o"], h=ohcv["h"], l=ohcv["l"], c=ohcv["c"],
                       v=ohcv["v"], t=ohcv["t"], n=ohcv["n"])
    reg = features.build_registry()
    return features.compute_features(ctx, reg)


def test_crosscheck_all_mapped(ohcv, cols):
    """Every mapped feature cross-checks: exact group < 1e-6; definitional
    group finite; no_lib group skipped without error."""
    res = run_crosscheck(ohcv["o"], ohcv["h"], ohcv["l"], ohcv["c"], ohcv["v"], cols)
    n_exact = n_def = n_skip = 0
    for name, (tag, d) in res.items():
        if tag == "no_lib":
            n_skip += 1
            assert d is None
        elif tag == "exact":
            n_exact += 1
            assert d is not None, f"{name}: exact but no finite overlap"
            assert d < 1e-6, f"{name}: cross-library drift {d:.3e} (expected < 1e-6)"
        elif tag == "definitional":
            n_def += 1
            assert d is not None, f"{name}: definitional but no finite overlap"
            assert np.isfinite(d), f"{name}: definitional diff not finite"
        else:
            raise AssertionError(f"{name}: unknown tag {tag!r}")
    # coverage guards: the ptc group must actually cover a meaningful slice
    assert n_exact >= 25, f"expected >=25 exact cross-checks, got {n_exact}"
    assert n_def >= 10, f"expected >=10 definitional cross-checks, got {n_def}"
    assert n_skip >= 10, f"expected >=10 documented skips, got {n_skip}"


def test_crosscheck_ptc_covers_tulipy_gaps():
    """The whole point of ptc as the PRIMARY control: it must map the three
    features tulipy cannot (plus_di/minus_di/supertrend) to real producers,
    tagged exact (verified < 1e-10 on real data)."""
    from crosscheck_pandas_ta_classic import MAP
    for name in ("plus_di_24", "minus_di_24", "supertrend"):
        producer, tag = MAP[name]
        assert producer is not None, f"{name} must have a ptc producer (tulipy gap)"
    # plus_di / minus_di are exact; supertrend is definitional on short
    # fixtures (path-dependent ratchet seed; exact = 0.0 on 40k real bars).
    assert MAP["plus_di_24"][1] == "exact"
    assert MAP["minus_di_24"][1] == "exact"
    assert MAP["supertrend"][1] == "definitional"
