# Lyra 功能需求（Requirements）

> **English**: [requirements.en.md](./requirements.en.md)
>
> 本文档是 Lyra 的需求基线。后续每一个 feature 的决策文档（`docs/decisions/NNNN-*.md`）
> 都应该显式引用本文档的条目；改动需求本身也要在这里留一条记录。

## R0. 一句话目标

在有限的 AI 预算和业余时间之内，提供一个**稳定、轻量、可审查**的策略研究
工具，让我能持续地"试 + 分析"策略。它**不是**一个产品，也不是一个合规/审计
系统。

## R1. 研究问题

- 给定一组标的（forex / precious metals / crude oil / equity indices），
  一条 universal strategy（相同规则、相同参数、相同成本），能不能得到
  **每个月的实际开仓机会**？
- 如果能，它的**年化净收益分数**（arithmetic sum of net trade returns ÷
  full calendar years, 365.25 days/year）是不是正数，是不是比同类候选更高？
- 每个标的**单独**报告，不合成 portfolio return，不引入 Buy & Hold 门槛。
- "没有优势"是一个合法的研究结果，工具必须能把它**如实**呈现，不夸大。

## R2. 策略语言

- **YAML 是唯一策略语言。** 不允许 SQL、Python、eval、callback、外部脚本。
- **参数固定。** 每个 feature 的参数在注册时就定死了，不做参数扫描
  （防 overfit）。要新东西就注册新 feature。
- **比较算子**：`eq / ne / gt / gte / lt / lte`。
- **时间算子**：`all / any / not`，`held_for`，`within`，`after_event`。
- **右值**：常量 **或** 另一个已注册 feature 列。**禁止** feature 之间的
  算术（`+ - * /`）、禁止跨标的比较、禁止任意 SQL 片段。
- **一个策略 = 一个 timeframe。**（不做 60m entry + 5m exit 这种组合）
- **一个策略 = 一个方向规则集**，`long` / `short` 可分别指定，冲突时
  两个都不开。
- **向后兼容**：现有 332 个策略 YAML 全部能在 Lyra 编译器上跑通，语法
  不变。

## R3. 特征模型

### R3.1 标准特征（开源，随 repo 走）

固定注册名 + 固定参数。**窗口参数只取 CFD 网格 {6, 12, 24, 60, 120}**
（2026-11-07 用户拍板，0003 K8：不用 Wilder 时代 "14 ≈ 2 周"
遗留参数；参数面收窄以抑制极窄参数环境过拟合；**120 与 moneta
`catalogue.py` 权威网格对齐**）。初始清单：

- 市场数据：`open / high / low / close / volume`（UTC 对齐）
- SMA：6, 12, 24, 60, 120
- EMA：6, 12, 24, 60, 120
- ATR：Wilder-ATR 6 / 12 / 24 / 60 / 120（**24 = ATR 归一化分母默认**）
- NATR：`atr / close` 归一化（6, 12, 24, 60, 120）
- RSI：6, 12, 24, 60, 120
- PSAR：(0.02, 0.2)（例外：加速/极值因子，非窗口参数）
- Supertrend：(ATR 窗口 24, multiplier 3)（**`talib.SUPERTREND`
  库实现**，0003 K1；moneta/nova 自研参考作 golden 交叉锚点）
- MACD（精选三元组，非全网格展开）：(6, 12, 6) / (6, 24, 6) / (12, 60, 12)
- ROC：6, 12, 24, 60, 120
- STOCH：%K/%D，(fastk, slowd) ∈ {(6,6), (24,12), (60,24)}（slowk 平滑 = 1）
- BBANDS：%B + 带宽，窗口 (24, 60, 120)，std = 2
- ADX / PLUS_DI / MINUS_DI：24, 60（趋势强度族，仅 2 点）
- CCI：24, 60
- WILLR：24, 60
- MFI：24, 60（量价资金流）
- CMO：24, 60
- OBV + `obv_slope_24`（累计量 + 24-bar 斜率）
- LINEARREG_SLOPE（归一化斜率）：24, 60
- KAMA（自适应均线）：24
- **v0.9 新增（P0 缺口补全）**：
  - DEMA：6, 24, 60
  - TEMA：6, 24, 60
  - HMA（Hull）：24, 60
  - MOM（n-bar 动量）：6, 24, 60
  - Rolling StdDev（价格离散度）：24, 60
  - Z-Score（标准化价格位置）：24, 60
  - Efficiency Ratio @60（v0.8 已有 eff_24）：60
  - Donchian @60（prior60_high / prior60_low，v0.8 已有 prior24_*）：60
