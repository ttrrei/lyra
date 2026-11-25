# 决策 0017 — OCI run 预检与不可变冲突处置

> **English**: [0017-oci-run-preflight-and-conflict-runbook.en.md](./0017-oci-run-preflight-and-conflict-runbook.en.md)
>
> 范围：本地没有对应 run 时，运行前只读查询 OCI 历史 backup 布局；命中且完整则恢复并复用，查询故障则告警后继续本地执行。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0017` |
| 标题 | OCI run 预检与不可变冲突处置 |
| 状态 | 已批准 / Approved |
| 创建日期 | `2026-11-25` |
| 相关需求 | `docs/requirements.md` §R6, §R7 |
| 相关 HLD | `docs/hld.md` §2.5, §4 (I17, I19, I20) |
| 相关决策 | 0006、0007、0016 |

## 1. 问题

本地复用（0016）无法防止另一台机器在本地没有旧 run 时重算同一 `run_id`，并尝试向 OCI immutable 路径上传不同字节。当前 `backup` runs 使用的 OCI 对象路径是 `runs/<name>/<date>/<run_id>/<file>`；已有 PAR list/download helper 可按 bucket 根列举并单对象下载。

## 2. 方案

1. `run_strategy` 在本地搜索未命中后、策略 SQL/simulation 前调用可选 OCI loader。CLI 仅在 `strategies_par_url` 或 fallback `data_par_url` 已配置时提供 loader；无远端配置则正常运行。
2. Loader 只读列举 OCI 根目录，筛选精确 `runs/<name>/*/<run_id>/` 下的 run 对象。若存在多个日期副本，全部下载并校验；任一副本不完整或字节不同即 fail-closed，完全相同才选一份。先下载到系统临时目录校验，再复制到目标目录旁的 staging 并二次校验，最后同文件系统原子 rename 到本地 runs。由 0016 的同一 metrics loader 返回 `reused=True`；不执行策略 SQL/simulation。
3. 无匹配对象时继续本地运行。列表/网络/授权错误只打印不含 PAR URL 的 WARN 并继续；命中对象缺文件、SHA 不符、manifest 无效或本地目标冲突时 fail-closed，不修复、不覆盖。
4. `oci_push` 的 immutable conflict 错误说明路径已存在且内容不同，并给出可执行恢复步骤：先将该 run_id 的所有本地日期副本移入 `superseded-runs/`，在 OCI 可达时用相同策略、数据、name/track/config 重跑 `lyra run`，使此预检只读恢复并校验 OCI 原件，再重新 dry-run；此处的 `pull-runs` 不适用于旧 backup 路径。预检不可用时停止并保留副本，禁止覆盖。
5. 0007 与 `lyra/ai_readme.md` 增加跨机器运行与冲突处置手册。此预检仅查询 `strategies_par_url` / `data_par_url` 下既有 backup layout；不变更 `runs_par_url`、canonical push-runs layout 或 OCI 内容。

## 3. 边界与残余风险

- 预检是 best-effort：本地无 run 且 OCI 不可达时会继续执行。若随后同一路径内容不同，push 必须 fail-closed 并按手册恢复；不会有 OCI 覆盖或静默丢失。
- 已有 PAR list/download 函数复用，未新增抽象层或改 OCI 布局。
- OCI 命中时只安装完整验证通过的 run；下载中断只影响临时目录，清理后不留下目标 run。

## 4. 测试

| 测试 | 场景 |
|---|---|
| `test_oci_preflight_restores_complete_run_and_skips_execution` | 假 OCI 命中，恢复校验后复用，策略 SQL/simulation 不执行 |
| `test_oci_preflight_miss_or_unreachable_warns_and_runs` | 无命中正常运行；查询故障 WARN 后继续 |
| `test_oci_preflight_rejects_corrupt_remote_run` | 远端 manifest/artifact 校验失败时不安装、不运行、不覆盖 |
| `test_oci_immutable_conflict_actionable_message` | 冲突信息明确禁止覆盖并给出恢复动作 |

## 5. 审批

- [x] 用户 review（执行计划 v2）
- [x] AI review（第二模型；复核通过，见修订记录 0.2）
- [x] 测试全绿（pytest 447 passed / 2 skipped、pyflakes、alpha-gate）
- [x] OCI 只读路径核验；不执行 OCI 写入

## 6. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-25 | 0.1 | 提案：复用 OCI list/download helpers 做运行前只读预检，补充 immutable 冲突恢复手册。 |
| 2026-11-25 | 0.2 | 第二模型复核后明确 OCI 同 run 多日期副本必须逐一校验并拒绝歧义；系统临时下载后复制到目标旁 staging 再原子 rename；冲突手册隔离该 run_id 全部本地副本后重跑相同命令以触发预检恢复。 |
