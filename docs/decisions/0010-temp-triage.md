# 决策 0010 — temp/ 策略迁移分诊（Triage）

> **English**: [0010-temp-triage.en.md](./0010-temp-triage.en.md)
>
> 范围：`strategies/temp/` 下 146 nova campaign + 132 moneta S 系列的 promote / drop / archive 分诊（HLD §8 第 10 行，#99 新增）。

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0010` |
| 标题 | temp/ 策略迁移分诊（Triage） |
| 状态 | 提案 |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-14` |
| 相关提案 | 无 |
| 相关需求 | `docs/requirements.md` §R8, §R12 |
| 相关 HLD | `docs/hld.md` §8 |
| 取代 | 无 |

## 1. 问题

解决从历史仓库（Nova、Moneta）沉淀的 278 条候选策略语料在 Lyra 中的系统性分诊、清洗、验证与纳管问题。这些历史语料不能直接当作有效策略使用（包含过时特征引用、未在 Lyra 数据集验证、未纳入 Track 治理），也不能简单丢弃，需要一套可重放、符合 Alpha 边界且受门禁约束的分诊机制。

## 2. 背景

- **语料现状**：
  - **Nova campaign**：146 个 YAML + 146 个 `meta.json`，位于 `strategies/corpus/nova_campaign/<family>/<hex>/`（或本地 `temp/`）。全部为 60m 单档策略。146 个 ID 全部唯一。实测 122 个通过 `lyra validate`，24 个因引用 `rsi_14`（Lyra 特征层仅注册 `rsi_12`）失败；1 个特例 `directions_volatility_expansion` 与正式库基线逐字节相同。
  - **Moneta S 系列**：132 条记录，原始形态为 Python 策略代码（位于 Moneta 仓库内，未直接拷入 Lyra），在 temp/corpus 下仅有 `_index.json` 索引，原始 verdict=null。
- **历史裁决**：
  - **O18 裁决（2026-11-11）**：Nova/Moneta 语料的历史成绩不可直接沿用，进入 Lyra 的策略必须在 Lyra 真实 bar 集上全部重算。
  - **用户裁决（2026-11-14）**：Nova 迁移件使用独立 track ID `nova`；Moneta S 系列无 direction 归属，不拆进任何 direction，保留在 temp/ 登记；工作同时要求程序正确与内容正确。
  - **F2 裁决**：分诊裁决写入 OCI corpus `_index.json`（append-only），不进入 git。

## 3. 方案

### 3.1 做什么

1. **分诊对象与清单**：
   - 清单以 OCI corpus（`strategies/corpus/…` + `_index.json`）为准；本地 temp/ 原稿若在即只读使用，不在则通过 pull 拉回。若 Moneta 132 条两边均缺源代码，则记录缺口，分诊只用可得素材。
   - 首轮分诊不一次性处理全量 278 条，而是选择 1 个方向家族的子集（20–40 条）作为实验场，逐条裁决由用户拍板。
2. **分诊三态与判定标准**：
   - **promote**：通过 `lyra validate`（语法合规、特征存在、SQL 可编译）且具备研究价值。复制到 `directions/<family>/nova/v<NN>.yaml`，在头部追加 provenance 注释块（源 ID、源路径、content sha256、假设、nova 历史 pass 数、分诊日期与裁决），其余部分逐字节不动。
   - **drop / archive**：无法通过 validate（如 24 个 rsi_14 件）或历史表现无效（pass=0 等）。保留在 temp/ 语料中，不迁移，在索引中标记 `verdict: archive` 并记录具体原因（例如待改写 rsi_12 后重审）。
   - **duplicate**：与正式库基线逐字节完全一致（如 `directions_volatility_expansion`）。不迁移，索引标记 `verdict: duplicate_of_baseline`。
   - **keep-in-temp**：Moneta S 系列全部 132 条，保持在 temp 登记，不迁移到任何 direction（`verdict: keep_in_temp`）。
3. **入库与重跑流程（O18 强制）**：
   - promote 的策略进入 `strategies/<family>/nova/`，track ID 为 `nova`。
   - 必须在 Lyra 活体特征数据（21 标的 1h）上执行完整 `lyra run`，产生标准运行产物，严禁直接信赖或抄录 Nova 历史绩效。
4. **I21 激活上限（8 active/track）合规**：
   - 迁移件入库登记不等同于全部激活。Track `nova` 的 `active_branches` 只激活通过 validate 且初筛表现领先的至多 8 个候选。其余件以 inactive 文件和索引形式存在，后续通过 `lyra prune` / 轮换管理。

### 3.2 不做什么

- 不一次性把 278 条全部粗暴迁入（首轮只做 1 个家族 20–40 条子集）。
- 不把真实策略 YAML、真实绩效数字或批次归档提交到 git（严格遵守 Alpha 边界）。
- 不为容纳历史语料而破坏 I21（不改大每 track 8 个 active branch 的上限）。
- 不自动改写 rsi_14 特征定义来迎合历史无效件；不注册幽灵特征。

### 3.3 边界

- **OCI 边界**：语料清单与追加的 verdict 记录在 OCI `strategies/corpus/**/_index.json`，遵循 append-only（F2 裁决）。
- **Git 边界**：仅分诊脚本（如 `scripts/triage_0010.py`）与决策/报告文档进入 git，策略 YAML 与运行数据全部在 workspace / OCI。
- **与 0012 边界**：0010 负责历史语料的分类与存量候选入库；入库后的候选如何参与多候选批量演进研究由 0012 规定。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I17 | OCI 双层不可变与追加规则：策略文件不可变，索引只增不减 | HLD §4 |
| I18 | Track 隔离与身份绑定：所有 nova 迁移件均在 track `nova` 下 | HLD §4 |
| I21 | 激活上限门禁：每个 track 最多 8 个 active branch | HLD §4 |
| O18 | 结果必须重算：进入 Lyra 的策略必须在 Lyra bar 集上重算，严禁沿用历史数值 | 决策 O18 |
| B13/B14 | Alpha 边界：策略与运行产物严格保留在 workspace，不进 git | Proposal |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_triage_0010_dry_run` | 验证分诊脚本 dry-run 幂等性，不产生意外写操作 |
| `test_triage_promoted_validate` | 验证所有 promote 候选 100% 通过 `lyra validate` |
| `test_triage_duplicate_skipped` | 验证基线重复项（如 directions_volatility_expansion）被正确跳过 |
| `test_triage_provenance_comments` | 验证添加 provenance 注释后策略的 plan_hash 与原策略完全一致 |
| `test_triage_i21_active_cap` | 验证 track `nova` 激活候选数量严格不超过 8 个 |

## 6. 回滚

- **代码层面**：分诊脚本和文档可通过 git 提交直接 revert。
- **数据层面**：清空 workspace 下对应的 `strategies/<family>/nova/` 目录与相关 run 产物；OCI 端通过更新 append-only 索引标注废弃或通过版本标记隔离。
- **兼容性**：不改变任何引擎代码或现有正式基线策略，回滚无连锁破坏。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] OCI 端到端验证

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-14 | 0.1 | 初稿：完成输入盘点、命名规范与三态分诊定义。 |
| 2026-11-22 | 1.0 | 补全标准决策文档结构（问题、边界、不变量、测试、回滚），对齐 HLD §8 要求与 P1 规划。 |