- **v1.1 新增**：Heikin Ashi（`ha_o / ha_h / ha_l / ha_c`，K7 自研，递归变换无窗口参数，warmup 16）
- **v1.3 新增（6 族，趋势强度/效率维度）**：
  - TRIX（三重 EMA 平滑动量）：24, 60
  - TSI（双 EMA 动量，精选 fast/slow 二元组）：(24,12), (60,24)
  - VHF（波动率效率）：24, 60
  - Vortex（方向强度 VI+/VI−）：24, 60
  - Aroon（趋势年龄 UP/DOWN）：24, 60
  - （均 TA-Lib 0.8.2 有库实现、K8 网格、pandas-ta-classic 可机器验证）
- **缓做（有理由，非遗忘；v1.3 移除已落地的 TRIX / AROON / TSI / Vortex / VHF）**：
  - Keltner（= EMA±2×ATR，BBANDS 已覆盖"均值±n 波动带"信号）
  - Choppiness（= 100×LOG(SUM(TR)/MAXHIGH−MINLOW)，是 ATR+Donchian 组合变换，非独立信号）
  - Relative Volume / VWMA（v0.8 rel_quote_activity 已覆盖相对量信号）
  - PPO（MACD 归一化变体，冗余）；ULTOSC / SMI（利基动量变体，参数面过大）
  - CMF / EFI / PVT（量价/方向比，与 MFI/OBV 信号重叠）
  - QQE / RSX / VFI / Squeeze / Schaff / Ichimoku / Inside Bar / Williams Fractal（需自研或参数面爆炸；Heikin Ashi 已于 v1.1 落地）
  - CORREL / BETA（单标的宇宙无自然基准序列）
  - HT_*（过拟合风险）；CDL*（需先做统计预筛）
  - **v1.3 显式缓做 5 组**（Ehlers 周期/滤波族、截面相对强弱、多周期、OHLC 波动率估计器、Connors RSI/累计RSI(2)）——各组的被挡原则 / 缓做理由 / **解锁门槛**详见 `decisions/0003-feature-builder.md` §3.4 "v1.3 显式缓做 5 组" 表（中英成对）；其中**截面组是用户标注的最高优先级候选**，R9 扩展为多标的后应最先纳入
- 语义 / 结构：`sma_cross_up_6_24 / sma_cross_down_6_24`、
  `sma_alignment_6_24 ∈ {-1, 0, 1}`、`rsi_divergence_up / down`、
  `psar_bullish / bearish`、`supertrend_bullish / bearish`
- 研究原语（v2 已定）：prior-24-bar 高/低/范围/范围位/宽度、
  breakout / failed-breakout 谓词、6-bar ATR 归一化位移、bar range/ATR、
  相对报价活跃度、UTC 开盘小时、24-bar path efficiency

### R3.2 自定义（alpha）特征 — Python 是底线

- **所有自定义特征用 Python 写**（不是 DSL / 伪代码 / operator algebra）。
- 每个特征必须带 **契约卡（contract card）**：状态变量、转移规则、seed、
  gap/flip 边界、依赖的输入列。
- 每个特征必须带 **golden test**：固定输入 → 固定输出，把语义钉死。
- 代码 + 契约卡 + golden test 整体是 **alpha，只放 OCI**，不进 git。
- Git 侧只保留一个干净的**扩展点**：`lyra.features.load_from(directory)`，
  通用特征随 repo 走，alpha 特征运行时从 OCI 挂载路径加载。

### R3.3 因果性

- 每个 feature 在 `bar_close_time` 时可用。"per-bar" 不禁止 EMA/PSAR
  使用历史；它只禁止使用未来。
- 编译出的 SQL 必须是 **past-only**：`lag` / 以当前行为结尾的窗口，
  不允许 `lead`、不允许跨未来的 join。
- Warm-up NULL **保留**，不任意删一段；`held_for` / `within` 要求完整
  N 行非 NULL 才判真（保守约定，沿用 starter）。

## R4. 执行合约（Trade engine）

- **收盘确认信号，下一根开盘价成交。**
- **2% 强制不利退出**（相对该笔实际开仓价）：
  - 多单：价格 ≤ entry × (1 − 0.02) 时，下一根开盘前触发。
  - 空单：价格 ≥ entry × (1 + 0.02) 时，下一根开盘前触发。
  - 跳空 / 滑点损失可能超过 2%；**2% 是触发器，不是最终净损失上限**。
