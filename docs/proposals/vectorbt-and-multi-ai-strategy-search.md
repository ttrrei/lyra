# VectorBT 与多 AI 策略搜索评估（2026-11-08 批次 1）

> **English**: [vectorbt-and-multi-ai-strategy-search.en.md](./vectorbt-and-multi-ai-strategy-search.en.md)
>
> 状态：独立评估 / 提案；未批准代码改动。本稿不读取或依赖其他 AI 为本议题编写的评估文档。
>
> **【审计注 2026-11-08】**本稿为来源稿，已被 [2026-11-08-vectorbt-multi-ai-consolidated.md](./2026-11-08-vectorbt-multi-ai-consolidated.md) **v0.3 §9 用户裁决**取代（含本稿 §4.4 建议的"全局 8"——用户最终裁决为**每 track 8**）。正文保留原样供审计，**勿以本稿措辞为准**。
>
> 范围：评估 VectorBT 是否适合作为 Lyra 的依赖/回测引擎；为同一方向内不同 AI 模型各自独立、按自身节奏搜索策略，提出可落地的边界；说明对 0004 compiler 的影响。

## 1. 结论摘要

1. **不把 VectorBT 放进 Lyra 核心依赖或正式 trade engine。** VectorBT 有可复用的信号模拟、止损和交易记录能力，但它的 portfolio 模型、运行时依赖量、许可证条款，以及“入场 bar 不处理 stop”的执行语义，与 Lyra 的边界不匹配。一次性实验确认了次开盘、按实际成交价设 stop、跳空和止盈/止损同 bar 优先级中的若干配置可映射；也确认了 entry-bar stop 的关键不兼容。
2. **多 AI 应采用“方向下的独立搜索轨道（track）”，而不是把不同 AI 的分支混在一棵可互写的共享树里。** 每条轨道有自己的分支 YAML、lessons 和上下文；共用只读的方向假设快照、特征目录、行情数据和执行规则。跨 AI 比较仅在用户暂停该方向并明确要求后进行，比较结果单独保存且只读，不自动回写或合并。
3. **对低能力 AI 缩小任务粒度，不降低机器门禁。** 它可以一次只做一个候选变体、一次只诊断一个失败场景；`validate` / `compile` / `run` 使用与强模型相同的语法、因果性、交易语义和指标约束。无效候选不得进入 run；有效候选的优劣仍由统一报告和人工/AI 判断，不按模型能力放宽规则。
4. **0004 只做与策略路径无关的 YAML → past-only SQL 编译。** 不把多 AI 编排或 VectorBT 接入编译器。建议 0004 的编译 API 不假设策略位于某个模型目录，轨道来源与 run provenance 留给策略/runner/OCI 设计。

## 2. VectorBT 评估

### 2.1 可复用的能力

VectorBT 1.2.0 的 `Portfolio.from_signals` 支持 long/short 信号、OHLC 止损、按 acquisition/fill price 设 stop、止损与止盈、订单及交易记录，并可通过广播并行计算多个列。对大型数组研究而言，这些能力能节省不少执行器工程。官方说明 `Portfolio` 会建立 cash/position 与 equity curve，并提供组合绩效统计；因此其主要抽象仍是组合回测，而非 Lyra 的逐标的 trade ledger。

### 2.2 与 Lyra 的契合度

| 维度 | VectorBT 能力 | Lyra 约束 | 判断 |
|---|---|---|---|
| 信号确认与成交 | 可把收盘信号手工 shift，再以下一行 open 作为订单价 | 收盘确认、下一 observed open 成交 | 可映射，但 shift 与价格数组的配对必须由 Lyra 自己保证 |
| 2% adverse stop | 支持基于成交价的 `sl_stop`、OHLC 触发、stop-market 滑点 | 2% 必须从实际 entry fill 计算，跳空可扩大亏损 | 常规场景可映射 |
| 入场同根 stop | 官方 API 明确 stop 不能与入场信号在同一资产同一 bar 处理 | stop 必须从实际入场成交后生效；entry bar 后续价格不可漏查 | **语义不匹配**；本次实测 stop 延迟到下一根 bar |
| 同 bar 止盈/止损 | `from_signals` stop 优先；合成场景中同时触发时 stop-loss 获胜 | 亏损方优先 | 配置下匹配，但需版本锁与回归测试 |
| 每标的一笔、无反手 | 可通过信号/累积/冲突选项设置 | 不加仓、不反手、不同 bar 重入 | 能配置，仍需逐场景验证状态机 |
| 费用 | 有 fees/slippage 参数 | spread、per-side slippage、round-trip commission、按交易日 financing | 不完整等价；融资日历与 spread 还需 Lyra 自己建模 |
| 报告口径 | 有 portfolio/equity、资产和组合统计，也保留逐列记录 | 禁止 portfolio return / equity / CAGR 等；按标的报告 | 容易误用，必须绕开其汇总器并自行生成 Lyra 报告 |
| 依赖与许可 | 1.2.0 声明 18 个直接运行时依赖（NumPy、pandas、SciPy、Matplotlib、Plotly、Numba、scikit-learn 等），源码采用 Apache 2.0 + Commons Clause fair-code 条款 | R10 核心依赖 ≤15；Lyra 仓库为 Apache-2.0 | R10 未说明按直接依赖还是完整安装闭包计数；runtime 接入会显著扩大环境，且没有 test-only `control` 那样的已批准例外。商业分发/集成前还必须解决许可证兼容问题 |
| 0004 compiler | 不负责 Lyra YAML grammar，也不把 YAML 编译成 DuckDB past-only SQL | 0004 的唯一职责之一 | 不能替代 0004 |

