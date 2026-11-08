# 0005 — Trade Engine

> **English**: [0005-trade-engine.en.md](./0005-trade-engine.en.md)
>
> **范围**：把 0004 的 `CompiledPlan`（信号 SELECT + execution metadata）转成
> **逐笔交易**（entry / exit / P&L / cost），在 DuckDB 里跑，输出 trade
> 级别的记录集。不含 metrics / monthly / report（归 0006）。

## 1. 做什么

一个纯函数 `simulate(plan, ohlcv_df) -> list[Trade]`：

* **输入**：`CompiledPlan`（0004 产物：signal SQL + stop/tp/cost/mhb 元数据）
  + 一个 DataFrame（per-instrument OHLC 列，已按 time 有序）。
* **输出**：`Trade` 列表（instrument, direction, entry/exit 时间+价格,
  bars_held, gross/net return, stop/target price, exit_reason）。
* **语义**：与 moneta/nova 完全一致（hld I1-I7 不变量，nova `trades.py`
  参考实现），**零参数漂移**——不改 fill 规则、不改 stop 优先级、不改成本
  公式。

**不做**（0006 / 后续）：
* 不做 metrics / monthly / report（0006 runner 的职责）。
* 不做 sizing / account equity / margin（hld §5 "trade-level research only"）。
* 不做 parameter scan（I8）。
* 不做 OOS gate（hld §5 "无"）。
* 不做多 instrument 并行（per-instrument 单线程，0006 runner 负责并行调度）。

## 2. 为什么

hld §8 顺序：0004 compiler 出信号 → **0005 trade engine 出交易** → 0006
runner 出 metrics + monthly + report。0005 是信号与报告之间的**唯一桥**，
必须与 moneta/nova 语义一致（否则 0008 的 332 策略回归不可能通过）。

## 3. 边界（与 moneta / nova 对比）

| 边界 | moneta | nova | **lyra 0005** |
|---|---|---|---|
| 策略输入 | signal array | signal array | **CompiledPlan + SQL**（0004 产物，DuckDB 执行） |
| Fill 规则 | open of T+1, bid/ask + slippage | 同 | **同**（I2） |
| 2% stop | 有 | 有 | **有**（I3，execution metadata 由 0004 传入） |
| Take-profit | 可选 | 可选 | **可选**（`CompiledPlan.take_profit_pct`） |
| Stop 优先于 TP | 是 | 是 | **是**（I4） |
| 一标的一笔 | 是 | 是 | **是**（I5） |
| 零开仓月 | 保留 | 保留 | **保留**（I6，0006 monthly 层实现） |
| 成本 | commission + slippage + financing | 同 | **同**（`CompiledPlan` 的 4 个 cost 字段） |
| End-of-data | force-close at last close | 同 | **同** |
| 参数扫描 | 有（moneta 独有） | 无 | **无**（I8） |

## 4. 不变量（继承 hld I1-I7，本模块补充 T1-T8）

| # | 不变量 | 来源 |
|---|---|---|
| I1 | 每个 feature 在 `bar_close_time` 时可用 | hld §4 |
| I2 | 信号在 closed bar 确认、T+1 open 成交 | hld §4 |
| I3 | 2% 强制不利退出（相对实际开仓价） | hld §4 |
| I4 | 同根同时触及止盈/止损 → 亏损方优先 | hld §4 |
| I5 | 一标的一笔；持仓期间忽略新入场 | hld §4 |
| I6 | 零开仓月份保留 | hld §4 |
| I7 | 年化分数 = 算术和 ÷ 完整日历年 | hld §4 |
| **T1** | entry fill 价 = `open * (1 + side * slippage)`（long: pay more; short: receive less），spread 走 `quote()` | nova `trades.py:quote` + I2 |
| **T2** | exit fill 价 = `raw_price * (1 - side * slippage)` | nova `trades.py:finish` + I2 |
| **T3** | stop_gap：`open` 已越 stop → fill at `open`（gap loss 可超 2%） | nova `trades.py:stop_at_open` + I3 |
| **T4** | stop_inside：`low <= stop`（long）→ fill at `stop`（exactly 2%） | nova `trades.py:stop_inside` + I3 |
| **T5** | take_profit 同逻辑（reversed side），`target = entry * (1 + side * tp_pct)` | nova `trades.py:target` + I3 |
| **T6** | 同 bar 同触 → `stop_at_open` 先判，再 `target_at_open`；intra-bar `stop_inside` 先判，再 `target_inside`（I4 亏损方优先） | nova `trades.py` 判定顺序 + I4 |
| **T7** | `indicator_exit` / `time_exit` 在下一 bar open 成交（pending 机制，非同 bar） | nova `trades.py:pending_exit` + I2 |
| **T8** | end-of-data：force-close at last bar close，reason="end_of_data" | nova `trades.py` 末尾 + I6 |

