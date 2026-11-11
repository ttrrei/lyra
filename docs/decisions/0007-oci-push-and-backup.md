# 0007 — OCI 双向同步 + R12 交互式工作流（push / backup / list + tracks / context / new-version / compare / merge）

> **English**: [0007-oci-push-and-backup.en.md](./0007-oci-push-and-backup.en.md)
>
> 本决策文档覆盖 0007 的两块范围（**用户裁决 2026-11-10：两者都归 0007**）：
>
> **Part A — OCI 同步层**：`lyra push` / `lyra backup`（alias `sync`）/ `lyra list`
> 与 `push-strategy` / `push-direction` 的 OCI 持久化命令（R7 核心 feature + I17
> 两级文件规则 + I19/I20 幂等与 URL 脱敏）。
>
> **Part B — R12 交互式工作流**：`tracks` / `context` / `new-version --branch` /
> `compare --siblings` / `merge` 的方向组织与演进循环（构建在 0006 运行产物之上，
> 0006 D1 移出）。
>
> 本 feature **不做**：332 语料迁移 + O16 补齐（→ 0008）；doctor/README/CI 收尾
> （→ 0009）；调度器/文件锁/多进程并发（R9 排除）。

## 元信息

| 字段 | 值 |
|---|---|
| ID | 0007 |
| 标题 | OCI 双向同步（push/backup/list）+ R12 交互式工作流（tracks/context/new-version/compare/merge） |
| 状态 | **已实施（代码审查通过；R10 真实 OCI 桶验收待完成）** |
| Owner | `ttrrei` |
| 创建日期 | 2026-11-10 |
| 相关提案 | `docs/proposals/2026-11-08-vectorbt-multi-ai-consolidated.md`（tracks 落地路径 §9）、`docs/proposals/oci-alpha-layout.md`（OCI 布局 + B9/I17） |
| 相关需求 | `docs/requirements.md` §R6/R7（OCI 双向同步）、§R12（方向与迭代 / tracks / 每 track 8 cap）、§R9（非功能：无副作用、无并发） |
| 相关 HLD | `docs/hld.md` §2.5（oci client）、§3（数据流 OCI push）、§4（I11/I15/I16/I17/I19/I20）、§8（0007 行） |
| 相关决策 | 0002（OCI pull/clean/aggregate + oci_client）、0003（feature 快照身份）、0004（YAML→SQL，方向由策略文件夹决定）、0005（trade engine）、0006（`lyra run` + I5 可复现产物 + I16 逐标的隔离） |
| 未决项处置 | **O2**（runs/ 布局）：取 `runs/<direction>/<track_id>/<run_id>`（对齐 R12 tracks，**用户裁决 2026-11-10**）；**O15**（R7 命令命名）：一键命令保留 `lyra backup`，`sync` 作 alias（#89 倾向）；**R10/R11/R12**（#89 挂起项）：0007 承接其中与 OCI/工作流相关的实现，332 兼容仍归 0008 |

## 1. 问题

策略能被 0004 编译、0005 撮合、0006 跑成可复现产物，但**本地产物无法离开单机**：
没有 push/backup，研究成果只能躺在 `~/.lyra/<workspace>/runs/` 里；没有
R12 工作流（方向/分支/track/context/compare），**策略演进靠人手搬文件、凭记忆记
lessons**——多 AI 并行研究时彼此串扰、无法对比兄弟分支、无法把一版诊断落成
下一批候选。0007 补上这两个缺失环节：

1. **OCI 同步**（R7 核心 feature）：把 runs / strategies / alpha features 持久化
   到 OCI，可重建、可多机复用，且遵守 I17 两级文件规则（immutable / append-only）。
2. **R12 工作流**：把"方向 → 分支 → track → 候选 → run → lessons → 综合"这条
   演进循环做成命令，让 AI 与用户走同一套机械门禁（读 1 文件 / 写 1~N 分支 /
   各跑 1 次 / 记 1 段），且不引入并发协调（R9 维持）。

## 2. 背景

- **moneta**：有 `extract_oci.py`（pull），**无 push / 无 backup / 无 R12 工作流**
  （moneta 是单向拉取管线，没有"策略演进"概念）。
- **nova**：runner 产物落本地，无 OCI 同步层；无方向/分支组织。
- **0002** 已交付 `lyra/oci_client.py`（PAR list + download + I19 脱敏 + I20 幂等
  的**拉取侧**），`lyra/config.py` 已预留 `strategies_par_url` / `features_par_url`
  push 槽位（注释明标 "reserved for 0007"）。
- **0006 D1 / out-of-scope**：把 R12 交互式工作流明确移出 0006、归 0007，理由：
  工作流构建在 0006 运行产物之上、体量大、需独立对抗性自检、用户要"轻量、基座一套、
  多方向并行"。
- **综合稿 §9 / requirements R12 / O13（已关闭）**：tracks 是**研究身份而非执行身份**
  —— `track_id` 只用于隔离/归属/综合，**不改变** validate/compile/run/report 任何
  机器门禁；**每 track 各自 8 个 active branches**，tracks 互不挤占；不做调度器/锁/
  并发（R9）。
- **I17（HLD §4，B9 两级规则）**：OCI 文件分两级——(a) **Immutable**（`data/**`、
  `runs/**`、`strategies/**/vNN.yaml`、`alpha/features/**`）同 path 同 sha256 幂等、
  不同 sha256 报错；(b) **Append-only**（`strategies/**/hypothesis.md`、`lessons.md`、
  `index/*.json`）内容可向前推进（新 ⊇ 旧），push 校验超集，否则报错。
