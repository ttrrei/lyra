# 决策 0016 — Run 产物不可变与本地复用

> **English**: [0016-run-immutability-and-local-reuse.en.md](./0016-run-immutability-and-local-reuse.en.md)
>
> 范围：固定同一 `run_id` 只生成一次；完成的 run 目录不再被重复回测覆盖。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0016` |
| 标题 | Run 产物不可变与本地复用 |
| 状态 | 已批准 / Approved |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-25` |
| 相关需求 | `docs/requirements.md` §R5, §R6, §R8 |
| 相关 HLD | `docs/hld.md` §2.4, §2.5, §4 |
| 取代 | 修订 `docs/decisions/0006-metrics-and-runner.md` 的 I5/D5 产物写入细节 |

## 1. 问题

当前 runner 在执行信号 SQL 和回测后才计算 `run_id`，并用 `mkdir(exist_ok=True)` 直接覆盖同路径产物。再次请求相同 run 会重新执行并改写本应不可变的 OCI 路径；不同日期目录也可能重复存放同一身份。

## 2. 背景

- 决策 0006/I5 定义 run 身份和确定性产物；manifest 的 `generated_at` 被明确排除在字节确定性承诺之外。
- 决策 0013 将 `market_data_snapshot_id` 加入新 run 产物，同时保留原 `run_id` 输入；旧 run 不回写，缺少字段时按 `missing_*` fail-closed。
- OCI 将 `runs/**` 视为不可变对象，同路径不同内容必须拒绝。
- R5 要求 `report.md` 保留 git commit；0006 D5 要求 manifest 记录 git commit。二者均继续保留。

## 3. 方案

### 3.1 做什么

1. 在执行策略信号 SQL 和 trade simulation 前，使用 catalog 中目标 view 的 instrument 集合计算 `market_data_snapshot_id`、`data_digest` 和现有 `run_id`。这些身份输入及公式不变。
2. 先在本地 `runs/<name>/*/<run_id>/` 查找所有日期目录。完整性校验要求 manifest 中的 run ID 相符，所有列出的 artifact 均存在且 SHA256 相符；CLI 运行还要求 `run_meta.json` 存在。找到完整 run 时加载 `metrics.json` 返回结果，不执行策略 SQL / simulation、不写任何 run 文件。发现不完整、校验失败或同一身份存在内容不同的多个完整副本时，报错并保留所有目录，不覆盖。
3. 新 run 的全部文件先写入目标日期目录旁的临时目录，包含 CLI 提供的 `run_meta.json`；manifest 最后写入。完整写入成功后以同文件系统原子 rename 发布。目标路径若已出现则拒绝覆盖。
4. 新写 `run_meta.json` 的 `strategy_path` 使用相对 workspace 的路径。复用历史 run 时不修订其 sidecar。
5. 从 manifest 删除 wall-clock `generated_at`；保留 manifest 的 `git_commit` 和报告中的 `git commit`（R5/D5）。从 metrics 删除仅供报告转发且无独立保留要求的重复 `git_commit` 字段，报告生成器单独接收同一 git commit。git commit 取 Lyra 源码仓库的 HEAD，不受调用者当前工作目录影响。相同代码树与相同输入生成逐字节相同的全部 run 文件；跨 commit 不承诺字节一致。
6. 真实执行追加一行 JSONL 到 workspace 的 `research-batches/run-executions.jsonl`，记录 run ID、run 路径、执行时间、git commit 和命令行。该审计日志不属于 `runs/`，不在 backup 的同步顶层范围内；记录失败只 WARN，不改变已完成 run。
7. 更新 0006、0007、0013 的双语决策修订指针，明确旧 run 不回填、不覆盖。

### 3.2 不做什么

- 不改变 `_compute_run_id` 的 payload，不增加 `git_commit`、`code_digest` 或 artifact schema 到 run ID。
- 不改指标定义、指标数值、trade engine 或 R5 报告字段。
- 不回填旧 run，也不删除本地或 OCI run。
- 不在本决策实现 OCI 查询；跨机器复用由 0017 处理。

### 3.3 边界

- 本地完整 run 是缓存命中；验证失败必须 fail-closed，不得静默修复或覆盖。
- `run_meta.json` 是 CLI 归属 sidecar，不纳入 manifest 的 artifact SHA 清单；新 run 与 run 目录一起发布，CLI 复用时不重写。
- OCI 保持只读源事实；此决策不发起任何上传。
- 新增的相对 `strategy_path` 只用于新 run。历史 sidecar 原样保留。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I5 | 同代码树、同输入的确定性产物逐字节一致；身份变化沿用既有 `run_id` 规则 | 0006 I5 / 本决策收紧 `generated_at` 例外 |
| I17 | 已完成 OCI run 路径不可变，同路径异内容拒绝 | 0007 / OCI alpha layout |
| R5 | 报告保留 git commit 与既定指标语义 | Requirements §R5 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_local_run_reuse_skips_execution_and_writes` | 完整命中时不执行 SQL/simulation，所有文件字节与 mtime 不变 |
| `test_local_run_reuse_searches_all_dates` | 相同 run ID 在任意 UTC 日期目录可命中，不产生重复目录 |
| `test_local_run_reuse_rejects_corrupt_or_ambiguous` | 缺失文件、SHA 错误或内容冲突副本 fail-closed |
| `test_run_write_is_atomic` | 写入中断不发布半成品目标目录 |
| `test_run_artifacts_deterministic_for_same_tree` | 同代码树/输入、不同时间和 cwd，manifest/metrics/report/run_meta/parquet 字节相同 |
| `test_run_report_keeps_git_commit` | 报告保留 R5 的 git commit；metrics 数值不变 |
| `test_run_execution_audit_is_outside_backup_scope` | 实际执行日志写入 workspace，backup 路径规划不纳入该日志 |

## 6. 回滚

- 代码层面：revert 实现本决策的 commit。
- 数据层面：不要求删除或改写任何 run；新布局仍兼容现有目录读取。
- 已写入的本地审计 JSONL 可保留；它不影响 run/OCI 身份。

## 7. 审批

- [x] 用户 review（执行计划 v2）
- [x] AI review（另一模型；确认缓存命中可在执行 SQL/simulation 前复用，且需 CLI 不重写 sidecar）
- [x] 测试全绿（pytest 441 passed / 2 skipped、pyflakes、alpha-gate）
- [ ] OCI 端到端写入（不属于本决策；OCI 只读验证另行记录）

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-25 | 0.1 | 提案：同 run ID 本地只写一次、复用完整产物、拒绝覆盖并原子发布。 |
| 2026-11-25 | 0.2 | 用户批准执行计划 v2；第二模型复核无阻塞项，明确 run 身份在策略 SQL/simulation 前计算，CLI 复用时不重写 sidecar。 |
| 2026-11-25 | 0.3 | **澄清确定性边界**：`_git_commit()` 在 HEAD 短哈希后附加 `+dirty`，且 `git status --porcelain` 把未跟踪文件也计入（如本仓库的 `PROMPT/`）。因此"相同代码树"包含 dirty 状态：同一 HEAD 的干净检出与 dirty 检出会产生不同字节（manifest 与 report 均变）；跨机器复用依赖 0017 的只读 OCI 预检，预检不可用且字节已变时按 fail-closed 手册处理，绝不覆盖 OCI。此为 0006 M4 已接受风险的显式继承，不改变 `_compute_run_id` 的 payload。 |