## 5. API

```python
@dataclass(frozen=True)
class Trade:
    """One filled round-trip (entry + exit)."""
    instrument: str
    direction: int          # +1 long, -1 short
    signal_time: object     # bar time (open) of the signal bar — 见 §5 偏差说明
    entry_time: object      # bar open time of the fill (T+1)
    exit_time: object       # bar open/close time of the exit fill
    entry_price: float      # after spread + slippage (T1)
    exit_price: float       # after spread + slippage (T2)
    exit_reason: str        # stop_gap | stop_loss | take_profit | indicator_exit | time_exit | end_of_data
    bars_held: int          # number of bars in position (0-indexed, +1 per bar)
    gross_return: float     # direction * (exit - entry) / entry
    cost_return: float      # commission + financing (positive = cost)
    net_return: float       # gross - costs
    stop_price: float       # entry * (1 - side * 0.02) — the mandatory stop
    take_profit_price: float | None  # entry * (1 + side * tp_pct), None if not set

def simulate(
    plan: CompiledPlan,
    bars: Sequence[Mapping[str, Any]],
) -> list[Trade]:
    """One instrument, one trade at a time.  `bars` must be time-ordered,
    non-overlapping, and contain at least: instrument, time, open, high,
    low, close (and the 4 signal columns entry_long/entry_short/exit_long/
    exit_short — either pre-computed by the caller or joined from the
    CompiledPlan SQL by the runner).  Deterministic: same bars + plan =>
    same trades (no time, no randomness, no process state)."""
    ...
```

### Cost model（与 nova `trades.py` 逐字段一致）

```
gross = direction * (exit_price - entry_price) / entry_price
commission = commission_bps_round_trip / 10000          # flat per trade
financing  = financing_bps_per_day / 10000 * days_held  # proportional
costs      = commission + financing
net        = gross - costs
```

`days_held = (exit_time - entry_time).total_seconds() / 86400`。
Slippage 已在 entry/exit price 里体现（T1/T2），**不**再加到 `costs`。

### 与 nova 的已记录偏差（field-for-field cross-check 已确认）

| 字段 | nova | lyra | 原因 |
|---|---|---|---|
| `exit_time_precision` | 有（bar_open/bar_interval/bar_close） | **无**（Trade 不含该字段） | lyra Trade 契约精简；exit_time 本身已隐含精度（open fill vs close fill）。如 0008 golden test 需要，可按 `exit_time == entry bar open/close` 反推。 |
| `signal_time` | 信号 bar 的 `bar_close_time` | 信号 bar 的 `time`（= open） | 数据模型差异：nova bar 同时携带 `bar_open_time`/`bar_close_time` 两列；lyra bar 只有单列 `time`（= open，见 `aggregate.py` 的 `time_bucket`）。**不改变任何成交/P&L 语义**，仅信号时间戳相差 1 个 bar 周期。 |
| **financing 天数口径** | 自然日（`total_seconds()/86400`） | 默认同 nova（自然日）；**R4/O15 交易日口径经每笔交易的 `trading_days_for` 计数器由 0006 传入** | ✅ **批次3（H1）+ 批次4（C2）review 处置（均接受，按既定工作流已落地引擎侧支持）**：引擎默认保留 nova 自然日以维持 cross-check；R4/O15（周末+市场假日不计）由 caller 以**每笔交易**的交易日计数器 `trading_days_for(entry_time, exit_time) -> float` 提供（0006 拥有 bar 序列+日历，最终成本口径仍在 0006 锁定）。见下方"O-0005-1 / O17 处置"。 |

