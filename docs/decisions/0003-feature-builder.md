# 0003 — Feature Builder（标准特征 + alpha 扩展点）

> **English**: [0003-feature-builder.en.md](./0003-feature-builder.en.md)

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0003` |
| 标题 | Feature Builder（标准特征 + alpha 扩展点） |
| 状态 | **提案**（待用户审批） |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-07` |
| 相关提案 | — |
| 相关需求 | `docs/requirements.md` §R3（R3.1 标准特征 / R3.2 alpha 扩展点 / R3.3 因果性） |
| 相关 HLD | `docs/hld.md` §2.2（features 组件）、§8（构建顺序第 3 步） |
| 取代 | — |

## 1. 问题

策略（0004 compiler）的右值只能是"常量或已注册 feature 列"（I9），
所以 0004 之前必须存在一张**列名确定、语义确定、可复现**的特征宽表。
本 feature 解决：**从 0002 产出的 5m / 1h 聚合层 Parquet（`ohlcv_5m`
/ `ohlcv_1h`，非 bronze 1m 原始层），算出 R3.1 定义的全部标准特征，
落成"每标的一个 Parquet"的特征宽表，并留下一个干净的 alpha 特征
扩展点（R3.2）。**

不解决"用哪些特征组合出好策略"——那是 0004/0005 之后、
方向内策略迭代的事（用户核心诉求：迭代深度，不是特征广度）。

## 2. 背景

- **moneta**：305/270 列特征宽表（`load_data.py` + 特征脚本），
  特征与策略强耦合、列名即契约，但**无注册概念**——加特征就是
  加列、所有策略隐式可见，无版本、无 golden test。
- **nova**：~20 个注册特征（YAML 引用列名），引入
  `FEATURE_VERSION` 与"参数在注册时定死"（I8），但特征计算
  散落在 Python 代码里、无契约卡、无 golden test 要求；
  "策略寻找没有实质进度"的教训之一正是**特征面太宽且无验证**
  （详见 §2.3 moneta/nova 借鉴与反例）。
- **lyra 已有**：0002 的 bronze/5m/1h Parquet（21 标的，
  2020-01-02→2026-11-06 + 2019-11/12 回补未并入）、
  `lyra/catalog.py`（DuckDB catalog + 三 VIEW）、
  `open_limited_duckdb`（内存/线程/临时目录上限）。
- **相关开放问题**：O13（Active Branch Cap=8，0004 用，本 feature 不涉及）。

### 2.3 moneta / nova 借鉴与反例（只读扫描后回填，2026-11-07）

> 只吸收**设计决策与教训**，不吸收代码结构。来源路径：moneta
> `library/*.py` + `docs/indicators.md` §8 + `docs/indicator_research_20261031_report.md`；
> nova `src/nova/catalog.py` + `features.py` + `indicators.py`。

**采纳（已落进本方案）**：

1. **Supertrend 路径依赖 / 不删 warm-up 行**（moneta
   `library/supertrend.py` 实现与注释 / nova `indicators.py` 同源，
   现已被 `talib.SUPERTREND` 逐 bar 复现，见 K1）：canonical 构造 =
   ATR 基础带 + final band 对**上一根 close** 棘轮 + 方向在 close
   穿越活动带时翻转；**路径依赖**（path-dependent），warm-up 后状态
   仍不保证收敛——所以 lyra 从数据**源头**起算并保留 NULL warm-up
   （K4），**不**学 moneta 的"WARMUP_DROP 删行"（见反例 1）。
   moneta/nova 自研版头注释"TA-Lib ships no Supertrend"系**旧版本
   误解**（实测 TA-Lib 0.8.2 有 `SUPERTREND`），lyra 因此改用库
   实现 + 自研版作 golden 交叉锚点，但**路径依赖 / 保留 NULL
   warm-up** 这条纪律照收。
2. **`indicators` 模块纯 NumPy 边界**（moneta `library/__init__.py`
   "NumPy in, NumPy out; no parquet, no DuckDB, no network"）：
   指标函数零框架依赖 → 纯函数、好测（golden test 直接喂数组）、
   可独立版本化。lyra 采纳为 K1 的一部分。
3. **nova 注册表元数据**（`catalog.py` `definition(kind, unit,
   warmup_bars, family)`，kind∈{VALUE, STATE, EVENT}）：warm-up 行数
   是**注册表数据**而非隐式行为 → 0004 compiler 可静态引用；
   F2 的"warm-up 后 NULL = bug"断言可直接用此数据。已并入 §3.1 K3。
4. **研究特征边界排当前 bar**（nova `features.py:_research_features`
   头注释："Boundaries and activity baselines exclude the current
   bar"）：prior-24 高/低/范围、相对量、path efficiency 的窗口
   一律 `shift(1)` 后开窗，防当前 bar 污染自身结构特征。已并入 §3.4。
5. **moneta 六重质量门禁里的三条最硬**（`docs/indicators.md` §8）：
   Gate 1 因果截断（截断重算零重绘，<1e-12）、Gate 3 数值边界
   （RSI∈[0,100]、ATR≥0）、Gate 4 奇异值容错（零振幅不崩）——
   已落进 §5 测试清单。Gate 5（双库 parity）需要第二个库，lyra
   不引入第二实现，**不采纳**（过度工程）。
6. **utc_hour 用 bar 开盘小时的 UTC**（nova `features.py`："Session
   hour is the UTC hour of the bar opening, observable at the
   confirmation close"）——开盘时刻在收盘确认时**已知**，因果安全。
   已并入 §3.4 结构族。

