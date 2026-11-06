# Action Log（中央行动日志）

> **English**: [ACTION_LOG.en.md](./ACTION_LOG.en.md)
>
> 本文件是 Lyra 的**中央行动日志**：谁在什么时候做了什么、为什么、落在哪个
> 文档/规则上。各文档的"修订记录"是细粒度审计痕迹；**本文件是时间线总账**。
>
> **维护规则**：
> 1. 任何文档改动、规则新增/修改、用户决策、review 结论，**都必须在本次
>    改动里追加一行**（与改动同 commit）。
> 2. 只增不删。被推翻的条目**不删**，追加新行标注"推翻 #N"。
> 3. 每条必须有：日期、类别（decision / doc / review / fix）、内容、落点
>    （文档 + 章节/规则号）。
> 4. AI 和人都能读；AI 在动手前先扫本文件最近 10 行，避免重复决策或
>    推翻已定事项。
> 5. **`## 当前状态` 块是全文唯一允许随时间原地更新的位置**——且更新它是
>    **强制的**：任何一次改动（文档/代码/配置/策略/review）落地时，必须在
>    同一次改动里刷新该块（done / next / 待用户输入 / 更新于戳），见
>    AGENTS.md Non-negotiables 第 1 条。只做日志行、不刷状态块 = 改动不完整，
>    不得收尾、不得 commit；日志条目本体仍只增不删。
>    **新会话的"项目现在到哪了"以该块为准**（AGENTS.md 只指路，不写进度）。

## 当前状态（Current state）

| 项 | 值 |
|---|---|
| 更新于 | 2026-11-06（#39） |
| 构建顺序 | `docs/hld.md` §8（0001→0009，唯一事实来源） |
| 已完成 | **0001**（repo + OCI split，文档定案）；首次 commit `c8f3851`（文档骨架 + LICENSE + pyproject + examples） |
| 下一步 | **0002**：OCI pull + clean + aggregate —— 先写 `docs/decisions/0002-ohlcv-data-sync.md`（中英），再写代码 |
| 代码状态 | 尚无源码；`lyra/` 包将在 0002 随代码创建 |
| 代码交付顺序 | 0002 pull → 0003 feature builder → 0004 compiler → 0005 trade engine → 0006 metrics/runner（在 fixture 数据上）→ 0007 push/backup |
| 未决问题 | **无**（open-questions O1–O5、O11–O15 全部已关闭） |
| 待用户输入 | 0002 的 OCI 访问方式（PAR URL vs 签名请求，决定 O5 最终答案）+ OCI 连接参数 |

## 图例

- **decision**：用户拍板的决策
- **doc**：文档新增/改写
- **review**：用户或第二个 AI 的审查及结论
- **fix**：按审查结论做的修复

## 2026-11-05