**field-for-field cross-check**：用同一组合成 OHLC+信号同时驱动 nova `trades.simulate` 与 lyra `trade_engine.simulate`（slippage/spread/commission/financing/mhb 全开）。**fuzz 300 例 / 381 笔交易**：`instrument, direction, entry_price, exit_price, exit_reason, bars_held, gross_return, cost_return, net_return, stop_price, take_profit_price` **0 个真实不一致**；119 笔在 `cost_return`/`net_return` 上有差异——**全部**由 financing 天数口径（自然日 vs 交易日）解释。二次 fuzz（`financing_bps_per_day=0`）300 例 / 381 笔**全字段 0 不一致**，反证该唯一差异即 financing 天数口径。O-0005-1 裁决后（见下）：**nova cross-check 以"引擎自然日默认"为 oracle，该口径差异属"已知分歧（已裁决保留）"**，不再阻塞。上表前两行（exit_time_precision 精简 / signal_time 用 bar open）为数据模型已记录偏差，不进入字段比对。

### 批次3 review 处置（O-0005-1 / O17 融资口径）

**O-0005-1 / O17 financing 天数口径（自然日 vs 交易日）**：
- **背景冲突**：O15（用户 2026-11-06 拍板，closed）+ R4 明确要求按**交易日**计（周末+市场节假日不计）；而 nova `trades.py` 用**自然日**（`total_seconds()/86400`），故 nova cross-check 与 O15 不可兼得。
- **处置（接受 review H1/M1/M2 + 批次4 C2，按既定工作流"接受即落地"）**：
  * **引擎（0005）默认保留 nova 自然日**：`simulate(plan, bars)` 不传 `trading_days_for` 时按自然日计，与 nova 逐字段一致 → cross-check 以自然日为 oracle（该口径差异列为**已知分歧**）。
  * **R4/O15 交易日口径由 caller 落地（每笔交易）**：`simulate(plan, bars, trading_days_for=counter)` 接受 caller 提供的**每笔交易**交易日计数器 `counter(entry_time, exit_time) -> float`（批次4 C2 修正：取代旧的单一标量 `trading_days=<n>`——它对**所有**交易无差别地扣同一天数，使 R4/O15 在多交易回测中不可用）；**0006 runner 拥有 bar 序列 + 市场日历，负责按 R4/O15（排除周末/市场假日）逐笔计算并传入**，最终报告融资口径在 **0006 锁定**（与 O17 / ACTION_LOG #83 一致）。
  * **引擎不臆断交易日的原因**：引擎是纯函数、无日历、且无法从稀疏 bar 区分"周五→周五（跨周末）"与"隔夜"（日线数据下二者的时间戳间隔相同），故交易日历是 caller/数据关注点，不在引擎臆造。
  * **`bars_held` 不是天数**（review M1）：它是 bar 数，跨 timeframe 不等价于天数，0006 **不得**拿它当融资天数。
  * **fail-closed**（review M2 / C2）：计数器返回值非有限非负数、或无计数器时 `time` 缺失/不可减（如 naive/aware 混用），引擎**抛错而非静默 0 融资**（旧代码静默吞 `days=0.0`，已修）。
- **O15 / O17 状态**：O15 维持关闭（用户 2026-11-06 已定交易日）；O17（=O-0005-1）为中央开放项，**引擎侧支持已就位（每笔交易 `trading_days_for`），最终融资口径在 0006 锁定**——本条不推翻 O15，是把 R4/O15 落地到 0005/0006 的契约。0006 的扁平 `--financing-days` CLI 开关已移除（C2），默认按每笔自然日计。

### Exit reason enum

| reason | 触发 | fill price |
|---|---|---|
| `stop_gap` | open 已越 stop（gap） | `open`（gap loss） |
| `stop_loss` | intra-bar low/high 越 stop | `stop`（exactly 2%） |
| `take_profit` | open 或 intra-bar 越 target | 恒为 `target`（limit 语义：open 越过 target 时仍按 target 成交，nova 参考实现） |