**反例（lyra 明确不学）**：

1. **moneta"WARMUP_DROP 删前缀行"**（`library/supertrend.py` 头注释
   自己承认："dropping WARMUP_DROP rows reduces but does *not*
   eliminate the start-point dependence"）：删行掩盖路径依赖、且
   破坏 bar 时间对齐。lyra = NULL 保留（K4/F2），与 nova 一致。
2. **moneta P1 特征研究 2160 组合 0 晋级**（`docs/indicator_research_
   20261031_report.md`："No tested output qualifies for promotion"）：
   特征广度本身不产生策略深度。lyra 的边界呼应：**0003 只保证
   R3.1 清单正确、可复现、可编译**；"哪个特征有信息量"由 0005
   回测 + 方向 lessons 驱动，0003 不做有效性筛选（§3.2 已列）。
3. **moneta 575 列 Gold 宽表**（`indicator_research_20261031_report.md`
   数据表）：305/270 列宽表是"无注册、列名即契约、策略隐式全可见"
   的产物——加特征无版本、无 golden test 要求。lyra 的 ~20 注册
   特征 + FEATURE_VERSION + 契约卡是针对性收敛，不恢复宽表。
4. **nova `close_ema60_distance_atr` 用 `atr_14`（Wilder）而
   `close_sma24_distance_atr` 用 `atr_sma_14`**（`features.py:compute`）：
   同一语义族混用两种 ATR 归一化基准是**未定义行为**（读者无法
   推断哪条基准对哪个特征生效）。lyra 定案：**所有 ATR 归一化
   特征统一用 `atr_wilder_14`**（Wilder 是行业惯例基准），
   `atr_sma_14` 保留注册但只供显式引用。（**v0.5 更新**：随 K8
   网格纪律，14 窗口全族退役 → 归一化分母统一改 `atr_24`，
   混用基准的反例仍成立。）

**不适用**：moneta 的 OOS token / frozen bucket / 配对周块不确定性
（已废弃，hld §1 少即是多）；nova 的 SHA256 snapshot 目录（I11 已
定案不用）；moneta `library/catalogue.py` 的 median-stretch / log-OLS
残差族（属 moneta P1 研究输出，未晋级，不进 lyra R3.1）。

## 3. 方案

### 3.1 做什么

**CLI**：`lyra features [--minutes 5 60] [--instrument <inst>]`
（**恒重算、恒覆盖**——对齐 0002 A1 的"派生层恒重算"约定，
不做"已存在即跳过"的派生缓存，否则 bronze 被删/损坏时
静默复用陈旧特征；无 `--force`）。

**计算核心**（`lyra/features.py` + `lyra/indicators.py` + `lyra/registry.py`）：
- 输入：ohlcv_5m / ohlcv_1h（0002 契约的 bronze / 聚合 VIEW，
  列 = `instrument, time, volume, mid_*, bid_*, ask_*`）；
  **价格基准 = `mid_*` 列**（0002 bronze 契约），§3.4 的
  open/high/low/close 是 mid_o/mid_h/mid_l/mid_c 的语义简称；
- 每个标准特征 = 一个注册记录（K3），计算函数 =
  `indicators.py` 纯 NumPy 函数或 `features.py` 的向量化组合；
- 计算引擎：定案见 **K1**（标准指标全部来自 TA-Lib，含
  `talib.SUPERTREND`；窗口/结构类用 numpy/pandas 向量化）；
- **数据流控制律（D5）**：计算流水线**必须按标的逐个循环**
  （`for inst in instruments:`），每轮只向 DuckDB 请求
  `SELECT ... FROM ohlcv_<m> WHERE instrument = ? ORDER BY time`，
  算完该标的即落盘并释放，**严禁**一次性把 21 标的全量读进一个
  DataFrame（998 万行 × 60 列峰值 >12 GB，低配机必 OOM）；
- 输出：`data/features/<minutes>m/<instrument>.parquet`
  （**单文件，无 `<snapshot_id>` 目录层级**——对齐 0002 D4 已废弃
  的目录级 snapshot 体系；恒重算恒覆盖，无陈旧目录堆积，D1）。
  版本信息走 **Parquet 文件元数据**（`feature_version`、参数集
  sha256、生成时间戳），不依赖路径层级。列 = 输入 OHLCV 列
  （K2 复制）+ 全部注册特征列，pandas → `pyarrow` 写 Parquet，
  行序 = 输入行序（`ORDER BY time` 读入，0002 I18 同款确定性）；
- **Catalog 接入（D1）**：在 0002 的 `Catalog`（DuckDB 外部表）
  中注册 `features_5m` / `features_1h` 视图（与 `bronze`/`ohlcv_5m`/
  `ohlcv_1h` 同一消费层），0004 compiler 经 Catalog 查特征列，
  不扫文件系统拼路径。

**alpha 扩展点（R3.2）**：
- `lyra.features.load_from(directory)`：扫目录下 `*.py`，
  每个模块暴露 `register(registry)` 函数；alpha 特征 =
  带契约卡（模块 docstring，schema 固定：状态变量/转移规则/seed/
  gap/flip/依赖列）+ 同目录 golden test；