- **同根同时触及止盈/止损 → 亏损方优先。**
- **每标的最多一笔持仓**；持仓期间忽略新入场信号。
- **退出当根不重入；下一根满足入场条件可以重入。**
- **冲突的 long/short 条件 → 两个都不开。**
- **最后一根 bar 上排队的入场 → 作废（expire）。**
- **数据结束时还持仓 → 在最后一根收盘平仓。**
- **成本**：flat round-trip 佣金比例 + 按 **交易日**计的 financing 比例
  （elapsed = 持仓区间内的交易日数；**周末与市场节假日——新年 / 圣诞等——
  均不计**，非物理日历天）；
  spread / slippage 已在成交价中，不重复计。
- **收益公式**：`direction × (exit_fill − entry_fill) / entry_fill`，减去
  成本项。**不做**仓位管理、杠杆、保证金、账户净值、HWM、熔断。

## R5. 指标与报告

- **每标的、每月**一行：实际开仓次数、净收益和、胜率、平均持有 bar 数。
- **零开仓月份保留**，显式 0 而不是省略。
- **年化分数** = 所有交易净收益算术和 ÷ 完整日历年（365.25 天/年）。
- **月度机会** = 实际开仓次数（不是信号出现次数）。
- **不合成 portfolio**，不做 CAGR / HWM / Sharpe / Sortino。
- 报告必须列出：strategy 名、timeframe、标的清单、时间窗、feature
  snapshot id、git commit、日期。

## R6. 数据与 OCI

- **基础数据从 OCI 拉**（PAR URL），不在 git 里。
- 本地目录结构（见 `docs/proposals/oci-alpha-layout.md`）：
  - `oci://<bucket>/lyra/data/raw_csv/`：原始 CSV（OANDA / 其他源）
  - `oci://<bucket>/lyra/data/raw_parquet/`：原始 Parquet
  - `oci://<bucket>/lyra/data/market/<minutes>m/`：清洗后的 OHLCV Parquet
  - `oci://<bucket>/lyra/data/features/<minutes>m/`：特征宽表
- **alpha 边界**（全部只在 OCI，目录布局见 `docs/proposals/oci-alpha-layout.md`）：
  - `oci://<bucket>/lyra/alpha/features/*.py`
  - `oci://<bucket>/lyra/alpha/features/contracts/*.md`
  - `oci://<bucket>/lyra/alpha/features/tests/*.py`
  - `oci://<bucket>/lyra/strategies/<direction>/{hypothesis.md, lessons.md, vNN.yaml}`
    （方向文件夹组织，见 R12）
  - `oci://<bucket>/lyra/runs/<name>/<date>/*`
- **双向同步**是 Lyra 的核心 feature（见 R7）。
- **OCI 镜像默认在仓库外**：本地 `data/` `strategies/` `runs/` 解析为
  `~/.lyra/<workspace>/…`，**不落在 git 工作区内**（B13 防呆）。
- 本地缓存可删除重建（从 OCI 拉 + 重算）。
- 数据完整性：SHA256 校验、去重（`(instrument, time)` 唯一）、
  缺失分钟按 gap 处理（不合成填充）。

## R7. OCI 双向同步（Lyra 的核心 feature）

Lyra 的主要功能就是**跟 OCI 保持同步**：

- **pull**：按 `config.yml` 拉取所需数据集（raw → market → features），
  本地缓存，按 snapshot id 复用。
- **push**：策略运行完成后，把 runs / analysis 上传 OCI；
  alpha features 修改后可 push 回 OCI。
- **backup**：本地 `strategies/` 和 `runs/` 有变更时，
  提供 `lyra sync` 一键命令。
- **冲突策略**：`config.yml` 决定（默认：OCI 为 source of truth，
  本地变更需显式 `--force-push`）。
- **凭证**：PAR URL 优先；可选 OCI auth（`~/.lyra/credentials`）。
  凭证不进 git。

## R8. 非功能需求

- **稳定**：同一输入 + 同一版本 → 同一输出（bit-for-bit，DuckDB 版本
  一致时）。
- **轻量**：核心依赖 ≤ 15 个 Python 包；启动 < 3 秒；单次 21 标的
  H1 全量 run < 5 分钟（16 核机器）。**例外（2026-11-08）**：
  `control` 可选依赖组（当前仅 `tulipy`）不计入核心上限——它是
  **test-only 跨库对照组**，运行时不 import，
  `pip install "lyra[control]"` 显式启用（0003 v1.2 K1b）。