- **现有 CLI**：`pull / clean / aggregate / catalog / oanda / features / validate /
  compile / run / report / version`。**push / backup / list / push-strategy /
  push-direction / context / new-version / compare / merge 均无**——正是 0007 要补的。

## 3. 方案

### 3.1 做什么

**Part A — OCI 同步层**（新增 `lyra/oci_push.py` + `cli.py` 命令）：
- `lyra push [--strategies-root DIR] [--runs-root DIR] [--alpha-root DIR]
  [--force-push] [--dry-run]`：按 I17 两级规则把本地镜像推上 OCI；
  `--force-push` 覆盖"I17 immutable 冲突"门禁（R7 默认 OCI 为 source of truth）。
- `lyra backup`（alias `lyra sync`，O15）：一键 = **push 变更的 strategies + runs**
  + 冲突检测 + 摘要输出（R7 的"一键命令"）。
- `lyra list [--prefix <data|strategies|runs|alpha>]`：列出 OCI 上的对象
  （复用 0002 `list_objects`），只读。
- `push-strategy <direction>/<branch>` / `push-direction <direction>`：细粒度推送
  （单版本 vs 整方向）。
- 传输：PAR URL（config 备 `strategies_par_url`/`features_par_url`/`data_par_url`）+ `requests.Session`
  （get+put）。**OCI SDK auth 不实现（M3 拒绝，2026-11-11 用户裁决）**——PAR URL 自带签名、客户端零凭证。

**Part B — R12 交互式工作流**（新增 `lyra/workflow.py` + `cli.py` 命令）：
- `lyra tracks <direction> [--create <track_id>] [--list]`：管理方向内 track（研究身份）；
  track 冻结只读基线快照（hypothesis hash + data snapshot + feature catalog/version +
  执行规则版本）。
- `lyra context <direction> [--track <id>] [--n-lessons N]`：输出**单文件上下文包**
  （该 track 的 hypothesis 快照引用 + 最近 N 段 lessons + 活跃分支 vNN + 兄弟分支
  run 摘要对比表 + feature 清单）；普通迭代**不读**其他 track 的草稿/lessons。
- `lyra new-version <direction> --branch <name> [--track <id>] [--from <parent_branch>]`：
  从父版本派生 1~N 个分支模板（vNN.yaml 骨架 + `parent`/`parents` + `driven_by_lesson`
  占位）；**enforce 每 track 8 active branch cap**（O13）——超额 fail-fast。
- `lyra compare <direction> --siblings [--track <id>] [--branch <a> <b> ...]`：
  只读对比兄弟分支的 0006 `metrics.json` 摘要（逐标的 R5 指标），输出 continue/prune/
  cross 的**证据表**（不自动回写）。
- `lyra merge <direction> --parents <a> <b> [--track <id>]`：交叉/合成候选（整块/逐参数/
  改造由 AI 全权，`inherited`+`driven_by_lesson` 记来源）；**不改**源分支文件。
- 跨轨道综合：`lyra synthesize <direction> --by <ai> --out reviews/<ts>.md`——仅在
  用户暂停方向并明确请求后生成**只读报告**（`reviews/`），**不自动回写** lessons/候选；
  晋升/恢复由用户显式触发。

### 3.2 不做什么（Out of Scope）

- **332 语料迁移 + O16 feature 缺口补齐 + 全语料回归门禁**——0008。理由：0008 先按
  裁决补齐 0003 feature 再迁移验证，是兼容门禁，独立于同步/工作流。
- **doctor / README / CI / config_example 收尾**——0009。
- **调度器 / 文件锁 / 多进程并发协调**——R9 排除。tracks 是**逻辑隔离**（用户驱动的
  顺序工作），不是并发执行；Lyra 不承诺多个 writer 同时 push 同一工作区。
- **OCI 多桶路由 / 权限管理 / 数据版本晋级**——HLD §2.5"不做什么"。一个 bucket 一个
  prefix 就够；权限归 OCI 控制台；snapshot id 本地分配、OCI 只存文件。
- **改 0004 compiler / 0005 engine / 0006 runner 的机器行为**——0007 只**消费**
  0006 产物、只**读取** 0004/0005/0006 的输出；track 是研究身份，不改任何 validate/
  compile/run/report 门禁（R12 / 综合稿）。

### 3.3 边界

- **与 OCI 的边界**：Part A 读 OCI（`list`）+ 写 OCI（`push`/`backup`）；凭证来自
  `config.yml`（PAR URL 优先 / 可选 `~/.lyra/credentials`），**凭证不进 git**（R7）。
  Part B **不直接碰 OCI**——只读本地 runs/strategies 并生成上下文/候选/对比；
  持久化由 `push-direction` / `push-strategy` / `backup` 承担。
- **与 alpha 的边界**：push 时把 `alpha/features/**` 按 I17(a) immutable 规则推上 OCI
  （alpha 是 OCI 的 source of truth）；**core 不 import 任何具体 alpha 模块**
  （I16 维持）；0007 只按文件/哈希处理 alpha，不理解 alpha 语义。
- **与 0006 的边界**：`compare` 读的是 0006 产物 `metrics.json` / `trades.parquet`
  （I5 可复现、I16 逐标的）；0007 **不改** 0006 的 run 语义，只在其上做对比/综合。