> **m3（批次4 review，已挂起）— 极其保守的单边惩罚假设**：开盘跳空越过止盈线时（多头进场 100、止盈 102、次日高开 105），引擎按 `target=102` 结算，放弃开盘集合竞价的 300 bps 有利溢价；而跳空跌破止损时却按 `open` 全额吃下恶性跳空亏损。这一**不对称**忠实继承 Nova 的限价单保守设计（"不会拿到比 target 更好的价"），但在真实撮合中位于价内的止盈单通常按开盘价成交（获得正向价格改善）。因此对**跳空型策略**，当前模型系统性低估其有利跳空收益（单边惩罚）。此假设已刻意保留以与 Nova cross-check 保持逐字段一致（见 §6 裁决），**不做代码修改**，仅在此显式标注；若未来需要更贴近真实撮合的跳空收益，需作为增强项单独评估并同步更新 cross-check 口径。
| `indicator_exit` | exit signal 触发，下一 bar open | `open` |
| `time_exit` | `bars >= max_holding_bars`，下一 bar open | `open` |
| `end_of_data` | 数据耗尽时仍持仓 | `close` |

## 6. 测试（计划矩阵 — 实施时落地）

| 测试 | 场景 | 不变量 |
|---|---|---|
| `test_entry_fill_at_next_open` | signal bar T → fill at bar T+1 open，slippage 正确 | I2, T1 |
| `test_stop_gap_at_open` | open 已越 stop → fill at open，loss > 2% | I3, T3 |
| `test_stop_inside_bar` | low 越 stop → fill at stop（exactly 2%） | I3, T4 |
| `test_stop_wins_over_target_same_bar` | 同 bar 同触 → stop 优先 | I4, T6 |
| `test_take_profit_at_open` | open 已越 target → **fill at target**（limit 语义，与 stop_gap 不同；nova `trades.py` 参考实现） | T5 |
| `test_indicator_exit_next_open` | exit signal bar T → fill at T+1 open | I2, T7 |
| `test_time_exit_next_open` | bars == mhb → next bar open fill | T7 |
| `test_one_trade_per_instrument` | 持仓期间 entry 信号忽略 | I5 |
| `test_end_of_data_force_close` | 最后 bar 仍持仓 → close fill | T8 |
| `test_cost_commission_flat` | commission_bps 正确扣减 | cost model |
| `test_cost_financing_proportional` | financing 按天计 | cost model |
| `test_long_short_symmetry` | 同 OHLC long/short 对称 | I2, T1-T2 |
| `test_deterministic` | 同输入同输出（多次） | 确定性 |
| ~~`test_golden_trades_vs_nova`~~ | ~~对 nova 真实 trades.csv 子集逐字段 diff=0~~ **已降级**：nova runs 无 market bars 输入，改为 §5 的双实现 cross-check（更强） | 全部 |
| `test_pending_exit_beats_inside_stop_same_bar` | pending exit（open 层）优先于 inside-stop（nova 顺序） | 优先级 |
| `test_pending_exit_loses_to_stop_gap` | stop-gap（open 层）优先于 pending exit | 优先级 |
| `test_pending_exit_loses_to_target_at_open` | target_at_open（open 层）优先于 pending exit | 优先级 |
| `test_exit_long_does_not_close_short` | exit 信号方向特定（exit_long 不影响 short 仓） | 方向隔离 |
| `test_cost_financing_trading_days_override` | 跨周末 Fri→Fri：自然日 0.07 vs `trading_days_for=5` 交易日 0.05（O-0005-1 H1） | R4/O15 口径 |
| `test_cost_financing_trading_days_per_trade` | 同序列两笔交易（A 持 1 天 / B 持 10 天）逐笔计融资，扁平标量无法做到（C2） | R4/O15 口径（每笔） |
| `test_cost_financing_fail_closed_mixed_tz` | naive/aware 混合 time → 引擎抛错（非静默 0 融资）（O-0005-1 M2） | fail-closed |
| `test_cost_financing_rejects_bad_override` | `trading_days` NaN/inf/负/非数 → 抛错（O-0005-1 M2） | fail-closed |

