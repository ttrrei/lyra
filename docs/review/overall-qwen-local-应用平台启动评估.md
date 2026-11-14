# Lyra 应用平台启动评估

> **任务**：把 lyra 从"开发基座"转为"应用平台"。假设我作为用户，从 git clone → 从 PAR sync 历史策略 → 用不同 AI（ChatGPT/Claude/Gemini）针对不同 direction 写新 YAML → 跑命令拿 performance → 喂给下一轮 AI。这个循环**现在能不能转，离可靠还有多远**？
>
> **范围**：只针对 Lyra；只给中文评估；不含验收脚本。
>
> **输入**：`UsageInitialReview/` 下 CLAUDE × 2 + MINIMAX × 2 共 4 份独立评估 + 本项目既有 #116-#121 边界修复 + nova/moneta 仓库审计。
>
> **证据等级**：**[实测]** = 我实跑并观察到；**[读码]** = 静态追踪；**[评审]** = 四份评审交叉确认。
>
> **⏩ 进度（2026-11-15, v1.70-1.73 / #123-126）**：本文的 **H1 / H2 / H3 三个硬伤已修复并自测+对抗检验通过**（ACTION_LOG #123）：`tracks/` 现进 push/pull/staging 范围、baseline 冻结且幂等；`create_track` 校验前置不再静默重冻；`new-version`/`merge` 骨架改为合法 YAML、实测过 `lyra validate`；跨机完整闭环（create→push→pull→context→fork→push）实锤成立。**H4 `lyra submit` 一键命令已落地**（#124，validate 先行 fail-closed→run）。**T3 网页 AI context 包已落地**（#125，`lyra context` 现含"如何写策略"语法 + 实测过 `lyra validate` 的可抄模板）。**#1/#2/#3/#5 四个闭环缺口已修复**（#126，详见 §6.2）：`submit --track --branch` 把 AI 的 YAML **登记为该 track 的分支**（不再"骨架≠AI 策略"两个文件、run 正确归到 branch+track）、`submit` 直接打印**完整 report.md**（AI 下一轮直接可读）、新命令 `lyra lesson` 让迭代**带记忆**。**至此"基座→应用平台"的代码面 + web-AI 迭代闭环全部就绪**：`pytest` **362 passed**、pyflakes 干净；端到端闭环 + 6 项对抗 fail-closed 全部实锤。剩 **git push** + **branch protection**（均为仓库/用户侧，非代码）。

---

## 0. 一句话结论

**循环"现在能靠人工纪律转起来"**——主路径（validate → run → compare）实测通、多 AI 隔离正确、context 自包含基本达标；但**4 处会卡住或静默出错**（`tracks/` 未进 push → 闭环无记忆；`tracks --create` 同步后失败且已静默改写基线；`new-version`/`merge` 模板本身过不了 `validate`；AI 的 YAML 落地无一步命令），反馈信息偏薄。

**距离量化（MINIMAX 评审 + 本项目验证）**：

| Tier | 内容 | 工作量 | 达到 |
|---|---|---|---|
| **T1** | `tracks/` 进 push 范围 + `lyra tracks --adopt` + `create_track` 写入顺序修复 + `lyra prune` | **≈1 天** | 闭环**跨机器/跨会话成立**；基线不再被静默改写 |
| **T2** | 模板 4 缺陷 + 模板级测试 + `lyra lesson` | **≈0.5 天** | AI 的第一件作品**开箱即用** |
| **T3** | context 加"如何使用本文件" + 内嵌兄弟比较 + 文法速查 | **≈1 天** | **网页版 AI**（无文件访问权的 ChatGPT/Gemini）也能驱动 |
| **合计** | | **≈2.5-3 天** | |

> 若 AI 是有文件系统访问权的 agent（Claude Code / Codex / Cursor），**T1+T2 就够（≈1.5 天）**。

---

## 一、现状：已跑通的部分 ✅

- **多 AI 隔离正确**（`tracks --create` → track 间上下文隔离，I18）[实测]
- **context 自包含**：假设全文、特征名、各分支 YAML、每标的 trades/ann/win/net、最近 lessons [实测]
- **主路径通**：`validate → run → compare → synthesize` 端到端 [实测]
- **成本声明机制**：YAML 里 `execution:` 字段可声明；缺省 0 [读码]
- **分支命名**：`vNN` + 可选小写后缀（`v02a`、`v04ab`）[读码]

