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
| **financing day count** | natural days (`total_seconds()/86400`) | natural days by default (**same as nova**); **R4/O15 trading-day basis via the per-trade `trading_days_for` counter, supplied by 0006** | ✅ **Batch-3 (H1) + Batch-4 (C2) review dispositions, both accepted**: engine default keeps nova's natural days to preserve the cross-check; R4/O15 (weekends + market holidays excluded) is supplied by the caller as a **per-trade trading-day counter** `trading_days_for(entry_time, exit_time) -> float` (0006 owns the bar series + calendar; final cost basis is finalized in 0006). See the O-0005-1 / O17 disposition below. |

**Field-for-field cross-check**: same synthetic OHLC+signals drive both nova `trades.simulate` and lyra `trade_engine.simulate` (slippage/spread/commission/financing/mhb all enabled). **Fuzz 300 cases / 381 trades**: `instrument, direction, entry_price, exit_price, exit_reason, bars_held, gross_return, cost_return, net_return, stop_price, take_profit_price` show **0 real mismatches**; 119 trades differ on `cost_return`/`net_return` — **all** explained by O-0005-1 (financing natural-days vs trading-days). A second fuzz with `financing_bps_per_day=0` over the same 300 cases / 381 trades shows **0 mismatches on any field**, confirming O-0005-1 is the sole cause of the cost diffs. The two data-model deviations above (exit_time_precision dropped / signal_time uses bar open) are not part of the field comparison.

### Batch-3 review disposition (O-0005-1 / O17 financing basis)