- **可审查**：每个 feature 一个 commit + 一个决策文档；
  测试覆盖因果性 / 执行合约 / 指标口径 / 数据合约。
- **可移植**：POSIX + Windows；不依赖系统包（TA-Lib 通过 wheel）。
- **无副作用**：不写 git、不联网（除 OCI）、不改用户文件
  （除显式声明的本地目录）。

## R9. 明确不做（Out of Scope）

- 仓位管理、杠杆、保证金、账户净值、CAGR、HWM、Sharpe、Sortino
- 熔断、账户级 stop、恢复规则
- **autonomous / unbounded AI strategy generation**（无人值守批量生成
  候选策略、无方向约束的自动搜索）。**注意边界**：AI 作为**有界迭代**
  的一等写作者（在已批准的方向内写 vNN、人逐版 review）**属于范围
  内**，见 R12。两者区别：有没有方向假设约束 + 有没有人逐版把关。
- Live trading / broker 集成
- 分布式 / 多进程 / 云原生
- 数百个指标的自动扫描
- 组合优化 / 资产池晋级 / Buy & Hold 门槛
- 跨 timeframe 组合（一个策略 = 一个 timeframe）
- OOS ledger / one-shot gate / trial_log（Moneta 的老机制，不再沿用）

## R10. 验收

- `pytest -q` 全绿（含因果性 / 执行合约 / 指标口径 / 数据合约）。
- `lyra-doctor` 全绿。
- 至少 3 个策略（long-only / short-only / long+short）在 21 标的
  H1 全量数据上跑通，报告可审查。
- 332 个 legacy 策略 YAML 全部 `lyra validate` 通过。
- OCI pull/push 在真实桶上跑通一次端到端。

## R11. 兼容性

- **向后兼容 Nova**：332 个策略 YAML 直接能跑；
  17 个已注册 feature 名称不变；2% stop 语义不变。
- **不兼容 Moneta**：Moneta 的 OOS ledger / trial_log / 305/270 列
  feature 表不作为 Lyra 的输入合约；如需迁移，走
  `lyra ingest --kind moneta`（未来 feature）。

## R12. 方向与迭代（策略组织模型）

策略的一级组织单元是**方向（direction / research family）**，不是单个
YAML 文件。初始 12 个方向继承自 nova：`trend_continuation`、
`failed_breakout`、`mean_reversion`、`momentum_exhaustion`、
`pullback_reentry`、`range_trading`、`regime_transition`、
`relative_strength`、`session_temporal`、`volatility_expansion`、
`volume_activity`、`market_structure`。

**方向集合是 open 的（extendable）**：初始 12 个是种子，不是封闭清单。
用户可新建方向；建议新方向是一个可检验的独立市场假设，不与现有方向
重复（软标准；若可被现有方向表达，建议在该方向开新版本而非新方向）。
新方向与初始方向完全同权。

- **每个方向一个文件夹**，必须含：
  - `hypothesis.md`：可检验命题 + 放弃条件（kill criteria）+ 状态
    （active / paused / killed）+ 活跃分支 + 修改历史（只增不删）。
  - `lessons.md`：append-only 演进日志；每个分支版本一段
    （父版本 / 改了什么 / 驱动它的 lesson / 结果）+ 每个分叉判断一段
    （对比 / continue-prune-cross / 理由）。
  - `v01.yaml`, `v02a.yaml`, `v02b.yaml`, …：**版本树**（一个父版本可
    分叉多个候选分支；交叉分支命名如 `v04ab.yaml`）。
- **vNN（N≥2）必须声明** `parent: <父版本 id>`（交叉分支为
  `parents: [...]`）和 `driven_by_lesson: <一句话，指向 lessons.md>`。
  v01 不需要。
- **多分支是一等能力**：单线程深搜会陷局域最优；一个版本的诊断应
  推导出**多个**候选演进方向并行试；`lyra compare --siblings` 提供
  兄弟分支 run 摘要对比，AI/人 综合判断 continue / prune / cross。
  交叉（变异）：**找策略的 AI 全权决定**（整块 / 逐参数 / 改造，不限
  粒度）；框架的职责是保证 AI 有此能力（context 含活跃分支完整
  YAML+参数）；AI 在 YAML（`inherited` / `driven_by_lesson`）声明来源
  供审计。
  > **边界（I8 不变）**：改造仅作用于**策略层**（阈值 / 比较符 / 时间算子
  > / entry-exit 结构）；**严禁改动特征注册名及已注册特征底层参数**
  > （如 `sma_6_24`→`sma_7_25`，属 I8 违规，`validate` 拒绝）。特征要变 =
  > 注册新特征（走 contract card + golden test）。
