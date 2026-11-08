# VectorBT 与多 AI 策略搜索综合评估（2026-11-08 批次 1）

> **English**: [2026-11-08-vectorbt-multi-ai-consolidated.en.md](./2026-11-08-vectorbt-multi-ai-consolidated.en.md)
>
> 状态：**用户已裁决（2026-11-08）**：① cap 语义取 **B（每 track 各自 8，tracks 互不影响）**；② tracks 认可，`track_id` ↔ AI 对应（研究身份）；③ VectorBT **彻底抛弃**（不 runtime、不做 test-only control）；④ 0004 按 §5 收口定稿、本轮不开发；⑤ 轻量多思考线（多 AI 可同/不同方向并行，基座共用一套，无调度/锁/并发协调，维持 R9）。裁决落点见 **§9** 及 R12 / O13 / oci-alpha-layout / 0004 同步修订。
>
> 来源：[vectorbt-and-multi-ai-strategy-search.md](./vectorbt-and-multi-ai-strategy-search.md) 与 [2026-11-08-vectorbt-eval-and-multi-ai-v2.md](./2026-11-08-vectorbt-eval-and-multi-ai-v2.md)。用户本轮明确要求整合，因此本稿对照两份来源稿；来源文件保留原样，供审计。
>
> 本综合稿取代“先并存、不合并”的文档处理方式，不代表已批准其架构建议，也不改写 R9、R12、OCI 协议或 0004 决策。

## 1. 结论

1. **VectorBT 不进入 Lyra 核心依赖或正式 trade engine。** 它的批量信号模拟 API 有价值，但 Lyra 要求入场成交后的同 bar 止损；隔离实验观察到 VectorBT 会把止损推迟到下一根 bar。它也带来额外依赖和组合回测心智。简单 PnL 算术的可选测试对照仅作为未来低优先级选项，不能验证 Lyra 的 R4 执行合约。
2. **采用“方向内逻辑隔离轨道”的多 AI 设计作为待审方案。** R12 的分支树是基础，但仅靠分支名唯一不足以隔离 AI 工作：现行单份 direction context 和共享 lessons 会暴露彼此的过程。每条轨道应独立拥有 context、lessons、候选 YAML 和 run 身份；方向假设、行情、feature catalog 与执行规则通过固定快照只读共享。
3. **逻辑独立不等于 Lyra 支持并发多进程。** R9 明确排除多进程和分布式基础设施。本方案不加入调度器、锁服务或并发协调器；它按 track 分区研究材料，使 AI 能在用户控制的不同时间推进。Lyra 不承诺多个 writer 同时修改或 push 同一工作区。若要求受支持的并发执行，需先修改 R9 范围边界。
4. **所有 AI 使用相同的 YAML、validate、compile、run 和 per-instrument 报告规则。** 能力较弱的模型接收更小任务（例如一次写一个候选或诊断一个 run），不降低机器校验门槛，也不把 validate 当作策略质量证明。
5. **跨 AI 比较仅在用户暂停该方向并明确要求后进行。** 使用冻结输入生成只读综合上下文；报告独立保存，不自动改写轨道 lessons、假设或候选。方向恢复及任何知识晋升由用户明确触发。
6. **O13 的 8 个 active branch 上限建议按方向全局计算，覆盖该方向所有 AI tracks。** 不按 AI 数量扩张；名额如何在 tracks 间分配仍待用户决定。
7. **0004 只负责确定性 YAML → past-only SQL 编译和廉价校验。** 不把 track、模型身份、AI 协作或 VectorBT 接进 compiler。

## 2. 两份来源稿的合并与冲突处置

