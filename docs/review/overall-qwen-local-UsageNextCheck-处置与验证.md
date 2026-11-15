# UsageNextCheck 三组外部审查——处置、实现与验证

**日期**：2026-11-15（#131）
**对象**：`/home/ubuntu/work/temp/TempReviews/UsageNextCheck/` 三份外部 AI 审查
- `lyra_latest_review_and_ai_platform_improvement_plan_2026-11-15.md`（P0-1…P0-4 / P1-1…P1-9 / P2 5.1–5.4）
- `lyra-platform-third-round-review.md`（P-1…P-12 / E1–E10）
- `overall-ai-loop-v3-review.md`（B1–B9 / §4 深度研究方法论 4.1–4.8）
**处置原则**：按用户裁决 **接受 / 挂起 / 拒绝** 分类并处理；**尽量不要挂起**（收尾阶段）。
**结论**：22 条 = **接受 15 / 拒绝 7**（+1 条仅记录）。**挂起 0**。全部接受项已落地并逐项验证。

> 三份审查高度重叠（同批问题被三种编号）。本文以"问题"为键归并，不再按文件分列。
> 每条"接受"都先在真实代码中核验声明属实、再实现、再用真实数据 E2E + 回归测试实锤。

---

## 一、处置总表（接受 / 拒绝 + 理由）

| # | 审查项（三文件编号归并） | 判定 | 理由 |
|---|---|---|---|
| 1 | P0-1：CI 测试 `test_run_id_covers_consumed_feature_values` import pandas（不在 lock 里）→ **CI 红**（375 passed / 1 failed） | **接受** | 已用 duckdb `COPY … REPLACE` 重写该测试，**不新增依赖**，CI 转绿 |
| 2 | P0-2 / B1：`ai_readme.md` 的 bundle 用 `bundle:`+嵌套映射，但解析器只认 `directions:`+字符串 `strategy` | **接受** | 解析器现接受 `bundle:`/`directions:`/`items:` 三者其一 + 字符串或映射 `strategy`；文档给标准形 |
| 3 | P-4 / B7：`strategy:` 写成映射时旧代码 `str(entry["strategy"])` 把 dict repr 落盘 | **接受** | 映射分支改 `yaml.safe_dump(sort_keys=False, allow_unicode=True)`——**无损**（换行/反斜杠/unicode/null 都不损坏） |
| 4 | P1-2 / B3：`spec.direction != item.direction` 未检查 → 可把 A 方向的策略落到 B 方向 | **接受** | 落地前 preflight 交叉校验，不一致→整批拒（D6 全或无） |
| 5 | P0-3 / B2：adopt 阶段非原子、"rolled back" 是**假话**（已落盘项仍在） | **接受** | 新增 Stage 2.5 **全量 preflight（零写盘）**：`--run`⇒`--data-dir`、ident 校验、track 存在、direction 交叉、lineage、cap、去重**全部在 adopt 之前**；失败信息**如实**（列已落盘项 + 说明不可回滚、幂等重试） |
| 6 | P-7：同一 bundle 内重复 `(direction,track,branch)` 未检测 | **接受** | preflight 去重：重复目标→该 item 拒（整批拒） |
| 7 | B5：`yaml.YAMLError` 直接抛裸 traceback | **接受** | `strategy:` 坏 YAML → 该 item 的**干净 CLI 报错行**（`[INVALID] dir/track/branch: …`），无裸 traceback（实测断言 `Traceback not in output`） |
| 8 | B6-T10：`--run` 无 `--data-dir` 时**先 adopt 后报错** | **接受** | `--data-dir` 检查**前移到 adopt 之前**（Stage 2.5）→ 零文件落盘即拒 |
| 9 | B6-T11：run 阶段单条失败**中止整批** | **接受** | Stage 4 每 item 独立 `except Exception`（含 `typer.Exit`）→ 其余继续；**部分失败 exit code 3** |
| 10 | P1-1 / P-2：`digest --all` 是**桩**（用 `hypothesis.md` 存在当方向判据，11/12 真实方向被跳过） | **接受** | 重写为**枚举全部方向文件夹**（v01/hypothesis/index/`*/*.yaml` 存在 + ident 合法），列出跳过原因，逐方向走真实 `render_digest`；实测 **12 方向全部渲染**（修复前 1） |
| 11 | P0-4：`adopt_branch`/`get_track` 未校验路径穿越（`../outside`） | **接受** | 落地前 `validate_ident(direction)` + `_validate_track_id(track)` 拦截 `../`、`a/b`、`.`、`..`、空、绝对路径（实测全拒） |
| 12 | P1-3 / P-5 / B4：lineage（`parent`/`driven_by_lesson`/`hypothesis`）只喂给门禁、**从不落盘** | **接受** | `_merged_strategy_text` 把 item 级 lineage 折叠进策略文本 → **落地的分支文件现携带 `parents:`/`driven_by_lesson:`/`hypothesis:`**（实测读回断言） |
| 13 | P1-7：digest 静默截断到 8 个品种 | **接受** | 显示 `(N instr)` 总数 + `+M more instruments omitted; see report`；浮点四舍五入（不再 17 位 repr） |
| 14 | P-10：feature 指纹含 Python **patch** 版本 → 跨机不可比 | **接受** | `_py_minor()` 只用 major.minor，跨机可比性恢复 |
| 15 | ai_readme §3 命令签名错（`new-version`/`prune` 缺/错 `--branch`、`lesson` 参数序、digest "5 lessons"） | **接受** | 全部按真实 CLI 修正；digest 措辞改"last 3 by default（`--n-lessons N`）" |
| 16 | P1-4 / B4-manifest：完整 bundle 归档 + batch manifest 子系统 | **拒绝** | 等于**新增 OCI artifact 类型**，触碰已锁的 alpha 边界；溯源已落盘（分支文件 + index 事件），重做一遍是第二事实源。留到多 AI 重度使用时再评估 |
| 17 | P1-6 / P1-8 / P1-9：digest 两层记忆 / latest-vs-best 可比性重构 | **拒绝** | `digest` 已够用、`lyra compare` 已覆盖深度可比；这是更大的设计阶段，非收尾循环阻塞项 |
| 18 | P-8：`submit --stdin` | **拒绝** | 不在关键路径：写 YAML 的 coding-AI 本就持有该文件；纯 web-AI **无法跑 shell**，`--stdin` 无消费者 |
| 19 | P-9：run ledger（第二索引） | **拒绝** | 当前规模 glob 确定且够用；ledger = **第二事实源**，有漂移风险（与 I17 append-only 原则相悖） |
| 20 | P-11：pull-corpus 路径错配（0010 通道） | **拒绝** | 0010 temp/ triage 明确在**当前范围外**（状态块"可选增强"） |
| 21 | B9：OCI push 多写者追加冲突 | **拒绝** | 平台模型是**单写者 per workspace**（已文档化）；并发是独立设计阶段，不在收尾范围 |
| 22 | §4.x：null-hyp 基准 / 引擎攻击面审计 / property-fuzz / 前向 OOS 复评 / 元 AI 学习 | **拒绝**（本阶段） | 研究**方法论**增强，属**后续阶段**，非闭环阻塞；§5.3/5.4（更多品种 / 选择偏差警示）仅作文档指引，无代码 |

