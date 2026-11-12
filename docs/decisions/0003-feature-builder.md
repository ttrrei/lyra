# 0003 — Feature Builder（标准特征 + alpha 扩展点）

> **English**: [0003-feature-builder.en.md](./0003-feature-builder.en.md)

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0003` |
| 标题 | Feature Builder（标准特征 + alpha 扩展点） |
| 状态 | **已实施**（0003 代码落地，107 测试通过，真实数据 E2E 通过；v1.1 新增 Heikin Ashi；v1.2 引入 tulipy 跨库对照组 K1b；v1.3 新增 TRIX/TSI/VHF/Vortex/Aroon 6 族 + pandas-ta-classic 提升为主要对照组；v1.3 补文档级自检与对抗性自检 §5b + 缓做 5 组完整落表 §3.4；**v1.4 处置批次1 外部对抗性 review（§5c）：接受 7/挂起 1/拒绝 0，落 5 项代码/文档修复 + M5 文档收窄，104→107 测试**） |
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
- 输出：`data/features/ohlcv_<layer>/<instrument>.parquet`
  （`<layer>` = `5m` / `1h`，对齐 0002 聚合层命名；**单文件，无
  `<snapshot_id>` 目录层级**——对齐 0002 D4 已废弃的目录级 snapshot 体系；
  恒重算恒覆盖，无陈旧目录堆积，D1）。
  版本信息走 **Parquet 文件元数据**（`feature_version`、参数集
  sha256、生成时间戳），不依赖路径层级。列 = 输入 OHLCV 列
  （K2 复制）+ 全部注册特征列，DuckDB（或纯 Python）→ `pyarrow` 写 Parquet，
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
- **API 契约（v0.7 补，D7；v1.4 修正 H2）**：`registry.register(name, compute,
  *, kind, unit, warmup_bars, family, params, window_params, self_implemented)`
  为唯一入口；
  `compute` 是**纯函数**，真实签名为 `compute(ctx: Ctx, spec: FeatureSpec)
  → 1-D float64 ndarray`，其中 `ctx` 是每标量的只读上下文
  （`o/h/l/c/v` 为 1-D ndarray、`t` 为 datetime64[us] 或 epoch-µs int64、
  `n` 为行数、`atr24` 为派生属性），`spec` 携带该特征的
  `params`/`window_params`/`family` 等元数据。返回值**必须**是
  `shape == (ctx.n,)` 的 `np.ndarray`（`compute_features` 显式校验，
  违反则抛 `TypeError`/`ValueError`）。**多列特征**（如 MACD line/signal/hist、
  Stoch k/d）通过在 `register()` 中注册**多个独立特征**实现（每个特征一个
  列名 = SQL 右值契约），而非让单个 `compute` 返回 `{col: array}` ——
  后者不被支持（v1.4 修正：此前文档误写为 `*extra` 入参与 `{col: array}`
  返回，与实际实现不符）。`load_from` 对任一
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

**K1b 跨库对照组（v1.2 引入 tulipy；v1.3 提升 pandas-ta-classic 为主要对照组）**：
K1 用 TA-Lib 作为**唯一计算后端**，为防止未来 TA-Lib 换版本悄悄改语义，
引入**独立第二实现**做交叉验证。选型实测（隔离 venv、py3.12 + numpy 2.5.4）
后结论（v1.3 更新）：
- **主要对照组 = pandas-ta-classic**（v1.3 新增）——活跃维护（2026-10 仍在发版）、
  **276 指标**（> tulipy 的 105）、**全长度 NaN 前缀**（与 TA-Lib 同行为，**无需
  tail-align**）、恰好覆盖 tulipy 缺的 plus_di/minus_di/supertrend/hull。
  实测 exact 组 18 族机器精度一致（<1e-9），definitional 组（MACD/ROC/CMO/MFI/
  STOCH/BBANDS/Aroon/TSI/OBV/Supertrend）为库间约定差异（平滑器/×100/命名/种子）。
  `tests/crosscheck_pandas_ta_classic.py` + `test_crosscheck_pandas_ta_classic.py`。
- **补充锚点 = tulipy**（v1.2，**2019-04 后停更**，保留因 C 后端独立代码路径）——
  C 后端、**免 pandas**（唯一免 pandas 的第三方指标库）、
  100+ 指标、覆盖面 > `test_indicators.py` 的手写纯 NumPy 参考，且以后加
  P1/P2 指标时可直接复用为对照组。**作为可选依赖** `lyra[control]`（
  `pyproject.toml` 的 `[project.optional-dependencies] control = ["tulipy"]`），
  **不进核心依赖**（R10 保持 ≤15 核心包），仅 `tests/` 期 import；
  `tests/test_crosscheck_tulipy.py` 在 tulipy 缺失时 `pytest.importorskip`
  自动跳过，不破坏核心套件（100 测试含其 2 项，缺库时 98）。
- **排除 Finta**——PyPI 名 `fintech` 被无关的 LicenseManager 包抢注，装不到真身、
  且已归档；**排除 bukosabino/ta 与 pandas-ta-classic**——都强绑 pandas，违背
  "运行时栈刻意无 pandas"，且本质是 TA-Lib 的 re-implementation，对照价值
  tulipy 已覆盖；**排除 vectorbt**——整套策略研究框架（自带回测/组合），非指标
  库，引入即成"第二个找策略引擎"，正是 moneta 踩过的外围过度工程坑。

**两组实证差异（K1b 核心发现，固化进对照标签，非 bug）**：
- **机器精度一致（tag `exact`，断言 < 1e-6）**：SMA / HMA / KAMA / RSI / MOM /
  CCI / WILLR / MFI / STDDEV——这些**不用衰减递光滑滑器**，两个 C 库仅差浮点噪声。
- **定义差异（tag `definitional`，只断言有限、不断言量级）**：EMA / DEMA / TEMA /
  ATR / ADX / NATR / ROC / CMO / OBV——这些**用递光滑滑器**（EMA 或 Wilder），
  TA-Lib 与 tulipy 的递归**种子不同 / alpha 不同 / ×100 缩放 / OBV 种子**，
  尾部在合理序列长度下**不收敛到机器精度**（实测 EMA/DEMA ~1e-2、TEMA ~1e-3、
  ATR/ADX ~3e-3、随长度波动）。这是合法的库间约定差异，与 #61 的 CMO/MFI
  同源。**关键工程点**：tulipy **裁剪 warm-up 前缀、返回短数组**（与 TA-Lib
  保留 NaN 前缀、长度不变相反，正是 moneta §2.3 反例 1 的"删前缀"陷阱），
  故对照**必须按尾部对齐**（`a[-k:]`），不可假设等长。

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
| NATR | `natr_6 / natr_12 / natr_24 / natr_60 / natr_120` | 网格（K8） | `talib.NATR`（`atr/close` 波动尺度） |
| MACD | `macd_6_12_6 / macd_6_24_6 / macd_12_60_12`（各含 `line / signal / hist` 三列） | **精选三元组**（K8 例外，见下） | `talib.MACD`（fast/slow/signal） |
| ROC | `roc_6 / roc_12 / roc_24 / roc_60 / roc_120` | 网格（K8） | `talib.ROC`（动量） |
| STOCH | `stoch_k_6 / stoch_d_6` 等，(fastk, slowd) ∈ {(6,6),(24,12),(60,24)} | 网格内配对（K8） | `talib.STOCH`（%K/%D） |
| BBANDS | `bband_pctb_24 / bband_pctb_60 / bband_pctb_120` + `bband_bw_24 / 60 / 120` | 网格（K8），std=2 | `talib.BBANDS`（%B + 带宽，**不用原始上下轨**） |
| ADX 族 | `adx_24 / adx_60`、`plus_di_24 / plus_di_60`、`minus_di_24 / minus_di_60` | 24/60（K8，仅 2 点） | `talib.ADX / PLUS_DI / MINUS_DI`（趋势强度） |
| CCI | `cci_24 / cci_60` | 24/60（K8，仅 2 点） | `talib.CCI`（均值回归动量） |
| WILLR | `willr_24 / willr_60` | 24/60（K8，仅 2 点） | `talib.WILLR`（均值回归） |
| MFI | `mfi_24 / mfi_60` | 24/60（K8，仅 2 点） | `talib.MFI`（需 volume，量价资金流） |
| CMO | `cmo_24 / cmo_60` | 24/60（K8，仅 2 点） | `talib.CMO`（动量） |
| OBV | `obv`、`obv_slope_24`（`obv` 的 24-bar `LINEARREG_SLOPE`） | 斜率窗口 24（K8） | `talib.OBV` + 斜率派生（**不用绝对值**，用斜率/变化率） |
| 回归斜率 | `lrslope_24 / lrslope_60`（`LINEARREG_SLOPE / close` 归一化） | 24/60（K8，仅 2 点） | `talib.LINEARREG_SLOPE`（趋势方向） |
| KAMA | `kama_24` | 24（K8） | `talib.KAMA`（自适应均线，ER 因子内建） |
| DEMA | `dema_6 / dema_24 / dema_60` | 6/24/60（K8） | `talib.DEMA`（二阶指数均线 `2·EMA − EMA(EMA)`，比 EMA 更贴价格、比 SMA 更稳） |
| TEMA | `tema_6 / tema_24 / tema_60` | 6/24/60（K8） | `talib.TEMA`（三阶指数均线，去趋势更彻底） |
| HMA | `hma_24 / hma_60` | 24/60（K8） | `talib.HMA`（Hull：平滑且滞后低，适合趋势方向） |
| MOM | `mom_6 / mom_24 / mom_60` | 6/24/60（K8） | `talib.MOM`（`close − close[n]`，n-bar 绝对动量；区别于 ROC 的相对百分比） |
| StdDev | `stddev_24 / stddev_60` | 24/60（K8） | `talib.STDDEV`（`close` 滚动标准差，绝对离散度；区别于 ATR 的 TR 基准） |
| Z-Score | `zscore_24 / zscore_60` | 24/60（K8） | 派生（`(close − SMA(close,n)) / STDDEV(close,n)`，标准化价格位置，无量纲；分母为已定义零分母） |
| PSAR | `psar / psar_bullish / psar_bearish` | (0.02, 0.2)（K8 例外：非窗口参数） | `talib.SAR` + 方向标志 |
| Supertrend | `supertrend / supertrend_bullish / supertrend_bearish` | (ATR 窗口 24, multiplier 3) | `talib.SUPERTREND`（K1，库实现）+ moneta/nova 自研参考作 golden 交叉锚点 |
| Heikin Ashi | `ha_o / ha_h / ha_l / ha_c` | 无窗口参数（递归变换，收敛 ~16 bar） | **K7 自研**（TA-Lib 无此指标）；递归 `ha_c=(o+h+l+c)/4`、`ha_o=(ha_o[i-1]+ha_c[i-1])/2`、`ha_h=max(h,ha_o,ha_c)`、`ha_l=min(l,ha_o,ha_c)`；warmup_bars=16 |
| TRIX | `trix_24 / trix_60` | 24/60（K8） | `talib.TRIX`（三重 EMA 平滑的一阶动量，无量纲比率；warmup 3n−2） |
| TSI | `tsi_24_12 / tsi_60_24` | (24,12)/(60,24)（K8，fast/slow 精选二元组） | `talib.TSI`（EMA 动量再 EMA 平滑，指数 [-100,100]） |
| VHF | `vhf_24 / vhf_60` | 24/60（K8） | `talib.VHF`（Volatility Hester Framework：方向性变动/总路径，[0,1]） |
| Vortex | `vortex_p_24 / vortex_m_24 / vortex_p_60 / vortex_m_60` | 24/60（K8） | `talib.VORTEX`（方向强度 VI+/VI−，无量纲） |
| Aroon | `aroon_up_24 / aroon_down_24 / aroon_up_60 / aroon_down_60` | 24/60（K8） | `talib.AROON`（趋势年龄：n−bars_since_highest/lowest，[0,100]） |
| 语义 | `sma_cross_up_6_24 / sma_cross_down_6_24 / sma_alignment_6_24 / rsi_divergence_up / rsi_divergence_down` | 引用已注册列（6/24） | 派生（已注册列的确定性谓词） |
| 结构 | `prior12_high / prior12_low / prior12_range / prior24_high / prior24_low / prior24_range / prior24_range_pos / prior24_width / prior60_high / prior60_low / prior60_range / breakout_up / breakout_down / failed_breakout_up / failed_breakout_down / shift6_atr / bar_range_atr / rel_quote_activity / utc_hour / path_eff_24 / path_eff_60` | 6 / 12 / 24 / 60（均网格内） | numpy/pandas 向量化（K1）；**v0.9 补 prior60_***（Donchian @60）+ `path_eff_60`（Efficiency Ratio @60）；**2026-11-12 补 prior12_***（Donchian @12，用户裁决） |

**v0.8 新增标准指标族（K8 网格 + 参数面纪律）**：上表 NATR / MACD /
ROC / STOCH / BBANDS / ADX 族 / CCI / WILLR / MFI / CMO / OBV /
回归斜率 / KAMA 共 **13 族**为本次纳入（2026-11-07 用户批准"推荐
范围"；外部建议清单的**参数一律不采用**，全部重排到 K8 网格）。
参数面纪律（呼应 K8 防过拟合动机）：
- **MACD 用精选三元组而非全网格展开**——fast/slow/signal 三者相互
  约束，全网格 `5×5×5` 会引入大量无意义组合（fast>slow、signal>slow
  等），只保留 3 个语义合理的网格内三元组；
- **趋势强度/动量/震荡族（ADX/CCI/WILLR/MFI/CMO）只取 24、60 两点**，
  不是 5 点全开——这些是"尺度选择"而非"关键信号点"，多开只是放大
  参数面；
- **BBANDS 用 %B + 带宽，不用原始上下轨**（原始轨含价格量纲，跨标
  的不可比；%B 与带宽无量纲、跨标的可比，符合"通用规则"）；
- **OBV 用斜率/变化率，不用绝对累计值**（绝对值量纲随标的成交量
  漂移，不可比）。

**缓做族（有理由，非遗忘；v1.3 移除已落地的 TRIX / AROON / TSI / Vortex / VHF）**：
PPO（MACD 归一化变体，冗余）、ULTOSC / SMI（利基动量变体、边际价值低）、
CORREL / BETA（单标的宇宙无自然基准序列，定义不清）、
HT_*（Hilbert 变换，解释性差易过拟合）、CDL*（61 根 K 线形态，稀疏二
值、单独统计显著性弱，需先做统计预筛再谈纳入）、
Keltner（= EMA±2×ATR，BBANDS 已覆盖"均值±n 波动带"）、
Choppiness（= 100·LOG(SUM(TR)/MAXHIGH−MINLOW)，是 ATR+Donchian 组合
变换、非独立信号）、QQE / RSX / Squeeze / Schaff / Ichimoku /
Heikin Ashi / Inside Bar / Williams Fractal（需自研或参数面爆炸）、
CMF / EFI / PVT（量价/方向比，与 MFI/OBV 信号重叠）。

**v1.3 显式缓做 5 组（用户研究清单的 10 维中，未纳入第一批的组；逐条给被挡原则 + 理由 + 解锁门槛）**：

| 组 | 被挡原则 | 缓做理由 | 解锁门槛（满足则移出本清单 + I13 +1） |
|---|---|---|---|
| **4. Ehlers 周期/滤波族**（Super Smoother / Roofing / Bandpass / Cyber Cycle / Decycler / Fisher·Inverse Fisher / Laguerre RSI / Schaff / Kalman 斜率） | K7 自研复杂度 + K8 参数面 + 可解释性 | ① 绝大多数需**自研**（TA-Lib 无），触发 K7 全套管理纪律（契约卡 + golden test + `self_implemented` 标记 + I13）；② 参数 2–4 个且相互耦合（如 Schaff 的 EMA fast/slow/cycle），全网格展开违反 K8 防过拟合初衷；③ 属周期/滤波变换，日级噪声大、解释性差，用户自己在备注里标注"先少量引入" | 0004 compiler 就绪后，先挑 1–2 个低滞后趋势滤波器（如 Super Smoother / Kalman 斜率）做小范围试点；验证有边际增益再扩 |
| **9. 相对强弱/市场背景（截面）族**（相对 XJO 超额收益 / 滚动 beta·相关性 / 行业相对强弱 / 截面分位 / 市场宽度 / 截面离散度） | **R9 单标的宇宙** | 跨截面特征**天然需要 ≥2 标的同时在场**（rank/百分位/相关性都要"相对宇宙"才有定义域）；R9 当前是单标的宇宙（CORREL/BETA 同被此条挡下）。单标的下硬加 = 造出无定义域的伪信号 | R9 扩展为多标的联合运行（0005/0006 范围）后，截面组才有意义。**注意：用户在研究清单里标注"这组对 LightGBM 帮助最大"——是最高优先级候选，门槛一解锁就应最先纳入** |
| **10. 多周期族**（日线指标的周线版本 / resample 后滞后一根） | **依赖 0004 时序对齐语义** | "把 M30/日线指标投影到 1h bar"必须回答"用上一根还是当前 bar、如何对齐、如何防前视"——这是**时序对齐语义**，属 0004 compiler 责任域，不在 0003 单 bar 特征基座范围。提前塞入 = 把 0004 复杂度下沉到 0003，违反"每层只做一层事" | 0004 compiler 交付时序对齐原语后，多周期作为 0004 之上的组合特征实现 |
| **6. OHLC 波动率估计器**（Parkinson / Garman-Klass / Rogers-Satchell / Yang-Zhang / 半方差 / 短长波动率比） | 信息维度重叠 + 复杂度预算 | 这 5 个都是**无偏波动率估计**，与 ATR/NATR 同属"波动率"维度，1h CFD bar 上与 ATR 相关性高、边际信息量小；一次加 5 个同维无参数列会撑大特征空间、抬升 0004/0005 搜索成本。**注意：用户标注"OHLC 估计比收盘到收盘更高效，是明显的新维度"——此组是我上一轮理由与用户判断冲突最明显的一条，见下文对抗性自检 A5** | 0006 metrics 实测若显示 ATR 归一化在特定方向有偏，再针对性补 1 个（优先 Garman-Klass），而非一次加 5 个 |
| **5b. Connors RSI / 累计 RSI(2)**（偏短线均值回归的动量变体） | **K8 网格违反** | Connors RSI 经典用法 `RSI(RSI(RSI close), 2)` 内层窗口 **2 不在 K8 网格 {6,12,24,60,120}**；用 K8 的 6 做内层则语义已变（≠Connors RSI）且与已有 `rsi_6` 信息维度重叠（仅多套两层 RSI、无新信息）。两头不讨好。**注意：用户标注"Connors RSI 与常规 RSI(14) 信息不同"——冲突点见对抗性自检 A5** | 若未来引入"允许 <6 的均值回归专用窗口"（需单独决策 + 过拟合防护），再评估 |

**v1.3 新增标准指标族（趋势强度/效率，6 族，2026-11-07）**：TRIX（趋势平滑动量，
24/60）、TSI（双 EMA 动量，24_12/60_24 精选）、VHF（波动率效率，24/60）、
Vortex（方向强度 VI+/VI−，24/60）、Aroon（趋势年龄 UP/DOWN，24/60）。理由：
TA-Lib 0.8.2 均有库实现、信息维度互补（非 SMA/EMA/ATR 冗余）、pandas-ta-classic
对照组可机器精度交叉验证（TRIX/VHF/Vortex/plus_di/minus_di/supertrend 实测 <1e-9，
Supertrend 40k 真实 bar 逐点 diff=0）。参数严守 K8 网格。TSI 用 (fast,slow) 精选
二元组（呼应 MACD 精选三元组纪律），不全网格展开。**触发 I13**：特征集 +14 列 →
**FEATURE_VERSION +1（3→4）**。

**v0.9 新增标准指标族（P0 缺口补全，8 项，2026-11-07）**：DEMA（6/24/60）、
TEMA（6/24/60）、HMA（24/60）、MOM（6/24/60）、StdDev（24/60）、
Z-Score（24/60，`(close−SMA)/STDDEV` 无量纲标准化）、Donchian @60
（`prior60_high/low/range`，v0.8 已有 prior24_*）、Efficiency Ratio @60
（`path_eff_60`，v0.8 已有 `path_eff_24`）。理由：P0 是"第一批基础
指标"的覆盖要求，这 8 项是 v0.8 尚未覆盖的真缺口且 TA-Lib 0.8.2 均有
库实现（DEMA/TEMA/HMA/MOM/STDDEV 直接可用，Z-Score 由 SMA+STDDEV
派生，Donchian@60 / path_eff_60 复用已有向量化逻辑换窗口）。参数仍
严守 K8 网格。**注意**：v0.8 曾把 STDDEV 列缓做（"ATR+BBANDS 已覆盖
波动"），v0.9 撤销该缓做——STDDEV 与 Z-Score 的"价格围绕均值的离散/
位置"信号维度与 ATR（TR 基准）/BBANDS（%B 相对位置）不完全重叠，
补上以完成 P0 覆盖；相应地从缓做清单移除 STDDEV。**触发 I13**：
特征集再变更 → **FEATURE_VERSION 再 +1**（v0.8 已 +1，累计 +2）。

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
> `rel_quote_activity` / v0.8 新增：`natr_*` / `bband_pctb_*` / `bband_bw_*` /
> `lrslope_*` / `mfi_*` / v0.9 新增：`zscore_*`）显式定义分母为 0 / 接近 0
> 的兜底规则（`mfi_*` 的钱流比、`bband_pctb_*`/`bband_bw_*` 的带宽差、
> `zscore_*` 的滚动标准差，遇 N 根全平价 bar → 分母 0，同属"已定义零
> 分母"合法 NULL 来源）
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
| `test_grid_only_windows` | **v0.9 扩范围**：注册表**所有**窗口参数（SMA/EMA/ATR/NATR/RSI/ROC/STOCH/BBANDS/ADX 族/CCI/WILLR/MFI/CMO/LRSLOPE/KAMA/obv_slope/MACD 三元组三参/DEMA/TEMA/HMA/MOM/STDDEV/Z-Score/prior60/path_eff_60）∈ {6,12,24,60,120}，无 14/15/20/50/100 等网格外值（K8 防回归） |
| `test_macd_triplets_known` | MACD 三组精选三元组 (6,12,6)/(6,24,6)/(12,60,12) 的 `line/signal/hist` 手工 golden；且满足 `line − signal == hist`（`talib.MACD`） |
| `test_roc_stoch_known` | ROC（24）与 STOCH（%K/%D，fastk=6/slowd=6）手工 golden；STOCH %K ∈ [0,100]（`talib.ROC` / `talib.STOCH`） |
| `test_bbands_pctb_bw_known` | BBANDS（窗口 24，std=2）：%B 手工 golden + 带宽 `(upper−lower)/middle ≥ 0`；**不注册原始上下轨**（无量纲纪律）（`talib.BBANDS`） |
| `test_trend_momentum_family_known` | ADX/PLUS_DI/MINUS_DI（24/60）∈ [0,100]；CCI(24/60) 有限、WILLR(24/60) ∈ [−100,0]、CMO(24/60) ∈ [−100,100]（`talib.ADX/PLUS_DI/MINUS_DI/CCI/WILLR/CMO`） |
| `test_volume_flow_known` | MFI(24/60) ∈ [0,100]；OBV 为累计量、`obv_slope_24` = 其 24-bar `LINEARREG_SLOPE`；KAMA(24) ∈ [low, high] 域；LRSLOPE(24/60) 有限（`talib.MFI/OBV/LINEARREG_SLOPE/KAMA`） |
| `test_natr_consistency` | `natr_W` == `atr_W / close`（逐点 < 1e-12），即 NATR 是 ATR 的 close 归一化，非独立指标 |
| `test_dema_tema_hma_known` | DEMA/TEMA/HMA（窗口 24）手工 golden；DEMA ∈ [low, high] 域、HMA 比 SMA 滞后更低（`talib.DEMA/TEMA/HMA`） |
| `test_mom_stddev_zscore_known` | MOM(24) == `close − close.shift(24)`（逐点 < 1e-12）；STDDEV(24) ≥ 0；Z-Score(24) == `(close − SMA(close,24)) / STDDEV(close,24)`，无量纲、均值≈0；全平价输入 → zscore 按 D4 兜底 NULL（`talib.MOM/STDDEV/SMA`） |
| `test_prior60_path_eff60_known` | `prior60_high/low/range` 手工 golden（`shift(1)` 后开 60 根窗，排当前 bar，同 prior24 口径）；`path_eff_60` == `|close−open60| / sum(|Δclose|, 60)`，分母 0 → NULL（Donchian@60 / Efficiency Ratio@60） |
| `test_psar_bull_bear_flags` | PSAR 方向标志与翻转 bar 对齐 |
| `test_supertrend_line_and_flags` | `talib.SUPERTREND` 线 + bull/bear 标志一致性 |
| `test_supertrend_parity_vs_reference` | `talib.SUPERTREND` 与 moneta/nova 自研参考实现逐 bar 对照（line/direction），偏差 < 1e-12（K1 双库 parity 固化成回归，防 TA-Lib 换版本悄悄改语义） |
| `test_warmup_null_semantics` | 连续无缺失输入：NULL **仅** warm-up 前缀；warm-up 后出现任何 NULL/NaN = 断言失败（F2 v0.7，D3）；**例外**：派生特征零分母（如 `prior24_range_pos` 全平价 24 根）按 D4 兜底规则产出 NULL/0，属合法（单独断言，不混入前缀规则） |
| `test_no_future_reference` | 截断数据末端 N 行 → 前缀特征值不变（I1 因果性，最硬的一条） |
| `test_deterministic_rerun` | 同输入、**同环境**重跑 → 特征值逐位一致（F4 严格层） |
| `test_wide_table_self_sufficient` | 宽表含全部 OHLCV 列，单文件可独立查询（F3/K2） |
| `test_feature_version_in_metadata` | 版本标识（FEATURE_VERSION/参数 sha256/数值栈版本）变 → Parquet 元数据里的版本串变（**非目录层级**，D1） |
| `test_output_single_file_no_snapshot_dir` | 输出为 `features/ohlcv_<layer>/<instrument>.parquet` 单文件（`<layer>` = `5m`/`1h`），**无** `<snapshot_id>` 子目录；重跑恒覆盖不堆积（D1） |
| `test_per_instrument_streaming` | 数据流按标的逐个循环（每标量取-算-写-释放的静态流式）：断言单标量工作集恰好为 1 个标的的行数（`built["n"]`）＋ 134 特征列——**非**全量 21 标量同驻（D5）。注：这是**结构性**断言（工作集按标量分片），**非内存门禁**（不测峰值 MB；批次1 M5 拒绝新增 flaky 内存断言） |
| `test_f4_same_env_bitwise_cross_env_allclose` | 同环境重跑逐位一致（F4 严格层）；文档化"跨平台 allclose(1e-12)"为可维护上限（F4/D6） |
| `test_universal_21_instruments` | 21 标的同特征同参数、算法逐点一致（K5） |
| `test_feature_count_matches_r31` | 宽表列集 == R3.1 清单（F1 防漂移） |
| `test_gate1_truncation_zero_redraw` | 截断数据重算 vs 全量前缀：`max\|V_trunc − V_full[:k]\| < 1e-12`（moneta Gate 1，I1 最硬形式） |
| `test_gate3_bounds_rsi_atr` | RSI ∈ [0,100]、ATR ≥ 0、PSAR/Supertrend 线 ∈ [low, high] 域（moneta Gate 3） |
| `test_gate4_zero_amplitude_no_crash` | 平价 bar / 零振幅 / 零 volume 注入 → 无 Inf / NaN 泄漏 / 崩溃（moneta Gate 4） |
| `test_atr_normalization_basis_atr24` | 所有 ATR 归一化特征分母 == `atr_24`（K6，防 nova 混用反例） |
| `test_supertrend_path_dependent_from_head` | 从数据头起算；中途起算结果可不同（路径依赖显式接受，warm-up NULL 保留，K4） |
| `test_supertrend_registry_params` | Supertrend（库实现）管理纪律：ATR 窗口取网格点、multiplier 显式入注册表（非硬编码于函数体）+ golden 值与 moneta/nova 参考实现逐点偏差 < 1e-12（K7 的库实现等价纪律，非"自研四项管理"——后者是未触发条件护栏） |
| `test_heikin_asi_known_values` | **v1.1**：Heikin Ashi 递归变换 golden test——独立纯 Python 教科书参考 vs shipped，从 bar 32 起逐点 < 1e-9（seed 依赖 ~16 bar 后收敛）；不变式 `ha_h ≥ ha_c ≥ ha_l` 全程成立（K7） |
| `test_heikin_asi_k7_management` | **v1.1**：K7 管理纪律——`self_implemented=True` 标记 + `window_params=()`（递归非窗口，K8 N/A）+ `warmup_bars ≥ 16` 三项断言 |
| `test_crosscheck_all_mapped`（tulipy） | **v1.2**（v1.3 降为次级锚点）：K1b 跨库对照——tulipy（C 后端，独立实现，2019-04 后未更新）vs 我们的 TA-Lib 后端，对 MAP 内每个特征交叉验证。`exact` 组断言 tail-reldiff < 1e-6；`definitional` 组只断言有限；`no_lib` 组（plus_di/minus_di/lrslope/supertrend/ha_o）文档化跳过。**尾部对齐**（tulipy 裁剪 warm-up 前缀返回短数组，与 TA-Lib 保留 NaN 前缀相反）。tulipy 缺失时 `importorskip` 自动跳过 |
| `test_crosscheck_skips_unknown_features`（tulipy） | **v1.2**：K1b 对照组健壮性——被 0004 重命名出注册表的映射特征被干净跳过（非 KeyError），未映射特征静默忽略 |
| `test_v13_family_known_values_and_invariants` | **v1.3**：TRIX 无量纲比率/零平动量趋零、TSI∈[-100,100]、VHF∈[0,1]、Vortex∈[0,100]、Aroon∈[0,100]、各特征 warmup 与 K8 网格（24/60 或 fast/slow 二元组） |
| `test_v13_family_registry_params` | **v1.3**：14 个新特征的 `indicator`/`window_params`/`warmup_bars` 符合 K8；Aroon UP/DOWN window 为 n 本身 |

## 5b. 自检与对抗性自检（v1.3，2026-11-08）

### 自检（脚本级，全部通过）
| 检查项 | 结果 |
|---|---|
| 测试套件 | **104 passed**（0002 的 58 + 0003 的 46 含真实数据 E2E + ptc 主对照 2），pyflakes 干净 |
| K8 网格 | 14 个新特征 `window_params` 全部 ∈ {6,12,24,60,120} ✓ |
| I13 | FEATURE_VERSION 3→4 ✓ |
| K7 | 14 个新特征全部 `self_implemented=False`（TA-Lib 背书，非自研）✓ |
| D4 平价序列 | 6 族平价序列尾部 finite、无 Inf/NaN 泄漏 ✓ |
| 因果性（无 lookahead） | 尾部扰动（bar≥150）不影响前值（bar 24–148）——trix/tsi/vhf/vortex/aroon 全过 ✓ |
| vortex p/m 拆分 | `vortex_p`=[0]=VI+、`vortex_m`=[1]=VI−，与 TA-Lib VORTEX 返回序一致 ✓ |
| 真实数据 | SPX500_USD 1h 134/134 特征全 present，新 6 族值合理（trix_24=-0.025、vhf_24=0.66、aroon_up_24=91.7）✓ |

### 对抗性自检（文档级，2026-11-08 补做——此前 v1.3 只做脚本级，本轮补文档级）
逐条 接受/挂起/拒绝。

| # | 发现 | 类别 | 处置 |
|---|---|---|---|
| **A1** | **文档缺口**：上一轮口头给出的 5 组缓做理由（Ehlers/截面/多周期/OHLC 波动率/Connors）在 0003 + requirements 中英 4 处**全部未落**（grep 全 0）——只存在于对话，未进文档 | 🔴 已修 | **接受并已修**：本轮在 0003 §3.4 新增"v1.3 显式缓做 5 组"表（组/被挡原则/理由/解锁门槛）+ requirements R3.1 缓做清单加指针，中英成对 |
| **A2** | **TSI ptc 映射**：`tsi_24_12`/`tsi_60_24` 映射到 ptc `TSI_f_s_13`（ptc 硬编码 signal=13），与我们的 (fast,slow) 签名不同 → 已正确标 `definitional`，非 bug | 🟢 无风险 | **接受（现状正确）**：签名差异已在 MAP 注释 + definitional 组标注 |
| **A3** | **Aroon 命名互换**：ptc `AROONU`=我们的 AROON_DOWN。风险点=策略代码若误信 ptc 语义会把 up/down 读反 | 🟢 无风险（shipped 正确） | **接受（现状正确）**：shipped `aroon_up_*`=TA-Lib `AROON_UP`（正确），互换只存在于 cross-check 映射侧并已注释；**建议**在 0004 消费方首次引用 aroon 时补一条"以 TA-Lib 语义为准"的提醒 |
| **A4** | **`test_crosscheck_ptc_covers_tulipy_gaps` 覆盖范围弱**：只断言 3 个 gap（plus_di/minus_di/supertrend），**未覆盖 lrslope/ha_o**（ptc 也没有，故如实留在 no_lib）——断言名"covers tulipy gaps"易被误读为"覆盖全部 no_lib" | 🟡 表述 | **挂起**：断言语义正确（ptc 确实只补齐这 3 个），但**建议在测试 docstring 里明确"仅覆盖 ptc 有能力补齐的 3 个，lrslope/ha_o 两库皆无"**，避免误读。不改断言（改弱了会失去防护价值） |
| **A5** | **缓做理由与用户研究清单 3 处正面冲突**：① OHLC 波动率（用户："明显的新维度"）我按"与 ATR 重叠"缓做；② Connors RSI（用户："与常规 RSI(14) 信息不同"）我按"K8 违反"缓做；③ 截面组（用户："对 LightGBM 帮助最大"）我按"R9 单标的"缓做 | 🟠 判断冲突 | **已裁决（用户 2026-11-08）：三条全部维持缓做**。用户接受三条硬约束（ATR 重叠 / K8 网格 / R9 单标的）作为暂缓理由，不放宽约束、不引入子 6 窗口类、不扩多标的。§3.4 缓做 5 组表的"解锁门槛"保持不变（OHLC 波动率等 0006 实测偏置后再补 1 个、Connors 等"子 6 均值回归窗口"类独立决策、截面等 R9 扩多标的时）。本项**关闭**，0003 无遗留待决 |
| **A6** | **vortex_m 语义**：`vortex_p`/`vortex_m` 命名指 VI+/VI−（方向强度），与"m"字面易被误读为 minus-MA | 🟢 无风险 | **接受（现状正确）**：命名沿用 TA-Lib VORTEX 的 VI+/VI− 惯例，已在 §3.4 表注明"方向强度 VI+/VI−" |
| `test_crosscheck_all_mapped`（ptc） | **v1.3**：**主对照组**——pandas-ta-classic（活跃 2026-10，`import pandas_ta_classic`）vs 我们的 TA-Lib 后端。`exact` 组（SMA/HMA/KAMA/RSI/ATR/NATR/CCI/WILLR/MFI/STDDEV/DEMA/TEMA/HMA/ADX/plus_di/minus_di/TRIX/VHF/Vortex/…）断言 full-length-reldiff < 1e-7（同长、仅差浮点噪声）；`definitional` 组（EMA 种子/×100/BBP 0.5 偏移/Aroon 上下命名互换/STOCH slowing/MACD/Supertrend 路径依赖）断言有限或 < 1e-3；`no_lib` 组（lrslope/ha_o/结构特征）文档化跳过。ptc 缺失时 `importorskip` 自动跳过 |
| `test_crosscheck_ptc_covers_tulipy_gaps` | **v1.3**：K1b 主从关系——tulipy `no_lib`（plus_di/minus_di/supertrend）在 ptc 中被覆盖为 exact/definitional（不泄漏 no_lib），证明 ptc 是更强对照组 |

## 5c. 外部对抗性 review 处置（批次 1，2026-11-08）

> 来源：`docs/reviews/对抗性review-2026-11-08-批次1.md`（外部 AI，10 条：H1–H4 / M1–M6）。
> 本窗对**每一条**都对照实际代码核验：8 条抽查全部为真、零幻觉（最强一份 review）。
> 处置按用户指示「接受 / 挂起 / 拒绝」三级：**接受 7 / 挂起 1 / 拒绝 0（M5 拆分：拒绝加内存测试 + 接受改文档）**。

| # | 发现 | 级别 | 处置 | 落地 |
|---|------|------|------|------|
| **H2** | 文档承诺 `compute(mid_o,…,*extra) → array \| {col:array}`，实现是 `compute(ctx, spec) → (n,) ndarray` | High | **接受**（文档错，非代码错） | §3.1 契约段已按真实签名重写（v1.4 修正 H2），中英成对 |
| **M2** | `load_from` 逐条复制**漏 `self_implemented`** → HA 的 K7 标记在真实 CLI 用的 registry 里静默丢失 | Med | **接受**（真 bug） | `lyra/features.py` `load_from` 补 `self_implemented=spec.self_implemented`；新测试 `test_heikin_asi_marker_survives_load_from` |
| **M1** | `spec.params` 是可变 `dict`（`FeatureSpec` 虽 frozen，但 dict 值仍可原地改） | Med | **接受** | `registry.register` 存 `MappingProxyType`（原地改抛 TypeError）；新测试 `test_params_are_read_only` |
| **M4** | `Catalog.views()` 白名单只含 `_LAYERS`，`upsert_feature_views` 建的 `features_5m/1h` 从不列出——契约不一致 | Med | **接受** | `catalog.views()` 纳入 `_FEATURE_VIEWS`；新测试 `test_catalog_views_lists_feature_views` |
| **M6** | HLD §8 状态仍写「v0.1 骨架」；§2.2/§3 用 `features/5m`、`features/60m` 路径 | Med | **接受**（文档错） | HLD 状态改「✅ 核心已实现（v1.3…）」；路径改真实 `features/ohlcv_5m`、`features/ohlcv_1h`，中英成对 |
| **M5** | `test_per_instrument_streaming` 只断言行/列，无峰值内存门禁 | Med | **拆分**：加内存测试**拒绝**（不可靠、非本层职责）＋ 文档表述**接受** | §5 D5/内存措辞收窄为「每标量取-算-写-释放（静态流式，非内存门禁）」，见 §5 说明；不新增 flaky 内存断言 |
| **H1** | `feature_path` 用 `f"{instrument}.parquet"`，无路径字符校验（路径穿越面） | High→降 Med | **挂起** | 数据受控（OCI/本地受控目录），非当前攻击面；指向 **0004 消费层 / 0007 push 层**统一做输入校验与清单原子性（见下 H3/H4 同批） |
| **H3** | `feature_version_string` 只 hash name/params/warmup，**不读 alpha 版本标签**、不含 alpha 内容哈希 | High | **挂起** | alpha 版本归属已由 §3.1「alpha 特征语义变更由其模块 docstring 版本标签承担」界定；把 alpha 内容纳入版本串属 **0007（OCI push 版本/清单）** 的完整 provenance 边界，需与 0007 同批定稿，避免本批半实现 |
| **H4** | `run_features` 逐标量直接写最终路径，无 staging/manifest——部分失败留下混合版本集 | High | **挂起** | 原子发布/清单是 **0007 push 层**（多机复用前必须原子）与 **0004 消费层**（Catalog 可见性）的联合职责；单写者本地场景当前可重算恢复（0002 A1 派生层规则），留待 0007/0004 边界一并落地 |
| **M3** | 版本串不含 timeframe（5m/1h 串相同） | Med | **拒绝**（无 bug） | timeframe 已由各标量文件路径（`ohlcv_5m/` vs `ohlcv_1h/`）+ `input_minutes` 元数据区分；同一 registry 对 5m/1h 复用是**设计意图**（K5 同算法跨周期），非缺陷 |

**小结**：本批落地 5 项代码/文档修复（H2/M2/M1/M4/M6）＋ M5 文档收窄，新增 3 测试（104→**107**）；H1/H3/H4 三条「跨边界」发现**挂起**，显式归属 0007/0004，避免半实现。M5 拆分（拒绝内存测试＋接受文档）、M3 拒绝（设计意图）。**A5（3 处缓做理由 vs 用户研究清单）已由用户裁决（2026-11-08）：三条全部维持缓做**（接受 ATR 重叠 / K8 网格 / R9 单标的三条硬约束，不放宽、不扩多标的）——见 §5b A5 行，0003 至此**无遗留待决项**，可签收。

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
| 2026-11-07 | 0.8 | **扩充标准指标集（用户批准"推荐范围"；外部建议清单的 5/10/14/20 等参数一律不采用，全部重排到 K8 网格 {6,12,24,60,120}）**：§3.4 新增 **13 族**标准指标——NATR（`atr/close`）、MACD（**精选三元组** 6_12_6/6_24_6/12_60_12，非全网格展开）、ROC、STOCH（%K/%D）、BBANDS（**%B+带宽**，不用原始上下轨）、ADX/PLUS_DI/MINUS_DI（趋势强度族，仅 24/60）、CCI、WILLR、MFI、CMO（均仅 24/60）、OBV（**斜率**非绝对值）、LINEARREG_SLOPE（归一化斜率）、KAMA（自适应均线）。参数面纪律：MACD 精选三元组、趋势强度/动量/震荡族只取 2 点、BBANDS/OBV 取无量纲形态（呼应 K8 防过拟合动机）。**缓做族**（有理由）：PPO/TRIX/ULTOSC/AROON/STDDEV（冗余或利基）、CORREL/BETA（单标的宇宙无基准）、HT_*/CDL*（过拟合/需先预筛）。D4 门禁补 5 个新除法特征（natr_*/bband_pctb_*/bband_bw_*/lrslope_*/mfi_*）；`test_grid_only_windows` 扩范围覆盖全部新族；**+6 测试**（MACD/ROC+STOCH/BBANDS/趋势动量族/量流族/NATR 一致性）。**触发 I13**：特征集变更 → **FEATURE_VERSION +1**。同步 R3.1（requirements 中英权威清单）。测试 28→**34**（中英一致） |
| 2026-11-07 | 0.9 | **补全 P0 基础指标缺口（用户确认；外部 P0/P1/P2 清单中 P0 缺口的 8 项落地，参数全按 K8 网格）**：§3.4 新增 6 族标准指标——DEMA（6/24/60）、TEMA（6/24/60）、HMA（24/60）、MOM（6/24/60）、StdDev（24/60）、Z-Score（24/60，`(close−SMA)/STDDEV` 无量纲标准化）；结构族补 **Donchian @60**（`prior60_high/low/range`，同 prior24 的 `shift(1)` 排当前 bar 口径）+ **Efficiency Ratio @60**（`path_eff_60`）。**撤销 v0.8 对 STDDEV 的缓做**（用户拍板：STDDEV 与 Z-Score 的"价格围绕均值的离散/位置"维度与 ATR（TR 基准）/BBANDS（%B 相对位置）不完全重叠，P0 要求覆盖）；缓做清单同步增补：Keltner（=EMA±2×ATR，BBANDS 覆盖）、Choppiness（ATR+Donchian 组合变换）、Relative Volume/VWMA（rel_quote_activity 覆盖）、P1 全族（AROON/TRIX/CMF/EFI/PVT/SMI/TSI/VHF/QQE/RSX/Ichimoku/HeikinAshi/InsideBar/Fractal/Squeeze/Schaff——参数面过大或需自研，留第二批待 0003 基础版跑通后评估）。D4 门禁补 `zscore_*`（第 6 个新除法特征，N 根全平价 → 滚动标准差 0）；`test_grid_only_windows` 扩范围；**+3 测试**（dema_tema_hma / mom_stddev_zscore / prior60_path_eff60）。**触发 I13**：特征集再变更 → **FEATURE_VERSION 再 +1**（v0.8 已 +1，累计 +2）。同步 R3.1（requirements v0.12 中英）。测试 34→**37**（中英一致） |
| 2026-11-07 | 1.0 | **0003 实施落地（用户批准"可以实现 0003 的内容了"）**：`lyra/registry.py`（K3 Registry/FeatureSpec，`window_params` 与 `params` 分离使 K8 守卫不误伤 nbdev/multiplier）+ `lyra/indicators.py`（TA-Lib 纯 NumPy 边界 + moneta/nova Supertrend golden 参考 + zscore）+ `lyra/features.py`（`build_registry()` 116 特征、`compute_features`、`load_from` alpha（D7 fail-fast + I16 core 不变）、`run_features` D5 per-instrument 流水线、Parquet 元数据版本）全部落地。**实施期据实修正（均不改特征清单/参数，不触发 I13）**：① NATR 实现为 `atr/close`（**非** `talib.NATR`——后者 ×100，违背 §3.4 与 `test_natr_consistency` 的无量纲契约）；② `rel_quote_activity` 实现为 `volume/SMA(volume,24)`（无量纲，与 nova 实证公式一致，取代早期讨论稿的 `×1e9` 变体）；③ **warm-up 前缀按实测精确化**（MACD = slow+fast−2、STOCH = fastk+slowd−2、DEMA/TEMA 保持安全上界、HMA = n+5、`shift6_atr` = ATR_NORM=24、`rsi_divergence` = 48）——`warmup_bars` 是 F2 断言的安全下界，取实测最大前缀。④ 输出路径 `data/features/ohlcv_5m|1h/<instrument>.parquet`（对齐 0002 聚合层命名 `<minutes>m`，目录名用层名而非分钟数）。**新增工程件**：`lyra features` CLI（恒重算恒覆盖，`--minutes 5|60` / `--instrument` / `--alpha-dir`）、Catalog `features_5m/1h` 视图（D1，glob `features/ohlcv_*/\*.parquet`）、`pyproject.toml` 加 `TA-Lib>=0.8.2` 依赖。**37 项文档测试全部实现并通过**（`tests/test_registry.py` / `test_indicators.py` / `test_features.py`，另 +1 真实数据 E2E），0002 套件 58 项仍全绿（合计 **96**）。**状态：提案 → 已实施**；`test_real_data_one_instrument`（SPX500_USD 1h，40435 行，124 列）实测通过。 |
| 2026-11-07 | 1.1 | **新增 Heikin Ashi 族（用户指令"如果可以把这个也加进去"；TA-Lib 无此指标 → 触发 K7 自研路径）**：§3.4 表新增 `ha_o / ha_h / ha_l / ha_c` 4 列（递归变换，无窗口参数 → K8 网格 N/A；warmup_bars=16 为递归收敛安全下界，seed 依赖 ~16 bar 后 < 1e-9）；**K7 管理纪律全部适用**：参数显式入注册表（`self_implemented: True` 标记，本次实施中把该标记落到 `FeatureSpec`/`Registry.register` 的显式字段上，0003 v0.6 K7 降级为条件护栏后首次实际触发）+ 契约卡（递归定义 + seed 规则 + 收敛界）+ golden test `test_heikin_asi_known_values`（独立纯 Python 教科书参考 vs shipped，从 bar 32 起逐点 < 1e-9）+ `test_heikin_asi_k7_management`（self_implemented=True / window_params=() / warmup_bars>=16 三项断言）。**触发 I13**：特征集变更（+4 列）→ **FEATURE_VERSION +1（2→3）**。测试 38→**40**（中英一致），0002 的 58 项仍全绿（**合计 98**）。缓做清单的 P1 族 HeikinAshi 项移除（已落地，非遗忘） |
| 2026-11-07 | 1.2 | **引入 tulipy 跨库对照组（K1b，用户拍板"装上对照、留着以后用"）**：实测选型（隔离 venv，py3.12 + numpy 2.5.4 + 无 pandas 栈）→ 采用 **tulipy**（C 后端、**免 pandas**、100+ 指标、覆盖面 > 手写参考，以后加 P1/P2 可直接复用），作为**可选依赖** `lyra[control]`（`pyproject.toml` 新增 `[project.optional-dependencies] control = ["tulipy"]`，**不进核心依赖**，R10 保持 ≤15 核心包）；**排除** Finta（PyPI 名 `fintech` 被无关 LicenseManager 抢注，装不到真身 + 已归档）、bukosabino/ta + pandas-ta-classic（都强绑 pandas，违背运行时无 pandas 原则）、vectorbt（整套策略研究框架，非指标库，引入即成第二个找策略引擎 = moneta 踩过的外围过度工程坑）。**新增** `tests/crosscheck_tulipy.py`（MAP 映射表 + `run_crosscheck` 尾部对齐）+ `tests/test_crosscheck_tulipy.py`（2 测试，tulipy 缺失时 `importorskip` 自动跳过）。**两组实证差异固化进标签**：`exact`（SMA/HMA/KAMA/RSI/MOM/CCI/WILLR/MFI/STDDEV，无递光滑滑器，断言 < 1e-6）vs `definitional`（EMA/DEMA/TEMA/ATR/ADX/NATR/ROC/CMO/OBV，递归种子/alpha/×100/OBV 种子差异，只断言有限）vs `no_lib`（plus_di/minus_di/lrslope/supertrend/ha_o，文档化跳过）。**关键工程点**：tulipy 裁剪 warm-up 前缀返回短数组（与 TA-Lib 保留 NaN 前缀相反，moneta §2.3 反例 1 的"删前缀"陷阱）→ 对照**必须尾部对齐**。§3.3 新增 K1b 段 + §5 测试表 +2 行。**不改特征集**（FEATURE_VERSION 维持 3）。测试 98→**100**（中英一致），pyflakes 干净 |
| 2026-11-07 | 1.3 | **新增 6 个标准指标族 + pandas-ta-classic 升主对照组（用户拍板"很多都值得现在 implement 掉" + "把 pandas-ta-classic 作为主要 control group"）**：① 用户实测调研——pandas-ta-classic **PyPI 活跃**（`2026-10-28`，276 指标）vs tulipy（`2019-04-11` 后未更新，用户判断对）；pandas 作为**测试对照依赖**引入被接受（用户："pandas 有没有其实无所谓，我没要求极轻量"）→ **K1b 主从调整**：pandas-ta-classic 升**主对照组**（新增 `tests/crosscheck_pandas_ta_classic.py` + `test_crosscheck_pandas_ta_classic.py`，full-length 对照、`plus_di/minus_di/supertrend` 实测 exact/definitional，覆盖 tulipy `no_lib` 缺口）；tulipy 保留为**次级锚点**（C 后端、免 pandas、独立实现，保留价值不变）；`pyproject.toml` `control = ["pandas-ta-classic","tulipy"]`。② **新增 6 族（14 特征）**：TRIX 24/60、TSI 24_12/60_24、VHF 24/60、Vortex 24/60（p/m）、Aroon 24/60（up/down）——均 TA-Lib 0.8.2 有库实现、信息维度互补（非 SMA/EMA/ATR 冗余）、K8 网格、pandas-ta-classic 可机器验证（TRIX/VHF/Vortex 实测 < 1e-12）。③ **特征集 +14 → FEATURE_VERSION 3→4**（I13）。§3.4 表 +6 行、§5 测试表 +4 行。测试 100→**104**（中英一致），pyflakes 干净，SPX500 真实数据 E2E 134/134 特征全出、新 6 族有限值合理。**v1.3 补（2026-11-08）**：① **缓做 5 组完整落表**（§3.4 新增"v1.3 显式缓做 5 组"表：Ehlers 周期/滤波、截面相对强弱、多周期、OHLC 波动率估计器、Connors RSI/累计RSI(2)，各含被挡原则/理由/**解锁门槛**）——此前仅口头给出，未进文档（对抗性自检 A1 发现并修复）；requirements R3.1 缓做清单加指针。② **新增 §5b 自检与对抗性自检**：脚本级 8 项全过 + 文档级 6 条（A1 已修 / A2·A3·A6 接受现状正确 / A4 挂起表述 / **A5 挂起——3 处缓做理由与用户研究清单正面冲突，待用户逐条裁决**） |
| 2026-11-08 | 1.4 | **处置批次1 外部对抗性 review（`docs/reviews/对抗性review-2026-11-08-批次1.md`，10 条 H1–H4/M1–M6；逐条对照代码核验，8/8 抽查为真、零幻觉）——按用户「接受/挂起/拒绝」三级：接受 7 / 挂起 1 / 拒绝 0（M5 拆分）**。新增 **§5c 处置表**（每条含级别/处置/落地，中英成对）。**接受并落地**：① **H2**（High，文档错）——§3.1 API 契约段按真实签名 `compute(ctx, spec) → (n,) ndarray` 重写，删除虚构的 `*extra` 入参与 `{col:array}` 返回、补多列=多 register 说明；② **M2**（真 bug）——`load_from` 逐条复制补 `self_implemented=spec.self_implemented`，新测试 `test_heikin_asi_marker_survives_load_from`（此前 v1.0–v1.3 HA 的 K7 标记在真实 CLI 用的 registry 里静默丢失，全窗自检均漏）；③ **M1**——`registry.register` 存 `MappingProxyType`（原地改抛 TypeError，frozen dataclass 之外补值不可变），新测试 `test_params_are_read_only`；④ **M4**——`catalog.views()` 纳入 `_FEATURE_VIEWS`（`features_5m/1h` 此前建了从不列出，契约不一致），新测试 `test_catalog_views_lists_feature_views`；⑤ **M6**（文档错）——HLD §8 状态「v0.1 骨架」→「✅ 核心已实现（v1.3…）」、路径 `features/5m`·`60m`→`features/ohlcv_5m`·`ohlcv_1h`，中英成对；⑥ **M5 拆分**——拒绝加 flaky 内存测试＋接受文档收窄：§5 `test_per_instrument_streaming` 行删除虚高的「<300MB 量级断言」，改「结构性断言（按标量分片），非内存门禁」，中英成对。**挂起（跨边界，归属 0007/0004）**：⑦ **H1**（路径穿越面，数据受控非当前攻击面）→ 0004/0007 统一输入校验；⑧ **H3**（版本串不含 alpha 内容/版本标签）→ 0007 OCI push provenance 边界同批定稿；⑨ **H4**（无 staging/manifest，部分失败留混合版本）→ 0007 push 原子发布 + 0004 Catalog 可见性联合职责。**拒绝**：⑩ **M3**（版本串无 timeframe）——timeframe 已由文件路径 `ohlcv_5m/`·`ohlcv_1h/` + `input_minutes` 元数据区分，同 registry 跨周期复用是 K5 设计意图，非缺陷。**不在此批**：A5（3 处缓做理由 vs 用户研究清单）仍待用户逐条裁决。**测试 104→107**（+3：M2/M1/M4），pyflakes 干净，ZH=EN 一致 |
| 2026-11-11 | 1.5 | **0008(#99/#100) 三裁决落地——K6 基变更 + 命名对齐 + C 类新增（用户 2026-11-11 最终裁决）**：① **B 类 10 改名**（无 alias 表）：`breakout_up→breakout_up_24`、`breakout_down→breakout_down_24`、`failed_breakout_up→failed_breakout_up_24`、`failed_breakout_down→failed_breakout_down_24`、`prior24_range_pos→range_position_24`、`path_eff_24/60→efficiency_24/60`、`rel_quote_activity→relative_volume_24`、`bar_range_atr→range_atr`、`prior24_width→range_width_atr_24`、`shift6_atr→return_6_atr`；moneta 语料名不映射（随 moneta decom 消解）。② **rsi_14 不新增**；3 个方向文件（momentum_exhaustion/pullback_reentry/session_temporal）改写 rsi_12 重跑（TODO，已随 0008 §3 迁移执行）；根级 `ema_pullback.yaml` 不属 12 方向范围。③ **ATR 归一化基 24→12**（K6 基变更；替代语料 ATR(14)、12 在 K8 网格内、不破格）；`ctx.atr24→atr_norm`；`range_atr`/`range_width_atr_24`/`return_6_atr` 分母随之改为 ATR(12)；C 类 `close_ema60_distance_atr`/`close_sma24_distance_atr` 亦用 ATR(12) 分母（nova 原始 ATR(14)/SMA(TR,14) 不采用）。**C 类 9 新增**：`psar_direction`/`supertrend_direction`（±1 STATE，与 {1,0}×2 的 bullish/bearish 并存）、`psar_flip_up/down`+`supertrend_flip_up/down`（EVENT，nova "dir==±1 & prior==∓1" 契约）、`ema_alignment_6_24`（sign(ema6−ema24) STATE）、`close_ema60_distance_atr`（(close−ema60)/ATR(12) VALUE）、`close_sma24_distance_atr`（(close−sma24)/ATR(12) VALUE）。**注册数 134→143**；**FEATURE_VERSION 4→5**（I13）。测试同步：`test_atr_normalization_basis_atr24→test_atr_normalization_basis_atr12`（含 C 类距离特征 ATR(12) 基核验）、新增 `test_psar_direction_and_flips`/`test_supertrend_direction_and_flips`/`test_ema_alignment_6_24`、`test_gate4_zero_amplitude_no_crash` 更新为改名后特征名、`test_feature_count_matches_r31` 134→143。 |
| 2026-11-12 | 1.6 | **prior12 窗口族注册（用户裁决 2026-11-12）**：用户确认 `range_high_12/low_12`（nova 语料幽灵名，语义=前 12 根滚动最高/最低价，排除当根）"是不错的 feature"，要求正式加入并计算到随时可用。落地：structural 循环 `(24,60)` → `(12,24,60)`，新增 **`prior12_high` / `prior12_low` / `prior12_range`**（与 prior24/prior60 同实现族，12 在 K8 网格内）；**注册数 143→146**；**FEATURE_VERSION 5→6**（I13）；§3.4 结构行同步。测试计数同步（test_features 143→146/151→154、test_registry 143→146、_compiler_fixtures 注释）。`strategies/examples/momentum_breakout/v01.yaml` 由 prior24 改写回 prior12（语义复原：突破前 12-bar 高点）+ `gt/lt` 保持。feature 宽表全量重算（21 标的 × 1h + 5m）。 |
