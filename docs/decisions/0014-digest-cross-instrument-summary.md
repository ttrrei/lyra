# 决策 0014 — 候选池摘要跨标的统计与兄弟比较中位数重排

> **English**: [0014-digest-cross-instrument-summary.en.md](./0014-digest-cross-instrument-summary.en.md)
>
> 范围：增强 `lyra digest` 输出宏观跨品种稳健性汇总，并重构 `lyra compare --siblings` 排序机制为基于中位数年化收益排序，杜绝单品种偏科的幸存者偏差。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0014` |
| 标题 | 候选池摘要跨标的统计与兄弟比较中位数重排 |
| 状态 | 提案 |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-22` |
| 相关提案 | 无 |
| 相关需求 | `docs/requirements.md` §R5, §R12 |
| 相关 HLD | `docs/hld.md` §4 (I7, I22), §8 |
| 取代 | 无（增强 workflow 与 CLI 展示逻辑） |

## 1. 问题

在现有的 `lyra digest` 中，每个候选分支仅展示前 8 个标的的简单单行指标，剩余 13 个标的被直接截断省略（`(+13 more instruments omitted; see report)`），缺乏跨品种宏观稳健性汇总（如中位数年化、中位数净收益、正收益品种比例、最差品种等）。同时在 `compare_siblings` 中，原先以跨品种最高单品种年化收益（`best`）进行展示和对比，违背了工具自身警示的单品种选择偏差（choice bias），诱导研究者和 AI 陷入单点爬山与过度拟合。

## 2. 背景

- **R5 与 I7 契约**：系统实行严格的单品种独立核算（I7: Per-instrument reporting），禁止直接相加收益构成组合。然而在横向评估候选策略的泛化能力时，跨品种统计特征（如中位数与正收益比例）是衡量策略稳健性的核心依据。
- **Pilot 实测撞墙证据（2026-11-22）**：在 `failed_breakout/pilot` 轨道的 Pilot 评估中，21 标的运行输出直接被截断，研究者无法一眼看出策略是全品种普遍正收益还是仅依赖单个偏科品种；而 `compare` 输出的 `best` 往往掩盖了其他 20 个品种全军覆没的现实。

## 3. 方案

### 3.1 做什么

全部计算均基于 `_runs_for_branch` 已加载的 metrics 数据进行纯内存投影，不新增任何外部依赖与底层数据表。

1. **`render_digest()` 每分支增强**：
   - 提取跨品种中位数：`median_annualized`、`median_net_return`、`median_expectancy`；
   - 计算盈利品种比例：`profitable_instrument_ratio = count(ann > 0) / len(universe)`。其中预期 universe = `per_instrument 键 ∪ instrument_failures`，包含零交易与失败品种，严禁悄悄剔除；
   - 样本量与执行完整性：统计总交易笔数、<20 笔低样本品种数、失败品种数。若存在失败品种或实际完成品种数少于预期，显式标注 `[Incomplete]`；
   - 暴露最差品种：标注单品种表现最差者（标的名与年化收益），单品种偏科严重是关键淘汰依据；
   - 压缩逐品种展示，保证 8 分支活跃池总文本尺寸控制在 ≤ ~5KB。
2. **`compare_siblings()` 排序与高亮重构**：
   - 将排序与主对比指标从 `best` 切换为 `median_annualized`；
   - 保留原单品种最高项为 `best_single_instrument`，并明确标注"最好的一次，非综合分"（single best, not aggregate）；
   - 顶层输出全池汇总：`median_annualized`、`min_annualized`、`median_profitable_ratio`、`incomplete_count`；
   - 不可比（`comparable is False` 或 `comparable is None`）的 run 列出具体原因，并排除出正式排名，置于末尾。
3. **不做 pool_score**：
   - 不引入单一硬编码复合评分（如 pool_score 或加权公式），保持透明维度展示供决策。

### 3.2 不做什么

- 不改动 `lyra/metrics.py` 的指标公式与单品种核算口径（保持 R5 冻结）；
- 不做跨品种资金组合聚合（不计算组合净值、Sharpe、CAGR）；
- 不引入数据库或磁盘持久化统计中间表；
- exit-month 诊断尾巴视配额情况明确记录或移交计划 3 §2.0。

### 3.3 边界

- **完全只读**：`render_digest` 与 `compare_siblings` 维持完全只读契约，不写盘。
- **缺失与异常处理**：0 笔交易品种计入分母，年化视作 0.0；失败品种计入分母，不漏报。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I7 | 单品种核算隔离：不构建跨品种投资组合净值，中位数仅作为横向分布参考 | HLD §4 |
| I22 | 比较证据链：只有相同底层行情的可比候选才参与中位数排名 | HLD §4 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_0014_run_stats_math` | 验证 median/min/ratio 计算数学准确性 |
| `test_0014_run_stats_empty_runs` | 空 runs / 无交易安全降级 |
| `test_0014_run_stats_single_instrument` | 单品种数据集边界情况 |
| `test_0014_run_stats_zero_trade_instruments` | 零交易品种必须计入 universe 分母且不计入盈利分子 |
| `test_0014_run_stats_instrument_failures` | 失败品种计入 universe 分母并触发 Incomplete 标记 |
| `test_0014_compare_siblings_median_sort` | 兄弟比较按 median_annualized 正确降序重排，排除不可比分支 |
| `test_0014_digest_size_budget` | 8 分支活跃池下的 digest 文本体积 ≤ 5KB |

## 6. 回滚

通过 git revert 回退 commit C4。所有变动均为纯 Python 展现层与只读聚合计算，不影响任何落盘数据结构。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] 真实 Pilot 数据验证通过

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-22 | 0.1 | 初版提案：digest 跨品种统计与 compare 中位数排序。 |
