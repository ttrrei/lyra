"""0005 trade engine tests — the 0005 §6 test matrix (bilingual decision).

Covers: entry fill at T+1 open (I2, T1), stop gap at open (I3, T3),
stop inside bar (I3, T4), stop before target same bar (I4, T6), take-profit
at open (T5), indicator exit next open (I2, T7), time exit next open (T7),
one trade per instrument (I5), end-of-data force close (T8), cost model
(commission flat + financing by days), long/short symmetry (I2, T1-T2),
determinism, and a golden test against nova real trades (conditional).

All tests use mid-price bars (no bid/ask split — the lyra/moneta case).
"""
from __future__ import annotations

import datetime as dt

import pytest

from lyra import trade_engine as te
from lyra.compiler import CompiledPlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = dt.datetime(2020, 3, 9, 3, 0, tzinfo=dt.timezone.utc)
H1 = dt.timedelta(hours=1)


def _bar(i: int, o: float, h: float, l: float, c: float,
         entry_long=False, entry_short=False,
         exit_long=False, exit_short=False) -> dict:
    return {
        "instrument": "AUD_USD",
        "time": T0 + i * H1,
        "mid_o": o, "mid_h": h, "mid_l": l, "mid_c": c,
        "entry_long": entry_long, "entry_short": entry_short,
        "exit_long": exit_long, "exit_short": exit_short,
    }


def _plan(**over) -> CompiledPlan:
    d = dict(
        strategy_id="t", view="features_1h", timeframe_minutes=60,
        sql="SELECT 1", params=(), features_used=("rsi_6",),
        stop_loss_pct=0.02, take_profit_pct=None, max_holding_bars=None,
        spread_bps=0.0, slippage_bps_per_side=0.0,
        commission_bps_round_trip=0.0, financing_bps_per_day=0.0,
        direction="x", parents=(), plan_hash="h",
        schema_version=1, feature_catalog_snapshot=None, compiler_version="t",
    )
    d.update(over)
    return CompiledPlan(**d)


# ---------------------------------------------------------------------------
# 0005 §6 test matrix
# ---------------------------------------------------------------------------

def test_entry_fill_at_next_open():
    """I2/T1: signal on bar T → fill at bar T+1 open.

    Bar 0: entry_long=True (signal). Bar 1: open=1.05 → fill at 1.05.
    Bar 1 also has exit_long=True → pending for bar 2.
    Bar 2: open=1.03 → indicator_exit fill at 1.03.
    """
    bars = [
        _bar(0, 1.00, 1.02, 0.99, 1.01, entry_long=True),
        _bar(1, 1.05, 1.06, 1.04, 1.05, exit_long=True),
        _bar(2, 1.03, 1.04, 1.02, 1.03),
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == 1
    assert t.entry_price == pytest.approx(1.05)
    assert t.exit_reason == "indicator_exit"
    assert t.exit_price == pytest.approx(1.03)
    # long: (1.03 - 1.05) / 1.05
    assert t.gross_return == pytest.approx((1.03 - 1.05) / 1.05)
    assert t.net_return == pytest.approx(t.gross_return)  # no costs


def test_stop_gap_at_open():
    """I3/T3: open already beyond stop → fill at open (gap loss > 2%).

    Entry at bar 1 open=1.00. Stop = 1.00 * 0.98 = 0.98.
    Bar 2 open=0.95 (gap below stop) → stop_gap fill at 0.95.
    Loss = (0.95 - 1.00) / 1.00 = -5% (exceeds 2%).
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),  # entry fill at open=1.00
        _bar(2, 0.95, 0.97, 0.94, 0.96),  # gap below stop=0.98
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop_gap"
    assert t.exit_price == pytest.approx(0.95)
    assert t.gross_return == pytest.approx(-0.05)  # gap loss > 2%


def test_stop_inside_bar():
    """I3/T4: intra-bar low beyond stop → fill at stop (exactly 2%).

    Entry at bar 1 open=1.00. Stop = 0.98.
    Bar 2: open=1.00, low=0.97 (below stop) → stop_loss fill at 0.98.
    Loss = (0.98 - 1.00) / 1.00 = -2% exactly.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.97, 0.99),  # low=0.97 < stop=0.98
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(0.98)
    assert t.gross_return == pytest.approx(-0.02)  # exactly 2%


