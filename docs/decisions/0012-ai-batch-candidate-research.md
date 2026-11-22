# 决策 0012 — AI 批量候选研究契约（AI Batch Candidate Research Contract）

> **English**: [0012-ai-batch-candidate-research.en.md](./0012-ai-batch-candidate-research.en.md)
>
> 范围：建立多候选池化演进的研究契约，防止 AI 单线程迭代陷入参数微调与局部最优。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0012` |
| 标题 | AI 批量候选研究契约 |
| 状态 | 提案 |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-22` |
| 相关提案 | 无 |
| 相关需求 | `docs/requirements.md` §R12 |
| 相关 HLD | `docs/hld.md` §8 |
| 取代 | 收窄与规范化 `lyra/ai_readme.md` 既有单分支迭代指引 |

## 1. 问题

在既有的单线迭代模式下，AI 倾向于围绕单一指标对同一个候选策略反复微调数值参数（例如不断尝试将 RSI 阈值由 35/65 微调为 40/60），迅速陷入过拟合与局部最优。需要建立一套批量候选研究契约：将 Track 治理容量（8 席位）转化为"存量精英/观察 + 多样化结构候选"的候选池机制，强制候选具备可解释的结构性差异，使演进建立在多样性证据和淘汰记忆之上。

## 2. 背景

- **既有基础**：Lyra 在 0009 与历次重构中已具备基础池化治理能力（`MAX_ACTIVE_BRANCHES_PER_TRACK = 8`、`lyra digest`、`lyra compare --siblings`、`lyra prune`、`lyra apply-batch` 批量预检等），但之前的 AI 交互指引（`lyra/ai_readme.md`）示范了单分支单线程微调（"One branch per iteration"、RSI 40/60 调参示例），对模型产生了不良引导。
- **用户裁决（2026-11-22）**：
  1. 对需求 R12（策略演进）的方法论进行明确收窄：**严禁纯参数/纯阈值/纯窗口微调**，必须写进 0012 契约，不得做成静默拒绝的黑盒 gate；
  2. 确立每批提报 3–4 个候选，同批只比较同 direction/track；
  3. 参数变体在演进分析中只标记不静默拒绝。
- **关联线**：决策 0010（temp/ triage）中分诊入库的存量策略即为候选池的首批基础素材；后续 0013（可比性增强）、0014（跨品种 digest）、0015（防微调护栏）构成本契约的技术实现步骤。

## 3. 方案

### 3.1 做什么

1. **每批提报规格（3–4 个候选）**：
   - 每次 AI 提报必须使用 `apply-batch` 打包提出 3–4 个候选分支；
   - 建议配比（作为启发式起点，非死板算法）：**2 个新假设 + 1 个逻辑组合 + 1 个机制替换**；
   - 每一个候选必须声明：研究假设、相对在池候选的**结构性差异**（新指标引入、进出场时机逻辑变动、状态机过滤器等）、父本 `parent` 与驱动教训 `driven_by_lesson`、预期失效场景。
2. **禁止纯参数微调**：
   - 严禁仅改变数值阈值（如 RSI 30→35）、仅改变平滑/回溯窗口（如 SMA 20→25）或将数值变体包装为新结构；
   - 结构差异必须能在文本假设中被人类审计清晰理解。
3. **成本与基线一致性**：
   - 候选策略的执行元信息四成本字段（`commission_round_trip`、`financing_per_day`、`stop_loss`、`slippage` 等）必须与当前 track 基线严格一致，禁止通过降低滑点或费率虚增绩效。
4. **同批同轨比较与阅读协议**：
   - 同一批次只比较相同 `direction` 与 `track` 内的候选；
   - AI 阅读协议以 `lyra digest`（低 token 摘要）为主；
   - 每轮仅按需精读 3–4 个最相关候选的完整 YAML、1 个具有启发性的失败案例以及相关 lessons，杜绝全量展开消耗上下文。
5. **候选状态推导**：
   - 候选状态（Experimental / Promising / Proven / Rejected / Incomplete）全部基于现有的 Branch、Run 产物与 Prune 记录**动态推导**，不建立中心化外部状态机数据库。
6. **批次归档规范**：
   - 批次提报 bundle 原文与运行结论归档于本地 workspace：`research-batches/<direction>/<track>/batch-NNNN/`；
   - 批次归档严禁提交至 git 仓库。
7. **Holdout 边界预留**：
   - 预留 Holdout 样本外验证边界概念，AI 仅接触 Research 窗口与授权反馈摘要，本阶段暂不实现 Sealed Holdout 物理隔离。

### 3.2 不做什么

- 不实现遗传算法（GA）、Candidate DB、PoolManager、LLM API 自动化外挂循环；
- 不在底层引擎中做隐式/静默的参数变体硬拒绝（避免黑盒报错中断批次执行）；
- 不设死板硬门槛（如 30 笔交易 / 60% 胜率 / 35% Jaccard 相似度硬切除）；
- 本阶段不实现物理 Sealed Holdout 隔离机制。

### 3.3 边界

- **Alpha 边界**：真实策略 YAML、绩效数据、批次结果严格留存于 workspace `research-batches/` 与 OCI，git 只保留契约与代码；
- **R5 冻结**：不修改 `lyra/metrics.py` 指标定义与现有字段语义，不引入 Sharpe、PF、CAGR 等组合投资级指标；
- **与后续实现边界**：本契约定义行为准则与交互标准，具体的特征可比性松绑见 0013，跨品种摘要见 0014，检测与报警工具见 0015。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I18 | Track 隔离与身份绑定：批次与候选严格绑定至单个 direction 与 track | HLD §4 |
| I21 | 激活上限门禁：每个 track 最多 8 个 active branch（先 prune 后 apply） | HLD §4 |
| R4 | 强制 2% 逆向止损：所有候选必须严格继承执行元规范 | HLD §4 |
| R5 | 指标定义冻结：评估仅使用 R5 规定标准单标的度量 | HLD §4 |
| R12 | 策略受限演进：在既定 direction 框架内推进，严禁无界随机生成与纯参数微调 | HLD §4 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_batch_bundle_structural_tagging` | 验证 apply-batch bundle 支持声明结构差异类型与假设说明 |
| `test_batch_execution_meta_consistency` | 验证批次内所有候选的成本字段与 track 基线保持严格一致 |
| `test_batch_candidate_cap_enforcement` | 验证批次导入前严格校验 8 席位容量（超出必须先 prune） |
| `test_batch_workspace_archive_layout` | 验证批次运行产物与结果摘要在 workspace 路径规范归档 |

## 6. 回滚

- **代码层面**：本决策为纯契约文档，可通过 git revert 提交直接撤回；
- **数据层面**：清空对应 workspace 下的 `research-batches/<direction>/<track>/` 目录；
- **兼容性**：不改变现有底层引擎的数据结构，与既有 CLI 命令完全向后兼容。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] Pilot 验证通过

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-22 | 1.0 | 初稿：确立 3–4 候选批次结构、禁止纯参数微调契约、8 席位池化流转规则。 |