- **runs 布局（O2 裁决）**：**OCI 规范布局** = `runs/<direction>/<track_id>/<run_id>/`
  （对齐 R12 tracks）。0006 `lyra run` 的本地工作区布局
  （`runs/<name>/<YYYYMMDD>/<run_id>/`）是**暂存/工作区**；`push` 时由策略所属
  **方向**（`strategies/<direction>/vNN.yaml` 的路径）+ 活跃 **track** 解析出规范
  OCI 路径。0006 本地布局**不变**（保持已完成 feature 稳定），规范 OCI 路径由 0007
  定义（D7）。

## 设计决策（D1–D10）

**D1（范围——用户裁决 2026-11-10）**：0007 = **OCI 同步层 + R12 交互工作流**两者
都归本 feature（用户在范围歧义裁决中明确选"OCI 同步层 + R12 交互工作流全套"）。
理由：两者都构建在 0006 产物之上、都围绕"研究成果的可持久化 + 可演进"，拆开会造成
push 与工作流互相悬空；合成一个 commit 便于对抗性自检整体覆盖。

**D2（I17 两级规则是 push 的核心门禁）**：`push` 对每个本地文件先判定属于
I17(a) Immutable 还是 I17(b) Append-only：
- **Immutable**：远端**不存在** → 上传；远端**存在且 sha256 相同** → 跳过（幂等，
  I20）；远端**存在但 sha256 不同** → **报错 fail-closed**（除非 `--force-push`，
  R7 默认 OCI 为 source of truth）。
- **Append-only**：远端**不存在** → 上传；远端**存在** → 校验**新内容 ⊇ 旧内容**
  （超集：旧文件每一行/每一段都在新文件里），是超集 → 上传；**非超集** → **报错
  fail-closed**（防止回退/篡改 lessons）。
> 分类依据：`runs/**`、`strategies/**/vNN.yaml`、`alpha/features/**`、`data/**` =
> Immutable；`strategies/**/hypothesis.md`、`lessons.md`、`index/*.json` = Append-only。
> 无法归类的路径 → **报错**（fail-closed，不猜测）。

**D3（幂等与脱敏继承 0002）**：`push` 复用 0002 `oci_client` 的 I19（PAR URL 脱敏，
签名 token 不泄漏进日志/异常）+ I20（同内容不重复上传）。上传侧的幂等判定用
**sha256**（I17 两级规则用 sha256 比对，比 md5 更强）；PAR 若仅给 md5 则退回
md5（与 0002 拉取侧一致）。

**D4（凭证）**：`config.yml` 的 `strategies_par_url` / `features_par_url` 为 push
目标（0002 已预留）；`auth_file`（`~/.lyra/credentials`）可选。**凭证不进 git**
（R7 / config_example 注释）；`push` 未配置 push 目标 → **报错**（不静默跳过、
不写本地占位）。
> **批次2/M3 终态（2026-11-11 用户裁决）**：`auth_file` / OCI SDK 认证**不实现（拒绝）**——
> PAR URL 方案完整覆盖读/写（URL 自带签名 token，客户端零凭证），SDK 只会引入 `oci` 包依赖
> + 凭证管理负担，与轻量立场冲突（HLD §2.5 不做权限管理）。当前受支持行为 = 无凭据 PAR
> 读/写 + `requests.Session`（`cli._push_transport`）。只读 PAR 下 push 会明确报错而非静默
> 失败。**R10 真实 OCI 桶验收以 PAR 方案走通，无 SDK 后门**（批次2 原挂起项，现改判拒绝、终态）。

**D5（track 是研究身份，不改机器门禁——R12/综合稿）**：`track_id` 只用于
**隔离**（每 track 独立 context/lessons/候选/run 归属）、**归属**（run manifest 记
direction+track_id+strategy sha+data/feature snapshot+compiler/engine version）、
**综合**（用户触发的只读报告）。`tracks` / `context` / `new-version` / `compare` /
`merge` **不改变** validate/compile/run/report 任何行为与门禁——0007 只在 0006
产物之上组织研究材料。

**D6（每 track 8 active branch cap——O13 终态）**：`new-version --branch` 创建新
active 分支时，计数**该 track**（非方向全局）的 active branches，已达 8 →
**fail-fast 报错**，必须显式 prune 一个才能再 fork。tracks 之间名额**互不挤占**
（"互不影响"优先）。这是**唯一**由 0007 引入的机器门禁（其余命令都是只读/派生/
组织，不加门禁）。

**D7（runs 规范 OCI 路径——O2 裁决）**：OCI 上 runs 一律
`runs/<direction>/<track_id>/<run_id>/`。`push` 解析：**direction** 来自策略文件夹
（`strategies/<direction>/vNN.yaml`，0006 manifest 已含 `direction` 字段可直接复用）；
**track_id** 是 0007 引入的研究身份，由 `push` 的 `--track` 参数（或该 track 的 track
manifest）指定并写入——0006 manifest **不含** track_id（0006 无 track 概念，正确）。
0006 的**本地工作区**布局 `runs/<name>/<YYYYMMDD>/<run_id>/` 保持不变（暂存区），
`push` 负责映射到规范 OCI 路径（把 `--track` 注入归档路径）。**本地与 OCI 布局不必
相同**（本地是工作区，OCI 是规范归档）。