| 议题 | 可合并内容 | 冲突或取舍 | 本稿结论 |
|---|---|---|---|
| VectorBT 定位 | 两稿都不建议用于正式 trade engine，并保留未来受限测试对照的可能 | 一稿强调 entry-bar stop 反例；v2 更侧重 portfolio / 参数扫描定位 | 采用实测反例作为关键兼容性证据；portfolio 报告、参数扫描、许可证和依赖负担作为额外理由 |
| 安装体量 | 两稿都指出 runtime 依赖成本明显 | v2 记录安装后 68 个发行包；本次复核同一临时 venv 时读到 70 个。VectorBT 1.2.0 版本化 pyproject 声明 18 个直接 runtime 依赖；Lyra 当前声明 8 个直接依赖 | 18 是直接依赖数，68/70 是某次环境中的发行包数，口径不同且总数会变。记录差异，不用某个闭包总数单独作为结论 |
| 多 AI 隔离 | 两稿都支持同一方向、用户控制节奏、共同工作流和用户触发跨 AI 学习 | v2 认为共享分支树加唯一分支名已足够；另一稿指出共享 context/lessons 会串扰并提议 tracks | 不采纳“分支唯一即可充分隔离”。采用逻辑 tracks，共享状态只读快照化 |
| 并发与 R9 | 两稿都排除分布式调度和无人值守生成 | v2 曾提出原子追加和文件锁作为重叠写入兜底；R9 明确排除多进程 | 不实现文件锁/多进程兜底。Lyra 只承诺用户驱动的 track 隔离，不宣称并发 writer 支持 |
| 弱 AI | 两稿都支持相同命令和统一机械门禁 | 单份完整 direction context 可能过大，也会暴露其他 AI 尚未整理的过程 | 同一 track-scoped context / validator / runner，按模型能力缩小任务；跨轨道综合由用户指定 AI 执行 |
| 0004 | 两稿都提出编译确定性、提前 validate、逐标的结果 | v2 把 git commit 放入编译纯函数输入；commit 是 provenance，不应决定 SQL 语义。“逐标的报告”也超出 compiler 单独职责 | 编译输入为规范化 YAML、schema/compiler 版本和 feature catalog/snapshot；commit 记入 run provenance。Compiler 产 past-only 信号 SQL，runner/report 保持 per-instrument 口径 |
| 8 个 active branches | 方向级上限已有约束，track 不应绕过 | v2 未明确多轨道总 cap；另一稿建议全方向共用 8 个 | 建议全方向所有 tracks 合计最多 8 个 active branches；名额分配开放给用户裁决 |

## 3. VectorBT：证据和建议

### 3.1 隔离实验

实验使用 Python 3.12.3、vectorbt==1.2.0 和 /tmp/lyra-vectorbt-spike 临时虚拟环境；没有改动 Lyra 代码或依赖。

- 人工 OHLC 场景把收盘信号移到下一根 bar，以 open 入场；启用 1% slippage、FillPrice stop entry、StopMarket stop exit、2% stop 和 6% take profit。
- 一般盘中止损、跳空止损以及同 bar 同时碰到 TP/SL 的场景可在该配置下映射：SL 优先；跳空和 slippage 可使实际损失超过 2%。
- **反例：** 入场 bar 的 open=101、low=98 已越过 2% stop，但本次运行没有在入场 bar 处理该 stop，而是等到下一根 open=99 才退出。Lyra 的 stop 从实际 entry fill 后立即生效，这个延迟不符合 R4。
- 实验没有覆盖全部费用/融资、缺失行情、所有 long/short 冲突、332 策略或全量性能；不能据此声称引擎全面等价。

### 3.2 依赖、能力和维护成本

VectorBT 1.2.0 的版本化项目元数据列出 18 个直接 runtime 依赖。v2 的隔离安装记录 68 个发行包；本次复核 /tmp/lyra-vectorbt-spike 读到 70 个。现有证据不能解释总数变化的原因，因此只把它们视为不同时间点的环境快照，不把单一闭包总数当稳定指标。Lyra 当前 pyproject.toml 声明 8 个直接依赖。R10 的“核心依赖 ≤15 个 Python 包”没有明确按直接依赖还是完整安装闭包计数。

VectorBT 的优势是成熟、向量化的信号模拟 API 和批量研究能力。其 portfolio、参数网格和账户绩效功能与 Lyra 明确排除的范围重叠；Lyra 仍需要自己的逐标的状态机、成本/融资口径、stop 语义和报告。加入 runtime 不会省掉这些核心规则。VectorBT 1.2.0 的许可证含 Commons Clause 限制，正式集成或分发前还需单独审查。

### 3.3 建议

- 不放入 Lyra core、trade engine 或默认可选依赖；由 Lyra 自己实现并测试 R4/R5 所要求的逐标的交易与报告语义。
- 未来若需要简单 PnL 算术交叉核对，可另提 test-only、默认关闭的 [control] 适配；不得作为交易执行 oracle，也不得把 portfolio/equity 指标导入 Lyra 报告。
- 重新评估前应明确 R10 依赖计数口径，并复跑 entry-bar stop、成本和报告边界测试；普通 stop 用例通过不能证明兼容。