### 2.3 隔离实验

- 环境：Python 3.12.3；`vectorbt==1.2.0`；一次性虚拟环境 `/tmp/lyra-vectorbt-spike`，没有改动 Lyra 的依赖或源码。
- 构造单标的人工 OHLC bars；收盘信号通过手工 shift 到下一行，以 `open` 成交；`slippage=1%`；`stop_entry_price=FillPrice`；`stop_exit_price=StopMarket`；止损 2%、止盈 6%。
- 结果：entry open 101 加买入滑点后成交 102.01，2% stop 为 99.9698。普通 intrabar stop 触发后按 stop price 加卖出滑点成交 98.970102，trade return 为 -2.98%；下一根开盘跳空至 99 时按 open 加滑点成交 98.01，trade return 为 -3.92%；同 bar high/low 同时击中 6% TP 与 2% SL 时，SL 优先。
- **反例**：entry bar 的 open=101、low=98 已穿过 2% stop，但 VectorBT 不在该 bar 处理 stop；直到下一根 open=99 才成交 98.01。这个延迟违反“从实际 entry fill 后立即监控 adverse stop”的 Lyra 合约，不能靠简单参数配置消除。
- 结论只针对这组版本与合成路径；未验证融资、整套费用、缺失数据、复杂 long/short 冲突、332 策略或全量性能。该实验不是 Lyra trade engine 验收。

### 2.4 建议

- 保持 Lyra 自己的逐 bar trade state machine；不要增加 VectorBT core/optional runtime dependency，不把它作为权威结果生成器。若未来重新评估，先说清 R10 是否按直接依赖或完整安装闭包计数，并明确批准哪种依赖分组。
- 只有未来某个独立研究需要大量向量化时，才另提可选 benchmark/探索适配器；必须先解决 entry-bar stop 等语义差异、逐标的报告隔离、依赖预算和许可证审查。
- 对照不意味着“使用两个引擎投票”：不匹配执行语义的结果不能作为 Lyra 正确性的 oracle。

## 3. 多 AI 策略搜索目标与现状差距

现有 R12 已具备方向内多分支、AI 一等写作者、单文件 context、兄弟分支摘要、continue/prune/cross 和每方向 8 个 active branch cap。缺少的是：

- 多 AI / 不同模型之间的文件隔离、独立进度和独立 lessons；
- 不同轨道如何固定共同假设和输入快照，防止实验不可比；
- 用户暂停后跨轨道比较、学习、整理的只读流程；
- 低能力模型可以承担的窄任务及统一的机械质量门禁；
- 当前 8 个 active branches 的上限如何作用于多个 AI 轨道。

## 4. 建议的隔离模型

### 4.1 文件与身份边界（提案）

```text
strategies/<direction>/
  hypothesis.md                       # 共同方向假设；轨道只读
  tracks/<track_id>/
    manifest.yml                      # owner AI / 模型版本 / 基线快照 / 状态
    lessons.md                        # 只属于本轨道
    v01.yaml, v02a.yaml, ...           # 只属于本轨道的不可变候选
  reviews/<review_id>.md              # 暂停后跨轨道综合；独立只读产物
```

`track_id` 是 AI 的隔离工作流标识；manifest/run provenance 记录具体 provider、模型版本、prompt/上下文版本和操作者。更换模型身份时建议新开轨道，以免把不同研究过程混作一条历史。所有路径仍是 alpha，留在 OCI/外部工作区，绝不进入 Git。