**D8（compare / synthesize 只读，不自动回写——R12）**：`compare --siblings` 与
`synchronize/synthesize` 只**读** 0006 产物并输出**只读证据表/报告**；**绝不**自动
写回 lessons、候选或跨轨道晋升。`merge` 只**新增**候选分支（`vNN.yaml`，写
`inherited`/`driven_by_lesson`），**不改**源分支。跨轨道综合报告落 `reviews/`，
独立保存。
> **复用点**：0004 `strategy_schema.py` 已实现 `parents`/`driven_by_lesson`/`inherited`
> 三个 provenance 字段（保留、不编译进 SQL），`new-version --branch` 派生与 `merge`
> 溯源**直接复用**这些字段，0007 无需扩展 schema。

**D9（fail-closed 优先）**：以下一律**报错而非静默**——push 目标未配置（D4）；
I17 分类失败（D2）；immutable 冲突无 `--force-push`（D2）；append-only 非超集
（D2）；track/branch/run ID 重复创建（fail-fast，不覆盖、不自动改名，综合稿）；
branch cap 超限（D6）。**无副作用**（R9）：dry-run 只报告不上传；任何命令不写
git、不联网（除 OCI）。

**D10（命令面与别名——O15）**：一键命令为 `lyra backup`，`lyra sync` 为其
**alias**（#89 倾向，R7 原文用 `sync`；取 `backup` 为主名、`sync` 别名，两者等价）。
`list` 只读。`push` 支持 `--dry-run`（先按 D2 两级规则校验并报告"将上传/将跳过/
将冲突"，不实际上传）。
> **批次2/M2 语义裁定**：`backup`/`sync`/`push` 一律 **push-only**（本地→OCI），与
> 实现一致；HLD §2.5 早期"pull+push"措辞已在 0.5 回合同步为 push-only。backup 额外覆盖
> 默认 `~/.lyra/runs`（H9），与 `push-runs` 的规范四段映射共存、冲突安全。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I17 | OCI 文件分两级：(a) Immutable 同 path 同 sha256 幂等、不同 sha256 报错；(b) Append-only 新 ⊇ 旧、否则报错 | I17 (HLD §4) / B9 |
| I19 | PAR URL（含签名 token）不泄漏进日志/异常 | I19 (HLD §4) / 0002 |
| I20 | 幂等：同内容不重复上传 | I20 (HLD §4) / 0002 |
| I11 | 本地 OCI 镜像（data/strategies/runs/alpha）可重建、默认在仓库外（B13） | I11 (HLD §4) |
| I15 | git 不出现 alpha 路径 / strategies 方向内容 / runs 全部 | I15 (HLD §4) / 0001 |
| I16 | core 不 import 任何具体 alpha 模块（0007 只按文件/哈希处理 alpha） | I16 (HLD §4) / 0001 |
| I18 | **track 是研究身份非执行身份**：`track_id` 不改变 validate/compile/run/report 任何机器行为与门禁；tracks/branch/run ID 重复创建 fail-fast、不覆盖 | 本 feature 新增（R12 / 综合稿 §9） |
| I21 | **每 track 各自 8 个 active branches**，tracks 互不挤占；`new-version` 超额 fail-fast | 本 feature 新增（O13 终态） |
| I22 | **compare/synthesize 只读**：不自动回写 lessons/候选/跨轨道晋升；`merge` 只新增候选、不改源分支 | 本 feature 新增（R12） |

## 5. 测试

必须覆盖的测试场景（pytest 用例名 + 一句话描述）：

**Part A — OCI 同步**：

| 测试 | 场景 |
|---|---|
| `test_push_immutable_new_uploads` | 远端不存在的 immutable 文件 → 上传（D2） |
| `test_push_immutable_same_sha_skips` | 远端同 sha256 → 跳过、不上传（I20 幂等） |
| `test_push_immutable_conflict_fails` | 远端不同 sha256、无 `--force-push` → 报错 fail-closed（D2/D9） |
| `test_push_immutable_force_push_overrides` | `--force-push` → 允许覆盖（R7） |
| `test_push_append_only_superset_ok` | lessons.md 新内容 ⊇ 旧 → 上传（D2） |
| `test_push_append_only_regression_fails` | lessons.md 删除/改写旧行（非超集）→ 报错 fail-closed（D2/D9） |
| `test_push_unclassified_path_fails` | 无法归 I17(a)/(b) 的路径 → 报错、不上传（D2/D9） |
| `test_push_no_target_fails` | 未配置 push PAR 目标 → 报错、不静默（D4/D9） |
| `test_push_url_redacted_in_error` | push 失败异常消息不含 PAR 签名 token（I19） |
| `test_push_dry_run_reports_no_upload` | `--dry-run` → 输出将上传/跳过/冲突清单、不实际上传（D10） |
| `test_backup_is_push_of_changed` | `lyra backup` = 变更的 strategies+runs 推送 + 摘要（R7 一键） |
| `test_sync_alias_equals_backup` | `lyra sync` 与 `lyra backup` 行为等价（D10/O15） |
| `test_list_is_readonly` | `lyra list` 列 OCI 对象、不写（R7） |

**Part B — R12 工作流**：

