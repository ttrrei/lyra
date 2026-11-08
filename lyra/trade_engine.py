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

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .compiler import CompiledPlan


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
    """
    name = ("bid_" if direction == 1 else "ask_") + point
    if bar.get(name) is not None:
        return float(bar[name])
    base = float(bar[point])
    if spread_bps:
        return base * (1 - direction * spread_bps / 20000)
    return base


def simulate(
    plan: CompiledPlan,
    bars: Sequence[Mapping[str, Any]],
) -> list[Trade]:
    """Simulate one instrument, one trade at a time (0005 §4 I2-I5, T1-T8).

    ``bars`` must be a time-ordered sequence of dicts, each containing at
    minimum: ``instrument``, ``time``, ``mid_o``, ``mid_h``, ``mid_l``,
    ``mid_c`` (the 4 OHLC points), plus the 4 signal columns
    ``entry_long``, ``entry_short``, ``exit_long``, ``exit_short``
    (booleans).

    Cost model (nova ``trades.py`` field-for-field):
    * slippage is folded into entry/exit *price* (T1/T2), NOT into costs
    * costs = commission_bps_round_trip/10000 + financing_bps_per_day/10000 * days
    """
    stop_pct = plan.stop_loss_pct or 0.02
    tp_pct = plan.take_profit_pct
    mhb = plan.max_holding_bars
    slip = (plan.slippage_bps_per_side or 0) / 10000
    spread = plan.spread_bps
    comm = plan.commission_bps_round_trip or 0.0
    financ = plan.financing_bps_per_day or 0.0

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
        # financing by days (nova trades.py:finish)
        try:
            days = (timestamp - position["time"]).total_seconds() / 86400
        except (AttributeError, TypeError):
            days = 0.0
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
        _finish(last, raw_close, "end_of_data", last["time"], "bar_close")

    return result