### 4.2 运行规则

1. 方向根目录提供共同 `hypothesis.md` 的只读快照。轨道 manifest 记录创建时的假设 hash、数据/feature snapshot、timeframe 与执行规则版本；共同假设后续变化不改写已冻结的轨道输入。
2. `lyra context <direction> --track <id>` 只输出一份文件：共同假设快照、该轨道 lessons、该轨道活跃 YAML、该轨道兄弟分支 run 摘要、固定 feature 清单。它不读其他 AI 的候选和 lessons。
3. 每个 run 的唯一键/报告记录 `direction + track_id + strategy SHA256 + data/feature snapshot + engine version`，防止两个 AI 使用相同 YAML id 时互相覆盖，也确保可比较性。
4. 轨道内分支的 `parent` / `driven_by_lesson` 与现有 R12 一致；同名版本可因路径隔离而并存。跨轨道交叉不得直接改写源轨道；需要交叉时，先从源文件复制/引用到新轨道或单独的 synthesis 分支，保留双方父本 hash。
5. 用户暂停一个方向后，写入禁止新建分支/lesson/run；CLI 生成冻结的 compare context。用户指定一个 AI 读取所有轨道快照并写综合报告，报告记录赞成/反对证据、共有失败模式、互补假设与可供人选择的下一步。**综合本身不修改任何轨道，也不自动创建候选。** 用户明确恢复/批准后，才能创建新分支或把 lesson 摘要复制回轨道。

### 4.3 让不同能力的 AI 都能贡献

- 把每次任务缩小为“给一个父分支生成一个受限变体”“只解释一个 run 的失败分类”“只校验某个候选是否遵守方向假设”等；弱模型不必承担 sibling comparison 或跨轨道综合。
- 输入仍是单文件 context；输出仍是 YAML candidate + 简短 rationale。AI 生成 SQL、Python 或 feature arithmetic 的候选均由 validator 拒绝。
- 每个模型走完全相同的 `validate → compile → run → per-instrument report` 路径；校验通过只是语法/契约合格，不代表假设正确或有优势。
- 不做自动模型路由、分布式调度或无界生成。由用户控制何时调用、给哪个 track、每轮最多创建多少候选；保留 R12 kill criteria 与 O13 上限。

### 4.4 active branch cap

O13 已由用户定为每方向同时最多 8 个 active branches。建议把它解释为**跨该方向全部 tracks 的全局总上限仍为 8**，而非每 AI 各 8 个；否则增加模型数就会绕过原来防止无限 fork 的门槛。被 prune 的历史保留，另立 OCI 存储/归档策略前不自动删除。8 个名额在 tracks 之间如何分配、是否允许用户临时重分配，属于待用户定案的运维规则。

## 5. 需要的后续改动（本稿只记录，未实施）

| 落点 | 需要补的契约/功能 | 归属时机 |
|---|---|---|
| `requirements.md` R12 | 明确 track、AI 身份、只读共同快照、跨轨道隔离与用户暂停后综合流程 | 用户认可设计后、策略搜索接口实现前 |
| `oci-alpha-layout.md` B9/I17 + §2.3 | 增加 tracks、track lessons、manifest、compare review 的路径和不可变/append-only 规则 | OCI 布局/0007 定稿前 |
| `hld.md` §2.3 | context/compare/pause CLI 契约；编译器保持 track-agnostic | 需求与命令边界定案后 |
| strategy/runner/report | track metadata、run 唯一键、snapshot 引用、暂停门禁和 8 条全局 cap | 最早在策略版本树/runner/OCI feature 中拆分；不是 0004 SQL codegen |
| 测试 | 交叉读取隔离、相同 YAML id 不碰撞、暂停后不写、恢复不重写历史、全局 cap、同快照跨 AI 比较 | 对应实现 feature |

## 6. 优势与风险

| 项目 | 优势 | 风险 / 控制 |
|---|---|---|
| 独立 track | 不同模型可以慢慢跑，不覆盖彼此的文件、lesson 或 run | shared root 假设若可由 AI 写入会污染全部轨道；根假设只读，修改者和 hash 可审计 |
| 弱模型小任务 | 可把简单候选构造、标签/摘要等工作交给低能力模型 | 语法正确仍可能是假设错误；run/报告只提供证据，不把模型判断当结论 |
| 暂停后综合 | 比较输入冻结，避免边比较边变更和即时信息泄漏 | 由更强 AI 汇总仍可能偏见；需附每个结论的 branch/run/hash 引用，人可复核 |
| 全局 cap 8 | 保持原有有界搜索约束，不因 AI 数量增长而膨胀 | 轨道之间可能抢配额；需要用户控制名额，不能暗中扩大 cap |
| OCI 轨道目录 | 文件命名空间隔离并与 Git alpha 边界一致 | 新目录规则和 append-only 路径需要同步 B9/I17、push 校验与备份 |
| VectorBT 复用 | 能快速复用批量模拟和记录 API | entry-bar stop 不匹配、组合统计诱发越界使用、依赖/许可证负担；不采用正式引擎 |