**O-0005-1 / O17 financing day count (natural vs trading days)**:
- **Background conflict**: O15 (user decision 2026-11-06, closed) + R4 require **trading days** (weekends + market holidays excluded); nova `trades.py` uses **natural days** (`total_seconds()/86400`), so the nova cross-check and O15 cannot both hold.
- **Disposition (Batch-3 H1/M1/M2 + Batch-4 C2 all accepted; engine-side support landed per the established "accept → implement" workflow)**:
  * **Engine (0005) default keeps nova natural days**: `simulate(plan, bars)` without `trading_days_for` charges natural days, field-for-field identical to nova → the cross-check uses natural days as the oracle (this basis difference is recorded as a **known divergence**).
  * **R4/O15 trading-day basis is applied by the caller, per trade**: `simulate(plan, bars, trading_days_for=counter)` accepts a **per-trade trading-day counter** `counter(entry_time, exit_time) -> float` (the Batch-4 C2 fix — it replaced the old flat `trading_days=<n>` scalar, which mischarged *every* trade the same day count and made R4/O15 unusable in multi-trade backtests). The **0006 runner owns the bar series + market calendar and can compute the R4/O15 count (weekends/holidays excluded) per trade**, so the reported financing basis is finalized in **0006** (consistent with O17 / ACTION_LOG #83).
  * **Why the engine does not guess trading days**: the engine is a pure function with no calendar and cannot distinguish a "Fri→Fri (over a weekend)" gap from an "overnight" gap when data is sparse (e.g. daily bars), so the trading calendar is a caller/data concern, not something the engine fabricates.
  * **`bars_held` is not a day count** (review M1): it is a bar count, timeframe-dependent, and 0006 must not use it as the financing day count.
  * **fail-closed** (review M2 / C2): a counter returning a non-finite / negative value, or missing / non-subtractable `time` (e.g. naive/aware mix) with no counter supplied, raises rather than silently charging zero financing (the old silent `days=0.0` fallback was removed).
- **O15 / O17 status**: O15 stays closed (user fixed trading days 2026-11-06); O17 (= O-0005-1) is the central open item, with the **engine-side support now in place (per-trade `trading_days_for`) and the final basis to be finalized in 0006** — this does not overturn O15; it lands the R4/O15 contract for 0005/0006. The 0006 flat `--financing-days` CLI knob was removed (C2) pending a real trading calendar; the default is per-trade natural days.

### Exit reason enum

| reason | trigger | fill price |
|---|---|---|
| `stop_gap` | open already beyond stop (gap) | `open` (gap loss) |
| `stop_loss` | intra-bar low/high beyond stop | `stop` (exactly 2%) |
| `take_profit` | open or intra-bar beyond target | always `target` (limit semantics: open beyond target still fills at target, per nova reference) |

> **m3 (Batch-4 review, held / 挂起) — an extremely conservative one-sided penalty assumption**: when an opening gap jumps *past* the take-profit line (e.g. long entry 100, target 102, next open 105), the engine settles at `target=102`, discarding the 300 bps favorable auction premium; whereas a gap *through* the stop settles at `open` and fully eats the adverse gap loss. This **asymmetry** faithfully inherits Nova's conservative limit-order design ("you never receive a better price than the target"), but in a real venue an in-price take-profit usually fills at the open (positive price improvement). Consequently, for **gap-type strategies**, the current model systematically under-states favorable gap gains (a one-sided penalty). This assumption is deliberately retained to keep the Nova cross-check field-for-field identical (see §6 disposition); **no code change** — only an explicit note here. If a closer-to-real gap capture is ever needed, it must be a separate enhancement that also updates the cross-check basis.
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
| `test_take_profit_at_open` | open beyond target → **fill at target** (limit semantics, unlike stop_gap; nova `trades.py` reference) | T5 |
| `test_indicator_exit_next_open` | exit signal bar T → fill at T+1 open | I2, T7 |
| `test_time_exit_next_open` | bars == mhb → next bar open fill | T7 |
| `test_one_trade_per_instrument` | entry signals ignored while in position | I5 |
| `test_end_of_data_force_close` | still in position at last bar → close fill | T8 |
| `test_cost_commission_flat` | commission_bps deducted correctly | cost model |
| `test_cost_financing_proportional` | financing by days | cost model |
| `test_long_short_symmetry` | same OHLC long/short symmetric | I2, T1-T2 |
| `test_deterministic` | same input, same output (multiple runs) | determinism |
| ~~`test_golden_trades_vs_nova`~~ | ~~field-for-field diff=0 on a nova real-trades subset~~ **downgraded**: nova runs carry no market-bar input; replaced by the §5 dual-implementation cross-check (stronger) | all |
| `test_pending_exit_beats_inside_stop_same_bar` | pending exit (open layer) beats inside-stop (nova order) | priority |
| `test_pending_exit_loses_to_stop_gap` | stop-gap (open layer) beats pending exit | priority |
| `test_pending_exit_loses_to_target_at_open` | target_at_open (open layer) beats pending exit | priority |
| `test_exit_long_does_not_close_short` | exit signals are direction-specific (exit_long does not affect a short) | direction isolation |
| `test_cost_financing_trading_days_override` | Fri→Fri: natural 0.07 vs `trading_days=5` trading 0.05 (O-0005-1 H1) | R4/O15 basis |
| `test_cost_financing_fail_closed_mixed_tz` | naive/aware mixed `time` → engine raises (not silent 0 financing) (O-0005-1 M2) | fail-closed |
| `test_cost_financing_rejects_bad_override` | `trading_days` NaN/inf/negative/non-numeric → raises (O-0005-1 M2) | fail-closed |

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

- [x] entry fill at T+1 open, not T close (I2). *Probe: `test_entry_fill_at_next_open` + fuzz.*
- [x] stop is 2% (I3), not relaxable (0004 guarantees; 0005 only executes). *Probe: `test_stop_inside_bar` + P2 (low==stop boundary).*
- [x] stop before target (I4). *Probe: `test_stop_wins_over_target_same_bar` + P5b + P6.*
- [x] one trade per instrument (I5). *Probe: `test_one_trade_per_instrument` + P8 (re-entry sequence).*
- [x] cost formula field-for-field identical to nova `trades.py` (commission flat + financing by days + slippage in price). *Note: default "days" = natural days (nova-consistent); R4/O15 trading-day basis via the `trading_days` param (0006); **O-0005-1/O17 batch 3 H1 accepted, engine-side support landed**. Probes: `test_cost_commission_flat` + `test_cost_financing_proportional` + `test_cost_financing_trading_days_override` + `test_slippage_in_entry_price` + fuzz 300 cases.*
- [x] financing fail-closed (M2): naive/aware mixed `time` or an invalid `trading_days` raises, instead of silently charging zero financing. *Probes: `test_cost_financing_fail_closed_mixed_tz` + `test_cost_financing_rejects_bad_override`.*
- [x] pure function, deterministic, no global state. *Probe: `test_deterministic` + fuzz 300 cases (no global-state side effects).*
- [x] direct field-for-field cross-check vs nova `trades.simulate` diff=0 (see §5 deviations). *Fuzz 300 cases / 381 trades, 0 real mismatches; second fuzz with financing=0 shows 0 mismatches.*
- [x] direction-specific exit signals (`exit_long` does not affect a short position). *Probe P9.*
- [x] exit priority: `stop_at_open` → `target_at_open` → `pending_exit` (open layer) → `stop_inside` / `target_inside` (intra-bar). *Probes P5/P5b/P6/P7.*

**Golden test disposition**: §6 originally planned a golden test using nova `runs/*/trades.csv` as the oracle. Since nova runs do not carry market bars (only signals/trades artifacts), the input bars cannot be replayed offline; the golden test is therefore **upgraded to a direct field-for-field cross-check against nova `simulate`** (stronger: same input, two implementations, diff=0). A real-data golden test will be added when the 0006 runner wires bronze→bars.

### Adversarial self-check (executed 2026-11-08)

| Attack | Finding | Disposition |
|---|---|---|
| Same bar open beyond both stop and target | if target checked first, author loses 2%+ less / gains more — semantic inversion | stop first (I4); fuzz covers |
| gap beyond 2%: fill at stop or open | fill at stop would misreport P&L (actual gap fill) | fill at open (T3), gap loss is real; probe P7 verified |
| open beyond target: fill at target or open | fill at open would misreport profit (limit semantics: never get a better price than the limit) | **fill at target** (nova reference, limit semantics); probes P3/P6 verified |
| slippage double-counted (once in price + once in costs) | costs inflated 2x | slippage only in T1/T2 price; costs only commission+financing; fuzz covers |
| financing by bar count, not days | cost wrong across weekends/holidays | natural days by default (`total_seconds()/86400`), matches nova; R4/O15 trading days via `trading_days` (0006); `bars_held` is explicitly not a day count (M1). **O-0005-1/O17: H1/M1 accepted, engine-side support landed** |
| max_holding_bars boundary (== vs >) | hold one bar too many/few | nova uses `>=`; lyra same (T7); probe P4 verified |
| cross-instrument signal leak | single-thread per instrument → no leak | 0005 takes single-instrument bars; 0006 runner isolates |
| entry_long and entry_short both TRUE | ambiguity | nova enters only on `bool(long) != bool(short)`; lyra same; probe P8 verified |
| **Can `exit_long` close a short position** | direction leak | nova/lyra both read `f"exit_{direction}"` for the position's direction only; **probe P9 verified exit_long does NOT affect a short** |
| **pending_exit (open fill) vs inside-bar stop on the same bar** | if inside-stop checked first, the pending signal is lost; nova's actual order is **open-layer first** (stop_at_open → target_at_open → pending_exit → inside) | matches nova (open chronology priority); **probe P5 verified pending_exit beats inside-stop** |
| **stop_at_open and target_at_open both true** | double-gap extreme: open beyond both | nova is `if/elif`: stop_gap first (loss side priority); **fuzz covers** |
| **financing natural-days vs R4/O15 trading-days conflict** (adversarial review batch 3 H1) | engine natural-day default conflicts with O15/R4 trading-day basis; nova cross-check can't prove R4/O15 compliance | **Accepted + engine-side support landed**: `trading_days` param supplied by the caller (0006) for the trading-day count; engine default keeps nova natural days to preserve the cross-check (recorded as a known divergence); final basis finalized in 0006 (O17); probe `test_cost_financing_trading_days_override` (Fri→Fri 0.07→0.05) |
| **`bars_held` misused as a day count** (batch 3 M1) | 24h hold = 24 bars at 60m but 288 at 5m; using bar count as days → 24%/288% cost | **Accepted**: doc states `bars_held` is not a day count; 0006 must pass an R4/O15-consistent trading-day count (`trading_days`), not `bars_held` |
| **time type mismatch → silent zero financing** (batch 3 M2) | naive/aware mix makes `total_seconds()` raise TypeError; old code silently swallowed to `days=0.0` | **Accepted + implemented**: `_day_count` fail-closed raises ValueError (not silent 0); invalid `trading_days` also raises; probes `test_cost_financing_fail_closed_mixed_tz` + `test_cost_financing_rejects_bad_override` |

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.1 | Initial draft: trade engine boundary, API, invariants (T1-T8), test matrix, golden-test hard gate, 7 adversarial self-check items. Awaits user review before implementation. |
| 2026-11-08 | 0.2 | Implementation complete: `lyra/trade_engine.py` + `tests/test_trade_engine.py` (23 tests all green). All 7 self-check items pass; all 7 adversarial items pass (incl. gap>2% fill at open, slippage not double-counted, `bool(long)!=bool(short)`). Field-for-field cross-check vs nova `trades.simulate` diff=0. Golden test downgraded to cross-check (nova runs lack market bars); §6/§8 annotated. Two deviations documented (exit_time_precision dropped; signal_time uses bar open). **New open item O-0005-1 discovered**: financing day count (nova=natural days vs R4/O15=trading days), currently natural days, marked OPEN awaiting user ruling. |
| 2026-11-08 | 0.3 | **Self-check + detailed adversarial self-check executed**: ① probes P1–P9 (boundaries open==stop / low==stop / high==target; priority stop_at_open > target_at_open > pending_exit > stop_inside/target_inside; direction-specific exit_long does not affect a short position; re-entry sequence) all pass; ② **fuzz 300 cases / 381 trades** vs nova `trades.simulate`: 0 real mismatches, 119 cost/net-only diffs all explained by O-0005-1; second fuzz with `financing=0` over the same 300 cases / 381 trades shows **0 mismatches on any field**, confirming O-0005-1 is the sole cause of the cost diffs; ③ 4 new adversarial regression tests added: `test_pending_exit_beats_inside_stop_same_bar` / `test_pending_exit_loses_to_stop_gap` / `test_pending_exit_loses_to_target_at_open` / `test_exit_long_does_not_close_short`; tests **23→27**, repository **180→184** green; ④ §5 deviation table / §6 test matrix / §8 self-check / §8 adversarial self-check all synced; adversarial self-check header changed from "planned" to "executed 2026-11-08", 3 new attack rows added (open-beyond-target fill semantics / exit_long direction isolation / pending_exit vs inside-stop order). |
| 2026-11-08 | 0.4 | **Adversarial review batch 3 disposition (H1/M1/M2 accepted; engine-side support landed per the established workflow)**: ① **H1 (accepted + engine-side support landed)** O-0005-1/O17 — engine default keeps nova natural days to preserve the cross-check (recorded as a known divergence); R4/O15 trading-day basis added as the `trading_days` param, supplied by the 0006 runner (review's "upstream-computed trading-day count"); final basis finalized in 0006 (O17, consistent with #83); ② **M1 (accepted)** doc states `bars_held` is not a day count and 0006 must not use it as the financing day count; ③ **M2 (accepted + implemented)** `_day_count` fail-closed — naive/aware mixed `time` or an invalid `trading_days` (NaN/inf/negative/non-numeric) raises ValueError instead of silently charging zero financing (old `except → days=0.0` removed). 3 new regression tests `test_cost_financing_trading_days_override` / `test_cost_financing_fail_closed_mixed_tz` / `test_cost_financing_rejects_bad_override`; tests **27→30**. O15 stays closed; O17 engine-side support in place, final basis finalized in 0006. |