| 测试 | 场景 |
|---|---|
| `test_tracks_create_freezes_baseline` | 建 track 时冻结 hypothesis hash + data/feature snapshot + 执行规则版本（综合稿 §9.1） |
| `test_tracks_duplicate_id_fails` | 重复 track/branch/run ID → fail-fast、不覆盖、不自动改名（I18/综合稿） |
| `test_context_track_scoped_isolated` | `context --track A` **不读** track B 的草稿/lessons（R12 隔离） |
| `test_context_contains_siblings_runs` | context 含该 track 活跃分支 + 兄弟分支 run 摘要 + feature 清单（R12） |
| `test_new_version_writes_parent_and_lesson` | 派生分支模板含 `parent`/`driven_by_lesson` 占位（R12 vNN≥2 必填） |
| `test_new_version_enforces_cap_8` | 第 9 个 active branch（同 track）→ fail-fast（I21/D6/O13） |
| `test_cap_is_per_track_not_global` | track A 满 8 不影响 track B 仍能 fork（I21"互不挤占"） |
| `test_compare_siblings_readonly` | `compare --siblings` 读 0006 metrics 输出证据表、不写任何文件（I22/D8） |
| `test_merge_adds_candidate_no_source_change` | `merge --parents a b` 新增候选、源分支 a/b 文件字节不变（I22/D8） |
| `test_synthesize_requires_explicit_and_writes_reviews_only` | `synthesize` 生成 `reviews/` 只读报告、不回写 lessons/候选（I22/D8） |
| `test_push_direction_uploads_full_direction` | `push-direction` 推 hypothesis+lessons+全 active vNN+index（D2 两级） |
| `test_push_strategy_immutable_only` | `push-strategy <direction>/<branch>` 只推单个 vNN.yaml（I17(a)） |

**跨不变量 / 回滚**：

| 测试 | 场景 |
|---|---|
| `test_run_id_provenance_in_manifest` | run manifest 含 direction+track_id+strategy sha+snapshot+版本（D5） |
| `test_no_git_side_effect` | 所有 0007 命令不写 git 工作区（R9 无副作用） |

**跨实现验证**：I19/I20 与 0002 `oci_client` 语义一致（同传输注入 fake transport）；
`compare` 的指标口径与 0006 `metrics.json` 逐字段一致（R5 冻结集）。

## 6. 回滚

- **代码**：revert 0007 commit（`lyra/oci_push.py`、`lyra/workflow.py`、`cli.py`
  新增命令、`tests/test_oci_push.py`、`tests/test_workflow.py`）。0002-0006 不受影响
  （0007 只**新增**模块与命令，不改 0006 runner/0005 engine/0004 compiler）。
- **数据**：push 是**幂等 + fail-closed**（D2/D9），未成功上传的不会留下半状态；
  已上传的 OCI 文件按 I17 immutable 规则**不被本地回滚删除**（OCI 是 source of
  truth）。`--force-push` 覆盖的 immutable 文件若需回退，由用户显式重新 push 正确
  版本（或走 OCI 控制台），**0007 不提供 destructive 删除命令**。
- **兼容性**：回滚后 moneta/nova 与 0001-0006 全部不变（0007 是增量 feature）。

## 7. 审批