- **分支生命周期**：`active` → `pruned`（文件保留不删）→ 或被交叉
  继承。kill criteria 作用于**所有活跃分支**连续 N 轮失败；单分支
  失败 = prune，不是 kill。
- **演进循环**（核心工作流）：
  `context` → `new-version --branch`（派生 1~N 个分支模板）→ 各跑 run
  → `compare --siblings` → 写 lessons（每分支一段 + 判断段）→
  （可选）`merge` 交叉 → `push-direction`。
- **AI 是一等写作者**：与用户走同一套命令；AI 的上下文必须自包含于
  方向文件夹——`lyra context <direction>` 输出单文件上下文包
  （hypothesis + 最近 N 段 lessons + 活跃分支 vNN + **兄弟分支 run
  摘要对比表** + feature 清单），AI 写循环 = 读 1 文件 → 写 1~N 个
  分支文件 → 各跑 1 次 → 记 1 段 + 1 段判断，不接触 repo 其他部分。
- **方向是标签，不是独立的赚钱机制**（继承 nova DECISIONS 的共识）；
  允许"没有优势"的结论；触发 kill criteria 后方向标记 `killed`，
  文件夹保留（不删，见 B6 的延伸）。
- **extendable**：新方向放 `strategies/_new/<name>/`，结构与初始 12 个
  一致；建议可检验、尽量不与现有方向重复（软标准）；新旧方向同权；
  killed 方向不删除。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿。从 `nova/docs/DECISIONS_2026-11-03.md` 与
  `nova/docs/DESIGN.md` 提炼；Moneta BRD/SAD 的适用部分并入 R4/R5。 |
| 2026-11-05 | 0.2 | R6 alpha 边界改为方向文件夹布局；新增 **R12 方向与迭代**
  （hypothesis / lessons / vNN 版本链 / kill criteria / 迭代循环）。 |