**golden test** 是 0005 的**硬门槛**：nova `runs/*/trades.csv` 选 3-5 个
不同 exit reason 的交易，逐字段（entry_price, exit_price, gross, net,
bars_held, exit_reason）与 lyra 输出 diff=0。

## 7. 回滚

* 代码层面：revert 0005 commit（`lyra/trade_engine.py` + tests）；0004
  compiler 不动（0005 只消费 CompiledPlan）。
* 数据层面：trade engine 不写数据（纯函数），回滚无副作用。
* 兼容性：无（0005 是新模块，无下游依赖）。

## 8. 自检与对抗性自检

### 自检

- [x] entry fill 在 T+1 open，不在 T close（I2）。*探针：`test_entry_fill_at_next_open` + fuzz。*
- [x] stop 是 2%（I3），不可放宽（0004 已保证，0005 只执行）。*探针：`test_stop_inside_bar` + P2（low==stop 边界）。*
- [x] stop 优先于 target（I4）。*探针：`test_stop_wins_over_target_same_bar` + P5b + P6。*
- [x] 一标的一笔（I5）。*探针：`test_one_trade_per_instrument` + P8（re-entry 序列）。*
- [x] 成本公式与 nova `trades.py` 逐字段一致（commission flat + financing 按天 + slippage 在 price 里）。*注：financing 默认"天"=自然日（与 nova 一致）；R4/O15 交易日口径经 `trading_days` 参数由 0006 传入，**O-0005-1 已裁决 2026-11-08（批次3 H1）**。探针：`test_cost_commission_flat` + `test_cost_financing_proportional` + `test_cost_financing_trading_days_override` + `test_slippage_in_entry_price` + fuzz 300 例。*
- [x] financing fail-closed（M2）：naive/aware 混合 time 或非法 `trading_days` → 抛错，非静默 0 融资。*探针：`test_cost_financing_fail_closed_mixed_tz` + `test_cost_financing_rejects_bad_override`。*
- [x] 纯函数、确定性、无全局状态。*探针：`test_deterministic` + fuzz 300 例（无全局状态副作用）。*
- [x] 与 nova `trades.simulate` 直接逐字段 diff=0（field-for-field cross-check，见 §5 偏差说明）。*fuzz 300 例 / 381 笔，0 真实不一致；financing=0 二次 fuzz 0 不一致。*
- [x] 方向特定 exit 信号（`exit_long` 不影响 short 仓）。*探针 P9。*
- [x] exit 优先级：`stop_at_open` → `target_at_open` → `pending_exit`（open 层） → `stop_inside` / `target_inside`（bar 内）。*探针 P5/P5b/P6/P7。*

**golden test 处置**：§6 原计划以 nova `runs/*/trades.csv` 为 oracle 的 golden test，因 nova runs 不携带 market bars（只有 signals/trades 产物），无法离线重放输入 bars，故降级为**与 nova `simulate` 直接逐字段 cross-check**（更强：同输入双实现 diff=0）。待 0006 runner 接入真实 bronze→bars 后，再补真实数据 golden test。

### 对抗性自检（已执行 2026-11-08）