- [ ] 用户 review（范围/布局裁决已确认：OCI 同步 + R12 全套、runs 取 tracks 布局）
- [ ] AI review（另一模型）
- [ ] 自检 + 对抗性自检（本附录 B/C）
- [ ] 测试全绿（新增 `test_oci_push.py` + `test_workflow.py`）
- [ ] OCI 端到端跑通（R10 验收：pull/push 在真实桶上跑通一次）
- [ ] 332 策略回归通过（**N/A**——332 语料门禁归 0008）

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-10 | 0.1 | 初稿：范围裁决（OCI 同步 + R12 工作流全套，用户 2026-11-10）；D1–D10；不变量 I18/I21/I22；测试矩阵；O2 runs 布局取 `runs/<direction>/<track_id>/<run_id>`、O15 `backup`/`sync` 别名；R10/R11/R12 挂起项中 OCI/工作流部分承接，332 归 0008。 |
| 2026-11-10 | 0.2 | 自检+对抗性核验（#93）修正 3 处：① D7 纠偏——track_id 为 0007 引入、由 `push --track` 注入 OCI 归档路径，0006 manifest 含 `direction`（可复用）但**无** `track_id`；② B5/C1 PAR-PUT 措辞精确化——取决于**挂载模式**（只读不支持、读写支持，`shutil.copy2` 即可），非"PAR 必然只读"；③ D8 补 0004 `strategy_schema.py` 已实现 `parents`/`driven_by_lesson`/`inherited` 的复用点。无阻塞设计问题，27 行测试矩阵实测通过，进入实现。 |
| 2026-11-10 | 0.3 | **已实施**（#94）：新增 `lyra/oci_push.py`（I17 分类器 / plan / dry-run / force-push 提升 immutable 冲突 / append-only 行级超集 / unclassified fail-closed / I19 脱敏 / D4 无目标报错）+ `lyra/workflow.py`（tracks 基线冻结 / 每 track 8 active cap（`MAX_ACTIVE_BRANCHES_PER_TRACK`，唯一机器门禁）/ prune / new-version 复用 0004 `parent`+`parents`+`driven_by_lesson` / context track 隔离 + 0006 metrics 摘要 / compare 只读 / merge 只新增候选（`inherited`）/ synthesize 只写 `reviews/`）；CLI 新增 12 命令（push/backup/sync/list/push-strategy/push-direction/push-runs/tracks/context/new-version/compare/merge/synthesize）；`tests/test_oci_push.py`（36）+ `tests/test_workflow.py`（20）全绿，全仓 228→283、pyflakes 干净。实现期确认：runs 无独立 PAR 槽位，push 侧 runs 回落到 `strategies_par_url`（或 `data_par_url`）——**实现期决策**（D7 未定 runs PAR 槽位，config_example 可 0009 补 `runs_par_url`）。 |
| 2026-11-10 | 0.4 | **自检+对抗性验证修两个真 bug**（对 0.07 已实施代码的独立核验）：① **I20 幂等跳过在真实 PAR listing 下失效**——真实 OCI PAR listing 只带 `name,size,md5(base64),timeModified`（见 `oci_client._LIST_FIELDS`）**无 sha256**，而 `oci_push.plan_push` 旧实现拿 remote md5 与 local sha256 直接比（两种摘要永不相等）→ 未变文件被全部误报 `immutable-sha-conflict`、I20 跳过永远失效；`FakeParRW` 测试 transport 自造 `sha256` 字段掩盖了该 bug。修：新增 `_same_object`——sha256 直通（保持兼容）/ md5↔md5（复用 `oci_client._md5_matches`，base64+hex 容错）/ size 回退；force-push 重建 UploadItem 的 `size=0` 一并修。② **`new-version`/`merge` 产出分支文件被推层判 unclassified（自相矛盾）**——0.3 把分支名放宽为任意 slug（`b0`/`foo`），但 I17 D2 分类器只认 `strategies/**/vNN.yaml` 为 immutable → 工具自己 `new-version` 出的 `b0.yaml` 推层判 unclassified、`lyra push` fail-closed 拒推。修：`_BRANCH_NAME_RE` 收紧回 `^v\d+$`，`merge` 默认名改为下一个空闲 `vNN`（不再 `merge-vNN-vNN`）。新增 4 条回归测试（2 真实 md5 listing + 2 vNN 分类自洽）。全仓 287 绿、pyflakes 干净。 |
| 2026-11-10 | 0.5 | **批次2 对抗性 review 处置**（`docs/reviews/对抗性review-2026-11-10-批次2.md` 处置记录）：14 项发现 **接受 13 / 挂起 1（M3）/ 拒绝 0**。核心修正：① **H1** push-strategy/push-direction 静默空操作 → 改为按 direction 切片 staging 成规范 `strategies/<direction>/...`（`push-direction` 含 runs 切片）再走 I17 分类器；② **H2** 无摘要按 size 判同 → 删除 size 兜底，两侧无摘要即 fail-closed 冲突（#89 R1）；③ **H3** PAR path-token 泄漏 → `redact_par_url` 只留 `scheme://host`，新增 `redact_in_message` 清洗异常文本；④ **H4** 路径越界/符号链接 → 新增 `validate_ident`（direction/track/run_id 单组件校验）+ `plan_push` 拒符号链接与逃逸路径；⑤ **H5** 兄弟/交叉分支命名 → `^v\d+[a-z]*$`（`v02a/v04ab`）workflow 与 I17 分类器统一；⑥ **H6** context 不自包含/混入他人 lessons → 重写 `render_context`（完整 hypothesis+哈希、feature 清单、逐分支完整 YAML、逐标的 run 指标），per-track lessons 落到 `tracks/<direction>/<track>.lessons.md`；⑦ **H7** 兄弟 run 串线/只报一个标的 → 严格分支身份匹配 + 保留全部 per_instrument；⑧ **H8** push-runs 未校验归档 → 上传前校验 `manifest.artifacts` 存在+sha256、拒清单外文件、写 `run_provenance.json` sidecar；⑨ **H9** backup 漏默认 run → `_push_all_roots` 增第二遍推 `~/.lyra/runs`（冲突安全）；⑩ **H10** 可变 track index 无法过 append-only → index 改 JSONL 事件日志（create/activate/prune），天然逐行超集；⑪ **M1** 冻结基线改用真实 `catalog.duckdb`；⑫ **M2** backup 定为 push-only 并同步 HLD §2.5/0007 文案；⑬ **M4** 同 run 内 manifest.json 最后发布、文档不再把逐对象 PUT 描述成事务。**M3（SDK auth fallback）挂起**：需 R10 实桶配合，本回合文档明确"当前受支持 = 无凭据 PAR 读/写 + requests session；auth_file 未实现，待 R10"。全仓 **302 绿**、pyflakes 干净。R10 真实 OCI 桶端到端验收仍未执行，本回合不视为 0007 最终签收。 |
| 2026-11-11 | 0.6 | **M3 改判拒绝（用户裁决 2026-11-11，终态）**：SDK auth fallback **不实现**——PAR URL 方案完整覆盖读/写（URL 自带签名 token、客户端零凭证），SDK 引入 `oci` 包依赖 + 凭证管理负担，与轻量立场（HLD §2.5 不做权限管理）冲突。D4 现状说明段改写为"拒绝（不实现）"；R10 真实 OCI 桶验收以 PAR 方案走通，无 SDK 后门。批次2 最终计数：接受 13 / 拒绝 1（M3）/ 挂起 0。HLD §8 0007 行与 ACTION_LOG 状态块同步。 |

---

## 附录 B：自检

**B1 范围核对**：Part A（push/backup/list + push-strategy/direction + I17/I19/I20）
+ Part B（tracks/context/new-version/compare/merge/synthesize + cap + 只读综合）
覆盖 HLD §8 0007 行（"OCI push+backup"）与 0006 D1 移出项（R12 工作流）✓；与
用户范围裁决一致 ✓。