## 4. 多 AI：待审的逻辑轨道方案

### 4.1 建议的数据布局

~~~
strategies/<direction>/
  hypothesis.md                         # 方向假设；各轨道固定一个只读版本
  tracks/<track_id>/
    manifest.yml                        # track id、基线 hash、输入快照、状态
    lessons.md                          # 本轨道 append-only 记录
    v01.yaml, v02a.yaml, ...            # 本轨道候选版本
  reviews/<review_id>.md                # 用户暂停后生成的跨轨道综合报告
runs/<direction>/<track_id>/<run_id>/   # track-scoped run 身份和产物
~~~

这是对 R12 / OCI 布局的提案，不是当前已实现路径。所有 track、strategy、run 仍属于 alpha，按 B9/I17 的 immutable / append-only 规则进入 OCI，不进入 Git。

### 4.2 运行与隔离规则

1. 创建 track 时固定方向 hypothesis.md 的内容 hash、数据 snapshot、feature catalog/version、timeframe 和执行规则版本。方向假设后续变化不回写旧 track。
2. lyra context <direction> --track <id> 生成一个文件，只含该快照、该 track 的 lessons、候选与 sibling run 摘要、固定 feature 清单。普通迭代 context 不读其他 track 的草稿或 lessons。
3. 每个 run 记录 direction + track_id + strategy SHA256 + data/feature snapshot + compiler/engine version。相同 YAML 名称可在不同轨道存在；已有 track、branch 或 run ID 再次创建时必须 fail-fast，不覆盖，也不自动改名。
4. Track 内沿用 R12 的 parent / parents 和 driven_by_lesson。跨轨道交叉时，新候选写入目标 track 或用户指定的 synthesis track，并保留双方父本和 hash；不得修改来源轨道文件。
5. 用户暂停整个方向并明确要求综合后，生成冻结的 cross-track context，供用户指定的 AI 比较分支、失败模式、互补假设和 run 证据。报告引用 track/strategy/run/hash，独立保存，不写回各轨道。
6. 仅用户明确要求恢复或晋升结论后，才创建候选、更新方向级假设或将 lesson 摘要带入某条轨道。比较本身不自动生成下一轮候选。
7. 轨道路径和唯一 ID 提供**逻辑内容隔离**；R9 下不实现锁服务、后台调度或 simultaneous multi-process 写入保证。同一 workspace 的策略变更与 OCI push 按用户控制的单写者顺序执行。

### 4.3 不同能力模型如何参与

- 强模型可提出多分支方向、分析 sibling 对比，并在暂停后做跨轨道综合。
- 较弱模型可被分配为“一次生成一个受约束候选”“只归类一个 run 的失败”或“只检查一个候选是否符合假设”等窄任务。
- 所有模型使用相同格式的 track-scoped context、validate → compile → run → per-instrument report 流程和策略约束。模型能力只影响任务范围，不改变规则。
- validate 只证明 YAML / feature / temporal contract 合法，不证明假设正确或策略有效。研究判断仍需 run 证据及用户/AI 审阅。
- 不提供自动模型路由、并发调度、无界批量生成或模型专属权限通道。AI 与用户共享同一工作方式和机械门禁。

### 4.4 Active branch 上限（**本方案最需要用户拍板的一点**）

建议 O13 的最多 8 个 active branches 继续按整个 direction 计算，包含该方向全部 tracks；不能按每个 AI 或 track 各给 8 个。Pruned 历史仍保留。如何分配 8 个名额、是否允许用户手动调配，需用户决定。

