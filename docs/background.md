# 背景：moneta → nova → lyra

> **English**: [background.en.md](./background.en.md)
>
> 本文是 Lyra 的"为什么存在"。读这份文档之前不需要读 moneta / nova 的
> 代码；读完这份文档你应该能回答"为什么不再继续改 nova，而要新开 lyra"。

## 0. 一句话

Lyra 是同一个研究目标（forex / precious metals / crude oil / equity indices
上的 universal strategy 发现）的**第三次**实现。前两次分别解决了"能不能跑"
和"能不能验证"，但没有解决"能不能让我在业余时间和小 AI 预算内持续做研究"。

## 1. Moneta（第一代）

**时间**：2026-10-19 ~ 2026-10-31（约两周）
**仓库**：`ttrrei/moneta`
**目标**：从零搭一个可跑的回测 rig，把"数据 → 特征 → 策略 → 回测 → 报告"
这条路打通。

**做了什么**：

- 数据管线：`extract_oci.py`（OCI PAR 下载 + unzip → CSV）、
  `extract_oanda.py`（OANDA gap-fill / 历史回填）、`load_data.py`
  （CSV → `all_data.parquet` + DuckDB catalog）、`aggregate_ohlcv.py`
  （1m → 5m/1h）、`indicators.py`（特征引擎，TA-Lib + 自研）。
- 共享回测引擎：`engine.py`（accounting + metrics，long & short，tested）。
- 策略层：`strategy_lib.py`（共享数据/eval 核心）、若干 `strategy_*_lib.py`
  （S-01 RSI、S-05 Supertrend、S-06 EMA spread）。
- 矩阵跑手：`run_matrix.py`（3 标的 × 2 时间窗 × 3 成本档 →
  `strategy/results/`）。
- OOS 治理：`oos_token.py`（数据层 holdout gate，fail-closed）、
  `oos_ledger.json`（one-shot holdout ledger）、`trial_log.md`
  （best-of-N discipline）。
- 研究 campaign：50 个 feature idea、200 个策略（2 轮 × 100），
  **0 个晋级**。
- 305 / 270 列特征宽表，Parquet + DuckDB。

**做得好的**：
- 因果性保护（1h feature 用 `m.close_time >= h.close_time` 的 as-of join；
  信号在 closed bar 确认、T+1 open 成交）。
- 共享引擎 + 测试覆盖（指标 6 道质量门、metrics 口径、pipeline 单元）。
- 332 个策略 YAML 全部在语法内（这个事实后来在 nova 里也验证过）。

**为什么停下**：

1. **研究目标没收敛**。50 feature + 200 策略 0 晋级，说明"指标够不够多"
   不是瓶颈；"同样的 CPU 时间能探索多少**不同类型**的策略"才是。
2. **搜索空间集中在熟悉的指标组合**上，没有真正的方向性。
3. **OOS ledger / trial_log / 305 列宽表**这套机制本身是好的，
   但对"业余时间 + 小 AI 预算"的场景过重：每次改一行都要重新走
   token mint、ledger 预约、holdout 流程。
4. 工程重心偏"研究功能开发"，而不是"研究效率 / 策略发现能力"。

**留下的资产**（nova 继承）：
- 验证过的 trade 语义（2% stop / next-open / 亏损方优先 / warmup-NULL）。
- 332 个策略 YAML（全部 in-grammar，可作为 Lyra 的回归集）。
- 17 个已注册 feature 的名称和参数。
- OCI PAR 下载的 `extract_oci.py`（可移植到 Lyra）。

## 2. Nova（第二代，2026-11-01 ~ 2026-11-03）

**时间**：约 3 天
**仓库**：`ttrrei/nova`
**目标**：在一个**新 repo** 里把 moneta 的核心语义"原样搬过来"，
去掉 OOS / ledger / trial_log 这套治理，让"跑一条策略看交易"这件事
变得**轻**。

**做了什么**（对照 `nova/docs/DECISIONS_2026-11-03.md` §9）：