## 二、硬伤 🔴（四份评审交叉确认，全部 [实测]）

> **✅ 状态（v1.70/#123，2026-11-15）**：下列 H1/H2/H3 已按各自"修复方案"落地并通过自检 + 对抗检验（ADV-1~ADV-9 全通过，`pytest` 352 passed、pyflakes 干净、骨架过 `lyra validate`、跨机闭环实锤）。以下为原始问题记录（保留以说明诊断依据）。

### H1 —— `tracks/` 根本不在 push 范围内 → 闭环无记忆

- `lyra/cli.py:498` `_BACKUP_TOP_LEVELS = {"strategies", "runs", "alpha"}` —— **没有 `tracks`**
- `lyra/cli.py:673-697` `_staging_slice()` 只拷 `strategies/<dir>/` 和 `runs/<dir>/`
- `classify_path` 对 `tracks/…/…lessons.md` 和 `tracks/…/…json` 都判 **`unclassified`**（fail-closed 拒推）
- **后果**：新机器 `pull-strategy` 后，`~/tracks/momentum_breakout/t_chatgpt.lessons.md` → **NO — LOST**；`t_chatgpt.json` → **NO — LOST**
- **讽刺**：`AGENTS.md:128-129` 写着"仓库的首要职能就是与 OCI 保持同步"，而**闭环的状态恰恰是唯一没被 sync 的那部分**

### H2 —— `tracks --create` 同步后失败，**且失败前已静默重冻结基线**

`lyra/workflow.py:245-265`：

```python
baseline = _baseline_for_direction(workspace, direction)   # 重新冻结
record = {..., "baseline": baseline}
_write_json(tp, record)                                     # ★ 先写盘
if idx.exists():
    raise WorkflowError("track index already exists … refusing to clobber")
```

**实测**：新机器 `tracks --create` → exit 1，但 **`t_chatgpt.json` 已写盘**（record written despite the command failing），且 `hypothesis_sha256` 从 `fc8d48ac…` 变为 `c8a5c034…`（**基线身份被静默改写**）。这摧毁了溯源机制的前提：`hypothesis_snapshot`、`feature_catalog_sha256`、`feature_version`、`data_digest`、`comparable` 判定全部以"基线未被改写"为前提。

### H3 —— `new-version` / `merge` 模板本身过不了 `lyra validate`

`lyra new-version` 生成的原始产物有 **4 个缺陷**（全部 [实测]）：

| # | 缺陷 | `validate` 实际输出 |
|---|---|---|
| 1 | `driven_by_lesson: <TODO: …>` 含"冒号+空格" | `INVALID: YAML parse error: mapping values are not allowed here` |
| 2 | `version: 0` | `INVALID: unsupported YAML schema version 0 (expected 1)` |
| 3 | `entry.long: {feature: X}` 缺 op/value | `INVALID: unrecognized expression shape with keys ['feature']` |
| 4 | `feature: sma_20_above_sma_50` **不是已注册 feature** | 146 个已注册 feature 里没有这个名字 |

**测试还把这个 bug 锁住了**：`tests/test_workflow.py:226` 断言 `"driven_by_lesson: <TODO" in text2`——它断言的是那段会破坏 YAML 的文本本身，却从不在模板上跑 `parse_strategy`。

**对 AI 循环的伤害**：AI 拿到坏文件后会**照抄坏模板的结构**（保留 `version: 0`、保留 `{feature: X}` 的形状、引用不存在的 feature），**每一轮、每个 AI、每个 direction 都要重踩这四个坑**。

### H4 —— AI 的 YAML 落地无一步命令（CLAUDE 评审 B2）