def test_stop_wins_over_target_same_bar():
    """I4/T6: same bar hits both stop and target → stop (loss side) wins.

    Entry at bar 1 open=1.00. Stop=0.98, target=1.02 (tp=2%).
    Bar 2: low=0.97 (stop hit), high=1.03 (target hit) → stop_loss at 0.98.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.03, 0.97, 1.01),  # both stop and target hit
    ]
    trades = te.simulate(_plan(take_profit_pct=0.02), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(0.98)


def test_take_profit_at_open():
    """T5: open beyond target → fill AT the target (limit-order semantics).

    Nova reference (trades.py): a stop-gap at the open fills at the open
    (real loss beyond the stop), but an open beyond the target fills at the
    target — the trader never receives a better price than the limit.

    Entry at bar 1 open=1.00. Target=1.02 (tp=2%).
    Bar 2: open=1.03 (above target) → take_profit fill at 1.02, not 1.03.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.03, 1.04, 1.02, 1.03),  # open=1.03 > target=1.02
    ]
    trades = te.simulate(_plan(take_profit_pct=0.02), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "take_profit"
    assert t.exit_price == pytest.approx(1.02)  # limit semantics, not open
    assert t.gross_return == pytest.approx(0.02)


def test_indicator_exit_next_open():
    """I2/T7: exit signal on bar T → fill at bar T+1 open.

    Entry at bar 1 open=1.00. Exit signal on bar 2.
    Bar 3: open=1.01 → indicator_exit fill at 1.01.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),  # signal
        _bar(3, 1.01, 1.02, 1.00, 1.01),  # fill at open
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "indicator_exit"
    assert t.exit_price == pytest.approx(1.01)


def test_time_exit_next_open():
    """T7: bars_held >= max_holding_bars → pending exit, filled at the
    NEXT bar's open (one-bar lag, like indicator_exit).

    Entry at bar 1 open=1.00. mhb=1.
    Bar 1 (entry bar, no stop/target): bars becomes 1 (== mhb) → pending_exit=time_exit.
    Bar 2: open=1.00 → time_exit fill at 1.00.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),  # bars=1 == mhb → pending
        _bar(2, 1.00, 1.01, 0.99, 1.00),  # fill at open
    ]
    trades = te.simulate(_plan(max_holding_bars=1), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "time_exit"
    assert t.exit_price == pytest.approx(1.00)


def test_one_trade_per_instrument():
    """I5: entry signals while in position are ignored.

    Entry at bar 1. Bar 2 also has entry_long=True (ignored).
    Exit at bar 3 → fill at bar 4.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, entry_long=True),  # ignored
        _bar(3, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(4, 1.01, 1.02, 1.00, 1.01),  # fill
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 1  # only one trade


def test_end_of_data_force_close():
    """T8: still in position at last bar → force close at close.

    Entry at bar 1 open=1.00. No exit signal.
    Last bar (bar 2): close=1.02 → end_of_data fill at 1.02.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.02, 0.99, 1.02),  # close=1.02
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "end_of_data"
    assert t.exit_price == pytest.approx(1.02)


def test_cost_commission_flat():
    """Cost model: commission is flat per trade (bps / 10000).

    commission_bps_round_trip=10 → 0.1% cost.
    Entry=1.00, exit=1.01 → gross=1%, net=1%-0.1%=0.9%.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(3, 1.01, 1.02, 1.00, 1.01),  # exit at 1.01
    ]
    trades = te.simulate(_plan(commission_bps_round_trip=10), bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.gross_return == pytest.approx(0.01)
    assert t.cost_return == pytest.approx(0.001)  # 10bps
    assert t.net_return == pytest.approx(0.009)


def test_cost_financing_proportional():
    """Cost model: financing is proportional to days held.

    financing_bps_per_day=10 → 0.1%/day.
    Entry bar 1 (T0+1h), exit bar 4 (T0+4h) → 3h = 3/24 days.
    financing = 0.001 * 0.125 = 0.000125.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),  # entry at T0+1h
        _bar(2, 1.00, 1.01, 0.99, 1.00),
        _bar(3, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(4, 1.01, 1.02, 1.00, 1.01),  # exit at T0+4h
    ]
    trades = te.simulate(_plan(financing_bps_per_day=10), bars)
    assert len(trades) == 1
    t = trades[0]
    days = 3 / 24  # 3 hours
    assert t.cost_return == pytest.approx(0.001 * days)