| # | 组件 | 落地 |
|---|---|---|
| 1 | Data (OCI) | `data.py`：archive + hash + dedup + UTC aggregate |
| 2 | Features | `features.py` + `catalog.py` + `indicators.py`（Supertrend 递归） |
| 3 | Compiler | `compiler.py` + `config.py`（YAML → past-only SQL） |
| 4 | Trade engine | `trades.py`（2% stop / next-open / 成本） |
| 5 | Metrics + runner | `metrics.py` + `runner.py` |
| 6 | Migration | 332 策略 in-grammar 验证通过 |
| 7 | Polish | `cli.py` + `doctor.py` + `audit.py` |

**做得好的**：
- 4 个核心组件的语义**和 moneta 一致**，没有漂移。
- 332 个策略 YAML 在 nova 编译器上 0 失败、0 未注册 feature、0 不支持算子。
- 测试覆盖因果性 / 时间确认 / long-short 成交价 / 不利 gap / 成本 /
  月度零值 / 数据合约 / 可复现性。

**为什么停下**（2026-11-03 的 DECISIONS 文档里用户原话）：

> "Nova 由 chatgpt 主动推进的版本，核心简陋，外围过度工程。
> 比如 lock 等等。但是核心功能比如从 OCI storage 下载数据、上传策略备份
> 等等基本没有。"

具体地：

- **外围过度**：
  - SHA256 快照目录名（`22d25208bac99177`），对人无意义。
  - `FROZEN_CORE.sha256` hard-fail guard，任何改动都让所有历史 run 失效。
  - 761 行 `manifest.json` 的 artifact-hash 清单。
  - `store.py` / `audit.py` / `doctor.py` 三个"治理"模块。
- **核心缺失**：
  - **OCI 双向同步完全没做**（pull / push / backup 都没有）。
  - **alpha 边界没有工程化**（custom feature 加载点、策略上传、
    run 备份都没有接口）。
  - **feature-vs-feature 比较**（DECISIONS §6 已同意放宽，
    但 nova 编译器没改）。
  - **supertrend 的 contract card + golden test** 样例没落。

**留下的资产**（lyra 继承）：
- 验证过的 4 个核心组件的语义（trade 语义、compiler 语法、
  指标口径、数据合约）。
- 332 个策略 YAML 的 in-grammar 验证结果。
- `extract_oci.py` 的 PAR 下载实现（moneta 的，可移植）。
- **一份完整的"要 drop 什么"清单**（DECISIONS §7）。

## 3. Lyra（第三代，现在）

**时间**：2026-11-05 起
**仓库**：`ttrrei/lyra`
**目标**：把 nova 验证过的 4 个核心组件**原样移植**，
**丢掉** nova 的外围治理，**补上** nova 缺失的 OCI 双向同步 + alpha 边界。

**原则**（2026-11-03 用户原话）：

> "这个项目是我在业余时间、用小 AI 预算，持续地试和分析策略。
> 它必须稳定、轻。它不能变成一个"完美工程但没用"的产物。"
> "alpha（自定义特征、策略定义、运行结果）是被动收入的来源，
> 绝对不能开源。alpha 公式分享得越多，被均摊得越快。"

**推进路线**：以 [hld.md §8](hld.md) 的 0001→0009 表为**唯一事实来源**
（每步 = 一个决策文档先于代码 + 一个 commit + 一组测试）：

1. **0001 repo + OCI 分工**（alpha 边界规则，已在文档层完成）
2. **0002 OCI pull + clean + aggregate** —— 第一个**代码**组件；
   数据同步是 Lyra 的主功能（R7），所以先于特征/编译器落地
3. **0003 Feature builder** → **0004 YAML compiler** → **0005 Trade
   engine** → **0006 Metrics & runner** —— nova 验证过的 4 个核心组件
   语义原样移植；每组件先用 fixture 数据跑通，再接真实 OCI 数据
4. **0007 OCI push + backup** —— 主功能的另一半
5. **0008 332 策略迁移 + 回归** → **0009 Polish**

**不做**（见 `requirements.md` R9）：
- 仓位 / 杠杆 / 保证金 / 账户净值 / CAGR / HWM / Sharpe
- **autonomous / unbounded** AI 策略生成（无人值守批量候选）。
  注意：**AI 有界迭代**（方向内写 vNN、人逐版 review）属于范围内，见 R12
- Live trading / broker 集成
- 分布式 / 云原生
- 数百指标自动扫描
- 组合优化 / 资产池晋级
- OOS ledger / trial_log（moneta 的老机制，不再沿用）