> **✅ 已落地核心一步（v1.71/#124，2026-11-15）**：新增 **`lyra submit <file> --data-dir … [--track T]`**——把 AI 的 YAML 直接跑起来，内部**校验先行（fail-closed，INVALID 绝不进撮合引擎、无半截 run）→ VALID 才委托 `run`**（复用 `--data-dir`/`--track`/`run_meta` 归因语义）。端到端实锤：`submit …/momentum_breakout/v01.yaml → VALID→OK→1155 trades`。**这就是用户描述的"写完 YAML → 一条命令拿到性能"的核心闭环**。
> **✅ 登记分支一步化（v1.73/#126，2026-11-15）**：`submit` 现支持 **`--track T --branch vNN`**——把 AI 的（已校验）YAML **逐字登记为该 track 的分支文件**（`adopt_branch`），随后 run 归到 `branch=vNN, track_id=T`，于是 `context --track` 显示**AI 的真实策略 + 它的 run**（此前是"骨架 + no runs"），`compare --track` 也能直接比兄弟版本。**"跑一次拿读数 + 纳入分支树做对比"现在是一条命令**（`submit --track --branch`），不再需要手工 `new-version` + 覆盖文件（那条路仍在，但 canonical 循环走 submit）。8 分支上限仍由 `lyra prune` 回收名额。
> **范围界定（诚实）**：`submit` 现覆盖"校验→登记分支→运行→**完整 report**"。#1（完整报告进 stdout）与 #3（`lyra lesson` 记忆）同日落地（#126），完整用法见 **§九 使用手册**。

<details><summary>原始问题记录（保留以说明诊断依据）</summary>

直接把 AI 返回的 YAML 存成 `strategies/<方向>/<track>/vNN.yaml` **不会被 track 识别**：`context` 与 `compare --track` 只列已登记分支，新文件不可见（要显式 `--branch vNN` 才能比）。**现在唯一可靠做法**：先 `lyra new-version --track T --branch vNN --from 父 --lesson …` 登记，再用 AI 的 YAML 整个覆盖生成的文件——**4 步**，且任何一步失败都可能占掉 1 个一次性名额（8 个分支/track，无 `prune` 命令回收）。
</details>

---

## 三、注意事项（代码不改的情况下，现在就要遵守）

以下每条都来自四份评审的实测，是"今天就能避免踩坑"的操作规则：

1. **初始化顺序**：先 `pull-strategy`，再 `tracks --create`（track 创建时冻结假设文本；先建 track 再同步，基线冻结的是空假设）[实测]
2. **每个 AI 一个独立 track**（精确到模型版本）：`claude-opus-5` / `gpt-5` / `gemini-3`；track 间上下文隔离（I18）[实测]
3. **8 个活跃分支/track 是无回收名额**（`prune_branch` 无 CLI 入口）——不要用 `new-version` 随手"试一下" [实测+读码]
4. **运行时必须带 `--track`**：不带时 run 成功，但 `run_meta.json` 里 `track_id=null`，之后 `compare --track` 只显示 `(no runs)` **没有任何报错** [实测]
5. **成本字段要人工核对**：每个策略自己声明 `execution`，缺省 0；多 AI 竞争同一个净收益排名时改成本是最省力的"提分"——**每次收到 AI 的 YAML 用 `diff` 对基线的 `execution:` 块**，必须完全一致 [实测+读码]
6. **lessons 是手工文件**：每个 track 的 `tracks/<方向>/<track>.lessons.md`，没有命令追加；`context` 只展示最后 N 行 [读码]
7. **AI 看不到的东西**：~~`lyra context` 没有 YAML 语法与强制规则~~ **（已修复 #125：context 现含"如何写策略"语法 + 实测过 `lyra validate` 的可抄模板）**；仍**没有**逐特征含义（只有 146 个名字，无"含义/类型/预热 bar"词典）、**没有**成本信息——若要 AI 理解特征语义，仍需额外给一份特征词典（可选增强，非闭环必需）

---

## 四、距离量化与落地顺序

### 4.1 距离量化（合并 MINIMAX 评审 + CLAUDE 评审）

| Tier | 内容 | 工作量 | 达到 |
|---|---|---|---|
| **T1（必须）** | H1 修复：`tracks/` 进 push + `lyra tracks --adopt` + `create_track` 写入顺序（先校验后写盘）+ `lyra prune`（补 `prune_branch` 的 CLI 入口） | **≈1 天** | 闭环**跨机器/跨会话成立**；基线不再被静默改写 |
| **T2（必须）** | H3 修复：模板 4 缺陷 + `tests/test_workflow.py:226` 改成"对模板跑 `parse_strategy`" + H4 落地：`lyra submit` 一步命令（validate → 校验成本 → 登记 → run → 打印对比）+ `lyra lesson` | **≈0.5 天** | AI 的第一件作品**开箱即用**；名额不浪费 |
| **T3（推荐）** | context 顶部加"如何使用本文件"（对网页版 AI 必需）+ 内嵌兄弟比较 + 内联文法速查 + 特征词典（146 个特征每个一行"名称/含义/类型/预热 bar"） | **≈1 天** | **网页版 AI** 也能驱动整个循环 |
| **合计** | | **≈2.5-3 天** | 循环可靠 |

