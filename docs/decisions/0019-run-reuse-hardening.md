# 决策 0019 — Run 复用加固：提示、验证、归属与数值金标

> **English**: [0019-run-reuse-hardening.en.md](./0019-run-reuse-hardening.en.md)
>
> 范围：一次核对（无代码）+ 一个实现 commit。不改 `run_id` 构成，不改产物格式。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0019` |
| 标题 | Run 复用加固：提示、验证、归属与数值金标 |
| 状态 | 已批准 / Approved |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-26` |
| 相关需求 | `docs/requirements.md` §R5, §R6, §R12 |
| 相关 HLD | `docs/hld.md` §2.4, §2.5, §4 (I5, I17) |
| 相关决策 | 0006、0016、0017、0018 |

## 1. 问题

0016 的本地复用与 0017 的 OCI 预检解决了"同一计算只写一次"，但复审指出一个真实体感问题：代码变化后，同一条分支仍会命中旧缓存并静默返回旧结果，用户无法从输出判断结果由哪个实现产出，也没有低代价手段核对"数值是否真的没变"。此外，相同策略内容（含内部 id）在不同 branch 下会算出同一个 `run_id`，复用时缺少归属校验。

独立复审曾建议把 `code_digest` 与 `artifact_schema_version` 加入 `run_id`。**该建议已否决**：改一行注释或一处报告格式就会让所有策略生成新 run_id、新路径，等于全量重测并堆积重复 run，与"数据和指标没变就不该重测"的目标相反。已定的替代方案是：`run_id` 构成不变；数值语义真的变化时手动递增已在 payload 内的 `_ENGINE_VERSION`，产生新身份、新路径，旧 run 保留。

## 2. 已定边界（不重新讨论）

- 不改 `_compute_run_id` 的 payload，不新增 `code_digest` / `artifact_schema_version` / `git_commit` 身份字段。
- 不改 manifest / metrics / report 的现有字段与格式；产物里的 git commit 继续保留（R5）。
- 不新增 `--recompute` / `--force` 或任何写回已有 run 路径的入口；不回填旧 run（v02a/v02b）。
- "本机无 run + OCI 预检不可达 + 此后 commit 已变 → push fail-closed"是 0016 已接受的残余风险，不是缺陷，本决策不试图消除它。

**`_ENGINE_VERSION` 递增规则**：仅当同一策略、同一数据下 signals / trades 或 metrics 的**数值**会发生变化时才递增（交易逻辑变化、指标公式或数值变化）。仅新增产物字段、改报告措辞、纯重构、改注释**不递增**。递增必须伴随同一 commit 更新数值金标（见 §3.4）与本决策修订行。

## 3. 方案

### 3.1 B1 — 复用时提示产出实现

- 触发：本地命中或 0017 预检恢复后复用（`RunResult.reused=True`）。
- 动作：读该 run 的 `manifest.json` 中记录的 git commit，与当前工作树的 git commit（含 dirty 标记，沿用既有记录方式）比较。不同时在 `reused existing run <id>` 之后追加一行：
  `note: 该 run 由 commit <旧> 产出，当前为 <新>；未重算。用 --verify 核对数值；仅当数值语义变化时才需递增 _ENGINE_VERSION（会生成新 run_id）。`
- 相同则不提示；manifest 无该字段（旧格式）显示 `legacy`；git 不可用（返回 `no-git`）则跳过提示。
- 仅提示，不阻断、不改退出码、不写任何文件。

### 3.2 B2 — `lyra run --verify`（只验证，永不写入）

- 前置：对应 run 已在本地存在且完整（沿用 `_load_complete_run` 校验）；不存在则报错退出并提示先运行或拉取。**不触发 OCI 预检**。
- 动作：用当前代码在**系统临时目录**重算同一输入，与已存档产物逐项比较；staging 必须不在 `runs/` 之下，完成后删除，不向 `runs/` 写任何内容。`--out` 仅用于定位已存档 run（只读），不提供任何写回开关。
- 三档结果：
  1. `IDENTICAL` — 全部产物字节相同。
  2. `DESCRIPTIVE_ONLY` — `signals` / `trades` 字节相同、metrics 指标数值相同，仅 manifest / report 的描述性内容不同；逐项列出差异字段名。
  3. `NUMERIC_DIFFERENCE` — signals/trades 字节不同或 metrics 数值不同；打印品种与指标名，并提示评估递增 `_ENGINE_VERSION`。