def test_cost_financing_trading_days_override():
    """H1 (review 批次3): R4/O15 financing must be charged in *trading*
    days. The engine cannot derive a trading calendar from sparse bars
    (a Fri→Fri gap is indistinguishable from an overnight gap), so the
    caller (the 0006 runner, which owns the bar series + calendar) passes
    the trading-day count via ``trading_days``.

    Fri 2026-10-30 → Fri 2026-11-06 is **7 natural days** but **5 trading
    days** (weekend + no market holiday excluded). With
    financing_bps_per_day=100 (1%/day): natural basis = 0.07, R4/O15
    trading basis = 0.05. The override must win.
    """
    entry = dt.datetime(2026, 10, 30, 0, 0, tzinfo=dt.timezone.utc)
    exit_ = entry + dt.timedelta(days=7)
    bars = [
        {"instrument": "X", "time": entry, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": True, "entry_short": False,
         "exit_long": False, "exit_short": False},
        {"instrument": "X", "time": entry + dt.timedelta(hours=1), "mid_o": 1.0,
         "mid_h": 1.0, "mid_l": 0.99, "mid_c": 1.0, "entry_long": False,
         "entry_short": False, "exit_long": False, "exit_short": False},
        {"instrument": "X", "time": exit_, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": False, "entry_short": False,
         "exit_long": True, "exit_short": False},
        {"instrument": "X", "time": exit_ + dt.timedelta(hours=1), "mid_o": 1.0,
         "mid_h": 1.0, "mid_l": 0.99, "mid_c": 1.0, "entry_long": False,
         "entry_short": False, "exit_long": False, "exit_short": False},
    ]
    plan = _plan(financing_bps_per_day=100)
    # natural-day default (nova-compatible basis) = 7 * 1% = 0.07
    natural = te.simulate(plan, bars)[0]
    assert natural.cost_return == pytest.approx(0.07)
    # R4/O15 trading-day basis via a per-trade counter = 5 * 1% = 0.05
    trading = te.simulate(plan, bars,
                          trading_days_for=lambda e, x: 5.0)[0]
    assert trading.cost_return == pytest.approx(0.05)


def test_cost_financing_trading_days_per_trade():
    """C2 (batch-4 review): the trading-day count must be applied **per
    trade**, not as one flat scalar shared by every trade in a
    ``simulate()`` call.

    Two trades in the same series: A held 1 day, B held 10 days.  A
    flat scalar (the old design) would charge both the same day count.  A
    per-trade counter charges A→1, B→10 — verified here with a counter that
    derives days from each trade's own interval.
    """
    base = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    D = dt.timedelta(days=1)
    # A signal at bar 0 → fills at bar 1's open (t1); A exit signal at bar 1
    # → fills at bar 2's open (t2).  Held t1→t2 = 1 day.
    # B signal at bar 3 → fills at bar 4's open (t4); B exit signal at bar 13
    # → fills at bar 14's open (t14).  Held t4→t14 = 10 days.
    # (bar 2 is A's exit-fill bar — no re-entry allowed on that bar.)
    def _mk(i, o=1.0):
        return {"instrument": "X", "time": base + i * D, "mid_o": o,
                "mid_h": o + .01, "mid_l": o - .01, "mid_c": o,
                "entry_long": False, "entry_short": False,
                "exit_long": False, "exit_short": False}
    bars = []
    for i in range(15):
        b = _mk(i)
        if i == 0:
            b["entry_long"] = True          # A signal → enters at bar 1 (t1)
        if i == 1:
            b["exit_long"] = True           # A exit → fills bar 2 (t2); 1 day
        if i == 3:
            b["entry_long"] = True          # B signal → enters at bar 4 (t4)
        if i == 13:
            b["exit_long"] = True           # B exit → fills bar 14 (t14); 10 days
        bars.append(b)
    # A per-trade counter: count the natural days of each trade's interval.
    def days(e, x):
        return (x - e).total_seconds() / 86400
    trades = te.simulate(_plan(financing_bps_per_day=100), bars,
                         trading_days_for=days)
    assert len(trades) == 2
    a, b = trades[0], trades[1]
    # A held 1 day → 1% = 0.01; B held 10 days → 10% = 0.10.
    assert a.cost_return == pytest.approx(0.01)
    assert b.cost_return == pytest.approx(0.10)
    # Sanity: the two trades carry *different* financing — impossible with a
    # single flat scalar, the whole point of the C2 fix.
    assert a.cost_return != b.cost_return