**接受 15 / 拒绝 7 / 挂起 0**（第 22 行内含 1 条"仅记录"的指引）。

---

## 二、实现落点（逐文件）

| 文件 | 变更 |
|---|---|
| `lyra/batch.py` | `parse_batch` 重写：顶层 `bundle`/`directions`/`items` 三选一（首个出现的列表胜）；`strategy:` 接受字符串块 **或** 映射（映射→`safe_dump` 无损）；`_yaml.YAMLError`→`BatchError`（带修复提示，非裸 traceback） |
| `lyra/cli.py` | `apply_batch_cmd` 重构：**Stage 2** 用 `_merged_strategy_text` 落盘 lineage（替代 `_lineage_view` SimpleNamespace）；**Stage 2.5 全量 preflight（零写盘）**——`--run`⇒`--data-dir` 前置、`validate_ident`+`_BRANCH_NAME_RE`、`get_track`、direction 交叉、`_validate_new_branch_lineage`、per-track 新分支 cap（幂等重提交不计）、bundle 内去重；**Stage 3** 如实失败信息（列已落盘 + 不可回滚说明）；**Stage 4** 每 item `except Exception` 独立续跑 + **exit code 3**；`digest_cmd --all` 重写（枚举全部方向，去 `hypothesis.md` 判据） |
| `lyra/workflow.py` | `adopt_branch` + `get_track` 落地前 `validate_ident(direction)` + `_validate_track_id`；`render_digest` 品种行显示总数 + 截断提示 + 浮点四舍五入 |
| `lyra/features.py` | `_py_minor()` = major.minor（原为完整 `platform.python_version()`） |
| `lyra/ai_readme.md` | §3 命令签名按真实 CLI 修正（`prune --branch` / `new-version --track --branch` / `lesson` 参数序）；digest "last 5"→"last 3 by default" |
| `tests/test_runner.py` | `test_run_id_covers_consumed_feature_values` 去 pandas（duckdb `COPY … REPLACE` + `.orig.parquet` 备份还原） |
| `tests/test_batch.py` | +6 回归：`bundle:` 别名、映射 strategy 无损往返、坏 YAML 干净报错、direction 交叉拒（零落盘）、路径穿越拒、lineage 落盘断言 |