> **若 AI 是有文件系统访问权的 agent（Claude Code / Codex / Cursor）**：T1+T2 就够（**≈1.5 天**）——"路径靠猜"的问题自动消失。
> **若 AI 是 ChatGPT / Claude / Gemini 网页版**：T3 是**必需的**。

### 4.2 建议落地顺序（合并 CLAUDE 的 B 项 + MINIMAX 的 CLI 缺口）

| 序 | 项 | 来源 | 理由 |
|---|---|---|---|
| 1 | H1：`tracks/` 进 push 范围（`_BACKUP_TOP_LEVELS` 加 `"tracks"`、`_staging_slice` 拷 `tracks/<dir>/`、`classify_path` 加 `tracks/…/…lessons.md`→append_only + `tracks/…/…json`→immutable） | MINIMAX H1 | 闭环无记忆 = 每次同步都从零开始 |
| 2 | H2：`create_track` 先校验后写盘（把 `_write_json` 移到 `idx.exists()` 检查之后） | MINIMAX H2 | 静默改写基线 = 摧毁溯源 |
| 3 | `lyra prune`（补 `prune_branch` 的 CLI 入口）+ `lyra tracks --adopt`（同步后接管） | CLAUDE B6 + MINIMAX 3.1 | 8 名额无回收 = 第 8 个分支后卡死 |
| 4 | H3：模板 4 缺陷 + 模板级测试 + `lyra lesson` | MINIMAX H3 + CLAUDE B6 | AI 照抄坏模板 = 每轮踩坑 |
| 5 | H4：`lyra submit <direction> --track T --from <parent> --file ai.yaml [--lesson …]` 一步命令 | CLAUDE B2 | 4 步 + 任意失败占名额 = 循环卡死 |
| 6 | 成本基线：`validate` 拒绝比基线低的 `execution`；`compare` 增加"生效成本一致"维度 | CLAUDE B4 | 多 AI 竞争时成本自报会被利用 |
| 7 | context 升级：使用说明 + 内嵌兄弟比较 + 文法速查 + 特征词典 | CLAUDE B1 + MINIMAX 3.2 | 网页版 AI 必需 |
| 8 | 防过拟合：留出窗口 + 尝试次数记录 + 跨标一致性 | CLAUDE B5 | 多 AI 反复迭代 = 被搜索出来的"好分数" |
| 9 | AI 溯源：`tracks --create --model <名> --note <提示词版本>` | CLAUDE B9 | 几轮后答不出"哪个模型写的" |
| 10 | 基线单一来源：`tracks --create` 时把基线 YAML 的 sha256 写入 track 记录 | CLAUDE B10 | git 与 OCI 两份基线谁权威无裁决 |

### 4.3 "循环可以开始用"的完成标准（CLAUDE 评审 §四，原文采纳）

1. 在一个干净工作区完成：`git clone → 安装 → doctor → pull / pull-strategy / pull-runs`，且本地目录布局与 OCI 对得上；
2. 三个 AI 各自仅凭 `lyra context` 的输出写出的 YAML，**首次 `validate` 通过率**可接受（例如 ≥ 80%），失败的错误信息能指导 AI 自行修正；
3. 从"AI 返回 YAML"到"得到评估卡"只需要一条命令，中途任何失败都不占用分支名额；
4. 两轮迭代后，`context` 能展示上一轮每个分支的评估卡，且三个 track 互不可见；
5. 手工把成本改成 0 的 YAML 会被拒绝；
6. 一个 track 用满 8 个分支后，可以通过 `retire` 继续；
7. 留出窗口的结果不会出现在任何给 AI 的输出里。

---

## 五、资产备份安全（你的 Q1/Q3）

> **直接答案**：**安全，剩 1 项收尾**。核心资产（代码 / 策略 / runs / 原始价格源）都有备份或可重建；~~nova 转 private~~ **（你已完成）**；剩余：② git push（你执行，本环境无凭据）。

