"""0006 metric-function tests (R5 / I15) — pure, no data fixture needed.

The metric functions read each trade's ``net_return`` + ``bars_held``
(0005 ``Trade``); a minimal duck-typed object suffices, keeping these tests
independent of the trade engine and the data pipeline.

R5 freezes the set: per-trade net, annualized score, win_rate, mean, avg bars
held, and per-month rows (actual openings / net sum / win_rate / avg bars).
R5 **forbids** CAGR / HWM / Sharpe / Sortino — there is no sharpe here.
"""

from __future__ import annotations

import datetime as dt

from lyra import metrics as M


class T:
    """Minimal duck-typed trade exposing the fields the metrics read."""

    def __init__(self, net: float, bars: int = 1, entry_time=None):
        self.net_return = net
        self.bars_held = bars
        self.entry_time = entry_time


def _span(days: float):
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=days)
    return start, end


def test_metrics_annualized_calendar_years():
    # 2 trades summing +0.10 net over a 365.25-day window -> 0.10/yr.
    trades = [T(0.06), T(0.04)]
    s, e = _span(365.25)
    assert M.annualized_return(trades, s, e) == 0.10
    # span 0 -> None (no division by zero); no trades -> None
    assert M.annualized_return(trades, s, s) is None
    assert M.annualized_return([], s, e) is None


def test_metrics_win_rate_zero_trades():
    assert M.win_rate([]) == 0.0
    assert M.win_rate([T(0.05)]) == 1.0
    assert M.win_rate([T(-0.02), T(0.03)]) == 0.5


def test_metrics_expectancy_matches_mean():
    trades = [T(0.06), T(-0.02)]
    assert M.expectancy(trades) == (0.06 - 0.02) / 2
    assert M.expectancy([]) == 0.0


def test_metrics_avg_bars_held():
    assert M.avg_bars_held([]) == 0.0
    assert M.avg_bars_held([T(0.05, 3), T(0.02, 5)]) == 4.0


def test_metrics_single_trade():
    t = [T(-0.03, 2)]
    assert M.win_rate(t) == 0.0
    assert M.expectancy(t) == -0.03
    assert M.avg_bars_held(t) == 2


def test_metrics_all_loss():
    trades = [T(-0.02), T(-0.04)]
    assert M.win_rate(trades) == 0.0
    s, e = _span(365.25)
    assert M.annualized_return(trades, s, e) < 0.0


def test_metrics_deterministic_and_score_equals_annualized():
    trades = [T(0.06), T(-0.02), T(0.01)]
    s, e = _span(365.25)
    a = M.compute_metrics(trades, s, e)
    b = M.compute_metrics(trades, s, e)
    assert a == b
    assert a["annualized"] == a["score"]           # R5: score == annualized


def test_metrics_monthly_rows_zero_open_months_kept():
    """I8: every calendar month in the window appears; zero-open kept as 0."""
    # 3 trades, all in Jan 2024; window spans Jan + Feb -> Feb kept as 0.
    jan1 = dt.datetime(2024, 1, 2, tzinfo=dt.timezone.utc)
    jan2 = dt.datetime(2024, 1, 15, tzinfo=dt.timezone.utc)
    feb1 = dt.datetime(2024, 2, 3, tzinfo=dt.timezone.utc)
    trades = [T(0.06), T(-0.02), T(0.01)]
    for t, entry in zip(trades, (jan1, jan2, jan2)):
        object.__setattr__(t, "_e", entry) if False else None
    # compute_metrics uses entry_time for month bucketing; give real entries.
    class E(T):
        pass
    e_trades = [
        E.__new__(E), E.__new__(E), E.__new__(E),
    ]
    for t, entry in zip(e_trades, (jan1, jan2, feb1)):
        t.net_return = 0.01
        t.bars_held = 1
        t.entry_time = entry
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(2024, 2, 28, tzinfo=dt.timezone.utc)
    out = M.compute_metrics(e_trades, start, end)
    months = {r["month"]: r for r in out["monthly"]}
    assert set(months) == {"2024-01", "2024-02"}
    assert months["2024-01"]["actual_entries"] == 2
    assert months["2024-02"]["actual_entries"] == 1


def test_metrics_forbidden_fields_absent():
    """R5 forbids CAGR/HWM/Sharpe/Sortino — none may appear as computed fields."""
    trades = [T(0.06), T(-0.02)]
    out = M.compute_metrics(trades, *_span(365.25))
    for banned in ("sharpe_ratio", "sharpe", "sortino", "hwm", "cagr",
                   "profit_factor"):
        assert banned not in out