- **API 契约（v0.7 补，D7）**：`registry.register(name, compute,
  *, kind, unit, warmup_bars, family, params)` 为唯一入口；
  `compute` 是**纯 NumPy 函数**（`(mid_o, mid_h, mid_l, mid_c, volume,
  time, *extra) → 1-D float64 数组或 {col: array}`，签名与入参约定在
  实施 spec 定稿，`indicators.py` 边界不变）；`load_from` 对任一
  alpha 模块的语法错误/缺依赖/异常**fail-fast 阻断**（抛错并指名文件，
  **不静默跳过**——静默跳过会让 0004 编译期才炸）；alpha 的
  `FEATURE_VERSION` 归属：alpha 特征语义变更由**其模块 docstring 的版本
  标签**承担，core 的 `FEATURE_VERSION` 只覆盖 core 注册项（I16 边界
  已隔离，不冲突）。
- core 不 import 任何具体 alpha 模块（I16），只 import
  `lyra.features`；alpha 目录来自 `config.yml` `local.alpha`
  （gitignored，B13/I15）；
- 注册名冲突：alpha 名与 core 名撞 → **报错**（不覆盖，不
  `_2` 后缀——特征列名是 SQL 右值契约，静默改名会让策略
  编译期才炸）。

**FEATURE_VERSION**：
- 一个整数，存 `lyra/features.py` 模块常量；
- 任何已注册特征的**计算语义或参数**变更 → +1（I13）；
- 特征宽表的版本标识 = `(timeframe,
  FEATURE_VERSION, 注册表全参数集 sha256, 数值栈版本三元组
  python/numpy/pandas)` 的**派生字符串**，写入 Parquet 元数据
  （**非目录层级**——0002 D4 已废弃目录级 snapshot 状态机，0002
  市场层也无"market snapshot id"实体，故此处不引用它；派生值可
  复现、无需分配器）。**TA-Lib 版本刻意不入版本标识**：
  TA-Lib 是指标参考实现的来源，若它变更语义，正确动作是
  FEATURE_VERSION +1（I13），而不是靠版本串隐式区分——
  snapshot id 表达"注册表语义"，不表达"第三方实现指纹"。

### 3.2 不做什么

| 不做 | 原因 / 归属 |
|---|---|
| 参数扫描 | I8 固定参数；扫描是方向内迭代的事（0004+ 策略层） |
| 特征组合 / 派生特征（feature 算术） | I9 禁止；新特征 = 新注册 |
| 特征有效性筛选（哪个特征"有信息量"） | 不是 0003 的验收标准；0005 回测 + 方向 lessons 驱动 |
| 特征推送 OCI | 0007 push（yml 位置 0002 已预留） |
| 跨 timeframe 特征（如 5m 特征用到 1h 列） | 首版不做；R3.1 清单无此类特征，避免过早抽象（后续需要 = 新方向） |

### 3.3 关键定案

**K1 计算引擎（定案，2026-11-07 二次修订：Supertrend 改回库实现）**：
**统一 Python 侧计算，不混 DuckDB 做计算；标准指标全部来自 TA-Lib**——
- 标准指标（SMA / EMA / ATR / RSI / PSAR / **Supertrend**）用 **TA-Lib**
  （moneta `library/psar.py` 与 nova `features.py` 双代验证：
  `talib.SAR/EMA/SMA/ATR/RSI` 是两代的参考实现，py3.12 wheel
  可用，hld §6 已选型）；
- **Supertrend 用 `talib.SUPERTREND`（TA-Lib 0.8.2 内置），不再自研**：
  moneta `library/supertrend.py` 与 nova `indicators.py` 头注释
  "TA-Lib ships no Supertrend" 是**旧 TA-Lib 版本的误解**——实测
  两代锁定的 TA-Lib 0.8.2 已内置 `SUPERTREND`（`timeperiod` +
  `multiplier` 参数，输出 line + trend）。**用真实数据做双库
  parity 验证**（SPX500_USD 1h，5000 bar，`PER=24, multiplier=3`）：
  自研版与 `talib.SUPERTREND` **逐 bar 100% 一致**（line
  max_abs_diff=0、direction 100% agreement），证明两者语义同源，
  直接采用库实现、以自研版（moneta/nova 参考）作 golden test
  交叉锚点（见 §2.3 采纳 1 + K7 规则 3）；
- 窗口/结构类（prior-24 / breakout / path efficiency / range 位 /
  ATR 归一化）用 **numpy/pandas 向量化**（`shift(1)` + `rolling`，
  nova `_research_features` 同款；§2.3 采纳 4）；
- `indicators.py` 保持**纯 NumPy 边界**（§2.3 采纳 2）：
  NumPy 进、NumPy 出，不 import duckdb/pandas/框架；
- **numba 不引入**（v0.1 草稿的"numba 硬依赖"作废）：TA-Lib
  C 核已覆盖递归类性能；hld §1 少即是多；
- **DuckDB 的角色**：0003 里只做**读输入 / COPY 输出**
  （0002 已验证的外部表模式），不做特征计算——计算语义
  全部在 Python 侧，便于 golden test 与确定性（F4）。