def test_cost_financing_fail_closed_mixed_tz():
    """M2 (review 批次3): a naive ``time`` on one side and an aware one on
    the other makes the day subtraction raise TypeError. The engine must
    FAIL CLOSED (raise) rather than silently charging zero financing.
    """
    naive_entry = dt.datetime(2020, 3, 9, 3, 0)  # NO tzinfo
    aware_exit = dt.datetime(2020, 3, 9, 6, 0, tzinfo=dt.timezone.utc)
    bars = [
        {"instrument": "X", "time": naive_entry, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": True, "entry_short": False,
         "exit_long": False, "exit_short": False},
        {"instrument": "X", "time": naive_entry + dt.timedelta(hours=1),
         "mid_o": 1.0, "mid_h": 1.0, "mid_l": 0.99, "mid_c": 1.0,
         "entry_long": False, "entry_short": False, "exit_long": False,
         "exit_short": False},
        {"instrument": "X", "time": aware_exit, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": False, "entry_short": False,
         "exit_long": True, "exit_short": False},
        {"instrument": "X", "time": aware_exit + dt.timedelta(hours=1),
         "mid_o": 1.0, "mid_h": 1.0, "mid_l": 0.99, "mid_c": 1.0,
         "entry_long": False, "entry_short": False, "exit_long": False,
         "exit_short": False},
    ]
    with pytest.raises(ValueError):
        te.simulate(_plan(financing_bps_per_day=100), bars)


def test_cost_financing_rejects_bad_override():
    """M2 (review 批次3) / C2 (批次4): the per-trade trading-day counter must
    return a usable non-negative finite number — NaN / inf / negative /
    non-numeric all raise, never silently drop financing."""
    entry = T0
    bars = [
        {"instrument": "X", "time": entry, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": True, "entry_short": False,
         "exit_long": False, "exit_short": False},
        {"instrument": "X", "time": entry + H1, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": False, "entry_short": False,
         "exit_long": True, "exit_short": False},
        {"instrument": "X", "time": entry + 2 * H1, "mid_o": 1.0, "mid_h": 1.0,
         "mid_l": 0.99, "mid_c": 1.0, "entry_long": False, "entry_short": False,
         "exit_long": False, "exit_short": False},
    ]
    plan = _plan(financing_bps_per_day=100)
    # C2: the per-trade counter must return a usable finite number >= 0.
    # NaN / inf / negative / non-numeric (raises on float()) all raise —
    # never silently drop financing.
    for bad in (float("nan"), float("inf"), -1, "three"):
        def _counter(e, x, _bad=bad):
            return _bad
        with pytest.raises(ValueError):
            te.simulate(plan, bars, trading_days_for=_counter)


def test_long_short_symmetry():
    """I2/T1-T2: same OHLC, long and short should be symmetric.

    Long: entry at open=1.00, exit at open=1.01 → +1%.
    Short: entry at open=1.00, exit at open=0.99 → +1%.
    """
    long_bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(3, 1.01, 1.02, 1.00, 1.01),
    ]
    short_bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_short=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_short=True),
        _bar(3, 0.99, 1.00, 0.98, 0.99),
    ]
    lt = te.simulate(_plan(), long_bars)[0]
    st = te.simulate(_plan(), short_bars)[0]
    assert lt.direction == 1 and st.direction == -1
    assert lt.gross_return == pytest.approx(st.gross_return)  # both +1%