## 4. 时间线速查

| 日期 | 事件 |
|---|---|
| 2026-10-19 | moneta 仓库建立 |
| 2026-10-26 ~ 30 | 5 轮 repo review（`moneta/docs/repo_review_*.md`） |
| 2026-10-31 | 50 feature idea + 200 策略 campaign 完成，0 晋级 |
| 2026-11-01 | nova 仓库建立（moneta-next starter v0.1 → v0.2） |
| 2026-11-01 | luna6.1design / sol6.1design 对话存档（`nova/background/`） |
| 2026-11-03 | DECISIONS 文档落盘（`nova/docs/DECISIONS_2026-11-03.md`），
  确定"drop 什么 / 保留什么 / 补什么" |
| 2026-11-05 | **lyra 仓库建立（本仓库）**，开始写文档 |

## 5. 关键决策的继承关系

| 决策 | moneta | nova | lyra |
|---|---|---|---|
| 数据底座 | Parquet + DuckDB | Parquet + DuckDB | **同** |
| 策略语言 | YAML | YAML | **同**（放宽 feature-vs-feature） |
| 特征存储 | 305/270 列宽表 | Hybrid（core + domain） | **Hybrid**（core + domain） |
| 时间条件 | SQL 层 | SQL 层（past-only） | **同** |
| 跨标的 | Universal | Universal | **同** |
| 杠杆 | 最高 30x | 30x（仅解释 2% stop 的来源） | **30x**（仅解释 2% stop 的来源） |
| 回撤规则 | HWM + 1%/2%（**已废弃**） | 只留 2% stop | **只留 2% stop** |
| 2% 强制退出 | 无 | 有（相对实际开仓价） | **同** |
| 一标的一笔 | 有 | 有 | **同** |
| 收盘确认 / 下一根开盘成交 | 有 | 有 | **同** |
| 月度机会 = 实际开仓 | 有 | 有 | **同** |
| 年化分数 = 算术和 ÷ 完整日历 | 有 | 有 | **同** |
| OOS ledger / trial_log | 有 | **无** | **无**（不沿用） |
| SHA256 快照目录 | 无 | 有 | **无** |
| FROZEN_CORE guard | 无 | 有 | **无** |
| Artifact-hash manifest | 无 | 有 | **无** |
| OCI 双向同步 | 单向 pull（`extract_oci.py`） | **无** | **有**（核心 feature） |
| Alpha 边界 | 无（moneta 是个人仓库） | 无 | **有**（OCI 为 source of truth） |

## 6. 怎么读 moneta / nova 的旧文档

- **moneta**：`docs/BRD.md`（需求）、`docs/SAD.md`（架构）、
  `docs/indicators.md`（特征规格）、`docs/data_profile.md`（数据画像）、
  `docs/repo_review_2026-10-26..31*.md`（5 轮 review，含失败诊断）。
- **nova**：`docs/DESIGN.md`（设计合同）、
  `docs/DECISIONS_2026-11-03.md`（**最重要的决策档案**）、
  `docs/REAL_DATA_RESULTS.md`（真实数据跑出来的结果）、
  `docs/VERIFICATION.md` + `docs/verification/`（验证证据）。
- **对话存档**（读着费劲，但信息密度高）：
  - `nova/background/luna6.1design`：luna 6.1 的完整对话（111 KB）
  - `nova/background/sol6.1design`：sol 6.1 的完整对话（14 KB）
  - `nova/background/moneta-next/START_HERE.md`：starter v0.2 的启动合同

## 7. 本文档的维护

- 每完成一个 Lyra feature，在 §3 推进路线对应步骤打勾，并在 §4 时间线加一行。
- 如果某个 moneta / nova 的决策被 Lyra **推翻**，在 §5 表里加一行
  （moneta 列保留原值，nova 列保留原值，lyra 列写新值 + 决策文档链接）。
- 本文档是**只增不删**的（历史决策不删，只在 §5 表里标"已废弃"）。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿。 |
| 2026-11-05 | 0.2 | §3 "三件事"改为"推进路线"，统一指向 hld.md §8 的 0001→0009 表（唯一事实来源），消除与 README 的顺序矛盾。 |