**B2 契约对照**：
- R7（OCI 双向同步：push/backup/list/冲突策略/凭证）→ D2/D3/D4/D10 ✓
- R12（方向/分支/track/cap/context/compare/merge/只读综合）→ D5/D6/D7/D8 + I18/I21/I22 ✓
- R9（无副作用/无并发）→ D9/D10 + I22 + §3.2 排除调度/锁 ✓
- I17（两级）→ D2 ✓；I19/I20（脱敏/幂等）→ D3 ✓；I15/I16（alpha 边界）→ §3.3 ✓
- O13（每 track 8 cap）→ D6 + I21 ✓；O2（runs 布局）→ D7 ✓；O15（命令命名）→ D10 ✓
- 综合稿 §9（track 冻结基线/重复 ID fail-fast/只读综合/每 track 8）→ D5/D6/D8 +
  I18/I21/I22 ✓

**B3 边界核对**：0007 只**消费** 0006 产物、只**读** 0004/0005/0006 输出，不改任何
机器门禁（§3.3 / D5）✓；Part B 不直接碰 OCI、持久化走 Part A（§3.3）✓；332 迁移/
doctor 明确移出（§3.2）✓。

**B4 潜在缺口（自检发现，已在正文处置）**：
- **G1 本地 vs OCI runs 布局不一致**：0006 本地 `runs/<name>/<date>/<run_id>` vs
  OCI 规范 `runs/<direction>/<track_id>/<run_id>`——D7 明确"本地是工作区、OCI 是
  规范归档，push 负责映射"，0006 本地布局不改（保持已完成 feature 稳定）。✓
- **G2 direction 从哪来**：D7 从策略文件夹 `strategies/<direction>/vNN.yaml` 解析；
  run manifest 需含 direction（0006 manifest 是否已有？见 B5）。
- **G3 `--force-push` 与 I17 immutable 的张力**：D9 明确 `--force-push` 是**唯一**
  豁免 I17(a) immutable 冲突的入口（R7 显式），且仅覆盖 sha 冲突、不豁免 append-only
  非超集（append-only 恒 fail-closed，防回退 lessons）。✓
- **G4 cap 计数边界**：D6 明确"active"计数（pruned 不计入 8 个名额，O13 原意"防无限
  fork"仍满足、pruned 历史保留）。✓

**B5 待实现期确认（非设计缺陷，列为实现检查项）**：
- 0006 run manifest 是否已记录 `direction` + `track_id`？若 0006 manifest 尚无
  direction（0006 以 `<name>` 为主键），实现期需在 push 侧从策略文件夹补 direction、
  track 从 `--track`/track manifest 解析（D7 已留此出口），**不要求**改 0006。
- `append-only 超集`校验的具体粒度（行级 vs 段级 vs 内容哈希前缀）在实现期定
  （D2 只定"新 ⊇ 旧"的语义）。
- PAR PUT 是否可用取决于**挂载模式**：**只读** PAR 不支持 PUT；**读写** PAR 支持
  PUT（`shutil.copy2` 即可，无新依赖）。实现期第一步确认可否以读写 PAR 挂载目标桶；
  只读时 push 侧走 OCI SDK（`config.auth_file`），D3/D4 已留 SDK 出口。**这是
  0007 实现期的最大不确定点**（拉取侧 0002 用只读 PAR 成立，push 需要写权限）。

**自检结论**：范围/契约/边界/不变量全对照通过；4 个自检发现（G1–G4）已在正文
D 决策处置；3 个实现期检查项（B5）非设计缺陷。无阻塞设计问题。

---

## 附录 C：对抗性自检

> 以下为设计层面的对抗性自检（实现期会再做代码级对抗性 review）。逐条给出
> "相反解释/失败模式" + 判定 + 处置。

**C1（高）PAR 是否支持 PUT？若 PAR 只读，整个 push 侧不成立**
- 失败模式：0002 拉取用 PAR（只读）成立；PAR 若为**只读挂载**则不支持 PUT，
  此时必须走 OCI SDK 签名。
- 判定：**部分成立**——这是 0007 实现期的最大不确定点（B5 已列）。**0.2 自检
  已纠正**：PUT 可行性取决于**挂载模式**（只读不支持、读写支持），非"PAR 必然只读"。
- 处置：D3/D4 已把传输抽象为"PAR 优先 / OCI SDK auth 备选"，`config.auth_file`
  出口已留；实现期第一步就是**在真实桶验证 push 传输**（R10 验收"OCI pull/push
  真实桶端到端跑通"）。
- **0.3 实施状态**：✅ **已落地**——`oci_push.push` 要求 transport 有 `.put` 方法，
  无则 `OciPushError("transport has no put() — ... is read-only; mount a read/write
  PAR or use SDK auth (0007 C1)")`；CLI 侧 `_push_transport()` 用 `requests.Session`
  同时暴露 `get`+`put`。读写 PAR（NFS mount）用 `shutil.copy2` 即可实现 `.put`。

**C2（高）append-only"超集"判定在语义上很弱，容易把"改一个词"当成合法推进**
- 失败模式：`lessons.md` 旧行"用 SMA"被改成"用 EMA"，行集合变了——若按"行 ⊇"
  判超集会报错（好），但若是**同一行内改字**（"SMA"→"EMA"）且该行仍在，则超集
  判定会**放过**这次篡改。
- 判定：**成立**——纯超集（集合包含）不能保证**旧内容逐字保留**。
- 处置：D2 的 append-only 语义应理解为**旧文件的每个字节/行仍是新文件的前缀子序列
  且未被改写**（更严格：新 = 旧 + 追加，或旧行的逐字保留）。实现期把"超集"收紧为
  **"旧内容逐字保留 + 只允许追加/段级扩展"**（B5 G4 粒度项）。**这条把 C2 从
  "可接受"降级为"需实现期收紧"**——设计层已把语义写为"新 ⊇ 旧"，实现期按更严的
  "逐字保留"落地，宁可 fail-closed。