def test_deterministic():
    """Same input → same output (multiple runs)."""
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.97, 1.00),  # stop hit
    ]
    p = _plan()
    t1 = te.simulate(p, bars)
    t2 = te.simulate(p, bars)
    assert t1 == t2


def test_ambiguous_entry_no_trade():
    """entry_long AND entry_short both True → no entry (nova rule)."""
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True, entry_short=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
    ]
    trades = te.simulate(_plan(), bars)
    assert trades == []


def test_slippage_in_entry_price():
    """T1: slippage affects entry price (long pays more).

    slippage_bps_per_side=10 → 0.1%.
    Entry at open=1.00 → fill at 1.00 * 1.001 = 1.001.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(3, 1.01, 1.02, 1.00, 1.01),
    ]
    trades = te.simulate(_plan(slippage_bps_per_side=10), bars)
    t = trades[0]
    assert t.entry_price == pytest.approx(1.00 * 1.001)


def test_spread_in_entry_price():
    """T1: spread affects entry price via quote().

    spread_bps=10 → quote(1.00, -1, 10) = 1.00 * (1 + 10/20000) = 1.0005.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(3, 1.01, 1.02, 1.00, 1.01),
    ]
    trades = te.simulate(_plan(spread_bps=10), bars)
    t = trades[0]
    # long entry: quote(bar, -1, "mid_o", 10) = 1.00 * (1 - (-1)*10/20000)
    # = 1.00 * 1.0005 = 1.0005
    assert t.entry_price == pytest.approx(1.0005)


def test_b4_m2_real_bid_ask_columns_used():
    """M2 (batch-4 review): ``_quote`` must read the *real* bronze/silver
    columns ``bid_o``/``ask_o`` (``clean.py``/``oanda.py``), not the ghost
    ``bid_mid_o``/``ask_mid_o`` the old string-concatenation produced.

    A bar carrying both ``mid_o`` and a true bid/ask quote must fill at the
    real quote — not at ``mid`` with a synthetic spread on top.
    """
    bar = {"mid_o": 1.0, "bid_o": 0.9990, "ask_o": 1.0010}
    # long wants the bid; short wants the ask.  Both must now be found.
    assert te._quote(bar, 1, "mid_o", 0.0) == pytest.approx(0.9990)
    assert te._quote(bar, -1, "mid_o", 0.0) == pytest.approx(1.0010)
    # Without a real quote the mid fallback still applies the spread.
    mid_only = {"mid_o": 1.0}
    assert te._quote(mid_only, 1, "mid_o", 10.0) == pytest.approx(
        1.0 * (1 - 10.0 / 20000))


def test_b4_m2_real_bid_ask_drives_fill_price():
    """M2 (batch-4 review): a bar with a real bid/ask must change the entry
    fill price to the real quote, proving the ghost-column path is gone."""
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(3, 1.01, 1.02, 1.00, 1.01),
    ]
    # Inject a real bid_o/ask_o into the entry-fill bar (bar 1's open).
    bars[1]["bid_o"] = 0.9990
    bars[1]["ask_o"] = 1.0010
    trades = te.simulate(_plan(spread_bps=0.0), bars)
    # Long *entry* is a BUY → fills at the real ask_o (1.0010), not mid (1.0).
    # (The ghost-column bug forced the mid fallback, giving exactly 1.0.)
    assert trades[0].entry_price == pytest.approx(1.0010)


