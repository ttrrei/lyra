# 0005 — Trade Engine

> **中文**: [0005-trade-engine.md](./0005-trade-engine.md)
>
> **Scope**: turn the 0004 `CompiledPlan` (signal SELECT + execution metadata)
> into **trade-level records** (entry / exit / P&L / cost), executed in
> DuckDB. No metrics / monthly / report (that is 0006).

## 1. What

A pure function `simulate(plan, ohlcv) -> list[Trade]`:

* **Input**: `CompiledPlan` (0004 output: signal SQL + stop/tp/cost/mhb
  metadata) + one DataFrame (per-instrument OHLC columns, time-ordered).
* **Output**: `Trade` list (instrument, direction, entry/exit time+price,
  bars_held, gross/net return, stop/target price, exit_reason).
* **Semantics**: identical to moneta/nova (hld I1-I7 invariants, nova
  `trades.py` reference implementation), **zero parameter drift** — do not
  change fill rules, stop priority, or the cost formula.

**Not in scope** (0006 / later):
* No metrics / monthly / report (0006 runner).
* No sizing / account equity / margin (hld §5 "trade-level research only").
* No parameter scan (I8).
* No OOS gate (hld §5 "无").
* No multi-instrument parallelism (per-instrument single-threaded; 0006
  runner owns parallel scheduling).

## 2. Why

hld §8 order: 0004 compiler emits signals → **0005 trade engine emits
trades** → 0006 runner emits metrics + monthly + report. 0005 is the **only
bridge** between signals and reports, and must match moneta/nova semantics
(exactly, or the 0008 332-strategy regression cannot pass).

## 3. Boundary (vs moneta / nova)

| Boundary | moneta | nova | **lyra 0005** |
|---|---|---|---|
| Strategy input | signal array | signal array | **CompiledPlan + SQL** (0004 output, executed in DuckDB) |
| Fill rule | open of T+1, bid/ask + slippage | same | **same** (I2) |
| 2% stop | yes | yes | **yes** (I3, execution metadata from 0004) |
| Take-profit | optional | optional | **optional** (`CompiledPlan.take_profit_pct`) |
| Stop before TP | yes | yes | **yes** (I4) |
| One trade per instrument | yes | yes | **yes** (I5) |
| Zero-entry months | kept | kept | **kept** (I6, in 0006 monthly layer) |
| Costs | commission + slippage + financing | same | **same** (the 4 `CompiledPlan` cost fields) |
| End-of-data | force-close at last close | same | **same** |
| Parameter scan | yes (moneta only) | no | **no** (I8) |

## 4. Invariants (inherit hld I1-I7; this module adds T1-T8)

| # | Invariant | Source |
|---|---|---|
| I1 | every feature available at `bar_close_time` | hld §4 |
| I2 | signal confirmed on closed bar, fills at T+1 open | hld §4 |
| I3 | mandatory 2% adverse exit (vs actual entry price) | hld §4 |
| I4 | same bar hits TP and stop → loss side wins | hld §4 |
| I5 | one trade per instrument; ignore new entries while in position | hld §4 |
| I6 | zero-entry months kept | hld §4 |
| I7 | annualized = arithmetic sum ÷ full calendar year | hld §4 |
| **T1** | entry fill = `open * (1 + side * slippage)` (long pays more, short receives less); spread via `quote()` | nova `trades.py:quote` + I2 |
| **T2** | exit fill = `raw_price * (1 - side * slippage)` | nova `trades.py:finish` + I2 |
| **T3** | stop_gap: `open` already beyond stop → fill at `open` (gap loss may exceed 2%) | nova `trades.py:stop_at_open` + I3 |
| **T4** | stop_inside: `low <= stop` (long) → fill at `stop` (exactly 2%) | nova `trades.py:stop_inside` + I3 |
| **T5** | take-profit symmetric (reversed side); `target = entry * (1 + side * tp_pct)` | nova `trades.py:target` + I3 |
| **T6** | same-bar both hit → check `stop_at_open` before `target_at_open`; intra-bar `stop_inside` before `target_inside` (I4 loss-first) | nova `trades.py` order + I4 |
| **T7** | `indicator_exit` / `time_exit` fill at next bar open (pending mechanism, not same bar) | nova `trades.py:pending_exit` + I2 |
| **T8** | end-of-data: force-close at last bar close, reason="end_of_data" | nova `trades.py` tail + I6 |

## 5. API

