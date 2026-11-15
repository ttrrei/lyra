# Lyra 应用平台 —— UsageFutherCheck 五组审查落地 + 自检/对抗/用户视角验证

> **性质**：实现记录 + 验证记录（非建议）。把 `/home/ubuntu/work/temp/TempReviews/UsageFutherCheck/` 4 份外部 AI 评估里的**必须执行 + 建议执行**项落地，并做自检、对抗、用户视角三层验证。
> **读者**：接手平台开发 / 审查的下一位（coding AI 或人）。
> **版本**：#129（v1.76）。前置：#128 平台自检 + 低 token 多 AI 迭代建议（见同目录 `overall-qwen-local-低Token多AI迭代-平台使用建议.md`）。

---

## 一、裁决与范围

用户裁决："把 4 份外部 AI 评估的**必须执行**和**建议执行**的部分，现在就执行起来，把改动做好；执行完做自检 + 对抗性检验，然后写一个文档。"

我逐条读了 4 份文件（`lyra_platform_review_and_change_plan`、`lyra-ai-loop-design-spec`、`lyra-ai-loop-risks-and-extended-fixes`、`overall-ai-loop-v2-design`），并**先读真实代码核验每一条 bug 声明**（没有直接照抄评估里的结论）。

**核验结果：评估声明的 3 个 P0 全部属实。** 逐条确认：

| 声明 | 我核验到的真实代码 | 结论 |
|---|---|---|
| M1 `adopt_branch` 原地覆盖 + cap 先判 | `workflow.py:512-548` 原 `dest.write_text(src.read_text())` 无条件；`enforce_branch_cap` 在存在性检查之前 | **属实** |
| M2 `submit --track --branch v01` 影子 baseline + 无 lineage 强制 | `_BRANCH_NAME_RE=^v\d+[a-z]*(_\d+)?$` 匹配 `v01`；`_branch_file` 给 track 级优先；全库无 lineage 强制 | **属实** |
| M3 两个 track 同 YAML 同日覆盖 run 归属 | `runner.py:396` `run_name=name or spec.id`、`run_dir=out/run_name/date/run_id`、`run_meta.json` 单条 `track_id` | **属实** |

其余（D7/D8/D6/D9/低 token 特性）属"实现规格 + 建议"，按用户裁决一并落地。

---

## 二、落地清单（必须执行 P0 → 建议执行）

### P0 闭环硬伤（影响研究可信度，先于一切）

**M1 — `adopt_branch` 分支内容不可变**（`lyra/workflow.py`）
- 原行为：重提交已存在分支（不同 SHA）会**静默覆盖** `v02a.yaml`；历史 run 保留同 slug → `context` 显示"新 YAML + 旧 run"，AI 把**陈旧证据当当前读**。
- 现行为：已存在分支 **字节相同 = 幂等 no-op**（不写、不加 index 事件、不耗 cap 名额）；**字节不同 = fail-closed**（"branches are IMMUTABLE…register a NEW slug"）；**pruned slug 永不复用**（`_branch_ever_seen` + active 判定）；**cap 检查只对真正新分支**（D8.1 顺序修正：先判存在、后计 cap）；写入改**原子**（同目录 tmp + `os.replace`）。
- 新增辅助：`_file_sha256`、`_branch_ever_seen`。

**M2 — v01 保留 + R12 lineage 强制**（`lyra/workflow.py` + `cli.py`）
- 原行为：AI 可把 track 的 `v01` **遮蔽** direction 级共享只读 baseline（破坏共同祖先契约）；R12（`docs/requirements.md:257+`）要求 vNN(N≥2) 必声明 `parent`/`parents` + `driven_by_lesson`，但**无任何强制**。
- 现行为：`_validate_new_branch_lineage` 挂在**唯一创建 track 分支的接缝** `adopt_branch`（fail-closed、无例外）——
  - `v01` 保留：拒绝 track 拥有；
  - vNN(N≥2)：必须 `parent`(或 `parents`) **且该 parent 实际存在**（direction baseline 或本 track 分支）、且 `driven_by_lesson` 非空 —— **禁止"抄 YAML 编造 lineage"**；
  - `new_version` 加 **v01 保留**（但保留 `parent` 可省——它是骨架生成器、模板带引号 placeholder；真门禁在 adopt/submit，见 D7/D8）；
  - **T3 grammar 模板**（`render_context`）加入 lineage 规则，让 web-AI 从 context 就学到（v01 保留 / 候选起 v02 / vNN 必声明 parent+lesson / 分支不可变）。