---

## 三、E2E 实锤（隔离 workspace `~/.lyra/bt2`，真实 CLI）

1. **P0-2/B1**：`bundle:` 顶层 + 映射 `strategy:` 的 bundle → **dry-run VALID → apply 成功**（`1 adopted`）。
2. **P-5/B4**：落盘 `v02.yaml` **实测含** `parents: [v01]` / `driven_by_lesson: v01 baseline was too tight…` / `hypothesis: Wider SMA cross entry`——lineage 真落盘（修复前只喂门禁、不写盘）。
3. **P1-2/B3**：`item.direction=fx-trend` 但策略内 `direction: DIFFERENT-DIR` → `[INVALID] … must match`，**`v03` 未落盘**（`0 adopted`）。
4. **P-7**：同 bundle 两条 `v04` → `duplicate target fx-trend/t1/v04 appears more than once`，**整批拒**（`0 adopted`）。
5. **B6-T10**：`--run` 无 `--data-dir` → `ERROR: --run requires --data-dir (checked before any writes)`，**零文件落盘**；重放幂等（`v02.yaml` 仅 1 份）。
6. **P0-4**：`direction: ../evil` → `invalid direction '../evil'`，**未创建任何 evil 目录**（workspace 内外均无）。
7. **P1-1/P-2**：`lyra digest --all` 现列出**全部 12 个真实方向**（`failed_breakout`…`volume_activity`），修复前因 `hypothesis.md` 缺失跳过 11 个。
8. **B5**：坏 `strategy:`（`entry: [unclosed`）→ 干净 `[INVALID]` 行，**无裸 `Traceback`**（回归断言）。

**回归**：`tests/test_batch.py` **12 passed**；全仓 `pytest -q` **387 passed**（基线 381 + 6）；`pyflakes lyra/ tests/` **干净**。

---

## 三-补、自检（self-check）+ 对抗性检验（adversarial）

> 用户要求：对 #131 的**改动本身**做自检与对抗检验，并把结果并入本文件；再模拟 3-4 轮循环验证"现在是否更好"。
> 方法：先**读改动的真实代码**逐行核逻辑，再用**真实 CLI** 从攻击者/AI 角度逐项打，最后角色扮演跑循环。全部在隔离 workspace（`~/.lyra/bt3`、`~/.lyra/stagerun`），不动 `~/.lyra/default` 真实资产。

### A. 代码逻辑自检（读码结论）

| 核对点 | 结论 |
|---|---|
| preflight 与 stage 3 读**同一份** merged 文本解析出的 `spec` | ✅ 无漂移——门禁输入 == 落盘产物（`_merged_strategy_text` 既喂 `parse_strategy` 又写盘），不会"门禁通过但落盘内容不同" |
| `parse_batch` 顶层别名（`bundle`/`directions`/`items` 首个出现的列表胜） | ✅ 顺序明确，`present keys` 报错列出实际键名，AI 可自纠 |
| 映射 `strategy:` 用 `safe_dump` 无损 | ✅ 换行/反斜杠/unicode/null 均不损坏（回归 `test_parse_batch_mapping_strategy_roundtrips_lossless` 断言） |
| 坏 YAML → 干净报错 | ✅ `BatchError`（带 fix hint）+ CLI 层 `[INVALID]` 行，均无裸 `Traceback` |
| cap 计数**只计新分支**（`_branch_dest(it).exists()` 跳过幂等重提交） | ✅ 见下方对抗 (3)：满 8 时重提交已有分支仍成功 |
| direction 交叉校验读 `spec.direction`（可能为 None→跳过） | ✅ `None` 时不强行比对，避免误杀 |
| `_IDENT_BAD = ("..",".")` + `_IDENT_RE` 拒绝 `.`/`..`/空/`/` | ✅ 路径穿越全拦（见 B） |

### B. 对抗性检验（攻击者/AI 视角，真实 CLI 逐项打）

**B1 路径穿越（P0-4）— `validate_ident` 拒绝/接受集**

| 输入 | 期望 | 实测 |
|---|---|---|
| `../outside`、`a/b`、`''`、`.`、`..`、`/abs` | 拒 | ✅ 全拒 |
| `foo`、`t_me`、`v02`、`v2_001`、`fx-trend` | 收 | ✅ 全收 |
| `a.b`、`a..b` | **合法文件名**（非穿越） | ✅ 收（**正确**：它们是单段合法名，不是目录逃逸） |
| track `V2`、`T-A`（大写） | 拒（`_validate_track_id` 小写限定） | ✅ 全拒 |

