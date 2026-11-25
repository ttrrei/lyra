# 决策 0013 — 行情数据快照 ID 与跨特征候选可比性解耦

> **English**: [0013-market-data-snapshot-id.en.md](./0013-market-data-snapshot-id.en.md)
>
> 范围：修订 0009 D13 可比性判定维度，引入 `market_data_snapshot_id` 解耦底层行情数据一致性与策略特征消费差异。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0013` |
| 标题 | 行情数据快照 ID 与跨特征候选可比性解耦 |
| 状态 | 提案 |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-22` |
| 相关提案 | 无 |
| 相关需求 | `docs/requirements.md` §R12 |
| 相关 HLD | `docs/hld.md` §4 (I5, I22), §8 |
| 取代 | 修订决策 0009 §D13 中将 `data_digest` 用于 `compare_siblings` 的规则 |

## 1. 问题

在 0009 D13 中，`compare_siblings` 将 `data_digest` 作为判断两个 run 是否可比的第一维度。然而在 `runner._data_digest` 的实现中，策略实际消费的 feature 列被拼入 SELECT 查询并计入哈希。导致消费不同特征列的候选策略（这恰恰是结构不同候选的本质定义）即使在完全相同的底层行情数据上运行，其 `data_digest` 也必然不同，进而被判定为 `NOT COMPARABLE (incomparable — data_digest)`。这混淆了**运行复现性身份（Run Identity）**与**横向可比性身份（Comparability Identity）**。

## 2. 背景

- **0009 D13 历史**：为了防止在不同数据切片上跑出的 run 被误放进同一张表比较，0009 引入了基于 `data_digest` 的可比性校验。当时为保证特征数据微调能改变 run 身份，`data_digest` 包含了策略引用的 feature 列。
- **Pilot 实测撞墙证据（2026-11-22）**：在 `failed_breakout/pilot` 轨道的首轮测试中，3 个结构不同的候选（`v02a` 读 `efficiency_24`，`v02b` 读 `rsi_12`，`v02c` 读 `bband_pctb_24`）在完全一致的 21 标的 1h 数据上运行，但 `lyra compare --siblings` 输出：
  ```text
  comparable: NOT COMPARABLE (data_digests=3, ...)
    v02a: run <run_id_v02a> incomparable — data_digest
    v02b: run <run_id_v02b> incomparable — data_digest
    v02c: run <run_id_v02c> incomparable — data_digest
  ```
  该错误直接阻断了多候选横向有效评估。

## 3. 方案

### 3.1 做什么

1. **新增 `market_data_snapshot_id`**：
   - 在 `lyra/runner.py` 中引入 `market_data_snapshot_id(con, view, instruments)`。
   - 对 `(view 名 + 排序后的 instrument 列表 + 仅 OHLC 基础列 time/mid_o/mid_h/mid_l/mid_c 的值)` 计算 SHA-256，**严格不含任何 feature 列**。
   - 实现上直接复用 `_data_digest(con, view, instruments, feature_cols=())`，保证底层查询与哈希逻辑完全一致，杜绝两套哈希算法实现漂移。
2. **产物落盘**：
   - 将 `market_data_snapshot_id` 写入 `metrics.json` 的数据身份区（与 `feature_snapshot_id`、`feature_version`、`data_digest` 并列）。
   - 同时写入 `manifest.json` 供重放审计。
3. **保留 `data_digest` 原有职责**：
   - `_compute_run_id` 的 payload 完全不动，`data_digest` 依然参与 `run_id` 计算，确保对特征值的扰动依然会导致 `run_id` 变更（I5 复现性保证不变）。
4. **修订 `workflow._run_comparable_reason`**：
   - 将第一检查维度从 `data_digest` 替换为 `market_data_snapshot_id`；
   - 若参与比较的任意 run 缺失 `market_data_snapshot_id`（如历史遗留 run），返回 `missing_market_data_snapshot_id`，遵循 fail-closed 原则降级为 `comparable=None`（unknown，不推定可比）；
   - 保留原有的 `feature_version` 与 `feature_snapshot_id` 检查。
5. **修订 `compare_siblings` 与 CLI**：
   - 提取 `distinct_market_data_snapshots` 并展示，横向对比同一底层行情的候选分支。

### 3.2 不做什么

- 不改变 `_compute_run_id` 的算法与输入，保证历史 run_id 不失效；
- 不删除 `data_digest`（它在 metrics 和 manifest 中继续存在，承担单 run 数据完整性与精确复现性职责）；
- 不改动任何 `lyra/metrics.py` 指标计算。

### 3.3 边界

- **兼容性**：缺少 `market_data_snapshot_id` 的历史旧 run 在 `compare_siblings` 中将被识别为 missing identity 并标记为 `comparable=None`，绝不盲目假定可比。
- **与 0014 边界**：0013 解决"能不能比"（可比性地基），0014 解决"怎么比"（跨品种摘要与排序）。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I5 | Run 产物可重现性：相同输入必须产生相同 run_id 与结果，feature 扰动依然改变 run_id | HLD §4 |
| I22 | 比较证据链：兄弟候选横向比较必须建立在严格相同的底层市场行情数据之上 | HLD §4 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_market_data_snapshot_id_stable_across_features` | 同底层数据下，消费不同 feature 的策略具有相同的 `market_data_snapshot_id` 但不同的 `data_digest` |
| `test_data_digest_and_run_id_change_on_feature_perturbation` | 扰动 feature 值导致 `data_digest` 与 `run_id` 改变，但 `market_data_snapshot_id` 不变 |
| `test_market_data_snapshot_id_changes_on_ohlc_perturbation` | 扰动底层 OHLC 导致 `market_data_snapshot_id` 与 `data_digest` 均改变 |
| `test_compare_siblings_comparable_across_different_features` | 消费不同 feature 的兄弟候选在相同市场数据下被判定为 `comparable=True` |
| `test_compare_siblings_missing_market_data_snapshot_unknown` | 历史 run 缺少 `market_data_snapshot_id` 时，判定为 `comparable=None` 且原因为 `missing_market_data_snapshot_id` |

## 6. 回滚

- **代码层面**：通过 git revert 回退 commit C3。
- **数据层面**：新写入的 run 包含 `market_data_snapshot_id` 字段，回滚后旧代码会将其作为未识别 JSON 字段自然忽略，不产生破坏性影响。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] 真实 Pilot 数据验证通过

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-22 | 1.0 | 初稿：提出 `market_data_snapshot_id`，修订 0009 D13 可比性判据，解耦特征差异与行情一致性。 |
| 2026-11-25 | 1.1 | 决策 0016：新字段只随新建 run 写入；已完成历史 run 不回填或改写，缺失身份继续按 `missing_market_data_snapshot_id` 处理。 |
