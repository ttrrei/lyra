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


def test_empty_bars_no_trades():
    """No bars → no trades (no crash)."""
    assert te.simulate(_plan(), []) == []


def test_no_signals_no_trades():
    """Bars but no entry signals → no trades."""
    bars = [_bar(i, 1.00, 1.01, 0.99, 1.00) for i in range(5)]
    assert te.simulate(_plan(), bars) == []