**M3 — 跨 track run 归属不覆盖**（`lyra/cli.py` `run`）
- 原行为：两个 track 跑**同一** YAML（同 spec.id/同 data/同 runtime → 同 run_id）+ 同 run_name → **同 run_dir** → 第二 track 的 `run_meta.json` **覆盖**第一 track 的 `track_id`（静默丢归因）。
- 现行为：`--track` 给值且 `--name` 未给时，run 名 scope 到 track（`<spec.id>__<track>`），每 track 各得独立 run_dir；显式 `--name` 恒胜（操作者意图优先）；同 track 重跑幂等不变。

### 建议执行（D7 / D8 / D6 / D9 / 低 token 特性）

- **D7**（`_workspace` 降级链）：config 缺失不再裸 traceback——`config → LYRA_WORKSPACE → LYRA_DATA_ROOT(父目录) → ~/.lyra/default`。修掉"CI 2 红 / 11 命令裸 traceback / 无谓仪式成本"。
- **D8**：D8.1 cap 顺序（并入 M1）；D8.2 `append_lesson` 把内嵌换行压成空格 + 去控制字符 + 限长 300（守"一行一条"）；D8.3 `submit --branch` help/docstring 去掉"Default = the strategy's own id"；D8.4 拒覆盖（并入 M1）。
- **D6 模式 B**（新 `lyra/batch.py` + `cli.py apply-batch`）：web-AI 写**一份**多 direction bundle（`directions:` 列表，每 item 自带 direction/track/branch/parent/driven_by_lesson/完整策略体），coding-AI 一条命令落地。分阶段全 fail-closed：解析 → **全部先校验（任一条无效 → 整个 batch 拒、一行都不写）** → adopt（M1 不可变）→ `--run` 才跑（单条失败记录、其余继续）→ 汇总。`--dry-run` 只到校验阶段、零写盘。
- **D9**（完整记录）：D9.1 `prune --reason`（写入 index 事件）；D9.3 digest 的 `pruned: <slug> — <reason>` 行（下轮 AI 看到"试过什么、为什么死"，不重推死路）。
- **低 token（#128 P0-1/P0-2）**：
  - `lyra digest <dir> --track T`（`render_digest`，<3KB：hypothesis 一行 + feature 数 + 每分支最新 run 一行结论 + lessons + pruned 行 + "全量见 context"指引）；
  - `lyra digest --all`（多 direction 紧凑综合视图，模式 B 的"读"入口）；
  - `submit --report digest|full|none`（默认 **digest**：每品种一行 trades/ann/win/net；full 仍落盘 `report.md`，`lyra report` 可复读）。

### 诚实边界（未做 + 为什么）

- **feature 字典**（146 个 feature 的 ≤15 字含义说明）：P2 增强，**未做**。理由：`context` 已给 feature 名清单、AI 能照抄 T3 模板起步，不阻塞循环；且 `features.py` 无 per-feature description 字段，需引入新数据源（超出本轮范围）。
- **`lesson --kind`（lead/ruled-out 两栏）**、**`lyra doctor --no-config`**（D7.3）：非阻塞，未做（D7.1 降级链已解决崩溃）。
- **D1 run ledger / D2 digest `--check` / D3 context 分层**：本轮已用 `render_digest` + `run_meta` sidecar 覆盖其**主要价值**（低 token 读取 + 可累加记录）；ledger 独立文件、digest `--check` 一致性校验属增强，未单列（避免引入"第二真相源"，见 RK-16）。