def test_b4_m1_end_of_data_exit_timestamp_is_bar_close():
    """m1 (batch-4 review): an end-of-data force close fills at the last
    bar's *close* price, so its exit timestamp must be the bar *close* time
    (bar open + one bar interval), not the bar open.  Otherwise a trade
    entered at the last bar's open and closed at its close accrues 0 days of
    financing despite holding a full bar.
    """
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    H = dt.timedelta(hours=1)
    b0 = {"instrument": "X", "time": base, "mid_o": 1.0, "mid_h": 1.0,
          "mid_l": 0.99, "mid_c": 1.0, "entry_long": True,
          "entry_short": False, "exit_long": False, "exit_short": False}
    b1 = {"instrument": "X", "time": base + H, "mid_o": 1.0, "mid_h": 1.0,
          "mid_l": 0.99, "mid_c": 1.0, "entry_long": False,
          "entry_short": False, "exit_long": False, "exit_short": False}
    # Signal at bar 0 → entry at bar 1's open (base+1h).  Bar 1 is the last
    # bar, so the position is force-closed by end-of-data at bar 1's close
    # (base+2h, given timeframe_minutes=60).
    trades = te.simulate(_plan(timeframe_minutes=60,
                               financing_bps_per_day=100), [b0, b1])
    assert len(trades) == 1
    t = trades[0]
    # entry at base+1h; exit at bar 1's close = base+2h → 1h = 1/24 day.
    # financing = 100bps (0.01/day) * (1/24 day) = 0.01 * 1/24.
    assert t.exit_reason == "end_of_data"
    assert t.exit_time == base + 2 * H
    assert t.cost_return == pytest.approx(0.01 * (1 / 24))


def test_b4_m2_simulate_rejects_mixed_instruments():
    """m2 (batch-4 review): ``simulate`` must simulate ONE instrument at a
    time (0005 I1, one trade per instrument).  A mixed-instrument sequence
    would silently interleave two instruments' signals into one position;
    the engine must fail closed instead."""
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00),
    ]
    bars[2]["instrument"] = "OTHER_INST"  # mixed instrument
    with pytest.raises(ValueError, match="single instrument"):
        te.simulate(_plan(), bars)


def test_bars_held_counting():
    """bars_held = number of bars managed (each bar increments before the
    exit fill is resolved).

    Entry bar 1 (bars→1). Bar 2 (bars→2, exit signal set). Bar 3 (exit at
    open; bars stays 2).
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),
        _bar(3, 1.01, 1.02, 1.00, 1.01),
    ]
    trades = te.simulate(_plan(), bars)
    t = trades[0]
    assert t.bars_held == 2


def test_stop_price_and_take_profit_price_fields():
    """Trade.stop_price and Trade.take_profit_price are computed correctly."""
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.97, 1.00),  # stop hit
    ]
    trades = te.simulate(_plan(take_profit_pct=0.03), bars)
    t = trades[0]
    assert t.entry_price == pytest.approx(1.00)
    assert t.stop_price == pytest.approx(0.98)  # 1.00 * 0.98
    assert t.take_profit_price == pytest.approx(1.03)  # 1.00 * 1.03


def test_short_stop_loss():
    """Short: stop is above entry (adverse = price up).

    Short entry at 1.00. Stop = 1.00 * 1.02 = 1.02.
    Bar 2: high=1.03 > stop → stop_loss at 1.02.
    Loss = (1.02 - 1.00) / 1.00 * -1 = -2%.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_short=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.03, 0.99, 1.01),  # high=1.03 > stop=1.02
    ]
    trades = te.simulate(_plan(), bars)
    t = trades[0]
    assert t.direction == -1
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(1.02)
    assert t.gross_return == pytest.approx(-0.02)


def test_short_take_profit():
    """Short: target is below entry (profit = price down).

    Short entry at 1.00. Target = 1.00 * 0.97 = 0.97 (tp=3%).
    Bar 2: low=0.96 < target → take_profit at 0.97.
    Gain = (0.97 - 1.00) / 1.00 * -1 = +3%.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_short=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.96, 0.98),  # low=0.96 < target=0.97
    ]
    trades = te.simulate(_plan(take_profit_pct=0.03), bars)
    t = trades[0]
    assert t.direction == -1
    assert t.exit_reason == "take_profit"
    assert t.exit_price == pytest.approx(0.97)
    assert t.gross_return == pytest.approx(0.03)


def test_multiple_trades_sequence():
    """Two consecutive trades (flat between them).

    Trade 1: entry bar 1, stop at bar 2.
    Trade 2: entry signal bar 2 (ignored, in position),
             entry signal bar 3 (flat, pending), fill bar 4,
             indicator exit bar 5, fill bar 6.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),  # entry 1
        _bar(2, 1.00, 1.01, 0.97, 1.00),  # stop 1 + entry signal (ignored)
        _bar(3, 1.00, 1.01, 0.99, 1.00, entry_long=True),  # entry 2 signal
        _bar(4, 1.00, 1.01, 0.99, 1.00),  # entry 2 fill
        _bar(5, 1.00, 1.01, 0.99, 1.00, exit_long=True),  # exit 2 signal
        _bar(6, 1.01, 1.02, 1.00, 1.01),  # exit 2 fill
    ]
    trades = te.simulate(_plan(), bars)
    assert len(trades) == 2
    assert trades[0].exit_reason == "stop_loss"
    assert trades[1].exit_reason == "indicator_exit"


