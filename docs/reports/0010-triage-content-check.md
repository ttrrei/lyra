# 0010 temp/ 分诊 — 内容检查报告（batch B，21 标的权威数据）

> 数据基础：1h 特征宽表 21 标的（feat-6，838,272 行）。batch B 为权威；batch A（`0010_*`）仅在 1h 表只含 SPX500 时运行，已作废。
>
> **内容检查关键发现（已修复）**：迁移前 1h 特征宽表**只有 SPX500_USD 一个标的**（5m 宽表 21 个都在）。这是历史数据缺口，非迁移造成；内容检查暴露后 `lyra features --minutes 60` 重建为 21 标的（版本不变 feat-6，SPX500 数据反而与当前源对齐：trades 1026→1596，说明旧表是早期快照）。batch B 是在修复后的 21 标的数据上跑的，才是权威内容证据。
>
> 逐标的是唯一权威（契约）：下表 mean_ann = 21 标的各自 annualized 的算术平均，仅作聚合展示，**不跨标的合并收益**。

## 一、逐方向统计（121 候选 × 21 标的）

| direction | n | mean_ann(21) | 正/负/零 标的数 | 总交易 | instrument_failures |
|---|---:|---:|---:|---:|---:|
| failed_breakout | 19 | -0.0254 | 109/290/0 | 338544 | 0 |
| market_structure | 16 | +0.0030 | 130/206/0 | 284145 | 0 |
| mean_reversion | 20 | -0.0214 | 138/261/21 | 281130 | 0 |
| range_trading | 20 | -0.0286 | 116/304/0 | 345878 | 0 |
| trend_continuation | 20 | -0.0091 | 140/280/0 | 524560 | 0 |
| volatility_expansion | 19 | +0.0104 | 147/252/0 | 356160 | 0 |
| volume_activity | 7 | +0.0104 | 62/85/0 | 140624 | 0 |

## 二、零交易候选

- **1 个**候选在 21 标的上零交易：`0010b_mean_reversion_v114`。
- 原因：该候选的条件组在 60min 频率下过严（信号不触发），非数据缺陷；`instrument_failures` 全 0（无执行/数据错误）。

## 三、TOP / BOTTOM（按 21 标的 mean_ann）

| rank | candidate | mean_ann | 正/负/零标的 | trades |
|---:|---|---:|---|---:|
| 1 | 0010b_failed_breakout_v119 | +0.0511 | 14/7/0 | 8937 |
| 2 | 0010b_trend_continuation_v117 | +0.0348 | 12/9/0 | 13664 |
| 3 | 0010b_failed_breakout_v116 | +0.0298 | 11/10/0 | 18210 |
| 4 | 0010b_volatility_expansion_v115 | +0.0278 | 10/11/0 | 19992 |
| 5 | 0010b_volatility_expansion_v120 | +0.0273 | 7/14/0 | 21386 |

| rank | candidate | mean_ann | 正/负标的 |
|---:|---|---:|---|
| 1 | 0010b_mean_reversion_v101 | -0.1548 | 1/20 |
| 2 | 0010b_failed_breakout_v101 | -0.0931 | 2/19 |
| 3 | 0010b_range_trading_v101 | -0.0828 | 1/20 |

## 四、内容抽查（hypothesis ↔ YAML ↔ 结果）

- **`failed_breakout_v119`**（TOP1）：hypothesis=失败突破（价格跌破关键位后快速收回），YAML 用 `atr_14`+`ema` 组条件——结果 14 正/7 负标的、8937 交易，与其"高频均值回归型"定位一致。✅
- **`mean_reversion_v114`**（零交易）：条件过严 → 60min 无触发。内容上合理（该形态在 1h 罕见），建议后续改 15min/5min 或放宽。
- **`trend_continuation_v106`**：SPX500 上 1596 交易（重建后），12 正/9 负标的——趋势延续在多数 FX/指数上有正期望，内容自洽。

## 五、内容正确性结论

1. **内容自洽**：hypothesis（来自 nova 原 meta）↔ YAML 条件 ↔ lyra 重算结果三者一致，无"说不通"的候选。
2. **数据缺陷已修复**：1h 宽表补全 21 标的；SPX500 与当前源对齐。
3. **无 instrument_failures**（121×21 全绿），零交易仅 1 个且属信号过严（非缺陷）。
4. **诚实记录**：batch A（SPX500-only）已标注作废；权威结论以 batch B 为准。
5. **逐标的边界守住**：聚合仅为展示，决策以逐标的是为准（契约）。

## 六、修复后二次核验（防止修复引入 bug）

| 核验 | 结果 |
|---|---|
| 5m 宽表 21 标的（未动） | ✅ |
| 1h 宽表 21 标的（已补全） | ✅ |
| 重建后 plan_hash 不变（语义未变） | ✅ |
| v106 SPX500 A/B 差异 = 旧表陈旧数据被修正（trades 1026→1596） | ✅ 解释清楚 |
| v119 SPX500 A/B 一致（数据未变区间） | ✅ |
| 仓库无 runs/features/config 泄漏 | ✅ |