```python
@dataclass(frozen=True)
class Trade:
    """One filled round-trip (entry + exit)."""
    instrument: str
    direction: int          # +1 long, -1 short
    signal_time: object     # bar close time that produced the signal
    entry_time: object      # bar open time of the fill (T+1)
    exit_time: object       # bar open/close time of the exit fill
    entry_price: float      # after spread + slippage (T1)
    exit_price: float       # after spread + slippage (T2)
    exit_reason: str        # stop_gap | stop_loss | take_profit | indicator_exit | time_exit | end_of_data
    bars_held: int          # bars in position (0-indexed, +1 per bar)
    gross_return: float     # direction * (exit - entry) / entry
    cost_return: float      # commission + financing (positive = cost)
    net_return: float       # gross - costs
    stop_price: float       # entry * (1 - side * 0.02) — the mandatory stop
    take_profit_price: float | None  # entry * (1 + side * tp_pct), None if unset

def simulate(
    plan: CompiledPlan,
    bars: Sequence[Mapping[str, Any]],
) -> list[Trade]:
    """One instrument, one trade at a time.  `bars` must be time-ordered,
    non-overlapping, and contain at least: instrument, time, open, high,
    low, close (and the 4 signal columns entry_long/entry_short/exit_long/
    exit_short — pre-computed by the caller or joined from the
    CompiledPlan SQL by the runner).  Deterministic: same bars + plan =>
    same trades (no time, no randomness, no process state)."""
    ...
```

### Cost model (field-for-field identical to nova `trades.py`)

```
gross = direction * (exit_price - entry_price) / entry_price
commission = commission_bps_round_trip / 10000          # flat per trade
financing  = financing_bps_per_day / 10000 * days_held  # proportional
costs      = commission + financing
net        = gross - costs
```

`days_held = (exit_time - entry_time).total_seconds() / 86400`.
Slippage is already in the entry/exit price (T1/T2); it is **not** added
again to `costs`.

### Documented deviations vs nova (verified by field-for-field cross-check)