def test_pending_exit_beats_inside_stop_same_bar():
    """Adversarial P5: pending indicator_exit (open-layer fill) has HIGHER
    priority than an inside-bar stop on the fill bar — matches nova order
    (stop_at_open → target_at_open → pending_exit → stop_inside/target_inside).

    Entry bar 1. Bar 2: exit_long signal → pending. Bar 3: low=0.97 (inside
    stop hit) — but pending_exit fills at open=1.00 FIRST (indicator_exit).
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),  # pending
        _bar(3, 1.00, 1.01, 0.97, 1.00),  # inside stop, but pending wins
    ]
    trades = te.simulate(_plan(), bars)
    t = trades[0]
    assert t.exit_reason == "indicator_exit"  # NOT stop_loss
    assert t.exit_price == pytest.approx(1.00)


def test_pending_exit_loses_to_stop_gap():
    """Adversarial P5b: a stop-gap at the open still beats a pending exit
    (the gap is the actual open price — worse than the stop, must be filled).

    Entry bar 1. Bar 2: exit_long → pending. Bar 3: open=0.95 (< stop 0.98)
    → stop_gap at open, not indicator_exit.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),  # pending
        _bar(3, 0.95, 0.96, 0.94, 0.95),  # open gaps through stop
    ]
    trades = te.simulate(_plan(), bars)
    t = trades[0]
    assert t.exit_reason == "stop_gap"  # NOT indicator_exit
    assert t.exit_price == pytest.approx(0.95)


def test_pending_exit_loses_to_target_at_open():
    """Adversarial P6: an open beyond the target beats a pending exit
    (target_at_open is checked before pending_exit in nova's order).

    Entry bar 1 (tp=2%, target=1.02). Bar 2: exit_long → pending.
    Bar 3: open=1.03 (> target) → take_profit at 1.02 (limit semantics).
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_long=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),  # pending
        _bar(3, 1.03, 1.04, 1.02, 1.03),  # open beyond target
    ]
    trades = te.simulate(_plan(take_profit_pct=0.02), bars)
    t = trades[0]
    assert t.exit_reason == "take_profit"  # NOT indicator_exit
    assert t.exit_price == pytest.approx(1.02)  # limit fill, not open


def test_exit_long_does_not_close_short():
    """Adversarial P9: exit signals are direction-specific. An exit_long
    signal must NOT close a short position (nova reads exit_{direction}).

    Short entry bar 1. Bar 2: exit_long=True (ignored). Bar 3: exit_short=True
    → pending. Bar 4: indicator_exit fill.
    """
    bars = [
        _bar(0, 1.00, 1.01, 0.99, 1.00, entry_short=True),
        _bar(1, 1.00, 1.01, 0.99, 1.00),
        _bar(2, 1.00, 1.01, 0.99, 1.00, exit_long=True),  # ignored for short
        _bar(3, 1.00, 1.01, 0.99, 1.00, exit_short=True),  # the real signal
        _bar(4, 1.00, 1.01, 0.99, 1.00),  # fill at open
    ]
    trades = te.simulate(_plan(), bars)
    t = trades[0]
    assert t.direction == -1
    assert t.exit_reason == "indicator_exit"
    assert t.exit_time == T0 + 4 * H1  # closed at bar 4, not bar 2/3


def test_empty_bars_no_trades():
    """No bars → no trades (no crash)."""
    assert te.simulate(_plan(), []) == []


def test_no_signals_no_trades():
    """Bars but no entry signals → no trades."""
    bars = [_bar(i, 1.00, 1.01, 0.99, 1.00) for i in range(5)]
    assert te.simulate(_plan(), bars) == []