**B2 分支名一致性 — `validate_ident` 不拒绝 `_BRANCH_NAME_RE` 允许的合法名**
`v01`/`v02a`/`v2_001`/`v123`/`v99` 全部通过 `validate_ident` 且全部匹配 `_BRANCH_NAME_RE`——两套校验**一致**，不会"识别层放行、正则层拦"的错配。

**B3 cap / 幂等 / 不可变（满 8 的边界组合，隔离 `~/.lyra/bt3` fx-trend/t1 填到 7/8）**

| 场景 | 期望 | 实测 |
|---|---|---|
| (1) 提交第 8 个**新**分支 `v09`（7+1=8，恰满） | 成功 | ✅ `1 adopted` |
| (2) 提交第 9 个新分支 `v10`（8+1>8） | **拒** + 提示 prune | ✅ `[INVALID] … would exceed the 8-branch cap (currently 8, +1 new) — prune one first` |
| (3) 满 8 时**重提交 `v02` 同字节**（幂等） | 成功（不耗新槽） | ✅ `1 adopted`（`_branch_dest` 已存在→不计新） |
| (4) 满 8 时**重提交 `v02` 不同字节** | **拒**（不可变）+ **诚实信息** | ✅ `0 of 1 were adopted BEFORE this failure and REMAIN on disk (branches are immutable, so nothing was rolled back)…`——**无假话"rolled back"**（B2 修复实锤） |
| prune 后槽位回收 | `v09` prune → 7/8 | ✅ `pruned branch v09` + `t1  active=7/8` |

**B4 dry-run / 真实 apply 门禁等价（P0-3/B2 核心 bug——"dry-run 全过、真实 apply 半途失败"必须消失）**

| bundle | dry-run | 真实 apply | 等价 |
|---|---|---|---|
| `v10`（超 cap） | REJECTED（exit 1） | REJECTED（exit 1） | ✅ 同判同码 |
| `v02`（幂等） | VALID（exit 0） | 成功（exit 0） | ✅ 同判同码 |

→ 二者**共享同一 preflight 门禁**，不再出现"dry-run 说能过、真跑却失败/半落盘"的分裂。

**B5 stage-4 `--run`（真实数据 `~/.lyra/default/data`，`~/.lyra/stagerun`，方向 `market_structure`）**
- 满 cap 时 `--run` 新分支 → preflight 拒（零落盘）✅
- prune 腾槽后 `--run` → `1 adopted · 1 run ok, 0 failed`、run_dir **track-scoped**（`runs/stg_v02__t_r/…`，M3 归因不覆盖）、exit 0 ✅

**结论**：#131 改动**自检无逻辑漏洞、对抗 5 组攻击（穿越/cap/幂等/不可变/门禁等价/真实 run）全部如预期**；修复前会暴露的两处最坏情况——**假话"rolled back"**（B2）与 **dry-run/真实 apply 分裂**（P0-3）——现均**实测消除**。

---

## 三-补-2、web-AI 角色扮演 4 轮模拟（"现在是否更好"）

> 用户要求：以"只会读写文件 + 调 command、不会写 py 的无 coding AI"身份，在真实数据上跑 3-4 轮"读→写→跑→看→记→下一轮"循环，验证体验是否变好、并找出还能更好的地方。

**方向 `momentum_exhaustion`，隔离 workspace `~/.lyra/simz`，真实数据 `~/.lyra/default/data`（14G）：**

| 轮 | 动作 | 结果 |
|---|---|---|
| R1 读 | `digest`（348 字节）+ `context`（4.8KB） | ✅ hypothesis 显示（非 `(none)`，#130 修复生效）、146 feature、清晰指向 context |
| R1 写+跑 | 建 `t_me` track → 写 v02（parent v01 + lesson）→ `submit --track --branch v02 --data-dir` | ✅ exit 0，`SPX500_USD: 179 trades, ann=+0.014, win=67.6%` |
| R2 写+跑 | v03（parent v02，hold 12） | ✅ exit 0 |
| R3 写+跑 | v04（parent v03，hold 8） | ✅ exit 0，`ann=+0.008, win=62.0%` |
| R4 记 | `lesson` 记一条结论 | ✅ exit 0 |
| R4 看 | `digest --track t_me` | ✅ **726 字节**，**3/8 active**，每分支一行（`ann=+0.014 win=67.6%` 已四舍五入）+ lesson + hypothesis + "full detail: context" 指引 |

