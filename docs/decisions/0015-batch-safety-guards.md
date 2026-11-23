# 决策 0015 — 批量候选提交护栏与留痕

> **English**: [0015-batch-safety-guards.en.md](./0015-batch-safety-guards.en.md)
>
> 范围：在 `apply-batch` 提交前锁定 track 成本、标记结构相似度与复杂度、并将真实批次归档到 workspace。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0015` |
| 标题 | 批量候选提交护栏与留痕 |
| 状态 | 提案 |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-23` |
| 相关提案 | 无 |
| 相关需求 | `docs/requirements.md` §R4, §R9, §R12 |
| 相关 HLD | `docs/hld.md` §2.3, §4, §8 |
| 取代 | 无 |

## 1. 问题

批次目前可以在没有显式护栏的情况下提交改变执行成本的候选，也不会标出只改窗口或阈值的近似分支。实际批次亦缺少可追溯的 workspace 留痕，难以汇总提出、拒绝、运行和去留结果。

## 2. 背景

- 0012 要求每批 3–4 个结构不同候选、同一 direction/track、成本与基线一致。
- `ExecutionMeta` 将四项成本保存为 `float | None`；未设置保持 `None`，显式 `0` 保持 `0.0`。交易引擎对成本计算将两者都按零成本处理，但提交校验保留二者差异，避免把未声明误当成已声明。
- `stop_loss_pct` 不是可选成本：schema 将其规范化为强制 `0.02`，所以它不属于四字段成本锁定；批次与基线都应遵守同一个强制止损契约。

## 3. 方案

### 3.1 做什么

1. `apply-batch` 要求一个 bundle 恰有 3–4 个候选，且全批共用一个 direction/track。全量预检期间读取该 direction 的共享只读 `v01.yaml` 基线。四个成本字段逐项比较，包含 `None` 与显式零的区别；批内候选也必须一致。任一不一致时整批零写入并给出修复说明。所有四项均为零或未设置时打印醒目 WARN，但与基线一致时允许提交。
2. 在 `strategy_schema` 提供纯函数 `ast_complexity(spec)` 与 `structural_signature(spec, registry)`。复杂度返回 feature 引用数、AST 节点数、叶子数、最大深度，以及 entry/exit 条件数。签名分别描述 long/short 的 entry/exit 树；比较结构节点、操作符和规范化 feature，参数保留常量、窗口和时间算子 bars。窗口规范化映射由传入 registry 的完整名称集构造：仅替换名称末尾以 `_` 分隔且属于 `{6, 12, 24, 60, 120}` 的窗口段；粘连数字不变。Alpha/未知名称不经映射并保持原样。结构变化、参数变化、完全相同分别标为 `structural_change`、`parameter_only`、`identical`；exit 树差异另设 `exit_structure_changed`。复杂度/签名只提示，不拒绝候选。
3. 每次真实提交（dry-run 除外）都归档原 bundle 和 `result.md` 到 workspace `research-batches/<direction>/<track>/batch-NNNN.*`，包括预检拒绝的零写入尝试。编号在对应目录内单调递增，路径段执行既有 ident 校验并约束在 workspace 内。结果记录提出、预检拒绝及原因、采用、OK/PARTIAL/失败计数、每次运行的实际 run ID（未产生时记录原因）和去留结论槽位。归档写入失败只发 WARN，不改变 adopt/run 结果；归档及真实策略内容绝不进入 git。
4. digest 对候选最近的签名分类添加紧凑提示；apply-batch stdout 与 workspace result 同时给出复杂度和同轨活跃分支的近似关系。

### 3.2 不做什么

- 不因结构相似、复杂度或样本数硬拒绝；不添加 BatchItem 放行字段。
- 3–4 个候选及单 direction/track 是 P3 批次契约的形状校验，不是表现门槛。
- 不改 `metrics.py`、trade engine、R5 指标口径，不引入 GA、数据库、模型 API、pool score 或 Holdout。
- 不把批次归档、真实假设、策略或绩效写入 git。

### 3.3 边界

- bundle 形状与成本预检在任何 workspace 写入之前完成，dry-run 与真实 apply 使用同一预检逻辑。真实提交即使预检拒绝，也会尝试留下批次档案。
- 签名对注册表中每个特征名称建立明确映射并以覆盖测试约束；未知/alpha 特征名称保持原样，不做猜测式数字剥离。
- 归档按 workspace 的本地研究记录处理，不是 OCI 同步对象。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| R4 | 强制 2% adverse-price stop 不可变 | Requirements §R4 |
| R5 | 指标输出语义冻结 | Requirements §R5 |
| R12 | 每 track 最多 8 个 active branch；先 prune 后 apply | Requirements §R12 / 0012 |
| B13/B14 | 真实策略及批次档案在仓库外，examples 是唯一跟踪策略目录 | AGENTS.md |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_apply_batch_cost_mismatch_is_zero_write` | 与基线或批内成本差异拒绝整批且零写入 |
| `test_apply_batch_cost_match_and_zero_warning` | 一致候选可通过，全零成本显示 WARN |
| `test_structural_signature_registered_feature_coverage` | 注册表所有特征都遵守明确窗口映射规则 |
| `test_ast_complexity_and_signature_classification` | identical、参数变化、结构变化、exit 变化分类正确 |
| `test_apply_batch_archive_numbering_and_contents` | workspace 归档编号、路径约束、计数和 run ID 正确 |
| `test_apply_batch_archive_failure_warns` | 归档失败仅 WARN，不覆盖 run 结果 |

## 6. 回滚

- 代码层面：revert C5。
- 数据层面：既有 workspace 归档保留，不删除或移动；旧代码忽略这些档案。
- 不修改 OCI、alpha、市场数据或运行产物。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 全套测试、pyflakes、alpha-gate 通过
- [ ] 真实 pilot 校准（独立于实现提交）

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-23 | 0.1 | 初稿：定义成本锁定、结构签名/复杂度提示与 workspace 批次留痕。 |
| 2026-11-23 | 0.2 | C5 已实现并完成第二模型对抗复核：成本与批形预检、结构/参数签名和复杂度提示、workspace 尝试归档及 digest 提示均已落地；归档编号冲突和拒绝文案问题已修正。全套测试 434 passed / 2 skipped，`pyflakes` 与 `alpha-gate` 通过。 |