- **TA-Lib 依赖与 R8 可移植性（v0.7 澄清，D2）**：TA-Lib 是**官方
  PyPI 包** `TA-Lib`（`github.com/ta-lib/ta-lib-python`，作者
  John Benediktsson；moneta/nova 锁定的 **0.8.2 即官方封装**，
  非 fork——reviewer"0.8.2 是未验证 fork"的说法不成立）。
  R8 的"可移植：POSIX + Windows；不依赖系统包（**TA-Lib 通过
  wheel**）"已把 TA-Lib 的底层 C 库显式纳入可移植边界。**实测
  moneta venv 的 0.8.2 wheel 是标准 manylinux wheel**：C runtime
  经 auditwheel 打包进 `site-packages/ta_lib.libs/libta-lib-*.so.1.1.0`
  （3.4 MB），`_ta_lib*.so` 直接链接该本地库、**外部仅依赖
  `libc.so.6`**——即 pip 安装即开箱可用，**无需 `apt-get
  libta-lib` / MSVC 手编**，与 reviewer"D2 会 pip 编译崩溃"的
  担忧相反。故**不构成 R8 破坏**。残留风险（若未来某平台无官方
  wheel 需回退源码编译）记为**实施期环境验证项**，不改变 K1 决策；
  且 core 保持"指标算法层与库实现解耦"（`indicators.py` 纯 NumPy
  边界），未来如需替换/降级引擎，只需换 `features.py` 的库调用
  而不触算法。

**K2 宽表粒度（定案）**：特征宽表按 **timeframe × instrument**
分文件（与 market 层布局一致）；每文件含原始 OHLCV 列（复制，
不引用）→ 0004 compiler 读**单文件**即自足，无需 join market 层。
代价：OHLCV 列重复存储（~1.2× 体积）——对齐 moneta"宽表
自足"的成熟做法，换 0004 的 SQL 简单性。

**K3 注册表形态（定案）**：纯 Python dict（`lyra/registry.py`），
不进 DB（注册表是**代码**，随 commit 走，git 即版本历史——
比 moneta 的"列名散落"强、比 nova 的"YAML 特征声明"简单）。
每条注册记录含 **nova 同款元数据**（§2.3 采纳 3）：
`(name, kind ∈ {VALUE, STATE, EVENT}, unit, warmup_bars, family,
params)`——`warmup_bars` 是 F2 断言的数据来源（warm-up 后
NULL = bug），`kind/unit` 供 0004 compiler 静态检查右值语义。

**K4 warm-up（定案）**：特征 warm-up 期输出 **NULL**（不填 0、
不截断行）；`held_for`/`within` 的 N 行非 NULL 判真规则在 0004
compiler 落实，0003 只保证 NULL 语义一致（R3.3）。

**K5 21 标的一致性（定案）**：同一特征在同一参数下对 21 标的
**逐点同算法**（universal，HLD §1 精神）；某标的因数据短 warm-up
更长是允许的（NULL 行数不同），算法不允许不同。

**K6 ATR 归一化基准（定案，§2.3 反例 4；v0.5 随 K8 改网格）**：
所有"距离/位移归一化"特征（`shift6_atr`、`bar_range_atr`、
`prior24_width` 的 ATR 变体等）**统一除以 `atr_24`**（Wilder
平滑、24-bar 窗口、网格默认点）；**不得**在语义族内混用不同
ATR（nova 混用 `atr_14`/`atr_sma_14` 是未定义行为，不学）。

**K7 自研特征管理（定案，v0.5 新增、v0.6 修订为条件护栏，用户
要求）**：**0003 标准特征范围内无自研实现**——Supertrend 已改回
`talib.SUPERTREND`（K1，经真实数据双库 parity 验证），故本规则在
0003 当前清单下**不触发**。它作为**条件护栏**保留：凡未来新增
非第三方库实现的特征（alpha 自研或 core 自研），在注册表中显式
标记 `self_implemented: true`，并强制四项管理（比库实现特征**更严**）：
1. **参数必须显式入注册表**（不得硬编码在函数体；窗口参数取
   网格点（K8），其余数值参数显式注册且 golden test 钉死）；
2. **契约卡强制**（R3.2 对 alpha 的要求同样适用于 core 自研）：
   状态变量 / 转移规则 / seed 约定 / 翻转边界，写在
   `indicators.py` 函数 docstring；
3. **golden test 用独立参考值**：不"自己算自己验证"——用手工
   推导的前 N bar 值 + 与独立实现逐点对照（如 moneta/nova 参考
   实现可作交叉锚点），偏差 > 1e-12 即失败；
4. **版本纪律**：自研特征任何语义变更 → FEATURE_VERSION +1
   （I13）且必须在决策文档修订记录说明理由（库实现变更通常
   只 bump 依赖版本，自研变更无外部锚点，必须自证）。

> 对**库实现**特征的等价纪律（Supertrend 现属此类，直接适用）：
> 参数显式入注册表（ATR 窗口 = 网格点、multiplier 显式）、
> golden test 钉死（Supertrend 用 moneta/nova 自研参考实现做
> 逐点交叉对照，见 K1 的双库 parity）。

**K8 参数网格纪律（定案，v0.5 新增、v0.6 加 120，用户要求）**：
所有**窗口类参数只取 CFD 网格 {6, 12, 24, 60, 120}**（对应
30m/1h/2h/5h/10h 量级，跨 timeframe 语义一致；**120 与 moneta
`library/catalogue.py` 的权威网格 `(6, 12, 24, 60, 120)` 对齐**，
moneta 对该网格之外的窗口直接
`raise ValueError("window outside CFD grid")`）；**不使用 14 这类
Wilder 时代"14 交易日 ≈ 2 周"遗留参数**（nova 研究特征实际全用
6/12/24/60——`return_6`、`prior24`、`efficiency_24`）。
动机（用户）：防止策略在极窄参数环境过拟合——参数面越小、
网格越粗，策略对参数的敏感性越低。**影响**：
- ATR 注册 `atr_6 / atr_12 / atr_24 / atr_60 / atr_120`（单一
  Wilder 平滑，窗口取网格；`atr_sma_14` 双平滑变体**删除**——
  网格纪律下"两种平滑 × 一种窗口"的收益不抵复杂度）；