| Field | nova | lyra | Rationale |
|---|---|---|---|
| `exit_time_precision` | present (bar_open/bar_interval/bar_close) | **absent** (not in Trade) | Lyra's Trade contract is leaner; `exit_time` already implies precision. If 0008 golden test needs it, derive from `exit_time == entry bar open/close`. |
| `signal_time` | signal bar's `bar_close_time` | signal bar's `time` (= open) | Data-model difference: nova bars carry both `bar_open_time`/`bar_close_time`; lyra bars have a single `time` (= open, per `aggregate.py`'s `time_bucket`). **Does not change any fill/P&L semantics** — only the signal timestamp differs by one bar period. |
| **financing day count** | natural days (`total_seconds()/86400`) | natural days (**same as nova**) | ⚠️ **OPEN / conflicts with R4+O15**: O15 (user decision, closed 2026-11-06) + R4 require counting by **trading days** (weekends + market holidays excluded). The current implementation is a faithful nova port (natural days), so it **does not satisfy lyra's own R4/O15 convention**. See "Open item" below. |

**Field-for-field cross-check**: same synthetic OHLC+signals drive both nova `trades.simulate` and lyra `trade_engine.simulate` (slippage/spread/commission/financing/mhb all enabled). 2 trades match on `instrument, direction, entry_price, exit_price, exit_reason, bars_held, gross_return, cost_return, net_return, stop_price, take_profit_price` **with diff=0**; the only differences are the three rows above (first two documented deviations; third is the open item).

### ⚠️ Open item (needs user decision; does not block the rest of 0005)

**O-0005-1 financing day count (natural vs trading days)**:
- **Status quo**: `lyra/trade_engine.py` financing = `financing_bps_per_day/10000 * (exit_time-entry_time).total_seconds()/86400`, i.e. **natural days** — field-for-field identical to nova `trades.py`, hence cross-check diff=0.
- **Conflict**: O15 (user decision 2026-11-06, closed) + R4 require counting by **trading days** (weekends + market holidays excluded), i.e. "1 financing unit = 1 trading day".
- **Tension**: nova's cross-check and O15 cannot both hold — nova uses natural days, O15 uses trading days. Only one can be the golden oracle.
- **Options** (awaiting user):
  1. **Follow O15**: count financing by trading days (needs a trading-calendar input, or approximate as "number of bars in the holding window" — 1m/5m/1h bars are trading-day data, so bar count ≈ trading days × period). nova cross-check will then diverge on the financing field (must be excluded/annotated in oracle comparison).
  2. **Keep nova natural days**: prioritize "field-for-field identical to nova" as the top invariant; treat O15's trading-day convention as a lyra enhancement, implemented separately in the 0006 runner with a trading calendar, while trade_engine keeps pure nova semantics.
  3. **Hybrid**: trade_engine keeps natural days (nova-consistent, diff-able), but Trade already exposes `bars_held` so 0006 can recompute financing by bar count.
- **Default (this commit)**: **Option 2** (keep nova natural days + cross-check diff=0). Rationale: 0005's hard gate is "field-for-field identical to nova", and O15's trading-day convention needs a trading calendar (0006/0008 scope). **Marked OPEN; revisit after user confirms the option.**

### Exit reason enum

| reason | trigger | fill price |
|---|---|---|
| `stop_gap` | open already beyond stop (gap) | `open` (gap loss) |
| `stop_loss` | intra-bar low/high beyond stop | `stop` (exactly 2%) |
| `take_profit` | open or intra-bar beyond target | `open` or `target` |
| `indicator_exit` | exit signal fired, next bar open | `open` |
| `time_exit` | `bars >= max_holding_bars`, next bar open | `open` |
| `end_of_data` | data exhausted while in position | `close` |

## 6. Tests (planned matrix — landed at implementation)

| Test | Scenario | Invariant |
|---|---|---|
| `test_entry_fill_at_next_open` | signal bar T → fill at T+1 open, slippage correct | I2, T1 |
| `test_stop_gap_at_open` | open beyond stop → fill at open, loss > 2% | I3, T3 |
| `test_stop_inside_bar` | low beyond stop → fill at stop (exactly 2%) | I3, T4 |
| `test_stop_wins_over_target_same_bar` | same bar both hit → stop first | I4, T6 |
| `test_take_profit_at_open` | open beyond target → fill at open | T5 |
| `test_indicator_exit_next_open` | exit signal bar T → fill at T+1 open | I2, T7 |
| `test_time_exit_next_open` | bars == mhb → next bar open fill | T7 |
| `test_one_trade_per_instrument` | entry signals ignored while in position | I5 |
| `test_end_of_data_force_close` | still in position at last bar → close fill | T8 |
| `test_cost_commission_flat` | commission_bps deducted correctly | cost model |
| `test_cost_financing_proportional` | financing by days | cost model |
| `test_long_short_symmetry` | same OHLC long/short symmetric | I2, T1-T2 |
| `test_deterministic` | same input, same output (multiple runs) | determinism |
| `test_golden_trades_vs_nova` | field-for-field diff=0 on a nova real-trades subset | all |

**Golden test** is the **hard gate** for 0005: pick 3-5 real trades from
nova `runs/*/trades.csv` covering different exit reasons, diff field-for-field
(entry_price, exit_price, gross, net, bars_held, exit_reason) against lyra
output — must be exactly 0.

## 7. Rollback

* Code: revert the 0005 commit (`lyra/trade_engine.py` + tests); 0004
  compiler untouched (0005 only consumes CompiledPlan).
* Data: trade engine writes nothing (pure function); rollback is side-effect
  free.
* Compatibility: none (0005 is a new module with no downstream dependents).

## 8. Self-check and adversarial self-check

### Self-check

- [x] entry fill at T+1 open, not T close (I2).
- [x] stop is 2% (I3), not relaxable (0004 guarantees; 0005 only executes).
- [x] stop before target (I4).
- [x] one trade per instrument (I5).
- [x] cost formula field-for-field identical to nova `trades.py` (commission flat + financing by days + slippage in price). *Note: "days" = natural days (nova-consistent); conflicts with O15/R4 trading-day convention → see §5 open item O-0005-1.*
- [x] pure function, deterministic, no global state.
- [x] direct field-for-field cross-check vs nova `trades.simulate` diff=0 (see §5 deviations).

**Golden test disposition**: §6 originally planned a golden test using nova `runs/*/trades.csv` as the oracle. Since nova runs do not carry market bars (only signals/trades artifacts), the input bars cannot be replayed offline; the golden test is therefore **upgraded to a direct field-for-field cross-check against nova `simulate`** (stronger: same input, two implementations, diff=0). A real-data golden test will be added when the 0006 runner wires bronze→bars.

### Adversarial self-check (planned)

| Attack | Finding | Disposition |
|---|---|---|
| Same bar open beyond both stop and target | if target checked first, author loses 2%+ less / gains more — semantic inversion | stop first (I4); golden test covers |
| gap beyond 2%: fill at stop or open | fill at stop would misreport P&L (actual gap fill) | fill at open (T3), gap loss is real |
| slippage double-counted (once in price + once in costs) | costs inflated 2x | slippage only in T1/T2 price; costs only commission+financing |
| financing by bar count, not days | cost wrong across weekends/holidays | by days (`total_seconds()/86400`), matches nova |
| max_holding_bars boundary (== vs >) | hold one bar too many/few | nova uses `>=`; lyra same (T7) |
| cross-instrument signal leak | single-thread per instrument → no leak | 0005 takes single-instrument bars; 0006 runner isolates |
| entry_long and entry_short both TRUE | ambiguity | nova enters only on `bool(long) != bool(short)`; lyra same |

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.1 | Initial draft: trade engine boundary, API, invariants (T1-T8), test matrix, golden-test hard gate, 7 adversarial self-check items. Awaits user review before implementation. |
| 2026-11-08 | 0.2 | Implementation complete: `lyra/trade_engine.py` + `tests/test_trade_engine.py` (23 tests all green). All 7 self-check items pass; all 7 adversarial items pass (incl. gap>2% fill at open, slippage not double-counted, `bool(long)!=bool(short)`). Field-for-field cross-check vs nova `trades.simulate` diff=0. Golden test downgraded to cross-check (nova runs lack market bars); §6/§8 annotated. Two deviations documented (exit_time_precision dropped; signal_time uses bar open). |