---

## 三、自检（Self-check）

| 项 | 结果 |
|---|---|
| `python -m pytest -q` | **375 passed**（#126 后 362 → +13：M1×5、M2 lineage×2、D8 cap 刷新/lesson 换行×2、D6 parse×4、D6 all-or-nothing×1、D9.1 prune reason×1；其中 1 个既有测试因 v01 保留而更新到 v02） |
| `pyflakes lyra/`（全包） | **干净**（含新 `lyra/batch.py`） |
| 新 CLI 命令面 | `digest` / `apply-batch` / `submit`(`--report`) / `lesson` / `prune`(`--reason`) 均在 `lyra --help` |

---

## 四、对抗性检验（Adversarial）—— 真实数据逐项实锤

环境：`~/.lyra/default/data`（真实 21 品种 OHLCV + catalog），隔离 scratch workspace `~/.lyra/e2e`（每轮 `rm -rf` 后重建，互不污染）。

| # | 对抗 | 实测结果 | 判定 |
|---|---|---|---|
| E1 | 完整循环 `tracks --create`→`submit ai_v02 --track t_ai --branch v02` | `VALID→adopted as fbtest/t_ai/v02→OK: run`+**digest 进 stdout**（`SPX500_USD 44 trades ann=-0.116 win=4.55%`） | ✅ |
| M1a | 重提交 v02 **不同**内容 | `branch 'v02'…already exists with different content — branches are IMMUTABLE…register a NEW slug (v02a → v02b)` | ✅ fail-closed |
| M1b | 重提交 v02 **相同**内容 | 幂等：同 run_id `13ca719f…`、无新 index 事件、不耗 cap | ✅ |
| M2a | `submit --track t_ai --branch v01` | `branch v01 is the DIRECTION baseline and is reserved — a track (direction/t_ai) must not own it` | ✅ |
| M2b | vNN 去 parent+lesson | `branch v03 on track fbtest/t_ai rejected (R12 lineage): …must declare its provenance… AND driven_by_lesson` | ✅ |
| M3 | 同 YAML 进**两个** track | `runs/fb_ai_v02__t_ai` 与 `runs/fb_ai_v02__t_other` 两目录，run_meta `track_id` 各为 `t_ai`/`t_other`（修复前第二 track 会覆盖第一 track 归因） | ✅ |
| D6a | 2 有效 item | `2 adopted`（v02 + v02a 均落盘） | ✅ |
| D6b | 1 有效 + 1 无效（unknown feature） | `0 adopted — 1 invalid of 2 → NOTHING written`，**有效那条也未写盘**（`strategies/fbtest/t1/` 目录不存在） | ✅ all-or-nothing |
| D6c | `--run` | `2 adopted · 2 run ok, 0 failed` | ✅ |
| D9 | `prune v02a --reason "dup of v02, no gain"` | digest 显示 `pruned: v02a — dup of v02, no gain` | ✅ |
| D7 | `lyra tracks fx --list --config /nonexistent.yml` | 修复前"裸 traceback exit 1" → 修复后"(no tracks in fx) **exit 0**" | ✅ |

---

## 五、用户视角验证（User perspective）

**模式 A — 单 track 低 token 循环（web-AI 无 FS / 无 coding）**：
```
lyra context <dir> --track T        # 读：hypothesis + feature 清单 + 语法/模板 + 分支 YAML + run + lesson
  → AI 写一个新 vNN.yaml（带 parent + driven_by_lesson）
lyra submit ai.yaml --track T --branch vNN   # 校验→登记分支→跑→digest 进 stdout（默认省 token）
lyra digest <dir> --track T          # 低 token 看历史 + 分支分数 + pruned 死路
lyra lesson <dir> --track T "..."    # 记一条教训（一行）
  → 下一轮 context 带上策略 + run + 教训
```
- 一轮 token 从"完整 report.md 90KB ≈ 2.5 万 token"降到"digest 每品种一行 ≈ 数百 token"（full 仍落盘、可复读）。
- 所有 fail-closed（INVALID 不跑、v01 保留、lineage 强制、分支不可变）都在 command 面，AI 无 FS 也能被拦下。