| 资产 | 位置 | 备份状态 | 风险 |
|---|---|---|---|
| **代码** | `ttrrei/lyra` git | ⚠️ 本地 ahead 3 待 push（需凭证） | 低 |
| **策略 YAML（133 directions + 296 corpus）** | OCI `strategies/` 桶 | ✅ 429 对象在 OCI | 低 |
| **146 候选原稿** | `ttrrei/nova` git + **已镜像到 OCI corpus** | ⚠️ nova 仍 public；但 OCI `strategies/corpus/` 已存 146 份（内容 sha 已核对一致） | 中——即便 nova 泄露，alpha 也已在私有 OCI 有备份 |
| **lyra runs (0010b_* 243 个, 497M)** | 本地 `~/.lyra/default/runs/` | ✅ **已备份**（`lyra push` 上传 1458 run 文件到 `lyra-runs` 桶，与本地 1458 文件完全匹配） | 低 |
| **lyra data (14G 派生)** | 本地 `~/.lyra/default/data/` | ✅ **可重建**：`lyra-data` 桶有原始源 `moneta_prices_m1.zip`（~1.28GB）；features 由代码从原始重建 | 低 |
| **moneta data (30G)** | `/home/ubuntu/work/moneta/data/` | ❓ 未审计（moneta 非 lyra 交付，优先级低） | 待查 |

### 收尾（按优先级，均为你的手动动作）

1. **把 `ttrrei/nova` 转 private**（GitHub Settings → General → Danger Zone → Change visibility → Private）。注：146 候选策略的**内容已备份到私有 OCI `strategies/corpus/`**，所以即便 nova 短期泄露，alpha 本身已在私有存储；转 private 是消除公开可见性的最后一步。
2. **`git push`**（本环境无凭据）——提交 `86a41ca`（边界收口）等 3 个本地提交上远端。
3. （可选）moneta 的 data+runs 备份——moneta 不是 lyra 交付对象，除非你想保留它。

> **结论**：lyra 本体的四类资产（代码 / 策略 / runs / 原始数据源）已 100% 有备份或可重建；"资产备份安全"成立，仅剩 nova-visibility 与 git-push 两个手动收尾。

---

## 六、仓库清理（合并 CLAUDE overall-cleanup + MINIMAX lyra-repo-cleanup-plan）

> 两份评审高度一致。核心：**`strategies/temp/`（296 文件/1.3MB）已在 #121 落地**（移出 git、进 OCI 标准库、原稿在 nova）——**这一项已完成**。

### 6.1 已完成（#121）

- `strategies/temp/` 移出 git、进 OCI（`strategies/corpus/…`，296 对象）
- `.gitignore` 去掉 `!strategies/temp/**`
- `lyra push-corpus` 命令 + `classify_path` corpus 规则

### 6.2 待做（合并两份评审，去重后）

| 级 | 项 | 来源 | 风险 |
|---|---|---|---|
| T0 | `docs/temp/suggested_indicators.md`（2.8KB，零引用，属于 ASX 另一项目） | CLAUDE 1.2 + MINIMAX T0-1 | 无 |
| T0 | 7 个无调用方函数（`aggregate_bronze`/`core_registry`/`to_report`/`iter_flat_csvs`/`read_csv_rows`/`by_family`/`bound_params`） | CLAUDE 1.3 | 低（vulture 标出 + grep 复核） |
| T0 | `lyra compare --siblings/--no-siblings` 选项无效果（`cli.py:1193` 参数未用） | CLAUDE 1.4 | 无 |
| T1 | `strategies/directions/` 12 个 v01.yaml（已在 #120/#121 移出 git、进 OCI） | MINIMAX T1-2 | **已完成** |
| T1 | `tests/test_alpha_boundary.py`（新建，守卫 alpha 边界） | MINIMAX T1-4 | 建议做（与 #121 gate 互补） |
| T2 | `docs/proposals/2026-11-08-vectorbt-eval-and-multi-ai-v2`（中英 4 文件，被 hld 1 处 + consolidated 2 处引用） | CLAUDE 二 + MINIMAX T2-1 | 归档并修 3 处链接 |
| T2 | `docs/proposals/vectorbt-and-multi-ai-strategy-search`（中英 4 文件，被 0004 2 处 + hld 1 处 + consolidated 2 处引用） | 同上 | 归档并修 5 处链接 |
| T2 | `docs/decisions/0008-bar-coverage-analysis.md`（编号冲突：两份 0008） | MINIMAX T2-2 | 改名（非删除）+ 修引用 |
| T2 | `docs/reviews/`（旧对抗性 review 18 篇中英 ~0.5MB，被 hld/0003/0004/0007/0009/tests 引用） | CLAUDE 二 + MINIMAX T3-1 | 归档并修 6 处引用 |
| T3 | `docs/review/` vs `docs/reviews/` 一字之差合并 | MINIMAX T3-1 | 合并 + 修引用 |
| T3 | `strategies/examples/README.md` 与实际内容不符 | MINIMAX T3-3 | 修 |
| T4 | **git 历史**：12 v01 基线已 public（#121 F1 用户接受，不改写） | MINIMAX T4 + #121 F1 | **已裁决**（接受） |
| T4 | **`docs/ACTION_LOG.md` 当前状态块过长**（~360KB） | CLAUDE 二 + MINIMAX T3-2 | 保留状态块 + 最近 15 条，更早拆到 `docs/archive/` |

