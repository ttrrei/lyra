# 决策 0018 — apply-batch 原文先行归档

> **English**: [0018-archive-batch-before-parse.en.md](./0018-archive-batch-before-parse.en.md)
>
> 范围：真实 `apply-batch` 在解析前先将用户提交的原始 bundle 保存在 workspace；dry-run 仍零写入。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0018` |
| 标题 | apply-batch 原文先行归档 |
| 状态 | 已批准 / Approved |
| 创建日期 | `2026-11-25` |
| 相关需求 | `docs/requirements.md` §R12 |
| 相关 HLD | `docs/hld.md` §2.5, §4 (I15, I17) |
| 相关决策 | 0007、0015、0017 |

## 1. 问题

当前 `apply-batch` 先读取并解析 bundle，随后才创建 `batch-NNNN.yaml` 归档。YAML 语法错误或 schema 解析失败会在归档之前退出，丢失被拒绝提案的原始内容，不利于复盘 AI 的输入与拒绝原因。

## 2. 方案

1. 非 dry-run 命令读取 bundle 原始 bytes 后，立即以 exclusive-create/atomic publish 写入 workspace intake，再解码和调用 `parse_batch`。intake 位于 `research-batches/_intake/`，使用随机不可碰撞文件名；即使 UTF-8 解码或 YAML 解析失败也保留原始 bytes。intake 写失败只 WARN，继续原有命令流程。
2. `parse_batch` 成功且所有候选共用同一安全 direction/track 后，将原文移入 `research-batches/<direction>/<track>/batch-NNNN.yaml`，沿用现有 ident 校验与该目录单调编号；混合 direction/track 的整包不得归到首项名下，改放 `_unparsed/unassigned/`。完整 preflight/adoption/run 结果写同一个编号的 `batch-NNNN-result.md`；不再二次创建 bundle 或分配第二个编号。
3. 解析失败时，尽力从安全且可解析的元信息中提取并验证一致的 direction/track；若 YAML/UTF-8 无法解析或路径身份无效，将原文保留在 `research-batches/_unparsed/unassigned/`，旁边写明失败原因。任何归档/移动/结果写入失败均 WARN，不改变 `apply-batch` 的原错误或执行结果；移动失败时 intake 原件保留。
4. Dry-run 完全不创建 intake、结果或任何其他归档文件，保持现有零写入契约。已有归档 API 的行为保持兼容；新 intake/finalize helpers 仅服务 apply-batch。

## 3. 边界

- 只归档用户传入 bundle 的原始文本；不将策略绩效、真实 OCI 内容或 credentials 写入 git。
- bundle 原文在完整解析/校验前已落盘；迁移到编号目录失败时保留 `_intake/` 原件，不丢失输入。
- 不改变 bundle 解析、validation、all-or-nothing adoption 或 run 语义。

## 4. 测试

| 测试 | 场景 |
|---|---|
| `test_apply_batch_archives_raw_bundle_before_parse_failure` | malformed YAML 在退出前原文已归档且带失败原因 |
| `test_apply_batch_archives_parseable_preflight_rejection` | schema/preflight 拒绝仍归档在 direction/track 下 |
| `test_apply_batch_dry_run_does_not_archive` | dry-run 不创建 intake 或归档内容 |
| `test_apply_batch_archive_failure_warns_and_continues` | intake/归档写失败只 WARN，不改变原命令结果 |

## 5. 审批

- [x] 用户 review（执行计划 v2）
- [x] AI review（第二模型；复核通过，见修订记录 0.2）
- [x] 测试全绿（pytest 451 passed / 2 skipped、pyflakes、alpha-gate）

## 6. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-25 | 0.1 | 提案：apply-batch 解析前先存原文，解析拒绝和 dry-run 边界明确。 |
| 2026-11-25 | 0.2 | 第二模型复核后明确按原始 bytes 先归档；仅一致且安全的 direction/track 可路由到编号目录，mixed/不可识别内容留在 `_unparsed/unassigned`；不重复分配 bundle 编号，失败时保留 intake。 |