- 退出码：前两档 0，第三档 2。

### 3.3 B3 — 复用时校验归属

- 复用前读 `run_meta.json` 的 `branch` / `track_id`（旧格式也接受 `track` 键）。
- 当前调用的 `branch` 由策略文件名确定；`track` 仅 `--track` 给定时确定（`apply-batch` 会传）。
- 不一致 → fail-closed：`该 run_id 已存在于 branch <旧>（track <旧>）；相同的策略内容（含内部 id）在 branch <新> 下不能复用。若确为新的候选，请修改 YAML 的实质内容（含 id）或使用新的 slug。` 不写任何文件。
- 旧格式缺 `branch` / `track_id` → WARN 一行后继续复用，不阻断。
- **范围**：branch 比较覆盖所有复用路径（本地命中与 OCI 恢复）；track 比较只在 `--track` 可确定时生效，裸 `lyra run <file>` 不做 track 比较。此范围同时记入 HANDOFF。

### 3.4 B4 — 数值金标测试

- 用测试已有的合成数据与策略夹具固定一个虚构样例 run；钉住 `signals.parquet` / `trades.parquet` 的 SHA256 与 `metrics.json` 的指标数值（不含 git commit 等描述字段）。
- 失败文案固定为："数值输出变化。如果这是有意的数值语义变化：递增 `_ENGINE_VERSION`，并在同一 commit 更新本金标和决策文档。如果不是有意的：说明引擎被意外改动。"
- 金标只钉数值，不钉 manifest / report 的描述性字节。

### 3.5 B5 — 文档与测试漂移

- 0016 §5 列出的 `test_run_artifacts_deterministic_for_same_tree`、`test_run_report_keeps_git_commit` 在 `tests/` 中不存在。同等行为已由 `test_run_reproducible_identical_manifest` 覆盖（同输入字节相同、无 `generated_at`、报告仍含 git commit）。按 append-only 规则在 0016 追加一行修订写明实际测试名，不改旧行。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I5 | 同输入确定性产物；复用不重写；数值变化必须经 `_ENGINE_VERSION` 显式表达 | 0006 I5 / 0016 / 本决策 |
| I17 | OCI `runs/**` 不可变；验证与提示均为只读，不存在覆盖入口 | 0007 / 0016 / 0017 |
| R5 | 报告继续列出 git commit；指标定义与数值冻结 | Requirements §R5 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| B1 提示 | manifest commit 与当前不同 → 提示；相同 → 无提示；旧格式 → `legacy`；不改退出码、不写文件 |
| B2 验证 | `IDENTICAL` / `DESCRIPTIVE_ONLY` / `NUMERIC_DIFFERENCE` 三档各一；缺失 run 报错；真实 runs 目录内容与 mtime 不变；不触发 OCI |
| B3 归属 | branch/track 不同 → fail-closed 且零写入；相同 → 正常复用；旧格式缺字段 → WARN 后复用；覆盖本地命中与预检恢复 |
| B4 金标 | 金标通过；人为改动引擎数值后失败且文案含"递增 `_ENGINE_VERSION`" |
| B5 漂移 | 0016 修订行写明实际测试名 |
| 回归 | 0016/0017/0018 既有测试零回归；R5 数值零变化；`_compute_run_id` payload 键集合固定 |

## 6. 回滚

- 代码层面：revert 实现本决策的单个 commit；`--verify` 与提示、归属校验消失后，0016/0017 行为恢复原状。
- 数据层面：不要求删除或改写任何 run；本决策不写 `runs/`。
- 金标常量随 revert 一并回退；历史 run 不受影响。

## 7. 审批

- [x] 用户 review（任务说明 new.md）
- [ ] AI review（第二模型；本次未单独执行）
- [x] 测试全绿（pytest / pyflakes / alpha-gate）
- [ ] OCI 端到端写入（不在本决策范围）

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-26 | 0.1 | 提案：复用提示、只读 `--verify` 三档验证、归属 fail-closed、数值金标与测试名漂移修订；明确否决 code_digest / schema_version 入 run_id，明确 `_ENGINE_VERSION` 递增规则。 |