| 2026-11-05 | 0.3 | R12 明确方向集合 **extendable**：初始 12 是种子非封闭清单，新方向准入标准 + 同权 + killed 不删。 |
| 2026-11-05 | 0.4 | R12 准入标准定为**软标准（A 方案）**：建议而非硬门禁。 |
| 2026-11-05 | 0.5 | R12 新增 **AI 一等写作者 + 上下文自包含**（`lyra context` 单文件上下文包；读1/写1/跑1/记1）。 |
| 2026-11-05 | 0.6 | R9 措辞修正：排除的是 **autonomous / unbounded AI generation**；明确 **AI 有界迭代（R12）属于范围内**，消除与 R12 的字面冲突。 |
| 2026-11-06 | 0.8 | R12 交叉段补 **I8 边界**（L2）：AI 改造能力仅限策略层（阈值/操作符/时间算子/entry-exit 结构），严禁改动特征注册名及已注册特征底层参数（如 `sma_6_24`→`sma_7_25`，属 I8 违规，`validate` 拒绝）；特征要变 = 注册新特征。 |
| 2026-11-07 | 0.9 | **R3.1 网格纪律（用户拍板，0003 K8）**：窗口参数只取 CFD 网格 {6,12,24,60}——不用 Wilder "14≈2 周" 遗留参数，参数面收窄防极窄参数环境过拟合。ATR 改 6/12/24/60（24=归一化分母默认）、RSI 改 6/12/24/60、SMA/EMA 补 12、Supertrend ATR 窗口 14→24；例外：PSAR (0.02,0.2) 非窗口参数保留。前代背书：moneta `catalogue.py` 网格外窗口 `raise ValueError("window outside CFD grid")`；nova 研究特征实际全用 6/12/24/60。同步 0003 v0.5（K6/K7/K8 + §3.4 + 测试 24） |
| 2026-11-07 | 0.10 | **R3.1 两项更新（用户指令）**：① **网格加 120** → {6,12,24,60,120}，**与 moneta `catalogue.py` 权威网格对齐**；ATR/RSI/SMA/EMA 各补 `*_120` 变体。② **Supertrend 改库实现**——实测推翻前代认知：moneta/nova 头注释"TA-Lib ships no Supertrend"系旧版本误解，两代锁定的 **TA-Lib 0.8.2 实测内置 `SUPERTREND`**；真实数据双库 parity（SPX500_USD 1h，5000 bar）自研版与 `talib.SUPERTREND` **逐 bar 100% 一致** → R3.1 Supertrend 行由"自研"改"`talib.SUPERTREND` 库实现 + moneta/nova 自研参考作 golden 交叉锚点"。同步 0003 v0.6（K1/K7/K8 + §3.4 + 测试 25） |
| 2026-11-07 | 0.11 | **R3.1 扩充标准指标集（用户批准"推荐范围"）**：新增 NATR / MACD（精选三元组 6_12_6/6_24_6/12_60_12）/ ROC / STOCH（%K/%D）/ BBANDS（%B+带宽，不用原始上下轨）/ ADX+PLUS_DI+MINUS_DI / CCI / WILLR / MFI / CMO / OBV（斜率）/ LINEARREG_SLOPE / KAMA 共 **13 族**；窗口参数一律取 K8 网格 {6,12,24,60,120}（外部建议清单的 5/10/14/20 不采用）。参数面纪律：MACD 精选三元组非全网格展开、趋势强度/动量/震荡族只取 24/60、BBANDS/OBV 取无量纲形态。**缓做**（有理由）：PPO/TRIX/ULTOSC/AROON/STDDEV、CORREL/BETA（无基准序列）、HT_*/CDL*。**触发 I13：FEATURE_VERSION +1**。同步 0003 v0.8（§3.4 + D4 门禁 + 测试 34） |
| 2026-11-07 | 0.12 | **R3.1 v0.9 补全 P0 缺口（8 项）**：DEMA(6/24/60)、TEMA(6/24/60)、HMA(24/60)、MOM(6/24/60)、Rolling StdDev(24/60)、Z-Score(24/60)、Efficiency Ratio @60、Donchian @60（prior24_* 基础上补 prior60_*）。**缓做新增**：Keltner（=EMA±2×ATR，BBANDS 已覆盖）、Choppiness（=ATR+Donchian 组合变换）、Relative Volume/VWMA（rel_quote_activity 已覆盖）、P1 全族（参数面过大或需自研，留第二批）。**触发 I13：FEATURE_VERSION +1**（v0.8 已 +1，本次再 +1 = 累计 +2）。同步 0003 v0.9（§3.4 + 测试 +6） |
| 2026-11-07 | 0.13 | **R3.1 新增 Heikin Ashi（用户指令；0003 v1.1）**：`ha_o / ha_h / ha_l / ha_c` 4 列，K7 自研（TA-Lib 无此指标），递归变换无窗口参数（K8 N/A），warmup_bars=16（递归收敛安全下界）；K7 管理纪律全部适用（`self_implemented: True` 注册表标记 + 契约卡 + golden test + I13）。缓做清单的 Heikin Ashi 项移除（已落地）。**触发 I13：FEATURE_VERSION +1（2→3）**。同步 0003 v1.1（§3.4 + 测试 +2） |
| 2026-11-08 | 0.14 | **R8 轻量条款例外（用户批准）**：`control` 可选依赖组（当前仅 `tulipy`）不计入核心 ≤ 15 包上限——test-only 跨库对照组，运行时不 import，`pip install "lyra[control]"` 显式启用（0003 v1.2 K1b：exact 9 族 <1e-6 一致 + definitional 9 族口径差异冻结 + 5 族无库跳过；tail-alignment 工程点）。requirements 本体指标集不变（120 features，FEATURE_VERSION=3）。 |
| 2026-11-08 | 0.15 | **R3.1 新增 6 族 + R8 对照组更新（0003 v1.3）**：R3.1 落地 TRIX(24/60) / TSI(24_12/60_24) / VHF(24/60) / Vortex(24/60) / Aroon(24/60 up/down) 共 **14 特征**（均 TA-Lib 有库实现、K8 网格、pandas-ta-classic 可机器验证）；缓做清单移除已落地项。**R8 例外扩为 2 个对照库**：`control = ["pandas-ta-classic","tulipy"]`——pandas-ta-classic 升**主**（PyPI 活跃 2026-10，276 指标，pandas 仅作测试对照依赖被用户接受）、tulipy 降**次**（2019-04 后未更新，保留 C 后端/免 pandas 的独立锚点价值）。**触发 I13：FEATURE_VERSION +1（3→4）**，标准特征 120→**134**。同步 0003 v1.3（§3.4 +6 行、§5 测试 +4 行）。 |