**模式 B — web-AI 综合 + coding-AI 落地**：
```
lyra digest --all                    # web-AI 读：多 direction 紧凑综合视图（一次读全）
  → web-AI 写一份 bundle.yaml（directions: [ {direction,track,branch,parent,driven_by_lesson, strategy} ]）
lyra apply-batch bundle.yaml --dry-run      # coding-AI 先看（零写盘）
lyra apply-batch bundle.yaml --run --data-dir ...   # 校验全过才落地 → 跑 → 汇总
```
- all-or-nothing：一个 item 坏，整批不落地（不会留下半截状态）。
- 分工清晰：web-AI 只出意图 + 完整策略体；coding-AI 只执行命令序列；接缝是 `bundle.yaml` + 命令面。

---

## 六、交付物 & 改动面

**代码**：`lyra/workflow.py`（`adopt_branch` 不可变 + cap 顺序 + 原子写、`_file_sha256`/`_branch_ever_seen`/`_validate_new_branch_lineage`、`append_lesson` 压行、`prune_branch` +reason、`render_digest`、T3 grammar +lineage、`new_version` +v01 保留）；`lyra/cli.py`（`submit --branch` help/`--report`+digest、`run` +track-scoped run_name、`_workspace` D7 降级链、+`digest`、+`apply-batch`、`_fmt_num`/`_print_run_digest`、`prune` +`--reason`、+math/types 导入）；**`lyra/batch.py`（新）**。

**测试**：`tests/test_workflow.py`（+M1×5/D8×2 回归、1 个既有 adopt 测试更新到 v02）；**`tests/test_batch.py`（新：D6 parse×4 + all-or-nothing + D9.1）**。

**文档**：`docs/ACTION_LOG.md` + `.en.md`（#129 行 + 状态块刷新）；本文件。

**待用户**：`git push`（本环境无凭据，origin/main 仍 = `526f2ea`）—— push 到 main 触发 CI。

---

## 七、与 4 份评估的对照

| 评估项 | 出处 | 处置 |
|---|---|---|
| M1 `adopt_branch` 覆盖 + cap 顺序 | plan §3.1 / spec D8.1 / v2 N2 | **已修**（不可变 + 顺序 + 原子） |
| M2 v01 保留 + lineage | plan §3.2 / R12 | **已修**（`adopt_branch` 门禁 + T3 教学） |
| M3 run 归属覆盖 | plan §3.3 / v2 N3 | **已修**（track-scoped run_name） |
| D7 无 config 降级 / 11 命令裸 traceback | spec D7 | **已修**（`_workspace` 降级链）；`doctor --no-config` 未做 |
| D8 新代码 5 缺陷 | spec D8 | **已修**（D8.1/8.2/8.3/8.4 全） |
| D6 `apply-batch`（模式 B） | spec D6 / v2 §5 | **已实现**（all-or-nothing + `--run` + `--dry-run`） |
| D9 prune reason / lesson kind | spec D9 | **部分**（prune reason + digest 已做；lesson `--kind` 未做） |
| D1 run ledger / D2 digest `--check` / D3 context 分层 | spec D1-D3 | **价值已覆盖**（digest + run_meta）；独立 ledger/`--check` 未单列 |
| feature 字典 | 多份 P1/P2 | **未做**（P2，不阻塞，理由见 §二） |
| 成本基线 / 零成本传染 / signals.parquet 体积 | v2 §5.8 / A1 | **未动**（属引擎/成本口径，超出"审查落地"范围，且涉及 I9/I13 边界） |