- **0.3 实施状态**：✅ **已落地**——`oci_push.is_append_only_superset` 实现为
  **行子序列**检查（旧的非空行须按原顺序出现在新内容中），**重排**
  （`line1\nline2` → `line2\nline1`）与**改写**均被拒绝，追加/段级插入放行；
  回归测试 `test_superset_reorder_rejected` 覆盖重排拒绝。

**C3（中）`--force-push` 覆盖了 immutable 冲突，等于开了一个绕过 I17 的口子**
- 失败模式：`--force-push` 让任何人覆盖 OCI 上的 immutable runs/vNN.yaml，破坏
  "source of truth" 与幂等承诺。
- 判定：**部分成立**——但 R7 **明确要求**"本地变更需显式 `--force-push`"，这是
  用户授权的逃生舱。
- 处置：D9 限定 `--force-push` 是**唯一**豁免 immutable sha 冲突的入口，**不豁免**
  append-only 非超集（防回退 lessons 恒 fail-closed）；且 `--force-push` 是**显式
  命令行**、不进默认路径。可接受——这是 R7 规定的语义，不是 0007 开的漏洞。

**C4（中）"每 track 8 cap"在跨机器 push 时可能超发（两台机器各 fork 到 8）**
- 失败模式：R9 排除并发，但**用户**可能先在机器 A fork 到 8，再在机器 B 继续 fork——
  本地计数看不到 A 的分支，cap 被绕过。
- 判定：**部分成立**——cap 是**本地 track 状态**的门禁，跨机器不共享状态。
- 处置：D6/I21 的 cap 是**单机本地**语义（R9 本就排除跨机并发）；跨机一致性靠
  **push 时的 I17 immutable 规则**兜底——两个不同 track 的 vNN.yaml 若 path 冲突，
  I17(a) 会报错。cap 不是安全边界而是**单机防呆**（O13 原意"防无限 fork"），不
  承诺跨机强一致。设计层已把 cap 定位为"本地防呆"，非分布式约束。

**C5（中）`context` 读"兄弟分支 run 摘要"，可能把 sibling 的 run 归属搞混**
- 失败模式：R12 要求 context 含"兄弟分支 run 摘要对比表"，但 0006 run 以 `<name>`
  为主键（D7），若两个 sibling 用同名策略跑，run 归属会串。
- 判定：**部分成立**——依赖 0006 run manifest 的 provenance 是否足够区分。
- 处置：D5 要求 run manifest 记 direction+track_id+strategy sha+snapshot+版本；
  `compare` 按 (direction, branch, run_id) 三元组定位 run，不靠 `<name>`。若 0006
  manifest 缺 track_id（B5 G2），`compare` 用 strategy sha + run_id 兜底。可接受，
  已在 B5 列为实现检查项。

**C6（中）`merge` 交叉候选的 `inherited` 来源追溯可能指向不存在的分支**
- 失败模式：`merge --parents a b` 写 `inherited: [a, b]`，但 a/b 后来被 prune——
  审计链断裂。
- 判定：**成立**——prune 是"文件保留不删"（R12 分支生命周期），但跨 track merge
  时来源可能在**另一 track**。
- 处置：D8 要求 merge 记**来源的 sha256**（不只分支名），来源文件**不改**；跨 track
  merge 时来源 hash 仍在 OCI（I17 immutable），审计链不依赖分支名存活。可实现，
  已在 D8 处置（记 sha 而非裸名）。
- **0.3 实施状态**：✅ **已落地**——`workflow.merge` 在候选分支中写
  `# parent_sha256 (0007 C6, provenance): <parent>: <sha256>`（`inherited` 仍记分支
  名供 0004 schema 使用，sha 为审计锚）；回归测试断言候选含两个来源的精确
  sha256 且源分支文件字节不变。

**C7（低）`lyra list` 在 PAR 只读下是成立的，但"列 OCI 对象"可能暴露对象清单**
- 失败模式：`list` 把 OCI 上的对象名/大小列出来，若含敏感路径则信息泄露。
- 判定：**不成立（低）**——对象路径本身不是敏感数据（alpha 是"进 OCI 不进 git"，
  可见性由 OCI 权限控制）；`list` 只列 name/size（0002 `_LIST_FIELDS`），不含内容。
  凭证（PAR URL）仍脱敏（I19）。可接受。

**C8（低）backup 与 push 的关系——`backup` 会不会重复上传 push 已传的内容**
- 失败模式：`backup` = "push 变更的 strategies+runs"，若 push 已上传，backup 再传
  一遍。
- 判定：**不成立**——D3/I20 幂等保证同内容跳过（sha256 比对）；`backup` 是 push
  的"一键 + 摘要"封装，底层同一条幂等路径。可接受。

**对抗性自检结论**：C1/C2 为**高**（C1=实现期最大不确定点，已留 SDK 出口+R10
真实桶验收；C2=append-only 语义需实现期收紧为"逐字保留"），C3/C4/C5/C6 为**中**
（均有 D 决策处置或已列 B5 实现检查项），C7/C8 为**低**（不成立/可接受）。
无阻塞设计缺陷；C1/C2 是**实现期门禁**（R10 真实桶跑通 + append-only 逐字保留
校验），需在 0007 实现期优先验证。