> **为什么这一点被单独拎出来（v2 贡献者补充）**：cap 的**计算口径**不是细节，而是把
> "多 AI" 编码成**合作**还是**竞争**的开关。O13 的原意（用户 2026-11-06 定案）是
> "**防 AI 靠无限 fork 规避 kill criteria**"——它的靶子是**单个研究流程**内的无限分叉。
> 现在引入 tracks 后有两种互斥语义，需用户二选一：
> - **A. 全局 8（合作）**：整个方向所有 tracks **共用** 8 个名额。语义与 O13 原意一致
>   （方向内分支总数有界），但代价是 **tracks 互相竞争名额**——一个 track 的分支占用
>   会挤占其他 track，这与用户"不同 AI **互不影响**"的目标**直接冲突**。
> - **B. 每 track 8（竞争）**：每条 track 各自 8 个名额，N 条 tracks 合计 8N。语义上是
>   "每个研究者的 fork 预算独立"，最贴合"互不影响"，但**突破了 O13 的方向级有界**
>   （等于把 N 个研究者的无限 fork 预算叠加，方向级分支总数不再封顶）。
>
> 本稿当前措辞偏向 **A（全局 8）**，与 O13 原意一致、但牺牲了"互不影响"。**这不是
> "分配规则"问题，而是方向级分支上限的**定义**问题**——建议升级为用户决策清单里的
> **第一优先裁决项**（见 §8 第 2 条已列，此处强调其权重）。在拍板前，tracks 的分支计数
> 逻辑不应被 0005/0006 实现锁定。

## 5. 对 0004 compiler 的合并要求

| 建议 | 0004 应承担的内容 | 边界 |
|---|---|---|
| 确定性 | 相同规范化 strategy YAML、schema/compiler 版本和 feature catalog/snapshot 必须得到相同 SQL；无时间、随机或进程状态依赖 | Git commit、AI/track identity 作为 provenance 记在 run manifest，不改变 SQL 语义 |
| 先行 validate | run 前廉价检查字段、feature、参数、比较类型、时间算子和值类型；错误尽量定位到字段/行 | YAML 合法不等于假设正确；compiler 不替代策略评审 |
| 因果与类型边界 | 只生成 past-only SQL；窗口在当前行结束；拒绝 lead、任意 SQL、重复 YAML key 和 feature arithmetic | Strategy files 仍只有 YAML；不接受 callback 或 AI 生成 SQL |
| 逐标的语义 | SQL 产生单策略信号；runner/report 对每个 instrument 独立输出，不汇总 portfolio | SQL compiler 不负责 trade engine、组合指标或 track 生命周期 |
| 多 AI 元数据 | 不需把 track 或 AI 字段加入 SQL AST | Track provenance 归版本树 / run 层；相同策略规则应编译出相同 SQL |

这些建议是对现有 docs/decisions/0004-yaml-compiler.md 的评审输入，不自动改写该决策稿；schema alias 和 after_event 语义仍按 0004 流程裁决。

## 6. 取舍、收益和风险

| 选择 | 收益 | 主要风险 / 控制 |
|---|---|---|
| 不接 VectorBT runtime | 避免 stop 语义不匹配、依赖扩张和 portfolio 优先的默认模型 | 自建 engine 有实现和维护成本；需按 R4/R5 独立测试 |
| 每 AI 一个逻辑 track | 分开 context、lessons、候选和 run 证据，可按各自节奏推进 | OCI B9/I17 与 push/run 命名需扩展；实施前冻结路径和 hash 契约 |
| 暂停后只读综合 | 用户控制何时比较与晋升知识；依据可追溯 | 需定义 pause、冻结快照和恢复；新假设不能覆盖旧快照 |
| 同一门禁、任务大小可变 | 弱模型可做小任务，同时不降低策略约束 | 语法合规仍可能逻辑错误；不可把模型输出或指标当自动晋级信号 |
| 全局 cap 8 | AI 数量增加时搜索仍有界 | tracks 可能竞争名额；分配需用户裁决，本稿不自动分配 |
| 不支持并发进程 | 遵守 R9、不增加协调基础设施 | 不提供同一 workspace 多 writer 同时运行的强保证；若必要应先修改范围约束 |

## 7. 自检与对抗性自检