## 7. 自检

- [x] VectorBT 讨论没有把它误当成 compiler 或指标库。
- [x] 将合成实验结果与官方语义说明分开，明确了未测范围。
- [x] 多 AI 设计仍遵守 YAML-only、固定 feature 参数、past-only SQL、每标的一笔和 per-instrument scoring。
- [x] 8 个 active branch 上限跨轨道全局计算，未形成按 AI 扩容的漏洞。
- [x] 共享行情与 feature 数据为只读；所有方向与轨道文件保持 OCI alpha 边界。
- [x] 未修改 requirements、OCI 协议、代码或依赖；设计仍是提案。

## 8. 对抗性自检

| 攻击/失败路径 | 若不控制会怎样 | 设计处置 / 留项 |
|---|---|---|
| 多轨道都按每方向 8 分支计 | N 个 AI 会把旧 cap 扩成 8N | 全方向全轨道 cap=8；配额分配待用户决定 |
| AI 互写根 `hypothesis.md` 或 lessons | 轨道独立性消失，实验历史被污染 | 根假设只读；lessons 位于轨道内；root 更新带 hash 并只影响新快照 |
| 两个 AI 写相同 strategy id/run name | 旧结果覆盖或指标归错 AI | run 身份含 track_id、strategy hash 和 snapshot；必须唯一写入 |
| 暂停只冻结某些文件，run 仍可变 | 比较快照不稳定，复现失败 | pause 是方向级写门禁；compare 输入从 frozen snapshot 生成 |
| “汇总学习”自动回写 lessons/分支 | 没经用户要求就跨轨道污染 | compare report 单独保存，只读；promotion/cross 要用户明示 |
| 弱模型生成 YAML 合法但交易含义错误 | 错假设照样进入高代分支 | validate 不宣称逻辑有效；以同一 run 语义测量，kill/prune 由证据与人决定 |
| 某条轨道大量保留已 prune 版本 | OCI 存储长期增长 | 不删历史；存储归档是独立 OCI 策略，需另行定义，不得私自 GC |
| 用 VectorBT 默认 `Portfolio` 成绩作为 Lyra 汇总 | 组合 return/equity 违反 R9 | 正式引擎不接入；任何未来 spike 只读逐标的记录且不得发布 portfolio score |
| VectorBT 只测普通 stop，不测 entry bar | 误判满足 I3 | 本次补做 entry-bar 反例并确认不匹配；否决核心复用 |
| 把一个直接依赖声明当作“只增加一个包” | R10 的依赖预算可能绕开 VectorBT 自身的 18 个运行时依赖 | 先定义 R10 按直接依赖或完整安装闭包计数；在定案前不作为 Lyra runtime dependency |

## 9. 参考资料

- [VectorBT 1.2.0 PyPI 发布与依赖说明](https://pypi.org/project/vectorbt/1.2.0/)（访问日期：2026-11-08）
- [Portfolio API：`from_signals`、信号 shift 提示、Portfolio 输出](https://vectorbt.dev/api/portfolio/base/)（访问日期：2026-11-08）
- [Portfolio enums：StopEntryPrice / StopExitPrice；同 bar entry/stop 限制](https://vectorbt.dev/api/portfolio/enums/)（访问日期：2026-11-08）
- [VectorBT 1.2.0 `pyproject.toml`](https://github.com/polakowo/vectorbt/blob/v1.2.0/pyproject.toml)（18 个直接运行时依赖；访问日期：2026-11-08）
- [VectorBT 1.2.0 许可证](https://github.com/polakowo/vectorbt/blob/v1.2.0/LICENSE.md)（Apache 2.0 + Commons Clause；访问日期：2026-11-08）
- Lyra 内部基线：`docs/requirements.md` R2/R4/R5/R9/R10/R12；`docs/hld.md` §2.3/§4/§8；`docs/proposals/oci-alpha-layout.md` §2.3、B9/B13/B14。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-08 | 0.1 | 初稿：VectorBT 评估 + 隔离多 AI track 提案 + 实测兼容性与对抗性自检。 |