### 6.3 明确不要动（两份评审共识）

- `strategies/examples/`（`lyra doctor` 编译冒烟依赖）
- `docs/decisions/`（设计记录，代码/测试注释引用）
- `docs/proposals/2026-11-08-vectorbt-multi-ai-consolidated`（被 0007 引用）
- `docs/proposals/oci-alpha-layout`（被 AGENTS/requirements/0001/0007 引用）
- `scripts/make_lock.sh`（README 当作 `requirements.lock` 唯一来源）
- `tests/crosscheck_*.py`（test 辅助模块）
- `lyra/workflow.py::prune_branch`（T1 的 `retire` 命令正需要它）
- `config/config_example.yml`、`.github/workflows/ci.yml`（需修，非删）

---

## 七、建议的执行顺序（合并所有输入）

### 第一优先：资产安全（**今天**）

1. `ttrrei/nova` 转 private（GitHub 手动操作）
2. `lyra push-runs`（497M）+ `lyra push`（raw_zips 1.5G）到 OCI
3. 确认 moneta/nova data+runs 备份状态

### 第二优先：闭环硬伤修复（**≈1.5 天**，T1+T2）

4. H1：`tracks/` 进 push 范围
5. H2：`create_track` 写入顺序修复
6. `lyra prune` + `lyra tracks --adopt`
7. H3：模板 4 缺陷 + 模板级测试 + `lyra lesson`
8. H4：`lyra submit` 一步命令

### 第三优先：AI 体验（**≈1 天**，T3，若用网页版 AI 则必需）

9. context 加"如何使用本文件" + 内嵌兄弟比较 + 文法速查 + 特征词典
10. 成本基线 + `validate` 拒绝低于基线 + `compare` 增加成本维度
11. 防过拟合（留出窗口 + 尝试次数 + 跨标一致性）
12. AI 溯源 + 基线单一来源

### 第四优先：仓库清理（**≈0.5 天**）

13. T0：零风险删除（`docs/temp/`、7 个无调用方函数、无效选项）
14. T2：归档（proposals 2 份来源稿、reviews、0008 编号冲突）
15. T3：结构整理（review/reviews 合并、examples README、ACTION_LOG 状态块瘦身）

### 第五优先：push + 收尾

16. `git push`（需凭证，本地 ahead 3）
17. `tests/test_alpha_boundary.py`（守卫 alpha 边界，与 #121 gate 互补）
18. 刷新 ACTION_LOG ZH+EN + 同步 TempReviews

---

## 八、本文件没有覆盖

- 真实 PAR 同步的布局（`pull`/`pull-strategy`/`pull-runs` 端到端）
- 同 track 内 `merge` 的行为
- 真实数据上的特征/引擎数值
- 各家 AI 对 YAML 语法的实际遵从率（需真实模型干跑才能给数字）
- moneta/nova data+runs 的备份审计

## 九、web-AI 迭代循环使用手册（#126 落地后的真实用法）

> 这是**用户视角**的逐步操作手册：假设你（人）已 clone 好代码、`lyra pull` 同步了历史策略与 track。
> 写策略的 AI 是**网页/聊天版**（无文件系统、无 coding），你只负责把它的 YAML 落到一个本地文件、并跑命令。
> 一轮循环 = 下面 5 步，全部由 `lyra` 命令面完成，AI 只需"读 context + 写 YAML + 看 report + 写 lesson"。

### 一轮完整循环（命令顺序）

