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
| 更新于 | 2026-11-07（#50） |
| 构建顺序 | `docs/hld.md` §8（0001→0009，唯一事实来源） |
| 已完成 | **0001**；**0002 全部完成并在真实数据上验证**——`lyra/` 包 + **49 个测试全绿**、pyflakes 干净、**真实 `lyra pull` 端到端跑通**（moneta 真实 PAR，12 GB / 4884 万行 bronze → 998 万 5m bars → 84 万 1h bars，21 标的，2020→2026）。批次4+5+6+7 审查全部完成；**批次7 的 9 项缺陷（D1–D9）全部接受并修复**；自审 F1 闭环；**对比 moneta/nova 补齐两个真缺**——① 数据质量校验（DQ1–DQ3 fail-fast，nova 有/lyra 无的 OHLC/spread/volume 校验固化进 clean，真实 6161 万 CSV 行 0 违反，新增 I23；**S1 自检细化 DQ2 为逐点列感知**）② OANDA 回补工具（`lyra oanda`，moneta 有/lyra 无的按标的/时间窗口补 1m 历史，断点续传，token 只在 gitignored config）；catalog + 21 标的接口就绪；**0002 收口** |
| 进行中 | **0002 已收口**（自检 + 对抗性复查两新功能：S1 已修，OANDA 模块逐行核验通过）；commit 中 |
| 下一步 | **0003 feature builder**（HLD §8）：per-instrument feature cards + Hybrid Parquet store，**直接 `SELECT` 自 0002 的 catalog 视图**（bronze/ohlcv_5m/ohlcv_1h），消费 4884 万行真实数据；**内存规划须含 aggregate ~10 GB 峰值 + `databackend.memory_limit` 配置项**；标的池引用 `Catalog.instruments()`（权威）或 0002 §3.3 的 21 标的快照 |
| 代码状态 | `lyra/` 包在真实 12 GB 数据上端到端可跑 + 完整性三层验证全过；读路径统一 DuckDB 外部表/VIEW；**D1–D9 全修复** + 自审 F1 + **DQ1–DQ3 数据质量校验（fail-fast，DQ2 逐点列感知）** + **`lyra oanda` 回补工具**；**49 测试全绿**；pyflakes 干净 |
| 代码交付顺序 | 0002 pull ✅（批次7 终审整改完成）→ 0003 feature builder → 0004 compiler → 0005 trade engine → 0006 metrics/runner → 0007 push/backup |
| 未决问题 | **无**（D1–D9 全处置；O1 已在 open-questions 正式关闭） |
| 待用户输入 | ① 确认 0002 已补齐两项 + 自检/对抗性复查通过（S1 已修、OANDA 核验）后启动 0003；② **真实 2019-11/12 全 21 标的 OANDA 实测被阻**——moneta 旧 token 对 practice/live 双 host 均 **401 过期**，需用户签发**新 token** 填进 gitignored `config/config.yml` 的 `oanda.api_token`，再跑 `lyra oanda GBP_USD --from 2019-11-01 --to 2019-12-31 --dry-run`（token 是秘密、需网络，离线无法代跑） |

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
| 40 | doc+decision | **0002 决策文档落地**（中英，状态=提案待审批）：① 扫 moneta `pipeline/extract_oci.py` + `aggregate_ohlcv.py` 摸清已验证机制（PAR prefix 列对象分页 / 对象流式下载 / size 幂等 / path-traversal 防护 / UTC 边界聚合 + `n_bars`）；② **定案 pull 用 PAR prefix URL**（沿用 moneta 机制，零 SDK 凭证；push 侧 signer 与否留 0007 再评估）；③ **O5 定案**：PAR 用户侧管理 + `lyra pull` 403/404 过期诊断 + 0009 doctor 体检；④ **用户要求的 PAR 预留**：`config_example.yml` `oci:` 段改为 3 个位置——`data_par_url`（0002 用）/ `strategies_par_url` + `features_par_url`（0007 用，本 feature 只占位不读取）；⑤ 定案新不变量：数据层可复现性（同 PAR+同代码 → 逐字节一致【#41 已修正为逐行一致】）、PAR URL 日志脱敏 | `docs/decisions/0002-ohlcv-data-sync.md`+`.en.md`（新建）、`config/config_example.yml`、`docs/open-questions.md`/`.en.md`（O5 关闭）、状态块 |
| 41 | review+fix | **0002 自检 + 批次3 对抗性 review**（用户要求；专项打 0002，逐条核对 moneta 源码/真实数据）。**自检 7 处**：S1 输入契约与 moneta 真实列不符（实际必需 `instrument,time,is_complete`，mid/bid/ask 可选，真实 15 列）🔴；S2 clean 语义漏 moneta `load_data.py` 三规则（is_complete 过滤 / (instrument,time) 去重 / 确定性存活行选择）🔴；S3"逐字节可复现"与未定义去重规则自相矛盾 + Parquet 文件字节本就不稳 🔴；S4 size 幂等太弱（moneta list 已取 md5 却未用）；S5 CLI 歧义；S6 缺 prefix 级 PAR / 非 1m 拒绝两句；S7 config 真实值位置未写明。**另抓到 0.1 不变量编号 I2–I6 与 hld §4 已占用编号冲突** → 重编 **I18–I22**。**批次3 红队 5 项**：A1 派生缓存陈旧（bronze 被删/损坏时静默丢数据）→ **raw 层唯一幂等，clean/aggregate 恒重算**；A2 bronze schema 未定义 → **显式定案**（7 列必含 / bid/ask 依源 / 不含 is_complete，0003 输入契约）；A3–A5 记录为接受边界。测试清单 9→14 | `docs/decisions/0002*`（v0.2→v0.3）、`docs/reviews/对抗性review-2026-11-06-批次3.md`+`.en.md`（新建）、状态块 |
| 42 | doc(用户问) | 用户问"0002/0001 等文档提到的 moneta、nova 是前代仓库，入口文档是否说明了"。核对：README/AGENTS/background 有定义，但**决策文档内部首次出现处没有就地指路**（新窗口读 0002 时"moneta"可能是第一个看到的陌生词）。修复：① 0002 §2 背景开头加谱系指路行（中英，指 `docs/background.md`）；② AGENTS.md 头部加 **Lineage** 块：Moneta(1代,2026-10) → Nova(2代,2026-11, clean-room 重构) → **Lyra(3代,本仓库)**，前两代为本地只读参考（**只继承机制、独立重写，永不 import/修改/拷贝其运行时代码**，与 0002 §6 回滚边界一致），完整"为什么"在 background | `docs/decisions/0002*` §2、`AGENTS.md` |
| 43 | code+test+review | **0002 代码实现 + 自检 + 批次4 对抗性 review（全过）**。① 实现 `lyra/` 包：`oci_client`（PAR prefix 列对象分页 + 对象流式下载 + path-traversal 防护 + PAR URL 脱敏 + **md5 归一化**）、`pull`（zip→flat CSV，`_N` 去重名，instrument 取列名不取文件名）、`clean`（is_complete 过滤 + (instrument,time) 确定性去重 + bronze schema）、`aggregate`（UTC time_bucket 5m/1h，first/last bar，`n_bars`，I22 校验）、`pipeline`（raw 唯一幂等 + clean/agg 恒重算，typed Parquet 落盘）、`cli`（`lyra pull/clean/aggregate/version`）、`config`（`data_par_url` 必需，push 2 个 PAR 预留不读取）；② **22 个测试全绿**（0002 承诺 14 个场景全覆盖 + 8 个边界/负例），pyflakes 干净，端到端 `FakePar` 验证（70+30 根 1m → bronze 100 / 5m 20 / 1h 3；重跑仅 1 次 list 请求）；③ **批次4 红队 11 项**：修复 5 个真 bug——**A1 md5 base64/hex 双编码恒失配**（I20 幂等静默退化为 size 回退，moneta 同款坑）/ A2 `pull.py` 未 import `Iterator` / A3 `INTERVAL '5 minutes'` 未加引号 + TIMESTAMPTZ 触发 pytz 崩溃 / A4 bronze `time` 落成 string 破坏 I18 稳定 schema / A10 空表 schema 漂移；A11 PAR 脱敏**复核后判定安全**（机密在 query `Signature` 已丢弃，`/p/<namespace>` 是公开标识符）；A5–A9 判定为正确行为或已清理。**无遗留未决项** | `lyra/*.py`（新建 8 个模块）、`tests/*.py`（新建 5 个测试文件 + conftest）、`docs/reviews/对抗性review-2026-11-06-批次4.md`+`.en.md`（新建）、状态块 |
| 44 | code+test+review(真实数据) | **用户指示用 moneta 真实 PAR 跑真实端到端** → 暴露一批 **fixture 永远测不到** 的偏差（批次5）。① 从 moneta `config/setting.yml` 取真实 PAR（Garage bucket，166 objects / 1.59 GB，其中 `moneta_prices_m1.zip` 1.28 GB 主数据 + ~150 日增 zip）；② **真发现 A1（致命）**：纯 Python clean（`csv.DictReader` 逐行）在 **4884 万行 / 12 GB** 下不可行（实测卡死）→ **clean 重写为 DuckDB** `read_csv(union_by_name)+ROW_NUMBER 去重+COPY`（moneta `load_data.py` 同款，独立重实现），48M 行 ≈15 min 内存平稳；③ **真发现 A2（契约在真实数据下不成立）**：I22 原"逐对 1m"把真实 **73 万处** 市场缺口（周末/休市/无成交）全判违规 → 精确化为 **I22 = 原生分辨率 1m**（每标的最小间隔 ≈1m，缺口合法），21 标的 min gap 全 1.00 min → 0 违规；④ 真发现 A3：**pytz 是硬读依赖未声明**（输出 `TIMESTAMPTZ`，下游 fetch 崩）→ pyproject 加 `pytz>=2023.3`；⑤ 真发现 A4：`read_parquet(?)` 拒 `PosixPath` 绑定参数 → 统一 `str()`；⑥ 真发现 A5：`COPY` 无 ORDER BY 行序漂移破坏 I18 顺序承诺 → 加 ORDER BY。**真实 `lyra pull` 端到端成功**：163 zips → 183 CSVs → **bronze 48,846,896 行** → **5m 9,986,167 bars** → **1h 838,272 bars**（15m51s，21 标的，2020-01-02→2026-11-06）；`n_bars` 峰值 5 + 部分窗口（缺口）标记正确。**24 测试全绿**（新增 gapped-1m 接受 / 5m 原生分辨率拒绝 / COPY 确定性 / 空表 schema），pyflakes 干净。0002 文档升 v0.4（I21/I22 精确化 + 修订记录）。**这是"fixture 全绿 → 真实可用"的关键跨越** | `lyra/clean.py`+`aggregate.py`+`pipeline.py`+`cli.py`（DuckDB 重写）、`tests/test_clean.py`+`test_aggregate.py`、`pyproject.toml`（pytz）、`docs/decisions/0002*`（v0.3→v0.4）、`docs/reviews/对抗性review-2026-11-06-批次5.md`+`.en.md`（新建）、状态块 |
| 45 | code+test+review(完整性/高效读写/catalog) | **用户 4 项请求：①确认前面的系统中断没造成静默失败/截断/损坏 ②review+对抗性自检 ③检查 DuckDB 高效读写 + 落地"DuckDB 作为 metadata/external-table catalog" ④效率改动后再自检+对抗性**（批次6）。① **A1 完整性三层验证全过**：bronze/5m/1h footer 可读且 `num_rows` 与成功报告一致（48,846,896/9,986,167/838,272）+ **全 row-group 解压扫描**（逐 page 解码，484/484 OK、扫到行数==footer）+ raw 163/163 zip 与远端 PAR 逐对象 **md5+size** 全等 → **确认中断无截断/损坏/静默失败**；② **A2 真缺陷**：`_register_bronze` 原 `CREATE TABLE`（物化全表 48M 行）→ 改 `CREATE VIEW`（流式），新增 `test_aggregate_streams_via_view_not_table` 断言 VIEW；③ **A3 用户诉求落地**：新增 `lyra/catalog.py`——持久化 DuckDB catalog（`~/.lyra/default/data/catalog.duckdb`，仓库外，274 KB 纯 schema），`bronze/ohlcv_5m/ohlcv_1h` 三 VIEW 命名入口，`lyra pull` 末步自动 `upsert_views`，新增 `lyra catalog` CLI（`--refresh` 重建）；④ **A4 真实回归**：视图改造后重跑 aggregate → 5m/1h bars 与批次5 逐行一致（I18 成立）；⑤ **A5 git 边界**：`catalog.duckdb` 在仓库外，`.gitignore` 已覆盖 `data/`+`.lyra/`，非备份资产（0007 push 对象是 Parquet）；⑥ **A6 诚实标注效率上界**：aggregate 分组工作集在 48M 行下实测峰值 ≈10 GB（DuckDB 哈希聚合固有形态，非 bug，非流式可消除），0003 设计大 feature 面须据此规划。**30 测试全绿**（+catalog 6 个），pyflakes 干净。0002 文档升 v0.5（输出契约补 catalog + 高效读写契约 + 修订记录） | `lyra/catalog.py`（新建）、`lyra/aggregate.py`+`cli.py`+`pipeline.py`（VIEW 化 + catalog 接线）、`tests/test_catalog.py`（新建）、`docs/decisions/0002*`（v0.4→v0.5）、`docs/reviews/对抗性review-2026-11-06-批次6.md`+`.en.md`（新建）、状态块 |
| 46 | review | **0002 设计与实现全量红队审查（批次7）**：站在下游 0003/0005 与极端运维视角发起全量对抗性压力测试。抓出 2 个 Major 缺陷（**D1** Windows 路径冒号/反斜杠被 `_quote` 正则误杀破坏 R8 跨平台、**D2** `pipeline.py` 裸调 `upsert_views` 缺乏锁保护，catalog 锁冲突时 15min pull 会在最后 1ms 假死崩溃）；4 个 Moderate 缺陷（**D3** 未向 DuckDB 传入 `databackend.memory_limit` 与 `tmp` 换页路径，低配机器必遭 OOM kill、**D4** O1 snapshot_id 文档称已关实则 open-questions 留白且代码已废除未同步、**D5** 21 标的清单在真实拉取后仍未在文档或代码中枚举落盘供 0003 消费、**D6** `_validate_1m` 误杀稀疏冷门标的且报错不透明）；3 个 Minor 缺陷（**D7** 空表回退 Parquet 使用 naive timestamp 产生 Schema 时区漂移、**D8** catalog upsert 内嵌相对路径跨工作目录失效、**D9** pull 缺 zip bomb 阈值拦截）。归档报告，建议开发 AI 优先闭环 D1/D2/D3/D5 | `docs/reviews/对抗性review-2026-11-06-批次7.md`+`.en.md`（新建）、状态块 |
| 47 | fix+test+review | **批次7 红队 9 项全部接受并修复**（0002 首次外部 AI 全面审查的整改闭环）：D1 Windows 路径改 SQL 转义 / D2 catalog 锁 try-except / D3 内存配置注入（含 config_example 1GB→16GB 脚枪）/ D4 O1 补关闭 / D5 21 标的落盘 + `Catalog.instruments()` / D6 报错透明化（拒绝放宽判据）/ D7 空表时区 / D8 相对路径 / D9 解压炸弹。**38 测试全绿**（+8），pyflakes 干净，0002 v0.6，**0002 收口** | `lyra/{clean,aggregate,pipeline,catalog,pull,config,cli}.py`、`tests/test_catalog.py`（+8）、`config/config_example.yml`、`docs/decisions/0002*`（v0.5→v0.6）、`docs/open-questions*`（v0.4→v0.5）、`docs/reviews/对抗性review-2026-11-06-批次7*`（+处置表）、状态块 |
| 48 | self-review+adversarial+fix+test | **0002 收口前的自审 + 对抗性自审**（用户要求：先自审再对抗性，找潜在问题；给 0002 总结 + 0003 预览）。逐条核验批次7 改动后抓出 **F1 真缺陷**：`Catalog.instruments()` 的 docstring 承诺"bronze 视图缺失/不可读时返回 []"，但 bronze parquet 被删除（或损坏）时 `SELECT` 抛 `IO Error` 而非降级——修：`except duckdb.Error: return []`，新增回归测试 `test_instruments_returns_empty_on_broken_catalog`（valid-then-delete 真实复现路径，已验证不再抛）。另核验 3 个候选均为**误报/拒绝**：② `run_pull` 未显式 close 两个 count 连接——属 CPython refcount GC 兜底、非正确性 bug，且改 scoped-close 会破坏 D2 现有测试结构 → **挂起**（值得 0003 时一并清理）；③ 0002 文档疑似引用不存在的 `_count_rows`——grep 证实文档用 DuckDB `COUNT(*)`，**误报**；④ `tmp/` 目录疑似泄漏——实为 DuckDB `temp_directory` 合法换页空间，**误报**。**39 测试全绿**（+1），pyflakes 干净。真实数据回归核验：bronze/5m/1h = 48,846,896/9,986,167/838,272（与批次5 一致，I18 成立）、`instruments()`=21 标的。**0002 正式收口**，0003 就绪 | `lyra/catalog.py`（F1）、`tests/test_catalog.py`（+1）、状态块 |
| 49 | code+test+doc(用户拍板) | **对比 moneta/nova 补齐两个真缺**（用户审阅后拍板"都补进 0002"）。**① 数据质量校验（0002 §3.4，DQ1–DQ3，fail-fast）**：moneta `load_data.py` 只有 is_complete 过滤 + 去重、**不校验** OHLC/spread/volume——脏数据会静默流入 bronze 污染 0003/0005；nova `data._validate` 有这些检查。把这一环显式固化进 `clean.py`：`_quality_checks`（列感知，DQ2 仅 8 列全有时启用防 `union_by_name` binder error）+ `_assert_quality`（is_complete 过滤 + 去重**后**、COPY 写 bronze **前**对存活候选行校验，违反即 `DataQualityError` 列出各项违反数、bronze 不写出）；`fetchall` 全消费结果防 list 路径的连接复用异常。DQ1 mid OHLC 正值且 o,c∈[l,h] / DQ2 两侧都有时 ask≥bid / DQ3 volume 有限非负。**真实 61,615,338 CSV 行（183 个真实 moneta CSV）0 违反**（不误伤）+ AUD_USD 单标的 246 万行端到端 clean 通过；新增不变量 **I23**。顺带修 **2 个测试 fixture 真 bug**：`test_aggregate.py` + `conftest.py` 的占位 bid/ask 是反的（bid_l>ask_l，物理不可能），被新 DQ 正确拒绝 → 改为 ask≥bid 的合法报价。**② OANDA 回补工具（0002 §3.5，`lyra oanda`）**：moneta `extract_oanda.py` 有"按标的/时间窗口补 1m 历史"、lyra 无。独立重写为 `lyra/oanda.py` + `lyra oanda` CLI——OANDA v3 分页（5000K 线上限 + 每页 1K 线重叠去重）/ UTC 日历月分块 / **断点续传**（已存在非空月份默认跳过、`--force` 重拉）/ **token 只在 gitignored config**（空 token → `OandaConfigMissing` 响亮失败，`--dry-run` 不需 token）/ 输出对齐 bronze 输入契约。clean 的 CSV glob `*.csv`→`**/*.csv`（DuckDB 2.0 递归展开）使 per-instrument 子目录一等公民。新增 `OandaConfig`+`oanda_from_dict`（config.py）+ `config_example.yml` oanda 段。**47 测试全绿**（+8：DQ 4 + OANDA 3 + nested-csv 1），pyflakes 干净。真实 OANDA 拉取留给用户填 token 后验证（token 是秘密、需网络，离线无法代跑；CLI `--help`/`--dry-run` 已验）。0002 文档升 v0.8（§3.4/§3.5/I23/测试清单/修订） | `lyra/clean.py`（DQ）、`lyra/oanda.py`（新建）、`lyra/config.py`（OandaConfig）、`lyra/cli.py`（lyra oanda）、`tests/test_catalog.py`（+8）、`tests/test_aggregate.py`+`conftest.py`（fixture 修复）、`config/config_example.yml`、`docs/decisions/0002*`（v0.7→v0.8）、状态块 |
| 50 | self-review+adversarial+fix+test(用户拍板) | **用户拍板：新加的两个特性先自检、再以对抗性复查复核，然后再进 0003**（"等一等再进行 0003"）。**① 自检（S1 真缺陷）**：DQ2 spread 校验原来用"8 列全有才算"门控——**部分报价输入（只有 `bid_o`/`ask_o`，或任意单点 bid/ask）会被静默跳过 spread 校验**，脏 spread 流入 bronze 污染 0003/0005。改为**逐点列感知**：对任意 p，只要 `bid_p` 与 `ask_p` 两列都在 `present` 就为该点生成 `ask_p>=bid_p` 子句（`IS NOT NULL` 守卫使部分行安全），仅当**无任何 bid/ask 报价对**时才整项跳过 DQ2；5 个边界（全有 / 单点 / 混合缺失 / 全缺 / 仅 o 点）全过，新增 2 回归测试（`test_clean_rejects_partial_quote_inverted_spread` / `test_clean_accepts_partial_quote_valid_spread`）。**② 对抗性复查（OANDA）**：逐行核验月份分块（`_months_between` 边界）/ 分页（5000K 上限 + 1K 重叠去重）/ 断点续传（非空月跳过、`--force`）/ token 防护（空 token → `OandaConfigMissing`、脱敏不打印）——**逻辑正确，无缺陷**。**③ 真实 2019-11/12 全 21 标的 OANDA 实测被阻**：moneta 旧 token（practice env）对 `api-fxpractice.oanda.com` 与 `api-fxtrade.oanda.com` **双双 401 Insufficient authorization** → **token 已过期/吊销，非代码问题**；代码正确报 `OandaError` 不崩溃（响亮失败，非静默）。**49 测试全绿**（+2 S1 回归），pyflakes 干净。0002 文档升 **v0.9**（§3.4 DQ2 逐点列感知 + §3.5 OANDA 401 备注 + 修订） | `lyra/clean.py`（S1 逐点 DQ2）、`tests/test_catalog.py`（+2 S1 回归）、`docs/decisions/0002*`（v0.8→v0.9，中英）、状态块 |

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
| 2026-11-06 | 0.5 | 补 #30–#45（0002 从初稿到真实 12GB 端到端全流程）；补 **#46（0002 设计与实现全量红队审查批次 07，提出 D1–D9 项缺陷）**；状态块同步更新。 |
| 2026-11-06 | 0.6 | 补 **#48（0002 收口前的自审 + 对抗性自审）**：核验批次7 后抓出 **F1 真缺陷**（`Catalog.instruments()` 在 bronze parquet 缺失/损坏时抛异常而非按 docstring 降级返回 []，已修 + 回归测试）；另 3 候选经核验为误报/挂起（run_pull 未显式 close 连接→挂起、`_count_rows` 引用→误报、`tmp/` 泄漏→误报）。**39 测试全绿**，pyflakes 干净，真实数据回归（48.8M/9.98M/838K）+ `instruments()`=21 核验一致；**0002 收口**。状态块同步更新。 |
| 2026-11-07 | 0.8 | 补 **#49（对比 moneta/nova 补齐两个真缺）**：① **数据质量校验（0002 §3.4，DQ1–DQ3，fail-fast）**——nova `data._validate` 有、moneta/lyra 无的 OHLC/spread/volume 校验固化进 clean（is_complete 过滤 + 去重后、COPY 前对存活候选行校验，违反即 `DataQualityError`、bronze 不写出；列感知防 `union_by_name` binder error；`_assert_quality` 用 `fetchall` 全消费结果防连接复用异常）；**真实 61,615,338 CSV 行 0 违反**（不误伤）+ AUD_USD 单标的 246 万行端到端 clean 通过；新增 I23；顺带修 **2 个测试 fixture 真 bug**（`test_aggregate.py` + `conftest.py` 的占位 bid/ask 是反的 bid_l>ask_l，被新 DQ 正确拒绝→改为合法报价）。② **OANDA 回补工具（0002 §3.5，`lyra oanda`）**——moneta `extract_oanda.py` 有、lyra 无的"按标的/时间窗口补 1m 历史"独立重写为 `lyra/oanda.py` + CLI（OANDA v3 5000K 线分页 + 每页 1K 重叠 / UTC 日历月分块 / 断点续传 / token 只在 gitignored config 空 token 响亮失败 / 输出对齐 bronze 契约）；clean 的 CSV glob `*.csv`→`**/*.csv`（DuckDB 2.0 递归展开）使 per-instrument 子目录一等公民。新增 `OandaConfig`+`oanda_from_dict`、`config_example.yml` oanda 段。**47 测试全绿**（+8），pyflakes 干净。真实 OANDA 拉取留给用户填 token 后验证（离线无法代跑）。0002 文档升 v0.8 |
| 2026-11-07 | 0.9 | 补 **#50（2 个新特性自检 + 对抗性复查，用户拍板"先自查再对抗性，然后再进 0003"）**：自检抓出 **S1 真缺陷**——DQ2 spread 校验原用"8 列全有才算"门控，**部分报价输入（只有某点 bid/ask）会被静默跳过** → 改为**逐点列感知**（任意 p 同时有 `bid_p`/`ask_p` 即生成 `ask_p>=bid_p` 子句、`IS NOT NULL` 守卫部分行安全，仅当无任何报价对才整项跳过），5 边界全过 + 新增 2 回归（49 全绿）；对抗性复查 OANDA（月份分块/分页 5000K+1K 重叠/断点续传/token 防护）逐行核验**逻辑正确无缺陷**；真实 2019-11/12 全 21 标的 OANDA 实测被阻——moneta 旧 token 对 practice/live 双 host **401 过期**（非代码问题，代码正确报 `OandaError` 不崩溃）。0002 文档升 v0.9（§3.4 DQ2 逐点列感知 + §3.5 OANDA 401 备注） |
