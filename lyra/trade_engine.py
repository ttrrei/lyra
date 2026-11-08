"""Trade engine — turns signal + OHLC into trade-level records (decision 0005).

Pure function: same input → same output.  No I/O, no global state.

Semantics are field-for-field identical to nova ``src/nova/trades.py``
(hld I1-I7 invariants, T1-T8 local invariants).  Moneta uses the same
fill/stop/cost rules; the only difference is that moneta's engine
operates on NumPy arrays while lyra operates on row-dicts (DuckDB output).

Does NOT:
* compute metrics / monthly / report (0006 runner)
* size positions / track equity (hld §5 "trade-level research only")
* scan parameters (I8)
* run OOS gates (hld §5 "无")
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .compiler import CompiledPlan

#: A **trading-day counter** (0005 R4/O15; 0004 C2, batch-4 review).
#: Maps one trade's held interval ``(entry_time, exit_time)`` → the number of
#: trading days held.  The caller (0006 runner) owns the market calendar and
#: the bar series, so it can count trading days per trade — something the
#: engine cannot derive on its own (a Fri→Fri gap is indistinguishable from
#: an overnight gap when bars are sparse).  ``None`` (the default) falls back
#: to *natural* elapsed days, the nova-compatible basis.
TradingDaysCounter = Callable[[Any, Any], float]


@dataclass(frozen=True)
class Trade:
    """One filled round-trip (entry + exit)."""
    instrument: str
    direction: int               # +1 long, -1 short
    signal_time: Any             # bar close time that produced the signal
    entry_time: Any              # bar open time of the fill
    exit_time: Any               # bar open/close time of the exit fill
    entry_price: float           # after spread + slippage (T1)
    exit_price: float            # after spread + slippage (T2)
    exit_reason: str             # stop_gap | stop_loss | take_profit |
                                 # indicator_exit | time_exit | end_of_data
    bars_held: int               # bars in position
    gross_return: float          # direction * (exit - entry) / entry
    cost_return: float           # commission + financing (positive = cost)
    net_return: float            # gross - costs
    stop_price: float            # entry * (1 - side * stop_loss_pct)
    take_profit_price: float | None  # entry * (1 + side * tp_pct), None if unset


def _day_count(entry_time: Any, exit_time: Any,
               counter: TradingDaysCounter | None) -> float:
    """Financing day count for the held interval (R4/O15; 0005 O-0005-1).

    0004 C2 (batch-4 review): the caller supplies a **per-trade** trading-day
    counter (``counter(entry_time, exit_time) -> float``) instead of a single
    flat scalar shared by every trade.  A flat scalar (the old
    ``trading_days: float``) mischarged every trade — a 1-day hold and a
    3-week hold were both charged the same day count, which is why R4/O15
    trading-day financing was unusable in any multi-trade backtest.  The
    counter is evaluated lazily per trade, exactly when the engine knows the
    held interval, so the caller no longer has to predict entry/exit bars in
    advance.

    * ``counter`` provided — its result is validated (finite, >= 0) and used
      as this trade's trading-day count.
    * ``counter is None`` (default) — derive *natural* days from the bar
      ``time`` stamps (the nova-compatible basis; kept so the
      field-for-field cross-check against ``nova.trades.simulate`` stays exact).

    Fail-closed: if the counter returns a non-finite / negative number, or
    the timestamps are missing / not subtractable datetimes (and no counter
    was supplied), raise rather than silently charging zero financing.
    """
    if counter is not None:
        days = float(counter(entry_time, exit_time))
        if not math.isfinite(days) or days < 0:
            raise ValueError(
                f"trading-days counter returned a bad value for "
                f"({entry_time!r} → {exit_time!r}): {days!r} "
                "(must be a finite number >= 0)"
            )
        return days
    if not isinstance(entry_time, dt.datetime) or not isinstance(exit_time, dt.datetime):
        raise ValueError(
            f"cannot compute financing days: entry_time={entry_time!r}, "
            f"exit_time={exit_time!r} are not datetimes (and no trading-days "
            "counter was supplied)"
        )
    try:
        return (exit_time - entry_time).total_seconds() / 86400
    except (AttributeError, TypeError) as exc:
        raise ValueError(
            f"cannot compute financing days: {entry_time!r} and {exit_time!r} "
            "are not comparable datetimes (mixed naive/aware, or wrong types)"
        ) from exc


def _quote(
    bar: Mapping[str, Any],
    direction: int,
    point: str,
    spread_bps: float | None,
) -> float:
    """Resolve a price point with spread — field-for-field identical to
    nova ``trades.py:quote``.

    Nova looks for ``bid_{point}`` (long) or ``ask_{point}`` (short) first;
    if present, returns it (already spread-inclusive).  If absent (the
    lyra/moneta case — mid prices, no bid/ask split), falls back to
    ``mid * (1 - direction * spread_bps / 20000)``.

    0004 M2 (batch-4 review): the real bronze/silver columns are
    ``bid_o``/``ask_o`` (``clean.py``/``oanda.py``), not ``bid_mid_o``.  The
    point passed in here carries the ``mid_`` prefix (``mid_o`` …), so we
    strip it before building the side-specific column name — otherwise the
    real bid/ask quote is never found and the synthetic spread is silently
    applied even when true quotes are present.
    """
    suffix = point[4:] if point.startswith("mid_") else point
    name = ("bid_" if direction == 1 else "ask_") + suffix
    if bar.get(name) is not None:
        return float(bar[name])
    base = float(bar[point])
    if spread_bps:
        return base * (1 - direction * spread_bps / 20000)
    return base


def simulate(
    plan: CompiledPlan,
    bars: Sequence[Mapping[str, Any]],
    *,
    trading_days_for: TradingDaysCounter | None = None,
) -> list[Trade]:
    """Simulate one instrument, one trade at a time (0005 §4 I2-I5, T1-T8).

    ``bars`` must be a time-ordered sequence of dicts, each containing at
    minimum: ``instrument``, ``time``, ``mid_o``, ``mid_h``, ``mid_l``,
    ``mid_c`` (the 4 OHLC points), plus the 4 signal columns
    ``entry_long``, ``entry_short``, ``exit_long``, ``exit_short``
    (booleans).

    ``trading_days_for`` (0005 O-0005-1 / R4 / O15; 0004 C2, batch-4 review)
    is a **per-trade trading-day counter** ``counter(entry_time, exit_time)
    -> float``, supplied by the caller (the 0006 runner owns the market
    calendar + bar series):

    * ``None`` (default) — the engine derives each trade's financing day
      count from the ``time`` stamps as *natural* elapsed days (``(exit -
      entry).total_seconds() / 86400``), the nova-compatible basis, kept so
      the field-for-field cross-check against ``nova.trades.simulate`` stays
      exact.
    * a **callable** — applies the R4/O15 rule (count *trading* days,
      excluding weekends/holidays) **per trade**, evaluated lazily once the
      engine knows each trade's held interval. This replaces the old flat
      ``trading_days: float`` scalar, which mischarged every trade the same
      day count (a 1-day hold and a 3-week hold both charged identically)
      and therefore made R4/O15 financing unusable in multi-trade backtests.

    The per-trade day count must be a finite number; it must not be
    ``bars_held`` (that is a bar count, not a day count — 0005 O-0005-1 /
    review M1).

    Cost model (nova ``trades.py`` field-for-field):
    * slippage is folded into entry/exit *price* (T1/T2), NOT into costs
    * costs = commission_bps_round_trip/10000 + financing_bps_per_day/10000 * days

    The day computation is **fail-closed** (0005 review M2): if ``time``
    values are missing or not subtractable datetimes, the engine raises
    instead of silently charging zero financing.
    """
    stop_pct = plan.stop_loss_pct or 0.02
    tp_pct = plan.take_profit_pct
    mhb = plan.max_holding_bars
    slip = (plan.slippage_bps_per_side or 0) / 10000
    spread = plan.spread_bps
    comm = plan.commission_bps_round_trip or 0.0
    financ = plan.financing_bps_per_day or 0.0

    # 0004 m2 (batch-4 review): the engine simulates ONE instrument at a time
    # (0005 I1 "one trade per instrument").  Guard against a caller passing a
    # mixed-instrument sequence, which would silently interleave two
    # instruments' signals into a single position — fail closed instead.
    first_inst = None
    for _b in bars:
        _inst = _b.get("instrument")
        if _inst is None:
            continue
        if first_inst is None:
            first_inst = _inst
        elif _inst != first_inst:
            raise ValueError(
                f"simulate() must be called with a single instrument's bars; "
                f"got instruments {first_inst!r} and {_inst!r}. Simulate each "
                "instrument separately (0005 I1, one trade per instrument)."
            )

    position: dict | None = None
    pending_entry: tuple[int, Any] | None = None
    pending_exit: str | None = None
    result: list[Trade] = []

    def _finish(
        bar: Mapping, raw_price: float, reason: str,
        timestamp: Any, precision: str,
    ) -> None:
        nonlocal position
        if position is None:
            return
        side = position["direction"]
        # T2: exit fill price = raw * (1 - side * slip)
        price = raw_price * (1 - side * slip)
        entry_px = position["price"]
        gross = side * (price - entry_px) / entry_px
        # financing by days (nova trades.py:finish; R4/O15 trading-day basis
        # via the per-trade trading_days_for counter, see simulate())
        days = _day_count(position["time"], timestamp, trading_days_for)
        costs = comm / 10000 + financ / 10000 * max(days, 0)
        result.append(Trade(
            instrument=bar["instrument"],
            direction=side,
            signal_time=position["signal_time"],
            entry_time=position["time"],
            exit_time=timestamp,
            entry_price=entry_px,
            exit_price=price,
            exit_reason=reason,
            bars_held=position["bars"],
            gross_return=gross,
            cost_return=costs,
            net_return=gross - costs,
            stop_price=entry_px * (1 - side * stop_pct),
            take_profit_price=(
                entry_px * (1 + side * tp_pct) if tp_pct else None
            ),
        ))
        position = None

    for bar in bars:
        exited = False
        # --- fill a pending entry at this bar's open (I2, T1) --------------
        if pending_entry is not None and position is None:
            side, sig_time = pending_entry
            raw_open = _quote(bar, -side, "mid_o", spread)
            price = raw_open * (1 + side * slip)
            position = {
                "direction": side,
                "price": price,
                "time": bar["time"],
                "signal_time": sig_time,
                "bars": 0,
            }
        pending_entry = None

        # --- manage open position (T3-T6; stop before target, I4) ----------
        if position is not None:
            side = position["direction"]
            entry = position["price"]
            opening = _quote(bar, side, "mid_o", spread)
            low = _quote(bar, side, "mid_l", spread)
            high = _quote(bar, side, "mid_h", spread)
            stop = entry * (1 - side * stop_pct)
            target = entry * (1 + side * tp_pct) if tp_pct else None

            stop_at_open = opening <= stop if side == 1 else opening >= stop
            target_at_open = target is not None and (
                opening >= target if side == 1 else opening <= target
            )
            stop_inside = low <= stop if side == 1 else high >= stop
            target_inside = target is not None and (
                high >= target if side == 1 else low <= target
            )

            # Nova reference: an opening gap PAST the stop fills at the open
            # (real loss), but an opening beyond the target fills AT the target
            # (limit-order semantics — you never receive a better price).
            if stop_at_open:
                _finish(bar, opening, "stop_gap", bar["time"], "bar_open")
            elif target_at_open:
                _finish(bar, target, "take_profit", bar["time"], "bar_open")
            elif pending_exit:
                _finish(bar, opening, pending_exit, bar["time"], "bar_open")
            else:
                position["bars"] += 1
                if stop_inside:
                    _finish(bar, stop, "stop_loss", bar["time"], "bar_interval")
                elif target_inside:
                    _finish(bar, target, "take_profit", bar["time"], "bar_interval")
            if position is None:
                exited = True

        pending_exit = None

        # --- (re)evaluate signals for the NEXT bar --------------------------
        if position is not None:
            direction = "long" if position["direction"] == 1 else "short"
            if bool(bar.get(f"exit_{direction}")):
                pending_exit = "indicator_exit"
            elif mhb is not None and position["bars"] >= mhb:
                pending_exit = "time_exit"
        elif not exited:
            # flat and did not just exit this bar → allow a new pending entry.
            # Enter only when exactly one side is True (nova: bool != bool).
            long_sig = bool(bar.get("entry_long"))
            short_sig = bool(bar.get("entry_short"))
            if long_sig != short_sig:
                pending_entry = (1 if long_sig else -1, bar["time"])

    # T8: end-of-data force close
    if position is not None and bars:
        last = bars[-1]
        raw_close = _quote(last, position["direction"], "mid_c", spread)
        # 0004 m1 (batch-4 review): the fill is at the bar *close* price
        # (mid_c), so the exit timestamp must be the bar *close* time, not
        # its open (last["time"]).  A trade entered at the last bar's open and
        # force-closed at its close otherwise has entry_time == exit_time and
        # accrues 0 days of financing despite holding a full bar.
        exit_ts = last["time"]
        if getattr(plan, "timeframe_minutes", None):
            try:
                exit_ts = (last["time"]
                           + dt.timedelta(minutes=plan.timeframe_minutes))
            except TypeError:
                exit_ts = last["time"]  # non-subtractable time → keep open
        _finish(last, raw_close, "end_of_data", exit_ts, "bar_close")

    return result