| # | 类别 | 内容 | 落点 |
|---|---|---|---|
| 1 | doc | 扫描 moneta / nova 全部文档后，建立 lyra 文档骨架（README、AGENTS、requirements、background、hld、proposals/oci-alpha-layout、decisions/TEMPLATE + 0001、open-questions、config_example） | 全库 |
| 2 | decision | 用户拍板：lyra 为新 repo（非改 nova）；所有模块都重构（程度不同）；**每次推进前先写决策文档**，按功能流顺序推进；alpha 布局可提 proposal 但要落文档供多方 review；README 英文 + 其余中文 | `hld.md` §8、`AGENTS.md` |
| 3 | decision | 用户修正：除 README 外，所有文档**中英对照两份**（`.md` 中文保留英文术语 + `.en.md` 英文） | 7 对文档 + `AGENTS.md` References |
| 4 | decision | `strategies/` 一级单元定为**方向（direction）+ 版本链（vNN）+ hypothesis.md + lessons.md**；迭代（前期 run 驱动后期设计）是核心工作流；继承 nova 的 12 方向 | `oci-alpha-layout.md` §2.3、`requirements.md` R12、新增 B11/B12 |
| 5 | decision | 方向集合 **extendable**：初始 12 是种子非封闭清单；新方向放 `_new/`，与初始同权 | `oci-alpha-layout.md` §2.3、`requirements.md` R12 |
| 6 | decision | 用户确认 **A 方案**：新方向准入标准为**软标准**（建议可检验/不重复），不建方向等价性检查器 | `oci-alpha-layout.md` §2.3（v0.4）、`requirements.md` R12 |
| 7 | review | 第二个 AI 发现：旧 `active/` `archived/` 模型残留在顶层目录树、B1、B6、I15（中英 5+ 处），与方向模型矛盾 | — |
| 8 | fix | 清除全部残留：目录树改方向文件夹；B1 改按**内容特征**判定（hypothesis/lessons/vNN）；B6 改"方向文件夹（含 killed）不可删"；I15 对齐 | `oci-alpha-layout.md` §1/§3（v0.5）、`0001` I15 |
| 9 | review | 用户发现：`config_example.yml` 的 `local.*` 全部指向 repo 根目录 → OCI 镜像（含 alpha）会铺进 git 工作区，误提交风险 | — |
| 10 | fix | 新增 **B13**（OCI 镜像默认在仓库外 `~/.lyra/<workspace>/…`；进工作区需 `--inside-repo` 显式确认）+ **B14**（`strategies/examples/` 是 git 唯一 strategies 子树，运行时不读写为 alpha）；config 改 workspace 模式；0001 I11 对齐 | `config_example.yml`、`oci-alpha-layout.md` §3（v0.6）、`requirements.md` R6、`0001` §3.3/§4/§5、`hld.md` §1.4/I11、`AGENTS.md` |
| 11 | review | 第二个 AI 发现：README / background / hld 对推进顺序三种口径打架（4 核心组件先行 vs 三件事 vs 0001→0009） | — |
| 12 | fix | 统一：**`hld.md` §8 为唯一事实来源**（0002 OCI pull 先于 0003-0006 核心组件，理由：数据同步是主功能 R7；核心组件 fixture 先行不阻塞）；README / background 改为引用 | `hld.md` §8（v0.2）、`README.md` Current status、`background.md` §3 |
| 13 | review | 第二个 AI 发现：B11/B12/B13/B14 引入后，7 处旧引用仍写"B1-B10"（layout §5、0001 三处、AGENTS） | — |
| 14 | fix | 全文 B 规则引用统一为 **B1-B14** | `oci-alpha-layout.md`（v0.7）、`0001`（v0.4）、`AGENTS.md` |
| 15 | doc | 建立本中央行动日志 | `ACTION_LOG.md` + `.en.md` |
| 16 | decision | 用户确认 **AI 是一等写作者**（策略迭代），且要求 AI 写时**上下文高效**：不读大量 repo 文件 | — |
| 17 | doc | 落"AI 效率要求"：`lyra context <direction>` 单文件上下文包（hypothesis + 最近 N 段 lessons + 最新 vNN + 上次 run 摘要 + feature 清单）；AI 写循环 = 读1/写1/跑1/记1；hypothesis/lessons/vNN 格式保持 LLM 友好 | `oci-alpha-layout.md` §2.3（v0.8）、`requirements.md` R12（v0.5）、`AGENTS.md` |
| 18 | review | 自查"AI 一等写作者"改动与其他文档的冲突：发现 **R9 "自动策略生成/AI candidate generation 不做" 与 R12 字面矛盾**；另两处"用户手动"（alpha features / rebuild-index）经查不冲突 | — |
| 19 | fix | R9 + background「不做」清单改为排除 **autonomous / unbounded AI generation**，并显式注明 **AI 有界迭代（方向内写 vNN + 人逐版 review）属于范围内（R12）** | `requirements.md` R9（v0.6）、`background.md` §3 |
| 20 | decision | 用户确定**版本树**模型：单线程深搜会陷局域最优，一个版本（成功或失败）都应支持多个演进方向；AI 要能对比多个分支并综合判断（continue / prune / cross，类基因算法的变异/交叉） | — |
| 21 | doc | 版本树模型落地：命名 `v<代数><分支后缀>`（v02a/v02b/v04ab）；新命令 `new-version --branch` / `compare --siblings` / `merge --from <a> --from <b>`；分支生命周期 active→pruned（文件保留不删）；kill criteria = 所有活跃分支连续 N 轮失败；context 包新增兄弟分支 run 摘要对比表；B12 改 `parent`/`parents` | `oci-alpha-layout.md` v0.9、`requirements.md` R12 v0.7、`AGENTS.md` |
| 22 | decision(推翻 #22 初稿) | **交叉/变异完全交给找策略的 AI**：取什么、怎么合成（整块 / 逐参数 / 改造参数）全由 AI 自由决定，框架**不限制粒度**；框架的职责是**保证这个 AI 有此能力**（`lyra context` 含活跃分支完整 YAML+参数，AI 可读取自由组合）；审计靠 AI 在 `inherited`/`driven_by_lesson` 声明来源。推翻了"克制式交叉（只能整块继承）"的初稿 | `oci-alpha-layout.md` §2.3、`requirements.md` R12 |
| 23 | review | 全库交叉审计发现 **hld 与 R12/版本树冲突**：§2.3 写"不生成新策略（未来由 campaign 做，不在 core）"——与"AI 是一等写作者 + 版本树迭代是核心工作流"直接矛盾；§7 目录树 ZH 缺 0008、EN 缺 0009 | `hld.md` §2.3/§7 |
| 24 | fix | hld §2.3 移除冲突行、补"策略演进"块（context / new-version / compare / merge / push-direction，对齐 R12 + AI 自由交叉）；§7 目录树中英补齐 0008/0009 并修正 0007 的 └── 符号 | `hld.md` v0.3、`hld.en.md` v0.3 |
| 25 | doc | 建 `.gitignore`：按 B1/B2/B13/B14 边界配置；`strategies/*` + `!strategies/examples/` 实现"忽略 alpha 方向文件夹、保留示例子树"；忽略 data/runs/features/tmp + 凭证 + Python 构建；`git check-ignore` 双向验证 19 条边界全对 | `.gitignore`（新建） |
| 26 | review | 自模拟对抗性 review，发现 **3 处真实冲突/漂移**：① AGENTS "no auto-strategy-generation" 与 R12（AI 一等写作者）字面冲突；② AGENTS References 写 "R0-R11"，实际已有 R12；③ hld §4 不变量表只列到 I14，但 AGENTS/0001 都引用 I15-I17（hld 作骨架不自洽） | AGENTS.md、`hld.md` §4 |
| 27 | fix | AGENTS "no auto-strategy-generation" → "no **autonomous/unbounded** strategy generation（有界 AI 迭代 in scope，见 R12）"；AGENTS References "R0-R11" → "R0-R12"；hld §4 不变量表补 I15/I16/I17（来源标 0001）中英两份 | AGENTS.md、`hld.md` v0.3、`hld.en.md` v0.3 |

## 2026-11-06

| # | 类别 | 内容 | 落点 |
|---|---|---|---|
| 28 | doc | 建立 `docs/reviews/` 专项目录，归档第一轮对抗性审查报告并逐项标明完成状态（.gitignore / 残留 active 清理 / 路线图统一已完成，LICENSE / pyproject / Commit 0 挂账） | `docs/reviews/对抗性review-2026-11-05-批次1.md` + `.en.md` |
| 29 | review | 第二轮对抗性红队审查（批次 02）：发现 7 处深层漏洞（B9/I17 OCI 全局不可变致 lessons.md 无法更新死锁、"改造参数"与 I8 特征参数锁死冲突、版本树跨代交叉未定义/分支无限蔓延规避 kill criteria、SQL 信号与 2% 止损逐 bar 极值断层、B13 遗漏 alpha/ 外部沙盒、21 标的清单与 financing 天数未定、工程脚手架挂账） | `docs/reviews/对抗性review-2026-11-06-批次2.md` + `.en.md` |
| 30 | review | 逐条核实批次1(10项)+批次2(7项)真实性后**分类评估**：✅真bug立即修=L1(B9/I17死锁)、L2(I8冲突)、L5(alpha隔离遗漏)、O4(悬挂)、批次1已修项；⏳合理后做=L4(SQL/trade-engine接口→0004/0005)、L6-financing口径→0004、LICENSE/pyproject/Commit0→T1/T3、CI→0009；🟡需用户拍板新决策=L3(跨代代次/命名碰撞/分支上限)、L6-21标的清单 → 转 O11-O15 | — |
| 31 | fix | 落地 4 处真 bug：**L1** B9/I17 改两级（Immutable: data/runs/vNN/alpha + Append-only: hypothesis/lessons/index 新⊇旧），消除 lessons 迭代 push 死锁；**L2** R12/layout 补 I8 边界（AI 改造仅限策略层，禁改特征底层参数）；**L5** B13/I11 补 `alpha/` + config 补 `local.alpha` + `.gitignore` 补 `alpha/` + AGENTS 同步；**O4** 关闭 | B9/I17(layout+0001+hld 中英)、R12(layout+requirements 中英)、B13/I11、config_example.yml、`.gitignore`、AGENTS.md、open-questions |
| 32 | decision(挂账待用户) | 批次2 中 **3 条属新决策**（非 bug）转 open-questions：**O11** 跨代交叉代数公式（建议 max+1）、**O12** 命名碰撞（建议 `_2` 后缀/hash）、**O13** Active Branch Cap（建议 3-4 上限）；**O14** 21 标的代码清单、**O15** financing 天数口径（建议物理日历天） | `open-questions.md` O11-O15（中英） |
| 33 | decision(用户) | 用户对 O11–O15 拍板：**O11** 跨代代数 = `max(父本代数)+1`；**O12** 版本名可加 `_1/_2` 区分同策略不同参数；**O13** Active Branch Cap **仍待用户定数字**（已解释含义：每方向同时 active 分支上限）；**O14** 标的继承 moneta 编码体系（`EUR_USD` 等 BASE_QUOTE，清单枚举归 0002）；**O15** financing 按**交易日**计（周末+市场节假日不计） | `open-questions` O11/O12/O14/O15 标已决（O13 挂）、`oci-alpha-layout` §2.3 命名、`requirements` R4 成本、`config_example` 注释 |
| 34 | decision(用户)+fix | **O13 定案 = 8**（每方向同时 active 分支数上限，防 AI 无限 fork；超额显式 prune）写入 open-questions + layout §2.3 中英；**修正批次1 review 标注**：item7（O4 悬挂）该 AI 标注的"未完成"已过期，因 #31 已关闭 O4，故 item7 ZH+EN + 两个汇总表第10行统一改"已完成" | `open-questions`(O13 已决)、`oci-alpha-layout` §2.3、`docs/reviews/批次1`(item7+表10) |
| 35 | fix | **T3 完成**：① `LICENSE`（Apache-2.0 全文）；② `pyproject.toml` 骨架（lyra 0.1.0, py≥3.11, 核心依赖 ≤ 8 包, `lyra` CLI entry, pytest/ruff/mypy 配置）；③ `strategies/examples/momentum_breakout/`（hypothesis.md + lessons.md + v01.yaml，YAML schema 按 nova 已验证结构）+ `strategies/examples/README.md` 清单——消除自我审计发现的"examples 悬空承诺"；.gitignore 边界验证全过（examples 可跟踪，自定义方向/alpha/data/config.yml 全忽略） | `LICENSE`, `pyproject.toml`, `strategies/examples/*`（4 文件） |
| 36 | commit | 用户决定跳过再次对抗性 review，直接做 **lyra 第一次 commit**（文档骨架 + 工程初始化：.gitignore / LICENSE / pyproject.toml / strategies/examples）。T1 关闭；下一步 T2（0002 OCI pull 决策文档 + 代码） | 首次 commit（见 git log） |
| 37 | doc | 用户问"AGENTS.md 是否足以让新对话窗口快速了解背景与进度"——审查后确认**契约部分足够，但缺三样**：①当前进度（0001 完成 / 0002 是下一个 / 尚无代码）②**双语成对规则 + ACTION_LOG 中英必须同步更新**（新窗口最易漏的约定）③一句话核心循环 + hld §8 单一事实来源点名。已补 `## Where we are (read first)` + `## Documentation conventions (load-bearing)` 两节 | `AGENTS.md` |
| 38 | doc(用户反馈) | 用户指出 #37 把"进度感"写死在 AGENTS.md 里**会过期、每次开新对话前都得手改**，不对。定案：**ACTION_LOG 的 `## 当前状态 / Current state` 块是进度的唯一事实来源**（全文唯一允许原地更新的区块，随每次日志追加同步刷新；日志本体仍 append-only）。AGENTS.md `## Where we are` 改为**只指路**（指状态块 + hld §8 + 核心循环），不再写任何会过期的进度事实；working style 的"动手前扫描"改为"先状态块、后最近 10 行" | `docs/ACTION_LOG.md`/`.en.md`（新增状态块 + 维护规则 #5）、`AGENTS.md` |
| 39 | decision(用户) | 用户（防呆对抗性检查后）定案：**"刷状态块"从维护惯例升级为强制规则**——每次执行任何工作（文档/代码/配置/策略/review），必须在同一次改动里 ① 追加 ACTION_LOG 行 + ② 刷新文件头 `## 当前状态` 块；缺其一 = 改动不完整，不得收尾、不得 commit。落点：AGENTS.md **Non-negotiables 第 1 条**（一行版，新窗口最先读到）+ Working style（完整版含判定标准）+ 两份 ACTION_LOG 维护规则 #5（强制措辞）。动机：新对话开场要读大量文档，存在失焦风险，状态块是唯一免读全文即可定位"项目在哪"的入口 | `AGENTS.md`、`docs/ACTION_LOG.md`/`.en.md` 维护规则 #5 |

## 待办（截至 2026-11-05 收工）

| # | 事项 | 依赖 |
|---|---|---|
| T1 | ✅ 用户已决定直接 commit（2026-11-06，跳过再次 review）→ **第一次 commit 进行中** | T 无 |
| T2 | 写 `0002-ohlcv-data-sync.md`（OCI pull + clean + aggregate）决策文档，含 O1 snapshot_id 定案 | T1 |
| T3 | ✅ 已完成（2026-11-06，#35）：`.gitignore`（#25）+ `LICENSE` + `pyproject.toml` + `strategies/examples/` 示例方向 | — |
| T4 | ✅ 已决（2026-11-05）：用户拍板 #22 为"AI 自由交叉"，推翻克制式初稿；layout/requirements 已同步 | — |

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿，回溯当日全部 15 条行动。 |
| 2026-11-05 | 0.2 | 补 #20/#21（版本树决策 + 落地）；补 **#22 克制式交叉（标注待确认）**；待办加 **T4**（用户确认 #22）。 |
| 2026-11-05 | 0.3 | **#22 翻转为"AI 自由交叉"**（用户拍板：交叉/变异全由找策略的 AI 决定，不限粒度；框架保证 AI 有此能力；审计靠 AI 声明来源）；T4 标 ✅ 已决。 |
| 2026-11-06 | 0.4 | 补 #28/#29：建立 `docs/reviews/` 专项目录，归档第一轮审查并标注完成状态；完成第二轮对抗性红队审查（批次 02）。 |