| 攻击点 | 发现 | 处置 |
|---|---|---|
| 同 bar open 同时越 stop 和 target | 如果 target 先判，作者会少亏 2%+ 多赚 tp%，语义翻转 | stop 先判（I4），fuzz 覆盖 |
| gap 超过 2% 时 fill 在 stop 还是 open | fill 在 stop 会虚报 P&L（实际 gap 价成交） | fill 在 open（T3），gap loss 真实；探针 P7 验证 |
| open 越 target 时 fill 在 target 还是 open | fill 在 open 会虚报盈利（limit 语义：不会拿到比 target 更好的价） | **fill 在 target**（nova 参考实现，limit 语义）；探针 P3/P6 验证 |
| slippage 加两次（price 里一次 + costs 里一次） | 成本虚高一倍 | slippage 只在 T1/T2 price 里，costs 只有 commission+financing；fuzz 覆盖 |
| financing 按 bar 数而非天 | 跨周末/假日时成本失真 | 默认按自然日（`total_seconds()/86400`）与 nova 一致；R4/O15 交易日经 `trading_days` 由 0006 传入；`bars_held` 明确非天数（M1）。**O-0005-1 已裁决（批次3 H1/M1）** |
| max_holding_bars 边界（== 还是 >） | 多/少 hold 1 bar | nova 是 `>=`，lyra 同（T7）；探针 P4 验证 |
| 跨 instrument 信号泄漏 | per-instrument 单线程，无并行 → 无泄漏 | 0005 只接 single-instrument bars，0006 runner 负责隔离 |
| entry_long 和 entry_short 同时 TRUE | 歧义 | nova 是 `bool(long) != bool(short)` 才入场，lyra 同；探针 P8 验证 |
| **exit_long 信号能否关掉 short 仓** | 方向泄漏 | nova/lyra 都是 `f"exit_{direction}"` 只读对应方向；**探针 P9 验证 exit_long 不影响 short 持仓** |
| **pending_exit（open fill）与 inside-stop 同 bar** | 若 inside-stop 先判，pending 信号失效；nova 的实际顺序是 **open 层优先**（stop_at_open → target_at_open → pending_exit → inside） | 与 nova 一致（open 时序优先）；**探针 P5 验证 pending_exit 赢过 inside-stop** |
| **stop_at_open 与 target_at_open 同时成立** | 双 gap 极端：open 同时越 stop 和 target | nova 是 `if/elif`：stop_gap 先判（loss 侧优先）；**探针 P6 变体已 fuzz 覆盖** |
| **financing 自然日 vs R4/O15 交易日冲突**（对抗性 review 批次3 H1） | 引擎默认自然日与 O15/R4 交易日口径冲突；nova cross-check 无法证明 R4/O15 合规 | **接受 + 已实现**：`trading_days` 参数由 caller（0006）传交易日数；引擎默认保留 nova 自然日以维持 cross-check（列为已知分歧）；探针 `test_cost_financing_trading_days_override`（Fri→Fri 0.07→0.05） |
| **`bars_held` 被误当天数用**（批次3 M1） | 24h 持仓 = 60m 24 bars / 5m 288 bars，拿 bar 数当天数 → 成本 24%/288% | **接受**：doc 明确 `bars_held` 非天数；0006 须传 R4/O15 一致的交易日数（`trading_days`），不拿 `bars_held` 当融资天数 |
| **time 类型不一致 → 静默 0 融资**（批次3 M2） | naive/aware 混合时 `total_seconds()` 抛 TypeError，旧代码静默吞 `days=0.0` | **接受 + 已实现**：`_day_count` fail-closed 抛 ValueError（非静默 0）；非法 `trading_days` 亦抛错；探针 `test_cost_financing_fail_closed_mixed_tz` + `test_cost_financing_rejects_bad_override` |

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-08 | 0.1 | 初稿：确定 trade engine 边界、API、不变量（T1-T8）、测试矩阵、golden test 硬门槛、对抗性自检 7 条。待用户审阅后实施。 |
| 2026-11-08 | 0.2 | 实施完成：`lyra/trade_engine.py` + `tests/test_trade_engine.py`（23 测试全绿）。自检 7 条全通过；对抗性自检 7 条全通过（含 gap>2% fill 在 open、slippage 不双计、bool(long)!=bool(short) 等）。与 nova `trades.simulate` field-for-field cross-check diff=0。golden test 降级为 cross-check（nova runs 无 market bars），§6/§8 已标注。记录两行偏差（exit_time_precision 精简、signal_time 用 bar open）。**新发现未决项 O-0005-1**：financing 天数口径（nova=自然日 vs R4/O15=交易日），当前按 nova 自然日，标记 OPEN 待用户拍板。 |
| 2026-11-08 | 0.3 | **自检 + 对抗性自检 详细执行**：① 逐条探针 P1–P9（边界 open==stop / low==stop / high==target；优先级 stop_at_open > target_at_open > pending_exit > stop_inside/target_inside；方向特定 exit_long 不影响 short 仓；re-entry 序列）全部通过；② **fuzz 300 例 / 381 笔**：与 nova `trades.simulate` 0 真实不一致，119 笔 cost/net-only 差异全部由 O-0005-1 解释；`financing=0` 二次 fuzz 300 例 / 381 笔**全字段 0 不一致**，反证该唯一差异即 O-0005-1；③ 新增 4 个对抗性回归测试：`test_pending_exit_beats_inside_stop_same_bar` / `test_pending_exit_loses_to_stop_gap` / `test_pending_exit_loses_to_target_at_open` / `test_exit_long_does_not_close_short`；测试数 **23→27**，全仓 **180→184** 绿；④ §5 偏差表 / §6 测试矩阵 / §8 自检 / §8 对抗性自检 全同步；对抗性自检表由"计划"改为"已执行 2026-11-08"，新增 3 行攻击点（open 越 target fill 语义 / exit_long 方向隔离 / pending_exit vs inside-stop 顺序）。 |
| 2026-11-08 | 0.4 | **对抗性 review 批次3 处置（接受 H1/M1/M2，按既定工作流"接受即落地"引擎侧支持）**：① **H1（接受+实现）** O-0005-1/O17 融资口径——引擎默认保留 nova 自然日以维持 cross-check（列为已知分歧），R4/O15 交易日口径新增 `trading_days` 参数由 0006 runner 传入（review 建议的"上游计算交易日数"），最终口径在 0006 锁定（与 O17 / #83 一致）；② **M1（接受）** doc 明确 `bars_held` 非天数、0006 不得拿它当融资天数；③ **M2（接受+实现）** `_day_count` fail-closed——naive/aware 混合 time 或非法 `trading_days`（NaN/inf/负/非数）抛 ValueError，不再静默 0 融资（旧 `except → days=0.0` 已删）。新增 3 回归测试 `test_cost_financing_trading_days_override` / `test_cost_financing_fail_closed_mixed_tz` / `test_cost_financing_rejects_bad_override`；测试 **27→30**。O15 维持关闭；O17 引擎侧支持就位、最终口径待 0006 锁定。 |
| 2026-11-08 | 0.5 | **对抗性 review 批次4 处置（C2/M2/m1/m2 接受+实现；m3 挂起仅标注）**。⚠ 本条取代 0.4 中所有 `trading_days` 标量表述。① **C2（接受+实现）** 融资天数契约重构：`trading_days: float` 单标量 → **每笔交易**计数器 `trading_days_for(entry_time, exit_time) -> float`（默认 `None`=自然日，保持 nova cross-check 逐字段一致）。旧标量对多笔交易无差别扣同一天数，R4/O15 在真实回测中死锁；新契约逐笔计，调用方无需预知进出场 bar。0006 扁平 `--financing-days` CLI 开关随之移除（误导性的扁平旋钮）。新增 `test_cost_financing_trading_days_per_trade`（A 持 1 天/B 持 10 天逐笔计）。② **M2（接受+实现）** `_quote` 幽灵列修复：真实列 `bid_o`/`ask_o`（`mid_` 前缀剥离后拼接），不再生成 `bid_mid_o` 导致真实点差被静默弃用。新增 `test_b4_m2_real_bid_ask_columns_used` + `test_b4_m2_real_bid_ask_drives_fill_price`。③ **m1（接受+实现）** end_of_data 强平时间戳改为 bar 收盘（`last["time"] + timeframe_minutes`）而非 bar 开盘，避免"整根 bar 持仓计 0 融资"。新增 `test_b4_m1_end_of_data_exit_timestamp_is_bar_close`。④ **m2（接受+实现）** `simulate()` 入口单标的守卫，混合标的 fail-closed。新增 `test_b4_m2_simulate_rejects_mixed_instruments`。⑤ **m3（挂起，仅标注）** 开盘跳空越过止盈按 `target` 结算 vs 跌破止损按 `open` 结算的**不对称单边惩罚**（继承 nova 限价保守设计）——刻意保留以维持 cross-check 逐字段一致，§5 已显式标注"极其保守的单边惩罚假设"，不改代码。全仓测试 **30→36** 绿（trade_engine 文件内）。 |