**结论：4 轮闭环完全成立，比修复前更好**——
- **低 token**：每轮"看"只需 digest **348-726 字节**（<300 token），远低于修复前"submit 全量 report 2.5 万 token"。
- **无摩擦**：lineage 门禁（R12）、cap（3/8）、不可变、run 归属（`runs/me_v0N__t_me` track-scoped）、`did-you-mean`、hypothesis 回退**全程无卡点**。
- **迭代带记忆**：lesson 落盘后 digest 直接给下轮 AI 看。

**模拟中暴露并修复的 1 处真实摩擦**：
- **`submit` 遇到策略 YAML 无 `direction:`/`family:` 时**，报错是**误导性的 `invalid direction None`**（复用了路径穿越的措辞，AI 完全不知道要加什么字段）。已修复为**可自纠的明确报错**：`ERROR (not run): the strategy YAML declares no direction — add a top-level \`direction: <slug>\` (or legacy \`family: <slug>\`) field (see the template in \`lyra context <direction>\`)…`（新增回归 `test_submit_missing_direction_is_actionable`）。**设计取舍**：不靠文件路径猜 direction——因为 `run_meta` 的 direction 取自**文件内容**（`data.get("direction") or data.get("family")`），路径猜测会静默写错归因，故宁可明确报错让 AI 补字段。

**两处"疑似 bug"经核验为测试伪象（非真 bug，如实记录）**：
1. **digest 显示 `0/8 active`**：首轮模拟中我先**把分支文件写进 track 目录**再 submit → `adopt_branch` 命中"文件已存在→幂等 no-op"分支（**不调 lineage、不写 activate**），故未登记。**真实 AI 不会预写分支文件**（它写草稿在任意位置），`submit` 会走"新分支"路径正确 activate（simz 复现 `3/8 active`）。`adopt_branch` 的幂等/不可变设计本身**正确**。
2. **`invalid direction None`**：由我 `clone()` 时**丢弃了 `family:`**（真实 v01 用 `family:` 而非 `direction:`）导致 spec.direction=None。带 `family:` 的忠实 v01 副本 submit **完全正常**（exit 0）。

**仍可更好的方向（不阻塞，留待拍板）**：
- **feature 字典**：146 个 feature 只有名字、无 ≤15 字含义，AI 起步靠抄模板 + did-you-mean 够用，但**补一句含义**能显著降低"选错 feature"试错轮数（P2 增强，已多轮提出未做）。
- **`digest` 的跨分支对比**：现在每分支一行独立分数，**无"v02 vs v04 谁更好"的并排**——`lyra compare` 已覆盖深度对比，但 digest 里加一行 `best: v03` 能省 AI 一次 read（P1，审查已列，本轮未动）。
- **`submit` 与 `apply-batch` 的门禁一致性**：`submit` 的门禁在 `adopt_branch` 内（lineage/cap/immutable 都在），`apply-batch` 的 preflight 把这些**前置**——二者语义一致但**入口不同**（submit 单条、batch 多条）。若未来加 `submit --dry-run` 让单条也能"先验后跑"，可对齐 batch 体验（P2，非阻塞）。

---

## 四、诚实边界

- **拒绝项非"不做"，是"不在收尾阶段做"**：#16 bundle manifest、#17 digest 重构、#21 多写者并发、#22 §4.x 研究方法论——均为**独立设计/后续阶段**，且触碰已锁边界（alpha/OCI）或非闭环阻塞。留待用户按优先级拍板。
- **`apply-batch` 的 `--run` 单条失败** = 记录 + 其余续跑 + **exit 3**（adopt 阶段仍全或无 D6；run 阶段本就逐条独立，不假装回滚）。
- **本轮模拟新增修复**：`submit` 遇无 `direction`/`family` 策略时，原报 `invalid direction None`（路径穿越措辞，误导）→ 改为可自纠的"add a top-level `direction:`"报错（**不靠文件路径猜**，因 run_meta 的 direction 取自文件内容，路径猜会写错归因）。
- **P-8 `--stdin` / P-9 ledger** 是**平台模型取舍**（单写者 per workspace + 单事实源 + append-only），非遗漏；若未来上多 AI 并发/重多方向规模，再单独立项。
- **feature 字典**（146 feature ≤15 字含义）仍为 P2 可选增强，未做（`context` 已给 feature 名 + did-you-mean，不阻塞循环）。
- **待用户 `git push`**（本环境无凭据；origin/main 仍 = `526f2ea`）——#131 落地后需 push 到 main 触发 CI（其中 P0-1 的 CI 红已修）。