```bash
# ① 读：把该 direction 的 hypothesis + 特征列表 + 语法 + 可抄模板 + 该 track 的
#    已有分支/历史 run/教训 打包给 AI（无 FS 的 AI 就靠这份文本）
lyra context failed_breakout --track t_demo > /tmp/ctx.md   # 粘给 AI

# ② 写：AI（网页版）读 ctx.md，按里面的语法 + 模板改出一条新策略 YAML 文本。
#    你把它落到本地一个文件（名字随意，内容里要带 direction + 合法 entry/exit）
#    —— 例：/tmp/ai_new.yaml

# ③ 跑 + 登记：一条命令完成 校验→(登记为 t_demo 的 v01 分支)→运行→打印完整报告。
#    fail-closed：AI 的 YAML 若非法，绝不进撮合引擎、也不登记分支、不产生 run。
lyra submit /tmp/ai_new.yaml \
    --data-dir ~/.lyra/default/data \
    --track t_demo --branch v01
#   → VALID → adopted as failed_breakout/t_demo/v01 → OK: run … → (完整 report.md 直接进 stdout)
```

**关键点（#126 修的四个缺口，现在都自动满足）：**
- **#2/#5 归因**：AI 的 YAML 被 `submit --track --branch` **登记为该 track 的分支文件**，run 记 `branch=v01, track_id=t_demo, spec_id=<AI 的 id>`。于是：
- **#1 完整结果**：`submit` 成功后直接打印该 run 的 **完整 `report.md`**（每品种指标 + 逐月表 + 跨品种 min/median/max）——AI 下一轮直接读到，不必再猜怎么读 run 目录。
- **#3 记忆**：AI 看完报告，把结论写回该 track：

```bash
# ④ 记：一条教训（append-only；下轮 context 会显示最近 5 条，迭代带记忆）
lyra lesson failed_breakout --track t_demo \
    "v01 win 58% 但负 EV(-0.13 net) — v02 收紧 stop_loss_pct、加趋势过滤"

# ⑤ 下一轮：context 现在显示 该 track 的真实分支 + 它的 run + 你刚写的教训
lyra context failed_breakout --track t_demo
```

### 迭代多版本（v01→v02→…）

```bash
# AI 基于 v01 的报告写 v02：
lyra submit /tmp/ai_v02.yaml --data-dir ~/.lyra/default/data --track t_demo --branch v02
lyra lesson failed_breakout --track t_demo "v02 收紧止损后 EV 转正，年化 3.2%"

# 同 track 内兄弟版本对比（v01 vs v02 各品种指标）
lyra compare failed_breakout --track t_demo
```

- **8 分支上限**（I19）：一个 track 最多 8 个活跃分支；满了用 `lyra prune failed_breakout --track t_demo --branch vNN` 回收名额。
- **换机/换会话**：`lyra push` 把 strategies + tracks(baseline+lessons) + runs 上 OCI；新机器 `lyra pull` 全量恢复——闭环记忆不丢（#123 H1 已修）。

### 常见错误与 fail-closed 行为（实测）

| 你做了 | 命令结果 |
|---|---|
| `submit --track t` 但没给 `--branch` | `ERROR (not run): --track requires --branch <slug>`（不跑） |
| AI 的 YAML 用了未注册 feature | `INVALID (not run): unknown feature …`（不进引擎、不登记、无 run） |
| `--track` 指向不存在的 track | `ERROR (not run): unknown track …`（不 adopt） |
| `--branch "not a slug!!"` | `ERROR (not run): invalid branch name …`（拒绝） |
| `lesson` 到不存在的 track / 空文本 | `unknown track …` / `lesson text is empty …`（拒绝） |

### 边界（诚实）

- **#4 feature 字典未做**（可选）：146 个 feature 只有名字，无"含义/类型/预热 bar"。AI 可照抄 context 里的模板起步（合法），但要**理解**某特征语义仍需额外给一份词典。
- `submit` 跑的是**已登记分支**（canonical 循环）；一次性 `lyra run` 仍按文件名归因（非 canonical，少用）。

## 关联文件

- `UsageInitialReview/CLAUDE/overall-ai-loop.md` + `overall-cleanup.md`
- `UsageInitialReview/MINIMAX/lyra-ai-loop-playbook.md` + `lyra-repo-cleanup-plan.md`
- `overall-qwen-local-git-oci-边界对抗检查.md`（#121 F1/F2/F3）
- `overall-qwen-local-git-oci-边界检查.md`（#120 五层核查）
- `overall-qwen-local-五组分类处置.md`（#119 12 接受/13 拒绝）