- RSI 注册 `rsi_6 / rsi_12 / rsi_24 / rsi_60 / rsi_120`（同上，
  网格）；
- SMA/EMA 注册 `sma_/ema_ 6 / 12 / 24 / 60 / 120`（网格全集）；
- **例外（显式记录）**：PSAR `(0.02, 0.2)` 是 Wilder 的
  标准加速/极值因子，**不是 bar 窗口**、不涉及"周"遗留，保留；
  Supertrend multiplier `3` 是倍数非窗口，保留但**参数显式入
  注册表 + golden test 钉死**（K7 库实现等价纪律）；
- 默认归一化分母 = `atr_24`（K6 更新）。

### 3.4 标准特征清单（R3.1 落表）

| 族 | 特征列 | 参数 | 计算类 |
|---|---|---|---|
| 市场 | `open/high/low/close/volume` | — | 复制（K2） |
| SMA | `sma_6 / sma_12 / sma_24 / sma_60 / sma_120` | 网格（K8） | TA-Lib（K1） |
| EMA | `ema_6 / ema_12 / ema_24 / ema_60 / ema_120` | 网格（K8） | TA-Lib（K1） |
| ATR | `atr_6 / atr_12 / atr_24 / atr_60 / atr_120` | 网格（K8） | `talib.ATR`（Wilder 平滑）；**`atr_24` = 归一化分母默认**（K6） |
| RSI | `rsi_6 / rsi_12 / rsi_24 / rsi_60 / rsi_120` | 网格（K8） | `talib.RSI` |
| PSAR | `psar / psar_bullish / psar_bearish` | (0.02, 0.2)（K8 例外：非窗口参数） | `talib.SAR` + 方向标志 |
| Supertrend | `supertrend / supertrend_bullish / supertrend_bearish` | (ATR 窗口 24, multiplier 3) | `talib.SUPERTREND`（K1，库实现）+ moneta/nova 自研参考作 golden 交叉锚点 |
| 语义 | `sma_cross_up_6_24 / sma_cross_down_6_24 / sma_alignment_6_24 / rsi_divergence_up / rsi_divergence_down` | 引用已注册列（6/24） | 派生（已注册列的确定性谓词） |
| 结构 | `prior24_high / prior24_low / prior24_range / prior24_range_pos / prior24_width / breakout_up / breakout_down / failed_breakout_up / failed_breakout_down / shift6_atr / bar_range_atr / rel_quote_activity / utc_hour / path_eff_24` | 6 / 24（均网格内） | numpy/pandas 向量化（K1） |

**结构族口径（§2.3 采纳 4/6，K6/K8）**：
- `prior24_*` 的 24 根窗口**排除当前 bar**（`shift(1)` 后开窗，
  nova `_research_features` 同款）；
- `failed_breakout_up` = 当前 bar `high` 越过 prior24_high 但
  `close` 收回其内（wick 扫过假突破，nova 同款定义）；
- `utc_hour` = bar **开盘时刻**的 UTC 小时（收盘确认时已知，
  因果安全）；
- 所有 ATR 归一化分母 = `atr_24`（K6 更新）；
- **v0.5/v0.6 网格化（K8，用户拍板）**：原 `atr_14 / rsi_14`
  （Wilder "14 交易日 ≈ 2 周" 遗留）与 `atr_sma_14` 双平滑
  变体**删除**；SMA/EMA 补齐 12；**v0.6 加 120**；所有窗口参数
  ∈ {6,12,24,60,120}。前代背书：moneta `catalogue.py` 对网格外
  窗口直接 `raise ValueError("window outside CFD grid")`（权威
  网格 = 6/12/24/60/120）；nova 研究特征实际全用 6/12/24/60。

> **D4 过程门禁（本表 ≠ 实现规格）**：上表是**特征清单**，不是
> 数学规格。进入 0003 实施**之前**，必须在实现 spec（`indicators.py`
> 各函数 docstring + `tests/` golden）里为**每个**自研语义/结构特征
> 补**精确到变量名与运算符的确定性数学定义**，并对所有除法特征
> （`path_eff_24` / `prior24_range_pos` / `shift6_atr` / `bar_range_atr` /
> `rel_quote_activity`）显式定义分母为 0 / 接近 0 的兜底规则
> （`denom == 0 → NULL` 或 `0.0`，且不得被 Gate 4 当 NaN 泄漏拦截）。
> 决策文档只锁定"算哪些、用哪族参数"，"怎么算"以 spec + golden
> test 为准（防止不同实现者写出不同代码、golden test 沦为自证）。

