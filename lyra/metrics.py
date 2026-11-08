"""0006 — R5 metric functions (definitions frozen, I15).

Pure, deterministic, per-instrument metric math.  **No sizing, no $ PnL, no
account equity / CAGR / HWM / Sharpe / Sortino** (I9 / R9; R5 explicitly
forbids Sharpe).  The frozen set matches ``nova/src/nova/metrics.py::summarize``
(authoritative port) extended with R5's per-month rows and avg holding bars:

Per instrument:
- ``trade_count``       = number of net round-trips.
- ``net_return``        = arithmetic sum of per-trade net returns ("净收益和").
- ``annualized``        = net_return / full calendar years (365.25 d/yr) —
                          the "年化分数"; ``None`` when span is 0.
- ``expectancy``        = mean net return (``net_return / trade_count``);
                          ``0.0`` when no trades.
- ``win_rate``          = share of net-profitable trades; ``0.0`` when none.
- ``avg_bars_held``     = mean bars in position; ``0.0`` when none.

Per month (the study window, every calendar month included):
- ``actual_entries``    = actual openings that month (0 kept, not dropped — I8).
- ``net_return_sum``    = net sum of that month's trades (0.0 if none).
- ``win_rate``          = that month's win rate (0.0 if none).
- ``avg_bars_held``     = that month's mean bars held (0.0 if none).

All functions are safe on empty / single / all-loss / all-win / zero-span
inputs (return ``None`` / ``0.0``; never raise).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

# 365.25 calendar days per year (I8 / I15 / R5) — same basis as nova metrics.
DAYS_PER_YEAR = 365.25


def _net(trades: Sequence[Any]) -> list[float]:
    """Extract the net return per trade (0005 ``Trade.net_return``)."""
    return [float(t.net_return) for t in trades]


def _month_key(x: Any) -> str:
    """``YYYY-MM`` UTC calendar month of a bar timestamp."""
    if isinstance(x, datetime):
        return x.strftime("%Y-%m")
    return str(x)[:7]


def _month_range(start: Any, end: Any) -> list[str]:
    """Every calendar month in the study window ``[start, end]`` (inclusive)."""
    if not (isinstance(start, datetime) and isinstance(end, datetime)):
        return []
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return months


def annualized_return(trades: Sequence[Any], start_time: Any,
                      end_time: Any) -> float | None:
    """R5 "年化分数": sum(net) / full calendar years between the window ends.

    ``None`` when there are no trades or the time span is zero (divide-by-zero
    guard).  The span is the *calendar* window, not the sum of holding periods.
    """
    if not trades:
        return None
    if not (isinstance(start_time, datetime) and isinstance(end_time, datetime)):
        return None
    span_days = (end_time - start_time).total_seconds() / 86400.0
    if span_days <= 0:
        return None
    years = span_days / DAYS_PER_YEAR
    return sum(_net(trades)) / years


def win_rate(trades: Sequence[Any]) -> float:
    """R5: share of net-profitable trades; ``0.0`` when there are none."""
    if not trades:
        return 0.0
    wins = sum(1 for x in _net(trades) if x > 0.0)
    return wins / len(trades)


def expectancy(trades: Sequence[Any]) -> float:
    """R5: arithmetic mean of net trade returns; ``0.0`` when none."""
    if not trades:
        return 0.0
    return sum(_net(trades)) / len(trades)


def avg_bars_held(trades: Sequence[Any]) -> float:
    """R5: mean bars in position; ``0.0`` when none."""
    if not trades:
        return 0.0
    return sum(int(t.bars_held) for t in trades) / len(trades)


def _monthly_rows(trades: Sequence[Any], start_time: Any,
                  end_time: Any) -> list[dict[str, Any]]:
    """R5 per-month rows over the study window (I8: zero-open months kept as 0)."""
    months = _month_range(start_time, end_time)
    if not months:
        months = sorted({_month_key(t.entry_time) for t in trades})
    by_month: dict[str, list[Any]] = {}
    for t in trades:
        by_month.setdefault(_month_key(t.entry_time), []).append(t)
    rows: list[dict[str, Any]] = []
    for mo in months:
        subset = by_month.get(mo, [])
        nets = _net(subset)
        rows.append({
            "month": mo,
            "actual_entries": len(subset),
            "net_return_sum": sum(nets),
            "win_rate": (sum(1 for x in nets if x > 0.0) / len(nets)) if nets else 0.0,
            "avg_bars_held": (sum(int(t.bars_held) for t in subset) / len(subset)
                              if subset else 0.0),
        })
    return rows


def compute_metrics(trades: Sequence[Any], start_time: Any,
                    end_time: Any) -> dict[str, Any]:
    """Aggregate the R5 metric set for one instrument (per-instrument, I7).

    Returns a plain dict.  No portfolio synthesis, no CAGR/HWM/Sharpe/Sortino
    (I9/R9/R5).
    """
    nets = _net(trades)
    wins = sum(1 for x in nets if x > 0.0)
    losses = sum(1 for x in nets if x < 0.0)
    ann = annualized_return(trades, start_time, end_time)
    return {
        "trade_count": len(trades),
        "winning_trades": wins,
        "losing_trades": losses,
        "net_return": sum(nets),
        "annualized": ann,
        "score": ann,  # R5: annualized score == annualized (same formula).
        "expectancy": expectancy(trades),
        "win_rate": win_rate(trades),
        "avg_bars_held": avg_bars_held(trades),
        "monthly": _monthly_rows(trades, start_time, end_time),
    }