| 对抗点 | 可能失败方式 | 本稿判断 / 处置 |
|---|---|---|
| 用普通 stop 用例证明 VectorBT 等价 | 漏掉 entry-bar low 已穿 stop 的反例 | 用实测反例否决正式 runtime 复用；其他执行细节仍未覆盖 |
| 把 18、68、70 当成同类依赖数 | 混淆直接依赖与安装闭包，或把某次环境数字当稳定承诺 | 分开记录：18 个直接依赖；v2 记录 68；当前 venv 复核 70。精确闭包数不作为主要论据 |
| 只按 track 隔离候选文件 | 每个 AI 的 context 仍读共享 lessons / active branch，产生串扰 | context、lessons、候选、run 都按 track 切分；只共享固定只读基线 |
| track / branch / run ID 撞名 | 后写者覆盖先写者，或 run 归属错乱 | 重复 ID 立即报错；不覆盖、不自动追加后缀 |
| 声称轨道隔离即支持并发 | 并发 append / push 仍可能冲突，且 R9 排除多进程 | 不承诺并发写；同一 workspace 的变更由用户顺序控制；若并发必需，先改范围约束 |
| 每 AI 分配 8 个 active branches | N 个模型把 O13 扩成 8N | 全 direction 所有 track 共用 8 个；名额分配留给用户 |
| 综合输出自动回写 lessons / 新分支 | 未经用户要求跨轨道污染或扩大搜索 | compare report 独立、只读；晋升/恢复必须由用户明确触发 |
| 弱模型写出合法但无意义 YAML | 校验通过后被当作有效研究结论 | validate 只查 contract；run 证据和人工/AI 审阅保持独立 |
| 把 track 实现塞进 0004 | compiler 与策略搜索状态、AI 元数据耦合 | 0004 保持 YAML → past-only SQL；track 放在 R12 / OCI / run 层 |
| 把 Git commit 作为确定性输入 | 同一策略仅因 commit hash 不同而生成不同 SQL | commit 是 provenance，不是 SQL 生成输入 |

**自检结论：** 本稿区分实验结果、版本元数据和建议；标明 tracks 是提案；不声称 R9 支持多进程并发；保留来源文件；没有修改 requirements、OCI 规则、代码、依赖或 0004 决策。

## 7a. v2 贡献者评审意见（2026-11-08 批次 1，v2 作者对本综合稿的意见）

> 说明：本条是 v2 作者对本综合稿的**评审**，不是改写。逐条给"赞同 / 需澄清 / 建议补强"，
> 供用户与最终裁决参考。**已核实的事实锚点**：O13（cap=8，用户 2026-11-06 定案，原意
> "防 AI 靠无限 fork 规避 kill criteria"，靶子是单研究流程）；R12 现有**方向 + 分支 + 单份
> hypothesis + 共享 lessons + 每方向 8 cap**，但**尚无 "track" 概念**；vectorbt 1.2.0 依赖
> 数字（18 直接依赖 / 68 与 70 发行包）本稿已正确区分口径。

**总体**：本综合稿比两份来源稿都更好，我**赞同其大方向**，并**主动接受它对我 v2 的两处纠正**
（见下）。主要意见集中在 §4.4（cap 语义）与一个本稿尚未点破的**实现成本 / 顺序**问题。

| # | 议题 | 我的意见 | 处置建议 |
|---|---|---|---|
| P1 | **cap 语义（§4.4 / §8.2）** | 这是本方案**唯一真正改变用户目标**的抉择：A(全局 8) 贴合 O13 原意但让 tracks 竞争名额、可能**饿死弱 AI**、牺牲"互不影响"；B(每 track 8) 贴合"互不影响"但突破 O13 方向级有界。**二选一，且应先于 0005/0006 的分支计数实现锁定**。 | 已把 §8.2 标为第一优先、§4.4 展开 A/B 两种语义（**已补**）。 |
| P2 | **tracks 是研究身份，不是执行身份** | `track_id` 应**只**用于内容隔离 / 归属 / 综合，**绝不能**改变 validate / compile / run / report 的机器行为或门禁；否则"换 track = 换个标准"会成为隐性后门，破坏 R2"参数固定 / 同一规则集"。本稿 §4.2 已隐含此意但未明写。 | 已在 §8.6 新增一条明确裁决项（**已补**）。 |
| P3 | **tracks 的实现成本 & 落地顺序（本稿最弱的一点）** | 本稿把 tracks 当作已定，但它是 **R12 + OCI + CLI 的新概念**（新文件布局 + 新 CLI 命令 + 新 run 命名），**实现成本不低**，且依赖 0005/0006 尚未落地的 runner / run 身份。**在 0004→0005→0006 落地前，tracks 只是提案，不应被任何实现锁定**。同时应给出**最小可用**的落地路径（见下），避免一上来就做满 §4.1 全布局。 | **建议新增一条最小路径**（本条为补充意见）：① 先只做 **§4.2-3 的 fail-fast 唯一 ID + §4.2-1 的快照冻结**（低成本、高价值、且是 0005/0006 的前置）；② tracks 目录布局与 `lyra context --track` 待 0006 runner 落地后再实现；③ 跨轨道综合（§4.2-5/6）本就用户触发，最后做。**不要**在 0004 compiler 里为 tracks 预留任何结构（本稿 §5 已正确做到"不把 track 塞进 compiler"，**赞同**）。 |
| P4 | **对我 v2 的纠正（接受）** | ① v2 保留了"文件锁作兜底"，本稿**正确删除**（更贴 R9：不承诺并发写，直接不实现锁）。② v2 的 C1 把 git commit 列为**编译输入**，本稿**正确改**为 commit 属 **provenance**（不进 SQL 生成）。两处我都同意本稿。 | 已在本稿 §2 冲突表 / §5 确定性行体现，无需再改。 |
| P5 | **vectorbt 结论** | 我**完全赞同**本稿（不进入 core / runtime）。本稿的 entry-bar stop **实测反例**比我的"参数扫描 / 组合指标 = R2/R9 禁区"论证**更硬**——它是**执行语义的实证不兼容**，不是"定位不匹配"的推理。我接受以它为主证据。 | 无需改（本稿 §3.1 已是主证据）。 |
| P6 | **弱 AI 平权（§4.3）** | 赞同"同一门禁 + 任务粒度可变 + validate 不证明策略有效"。补一点：应明写**弱 AI 的失败不自动触发跨轨道回写**（与 §4.2-6 一致，本稿已覆盖，**赞同**）。 | 无需改。 |