> 清单以 R3.1 为准；本表是 0003 的**实现分解**。新增/删减特征
> = 改 R3.1 + 本文 + FEATURE_VERSION。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I1 | 每个 feature 在 `bar_close_time` 时可用（past-only，无未来引用）——**列对齐**：0002 bronze / 聚合层的该时间列实名为 `time`（bar 起点，UTC），I1/R3.3 的 `bar_close_time` 是其语义名；0003 实现按 `time` 落列，**不新增** `bar_close_time` 列（否则 0004 双时间列歧义） | HLD §4 / R3.3（本 feature 澄清列名对齐） |
| I13 | 改特征计算/参数 → FEATURE_VERSION +1 | HLD §4 / R3.1 |
| I15 | alpha 特征目录不进 git（`local.alpha` gitignored） | 0001 / B13 |
| I16 | core 不 import 具体 alpha 模块，只 import `lyra.features` 扩展点 | 0001 |
| I17 | alpha 特征文件 Immutable（OCI 侧，同 sha 幂等） | HLD §4 |
| F1 | 特征宽表**列集确定**：同 FEATURE_VERSION + 同注册表 → 列名集相同（0004 编译期可静态检查） | 本 feature 新增 |
| F2 | warm-up NULL 语义（**v0.7 收紧**，D3）：0002 已保证输入 `mid_*` 零 NULL 且**无缺口占位行**（实测 998 万行 0 NULL），故特征 NULL **只允许**来自 (a) **warm-up 前缀**（K3 `warmup_bars`），或 (b) **派生特征的已定义零分母**（如 `prior24_range_pos` 遇 24 根全平价 bar → `range==0`，按 D4 门禁定义的兜底规则产出 NULL/0，属合法语义而非缺口传播）；**除此两类，warm-up 后出现任何 NULL/NaN 即判定为计算崩溃或除零 Bug**（Gate 4 拦截） | 本 feature 新增（v0.7 按 D3 收紧，删除"缺口传播闭包"幽灵概念） |
| F3 | 特征宽表每标的单文件自足（K2）：0004 读单文件即可编译，不 join market 层 | 本 feature 新增 |
| F4 | 计算确定性（**v0.7 收紧**，D6）：同输入 + 同 FEATURE_VERSION + 同数值栈版本 + **同平台/同数学库** → 特征值**逐位一致**（bitwise）；**跨平台**（Linux↔Windows↔macOS，AVX2/AVX-512/NEON、OpenBLAS/MKL 等数学库差异）只承诺 `np.allclose(atol=1e-12, rtol=1e-12)` 高精度一致，**不承诺逐位**——浮点求和/求积顺序与 1-ULP 舍入随硬件与编译器优化而变（D6），golden test 因此按"同平台逐位、跨平台 allclose"两级断言（对齐 moneta Gate 1） | 本 feature 新增（v0.7 按 D6 加跨平台容差层级） |
| F5 | 注册名冲突（core vs alpha）→ 报错，不覆盖 | 本 feature 新增 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_registry_core_names_unique` | 注册表无重名 |
| `test_registry_alpha_conflict_raises` | alpha 与 core 同名 → 报错（F5） |
| `test_load_from_alpha_dir` | `load_from(directory)` 加载示例 alpha 模块成功 |
| `test_load_from_core_only_unchanged` | 无 alpha 目录时 core 注册表不变（I16） |
| `test_sma_values_known` | SMA 手工值 golden test |
| `test_ema_recursion_known` | EMA 前 5 值手工 golden（递归起点 = 首值） |
| `test_rsi_grid_known` | RSI（窗口 24）手工 golden（`talib.RSI` Wilder 平滑） |
| `test_atr_grid_values_known` | `atr_6/12/24/60/120` 各窗口手工 golden；不同窗口值互不相同（网格生效） |
| `test_grid_only_windows` | 注册表所有窗口参数 ∈ {6,12,24,60,120}，无 14（K8 防回归） |
| `test_psar_bull_bear_flags` | PSAR 方向标志与翻转 bar 对齐 |
| `test_supertrend_line_and_flags` | `talib.SUPERTREND` 线 + bull/bear 标志一致性 |
| `test_supertrend_parity_vs_reference` | `talib.SUPERTREND` 与 moneta/nova 自研参考实现逐 bar 对照（line/direction），偏差 < 1e-12（K1 双库 parity 固化成回归，防 TA-Lib 换版本悄悄改语义） |
| `test_warmup_null_semantics` | 连续无缺失输入：NULL **仅** warm-up 前缀；warm-up 后出现任何 NULL/NaN = 断言失败（F2 v0.7，D3）；**例外**：派生特征零分母（如 `prior24_range_pos` 全平价 24 根）按 D4 兜底规则产出 NULL/0，属合法（单独断言，不混入前缀规则） |
| `test_no_future_reference` | 截断数据末端 N 行 → 前缀特征值不变（I1 因果性，最硬的一条） |
| `test_deterministic_rerun` | 同输入、**同环境**重跑 → 特征值逐位一致（F4 严格层） |
| `test_wide_table_self_sufficient` | 宽表含全部 OHLCV 列，单文件可独立查询（F3/K2） |
| `test_feature_version_in_metadata` | 版本标识（FEATURE_VERSION/参数 sha256/数值栈版本）变 → Parquet 元数据里的版本串变（**非目录层级**，D1） |
| `test_output_single_file_no_snapshot_dir` | 输出为 `features_<m>/<instrument>.parquet` 单文件，**无** `<snapshot_id>` 子目录；重跑恒覆盖不堆积（D1） |
| `test_per_instrument_streaming` | 数据流按标的逐个循环：单标的工作集峰值受控（<300MB 量级断言），非全量 21 标的同驻（D5） |
| `test_f4_same_env_bitwise_cross_env_allclose` | 同环境重跑逐位一致（F4 严格层）；文档化"跨平台 allclose(1e-12)"为可维护上限（F4/D6） |
| `test_universal_21_instruments` | 21 标的同特征同参数、算法逐点一致（K5） |
| `test_feature_count_matches_r31` | 宽表列集 == R3.1 清单（F1 防漂移） |
| `test_gate1_truncation_zero_redraw` | 截断数据重算 vs 全量前缀：`max\|V_trunc − V_full[:k]\| < 1e-12`（moneta Gate 1，I1 最硬形式） |
| `test_gate3_bounds_rsi_atr` | RSI ∈ [0,100]、ATR ≥ 0、PSAR/Supertrend 线 ∈ [low, high] 域（moneta Gate 3） |
| `test_gate4_zero_amplitude_no_crash` | 平价 bar / 零振幅 / 零 volume 注入 → 无 Inf / NaN 泄漏 / 崩溃（moneta Gate 4） |
| `test_atr_normalization_basis_atr24` | 所有 ATR 归一化特征分母 == `atr_24`（K6，防 nova 混用反例） |
| `test_supertrend_path_dependent_from_head` | 从数据头起算；中途起算结果可不同（路径依赖显式接受，warm-up NULL 保留，K4） |
| `test_supertrend_registry_params` | Supertrend（库实现）管理纪律：ATR 窗口取网格点、multiplier 显式入注册表（非硬编码于函数体）+ golden 值与 moneta/nova 参考实现逐点偏差 < 1e-12（K7 的库实现等价纪律，非"自研四项管理"——后者是未触发条件护栏） |

## 6. 回滚

- 代码：revert 0003 commit（`lyra/features.py` `lyra/indicators.py`
  `lyra/registry.py` + tests + 本文档）；0002 不受影响（特征层
  是纯新增，不碰 clean/aggregate/pull）。
- 数据：`data/features/` 整个目录可删（派生层，恒可重算——
  0002 A1 约定）；bronze/5m/1h 不动。
- 兼容性：0002 及以前行为零变化；0004 尚未开发，无下游依赖。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] `pyproject.toml` 加 `TA-Lib` 依赖（K1 引入，实施时同步 lock）
- [ ] 真实数据（bronze 48M 行）端到端跑通 5m/1h 特征宽表
- [ ] 2019-11/12 回补数据并入后（用户决定时机）特征 warm-up 跨月行为验证

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-07 | 0.1 | 初稿（骨架）：问题/背景/方案 K1–K5 定案 + R3.1 特征清单分解 + 不变量 F1–F5 + 17 测试 + 回滚。 |
| 2026-11-07 | 0.2 | **moneta/nova 只读扫描回填**：§2.3 采纳 6 条 + 反例 4 条 + 不适用 3 类（Supertrend 自研 / indicators 纯 NumPy 边界 / nova 注册表 warmup 元数据 / 结构窗口排当前 bar / Gate 1-3-4 门禁 / utc_hour 口径；反例 = WARMUP_DROP 删行、P1 2160 组合 0 晋级、575 列宽表、ATR 归一化混用）；**K1 修订**：numba 草案作废，改 TA-Lib + 自研 Supertrend + numpy 向量化，DuckDB 只读写不算；K3 补 nova 元数据；**新增 K6**（ATR 归一化统一 Wilder 基准）；§3.4 结构族口径明确；测试 17→**22**（+Gate1/3/4 + K6 + Supertrend 路径依赖） |
| 2026-11-07 | 0.3 | **自检修复（3 处自相矛盾 + 1 处实现歧义）**：① §3.1 CLI 原"已存在且 snapshot id 一致则跳过"与 0002 A1 派生层恒重算冲突 → 改恒重算恒覆盖；§3.1 残留的 numba/DuckDB 计算草稿与 K1 定案冲突 → 重写指向 K1；§3.2"不做 TA-Lib"行与 K1 采纳 TA-Lib 矛盾 → 删行。② §3.4 表列名 `open/high/low/close` 与 bronze 契约 `mid_o/...` 不符 → 明确价格基准 = mid 列、语义简称。③ I1 的 `bar_close_time` 与 bronze 实际列名 `time` 的双列歧义 → I1 行澄清列对齐（不新增列）。④ `atr_sma_14` 实现口径"混合"含义不明 → 定为 TR 的 14 根 SMA（与 Wilder 递推必须是两种不同算法）。另：TA-Lib 版本刻意不入 snapshot id（语义变更走 I13），审批清单补 TA-Lib 依赖项 |
| 2026-11-07 | 0.4 | **对抗性自检修复（1 处不变量过强）**：F2 原"warm-up 后任何 NULL = bug"在**市场缺口**（0002 I22 明确缺口合法、真实数据 73 万处）下会误判——缺口 bar 缺失传播到依赖窗口特征是**合法** NULL，非 bug。修订为"NULL 位置 ⊆ warm-up 前缀 ∪ 上游缺失传播闭包"（方向由 I1 因果性保证）；测试 `test_warmup_null_prefix_only` 更名为 `test_warmup_null_semantics` 并补缺口传播断言。其余候选项（F1/F4/F5、K2 复制体积、K5 与缺口交互、snapshot id 派生串长度）经核验为误报或已覆盖，不改 |
| 2026-11-07 | 0.5 | **用户拍板两点，落 K7/K8**：① **自研特征管理（K7）**——用户问"Supertrend 为什么自研"：TA-Lib **确无** Supertrend（moneta/nova 头注释均确认），自研特征比库实现更严：参数显式入注册表（禁硬编码）+ 契约卡强制 + golden test 用 moneta/nova 同源参考实现逐点交叉验证（<1e-12，不自己验自己）+ 语义变更必须 I13+1 并说明理由。② **参数网格纪律（K8，用户拍板）**——用户指出 14 是 Wilder "14 交易日≈2 周"遗留、要求尽量用 6/12/24/60 且参数不要太多防极窄参数过拟合；前代背书：moneta `catalogue.py` 对网格外窗口直接 `raise ValueError("window outside CFD grid")`、nova 研究特征实际全用 6/12/24/60 → **ATR/RSI 改 6/12/24/60 网格**、`atr_sma_14` 双平滑变体删除、SMA/EMA 补 12、Supertrend ATR 窗口 14→24、归一化分母 `atr_wilder_14`→`atr_24`（K6 更新）；例外：PSAR (0.02,0.2) 非窗口参数保留。同步 R3.1（requirements 中英权威清单）+ §3.4 表 + 测试（+`test_grid_only_windows`/`test_supertrend_k7_management`，2 个 14 相关用例改网格版）。测试 22→**24** |
| 2026-11-07 | 0.6 | **两项用户指令落实**：① **Supertrend 改用库实现**——用户要求"再 review 有没有 lib 能获得 Supertrend"。实测推翻前代认知：moneta/nova 头注释"TA-Lib ships no Supertrend"是**旧版本误解**，两代锁定的 **TA-Lib 0.8.2 实测内置 `SUPERTREND`**（`timeperiod`+`multiplier`，输出 line+trend）。用真实数据（SPX500_USD 1h，5000 bar，PER=24/mult=3）做双库 parity：自研版与 `talib.SUPERTREND` **逐 bar 100% 一致**（line diff=0、direction 100%），证明语义同源。→ **K1 改回**"标准指标全部来自 TA-Lib（含 Supertrend）"；**K7 降级为条件护栏**（0003 现无自研实现，规则保留供未来）；§2.3 采纳 1 由"必须自研"改"路径依赖/不删 warm-up 行"（Supertrend 语义不变，仅换实现来源）；§3.4 Supertrend 行计算类改 `talib.SUPERTREND`；**新增测试** `test_supertrend_parity_vs_reference`（双库 parity 固化成回归）。② **K8 网格加 120**（用户指令"加上120"）→ 网格 = {6,12,24,60,120}，**与 moneta `catalogue.py` 权威网格对齐**；ATR/RSI/SMA/EMA 各补 `*_120` 变体（§3.4 表 + K8 影响块 + `test_atr_grid_values_known` + `test_grid_only_windows` 同步）。同步 R3.1（requirements 中英权威清单）。测试 24→**25** |
| 2026-11-07 | 0.7 | **批次2 外部红队 D1–D8 处置（按用户接受/挂起/拒绝三级：接受 5 = D1/D3/D5/D6/D8，挂起 2 = D4/D7，拒绝 1 = D2）**：① **D1（接受）**——§3.1 废除 `<snapshot_id>` 目录层级与"market snapshot id"幽灵派生项（0002 D4 已废弃目录级 snapshot、市场层无该实体），改单文件 `features_<m>/<instrument>.parquet` + 版本入 Parquet 元数据；补 **Catalog 接入**（注册 `features_5m/1h` 视图，0004 经 Catalog 查列不扫盘）；测试改 `test_feature_version_in_metadata` + 新增 `test_output_single_file_no_snapshot_dir`。② **D5（接受）**——§3.1 补**数据流控制律**：强制 per-instrument 循环、单标的工作集受控、严禁全量 21 标同驻；新增 `test_per_instrument_streaming`。③ **D6（收紧）**——F4 由"bitwise"收紧为**同环境 bitwise + 跨平台 allclose(1e-12)** 两级；新增 `test_f4_same_env_bitwise_cross_env_allclose`。④ **D3（收紧）**——F2 删除"缺口传播闭包"幽灵概念（0002 DQ1 保证 mid_* 零 NULL 且无缺口占位行，实测 998 万行 0 NULL），改为 NULL 只允许来自 warm-up 前缀 ∪ 派生特征已定义零分母；`test_warmup_null_semantics` 同步。⑤ **D4（挂起+过程门禁）**——决策文档≠实现规格，§3.4 加 **D4 过程门禁**：实施前必须为每个自研语义/结构特征补精确数学定义 + 所有除法特征补零分母兜底（`denom==0 → NULL/0`，不被 Gate 4 当 NaN 泄漏）。⑥ **D2（拒绝其核心主张，据实澄清）**——K1 澄清：TA-Lib 0.8.2 是**官方 PyPI 包**（`ta-lib/ta-lib-python`，非 fork），**实测 wheel 经 auditwheel 打包 C runtime**（`ta_lib.libs/libta-lib-*.so`，外部仅依赖 `libc.so.6`），pip 即开箱可用、无需系统 C 库编译 → **不构成 R8 破坏**；残留"某平台无 wheel"风险记为实施期环境验证项。⑦ **D7（挂起+过程门禁）**——alpha 扩展点补 API 契约（`registry.register(...)` 入口 + compute 纯 NumPy 签名 + 加载 fail-fast 不静默跳过 + alpha 版本归属），细节落实施 spec。⑧ **D8（接受）**——§1 输入口径由"bronze/5m/1h"改为"5m/1h 聚合层"（0003 只消费 0002 聚合层，不碰 bronze 1m）。另修 **v0.5 遗留不一致**：`test_supertrend_k7_management` 语义（自研四项管理）与 v0.6 K7 降级矛盾 → 改 `test_supertrend_registry_params`（库实现管理纪律）。测试 25→**28**（+3：输出单文件/per-instrument/F4 两级；改 2：warmup_null、supertrend 管理；改 1：snapshot→metadata） |
