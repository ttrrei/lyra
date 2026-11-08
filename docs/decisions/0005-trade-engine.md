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
| **financing 天数口径** | 自然日（`total_seconds()/86400`） | 自然日（**同 nova**） | ⚠️ **OPEN / 与 R4+O15 冲突**：O15（用户 2026-11-06 拍板）+ R4 要求按**交易日**计（周末+市场节假日不计）。当前实现逐字段对齐 nova（自然日），是**忠实移植**，但**不满足 lyra 自身 R4/O15 口径**。见下方"未决项"。 |

**field-for-field cross-check**：用同一组合成 OHLC+信号同时驱动 nova `trades.simulate` 与 lyra `trade_engine.simulate`（slippage/spread/commission/financing/mhb 全开），2 笔交易在 `instrument, direction, entry_price, exit_price, exit_reason, bars_held, gross_return, cost_return, net_return, stop_price, take_profit_price` **全部 diff=0**；唯一差异为上表三行（前两行为已记录偏差，第三行为未决项）。

### ⚠️ 未决项（需用户拍板，不阻塞 0005 其余部分）

**O-0005-1 financing 天数口径（自然日 vs 交易日）**：
- **现状**：`lyra/trade_engine.py` 的 financing = `financing_bps_per_day/10000 * (exit_time-entry_time).total_seconds()/86400`，即**自然日**——与 nova `trades.py` 逐字段一致，故 cross-check diff=0。
- **冲突**：O15（用户 2026-11-06 拍板，closed）+ R4 明确要求按**交易日**计（周末+市场节假日不计）。即"1 个 financing 单位 = 1 个交易日"。
- **张力**：nova 的 cross-check 与 O15 不可兼得——nova 是自然日，O15 是交易日。二者只能择一作为 golden oracle。
- **可选处置**（待用户选择）：
  1. **按 O15 改**：financing 按交易日计（需要 trading-calendar 输入，或近似为"持仓区间内 bar 数"——1m/5m/1h bar 均为交易日数据，可近似为交易日数×周期）。nova cross-check 会在 financing 项上出现差异（需从 oracle 比对中剔除该字段或标注）。
  2. **保持 nova 自然日**：以"逐字段对齐 nova 黄金标准"为最高优先，O15 视为 lyra 增强项，在 0006 runner 里用 trading calendar 单独实现，trade_engine 保持纯 nova 语义。
  3. **折中**：trade_engine 保留自然日（与 nova 一致，可 diff），但在 Trade 里额外暴露 `bars_held`（已有）让 0006 按 bar 数重算 financing。
- **默认（本 commit 采用）**：**方案 2**（保持 nova 自然日 + cross-check diff=0），理由：0005 的硬门槛是"与 nova 逐字段一致"，且 O15 的交易日口径需要 trading calendar（属 0006/0008 范畴）。**此项标记为 OPEN，待用户确认方案后再改。**

### Exit reason enum

| reason | 触发 | fill price |
|---|---|---|
| `stop_gap` | open 已越 stop（gap） | `open`（gap loss） |
| `stop_loss` | intra-bar low/high 越 stop | `stop`（exactly 2%） |
| `take_profit` | open 或 intra-bar 越 target | `open` 或 `target` |
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
| `test_take_profit_at_open` | open 已越 target → fill at open | T5 |
| `test_indicator_exit_next_open` | exit signal bar T → fill at T+1 open | I2, T7 |
| `test_time_exit_next_open` | bars == mhb → next bar open fill | T7 |
| `test_one_trade_per_instrument` | 持仓期间 entry 信号忽略 | I5 |
| `test_end_of_data_force_close` | 最后 bar 仍持仓 → close fill | T8 |
| `test_cost_commission_flat` | commission_bps 正确扣减 | cost model |
| `test_cost_financing_proportional` | financing 按天计 | cost model |
| `test_long_short_symmetry` | 同 OHLC long/short 对称 | I2, T1-T2 |
| `test_deterministic` | 同输入同输出（多次） | 确定性 |
| `test_golden_trades_vs_nova` | 对 nova 真实 trades.csv 子集逐字段 diff=0 | 全部 |

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

- [x] entry fill 在 T+1 open，不在 T close（I2）。
- [x] stop 是 2%（I3），不可放宽（0004 已保证，0005 只执行）。
- [x] stop 优先于 target（I4）。
- [x] 一标的一笔（I5）。
- [x] 成本公式与 nova `trades.py` 逐字段一致（commission flat + financing 按天 + slippage 在 price 里）。*注：financing 的"天"=自然日（与 nova 一致），与 O15/R4 交易日口径冲突 → 见 §5 未决项 O-0005-1。*
- [x] 纯函数、确定性、无全局状态。
- [x] 与 nova `trades.simulate` 直接逐字段 diff=0（field-for-field cross-check，见 §5 偏差说明）。

**golden test 处置**：§6 原计划以 nova `runs/*/trades.csv` 为 oracle 的 golden test，因 nova runs 不携带 market bars（只有 signals/trades 产物），无法离线重放输入 bars，故降级为**与 nova `simulate` 直接逐字段 cross-check**（更强：同输入双实现 diff=0）。待 0006 runner 接入真实 bronze→bars 后，再补真实数据 golden test。

### 对抗性自检（计划）

| 攻击点 | 发现 | 处置 |
|---|---|---|
| 同 bar open 同时越 stop 和 target | 如果 target 先判，作者会少亏 2%+ 多赚 tp%，语义翻转 | stop 先判（I4），golden test 覆盖 |
| gap 超过 2% 时 fill 在 stop 还是 open | fill 在 stop 会虚报 P&L（实际 gap 价成交） | fill 在 open（T3），gap loss 真实 |
| slippage 加两次（price 里一次 + costs 里一次） | 成本虚高一倍 | slippage 只在 T1/T2 price 里，costs 只有 commission+financing |
| financing 按 bar 数而非天 | 跨周末/假日时成本失真 | 按天（`total_seconds()/86400`），与 nova 一致 |
| max_holding_bars 边界（== 还是 >） | 多/少 hold 1 bar | nova 是 `>=`，lyra 同（T7） |
| 跨 instrument 信号泄漏 | per-instrument 单线程，无并行 → 无泄漏 | 0005 只接 single-instrument bars，0006 runner 负责隔离 |
| entry_long 和 entry_short 同时 TRUE | 歧义 | nova 是 `bool(long) != bool(short)` 才入场，lyra 同 |

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-08 | 0.1 | 初稿：确定 trade engine 边界、API、不变量（T1-T8）、测试矩阵、golden test 硬门槛、对抗性自检 7 条。待用户审阅后实施。 |
| 2026-11-08 | 0.2 | 实施完成：`lyra/trade_engine.py` + `tests/test_trade_engine.py`（23 测试全绿）。自检 7 条全通过；对抗性自检 7 条全通过（含 gap>2% fill 在 open、slippage 不双计、bool(long)!=bool(short) 等）。与 nova `trades.simulate` field-for-field cross-check diff=0。golden test 降级为 cross-check（nova runs 无 market bars），§6/§8 已标注。记录两行偏差（exit_time_precision 精简、signal_time 用 bar open）。**新发现未决项 O-0005-1**：financing 天数口径（nova=自然日 vs R4/O15=交易日），当前按 nova 自然日，标记 OPEN 待用户拍板。 |