> **小结**：本综合稿可进入用户裁决。我唯一**强烈建议**的是把 **§8.2（cap 语义 A/B）** 和
> **§8.6（tracks=研究身份）** 作为**先于实现**的两项裁决；并在 §6/实施计划里加入 **P3 的最小落地
> 路径**（先 fail-fast + 快照冻结，后 tracks 目录与 CLI，再跨轨道综合），避免 tracks 被 0005/0006
> 提前锁定或过度实现。其余各条我赞同本稿原结论。

## 8. 需要用户裁决

1. 是否认可方向下独立 AI tracks，并接受当前仅保证逻辑隔离、由用户顺序驱动写入？
2. **【第一优先】cap 的语义二选一（见 §4.4）**：是 **A. 全局 8（合作，与 O13 原意一致、但 tracks 竞争名额、可能饿死弱 AI、牺牲"互不影响"）**，还是 **B. 每 track 8（竞争、贴合"互不影响"、但突破 O13 方向级有界）**？这是**方向级分支上限的定义**，不是分配规则；拍板前 0005/0006 不应锁定分支计数逻辑。
3. 是否认可 VectorBT 不进 runtime，且任何 PnL-only test control 默认不做？
4. 0004 是否按 §5 纳入确定性输入、validate 范围和 per-instrument 边界？
5. 若需要多进程同时写入/运行，是否先调整 R9？本稿不假设该能力已获授权。
6. **（v2 贡献者新增）是否认可 tracks 为"研究身份"而非"执行身份"**：即 `track_id` 只用于隔离内容 / 归属 / 综合，**不**改变 validate / compile / run / report 的任何机器行为与门禁。避免"换 track = 换个标准"的隐性后门。

## 9. 用户裁决（2026-11-08，取代 §8 的待决状态）

| §8 项 | 用户裁决 | 落点 |
|---|---|---|
| §8.1 tracks | **认可**。`track_id` 可对应一个 AI（研究身份：隔离 context / lessons / 候选 / run 归属）；不同 AI 可在**不同甚至相同方向**上并行推进，互不影响；基座（数据 / 特征 / catalog / compiler / CLI）共用一套；轻量——定义候选方向 → 评测 → 结论 → 推测下一段；**无调度器 / 文件锁 / 并发协调器**（维持 R9） | `requirements.md` R12、`oci-alpha-layout.md` §2.3 |
| §8.2 cap 语义 | **取 B：每 track 各自 8 个 active branches**，tracks 之间名额互不挤占（"互不影响"优先于 O13 原"方向级全局有界"；O13 原意"防单研究流程无限 fork"仍满足，因为 cap 按 track 计） | `requirements.md` O13 引用、`oci-alpha-layout.md`、`open-questions.md` O13 修订行 |
| §8.3 VectorBT | **认可并加强**：彻底抛弃——不进 core / runtime，**也不做** PnL-only test-only control（无未来重评估计划） | 本稿 §3 结论生效；R8/R10 不变 |
| §8.4 0004 | **认可 §5 收口**：确定性输入（规范化 YAML + schema/compiler 版本 + feature catalog/snapshot；git commit 只作 provenance）、run 前廉价 validate、past-only SQL、per-instrument 边界归 runner/report。**本轮只定稿文档，不开发** | `0004-yaml-compiler.md` 状态改"定稿，待排期开发" |
| §8.5 并发 | **轻量多思考线**：多 AI 并行研究是目标，但仅逻辑隔离 + 用户顺序驱动写入；不实现多进程并发写；若未来确需并发 writer 再走 R9 修订流程 | R9 不变；tracks 设计按 §4 逻辑隔离 |
| §8.6 tracks=研究身份 | **认可**。`track_id` 只用于隔离 / 归属 / 综合，不改变 validate / compile / run / report 的任何机器行为与门禁 | R12 + 0004 不变量 |

**实施顺序（采纳 P3 最小落地路径，细化）**：
1. 文档层（本轮已完成）：R12 tracks 条款 + O13 cap 语义修订 + oci-alpha-layout 布局 + 0004 定稿 + open-questions 状态。
2. 0004 实施：YAML → past-only SQL compiler（`lyra validate` / `lyra compile`），不触碰 tracks。
3. 0005 trade engine + 0006 metrics/runner 落地时，引入 tracks 目录布局（`tracks/<track_id>/`）与 `lyra context --track`；fail-fast 唯一 ID + 快照冻结作为前置。
4. 跨轨道综合（`reviews/` 只读报告）最后做，仅用户触发。

> 注意：O13 语义修订（2026-11-08 用户裁决）取代 2026-11-06 的"每方向全局 8"定案；旧措辞在 `open-questions.md` O13 行保留为历史，以修订行为准。

## 参考资料

- VectorBT 1.2.0 [版本元数据](https://github.com/polakowo/vectorbt/blob/v1.2.0/pyproject.toml)、[Portfolio API](https://vectorbt.dev/api/portfolio/base/)、[stop enums](https://vectorbt.dev/api/portfolio/enums/) 和[许可证](https://github.com/polakowo/vectorbt/blob/v1.2.0/LICENSE.md)，访问日期 2026-11-08。
- Lyra 基线：docs/requirements.md R2/R4/R5/R9/R10/R12；docs/hld.md §2.3/§4/§8；docs/proposals/oci-alpha-layout.md B9/B13/B14；docs/decisions/0004-yaml-compiler.md。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-08 | 0.1 | 按用户最新要求，对两份既有评估做合并审查；保留来源文件，明确合并点、冲突取舍、R9 并发边界、VectorBT 实验与 0004 接口建议，并完成自检和对抗性自检。 |
| 2026-11-08 | 0.3 | **用户裁决并入（§9）**：cap=每 track 8（B 案，tracks 互不影响）；tracks 认可（`track_id`↔AI，研究身份）；VectorBT 彻底抛弃；0004 按 §5 收口定稿（本轮不开发）；轻量多思考线（无并发协调，维持 R9）。同步 R12 / O13 / oci-alpha-layout / 0004 / open-questions / ACTION_LOG。 |
| 2026-11-08 | 0.2 | **v2 贡献者评审意见并入（P1–P6）**：① §4.4 + §8.2 把 **cap 语义**升级为**第一优先裁决**，展开 **A 全局 8（合作/竞争名额/可能饿死弱 AI）vs B 每 track 8（互不影响/突破 O13 有界）** 两种互斥定义；② §8.6 新增"**tracks=研究身份，非执行身份**"裁决项（防"换 track=换标准"后门）；③ §7a 记录 v2 作者对综合稿的评审（P1–P6，含**接受本稿对我 v2 的两处纠正**：删文件锁、git commit=provenance 非编译输入；及 **P3 最小落地路径**建议：先 fail-fast + 快照冻结 → 后 tracks 目录/CLI → 再跨轨道综合，避免 0005/0006 提前锁定 tracks）。中英成对。 |
