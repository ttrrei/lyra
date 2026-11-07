# 高层设计决策（High-Level Design）

> **English**: [hld.en.md](./hld.en.md)
>
> 本文是 Lyra 的"骨架"：组件划分、数据流、边界、核心不变量。
> 具体到每个组件的实现细节，见 `docs/decisions/NNNN-*.md`。

## 1. 设计原则（优先级从高到低）

1. **正确性 > 简单 > 性能**。
   正确性指因果性、执行合约、指标口径三件事；
   简单指代码量、依赖数、配置项数；
   性能指单次 run 时长、内存峰值。
   三者冲突时，**正确性不可让**，**简单优先于性能**。
2. **审查性 > 自动化**。
   每个 feature 一个 commit + 一个决策文档 + 一组测试，
   比"AI 一次生成 100 行"更有价值。
3. **alpha 与 core 严格分离**。
   core 开源、alpha 闭源；core 的接口必须**不依赖**任何具体 alpha 实现
   （只依赖"从目录加载 Python 模块"这个通用扩展点）。
4. **数据在 OCI，代码在 git**。
   本地 OCI 镜像（`data/` `strategies/` `runs/`）**默认在仓库外**
   （`~/.lyra/<workspace>/…`，B13），可重建；
   `strategies/examples/` 是 git 里唯一的 strategies 子树（B14）。
5. **少即是多**。
   不引入 moneta 的 OOS ledger / trial_log；
   不引入 nova 的 SHA256 快照目录 / FROZEN_CORE / artifact manifest；
   不引入任何"为将来可能用到"的抽象层。

## 2. 组件划分

```
┌─────────────────────────────────────────────────────────────────┐
│                     lyra CLI (lyra / lyra-doctor)               │
├────────────┬────────────┬──────────────┬────────────────────────┤
│  data      │  features  │  strategy    │  run                   │
│  (拉数据)  │  (算特征)   │  (编策略)    │  (跑回测 + 报告)        │
│            │            │              │                        │
│  - pull    │  - build   │  - validate  │  - execute             │
│  - clean   │  - load    │  - compile   │  - trade engine        │
│  - aggregate│ - extend  │              │  - metrics             │
│  - cache   │  (alpha)   │              │  - report              │
│            │            │              │                        │
├────────────┴────────────┴──────────────┴────────────────────────┤
│  oci client (pull / push / backup / list)  ── PAR URL + 凭证    │
├─────────────────────────────────────────────────────────────────┤
│  local cache (data/ strategies/ runs/)  ── 可重建               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 data 组件

**职责**：
- 从 OCI 拉取 raw CSV / raw Parquet（`lyra pull`）。
- 清洗：去重（`(instrument, time)` 唯一）、缺失分钟标 gap、
  UTC 对齐、Bid/Ask 字段校验。
- 聚合：1m → 5m / 60m（完整桶策略，partial 桶丢弃并计数）。
- 本地缓存：`data/raw_csv/`、`data/raw_parquet/`、
  `data/ohlcv_5m/ohlcv_5m.parquet`、`data/ohlcv_1h/ohlcv_1h.parquet`
  （**单文件外部表**——0002 D4 已废弃目录级 `<snapshot_id>` 层级，
  本 hld §2.1 早期措辞为历史草稿，以 0002 为准）。

**不做**：
- 不在这里算特征（那是 features 组件）。
- 不做 OOS gate / holdout（已废弃）。
- 不做"数据版本晋级"（snapshot id 是单调递增的整数，
  没有"active / reserved / completed"状态机）。

**关键不变量**：
- `data/raw_csv/` 和 `data/raw_parquet/` 内的文件**不可变**
  （SHA256 在 import 时记录；后续只读）。
- 聚合只从清洗后的 1m 起；partial 桶不合成填充。
- 日历 gap 保留为 gap。

### 2.2 features 组件

**职责**：
- 从 OHLCV（0002 聚合层 `ohlcv_5m`/`ohlcv_1h`）算出已注册的标准特征
  （SMA/EMA/RSI/ATR/PSAR/Supertrend/…）。
- 加载 alpha 特征（`lyra.features.load_from(directory)` 扩展点）。
- 发布特征宽表到 `data/features/<minutes>m/<instrument>.parquet`
  （**单文件，无 `<snapshot_id>` 目录层级**——0003 v0.7 对齐 0002 D4
  已废弃的目录级 snapshot 体系；版本入 Parquet 元数据；详见
  0003 §3.1 + §2.3 D1 处置）。

**不做**：
- 不做参数扫描（参数在注册时定死）。
- 不做"特征组合 / 派生特征"（要新特征就注册新的）。
- 不做 feature-vs-feature 的运行时比较（那是 compiler 的事）。

**关键不变量**：
- 每个特征在 `bar_close_time` 时可用（past-only）。
- Warm-up NULL 保留，不任意删（0003 v0.7 F2 收紧：NULL 只允许来自
  warm-up 前缀 ∪ 派生特征已定义零分母）。
- 特征版本标识 = (timeframe, FEATURE_VERSION, 完整参数集 sha256,
  数值栈版本) 的**派生字符串**，写入 **Parquet 元数据**（**非目录
  层级**——0003 v0.7 对齐 0002 D4 废弃的目录级 snapshot 体系；非
  单调递增整数、无分配器）。
- 改 feature 计算 → FEATURE_VERSION +1。

### 2.3 strategy 组件

**职责**：
- 读策略 YAML（从本地 `strategies/` 或 OCI `lyra/strategies/`）。
- `lyra validate`：语法检查 + feature 注册检查 + 参数检查。
- `lyra compile`：YAML → past-only SQL（DuckDB）。

**不做**：
- 不执行 SQL（那是 run 组件）。
- 不支持"策略组合 / 多策略组合"（一个策略 = 一个文件 = 一个
  timeframe）。

**策略演进（用户 + AI 都是作者，见 R12 / oci-alpha-layout §2.3）**：
- `lyra context <dir>`：输出单文件上下文包。
- `lyra new-version --branch`：从父版本派生候选分支。
- `lyra compare --siblings`：兄弟分支 run 摘要并排对比。
- `lyra merge --from <a> --from <b>`：AI 自由交叉（粒度不限）。
- `lyra push-direction` / `lyra push-strategy`：落盘到 OCI。
- 交叉由 AI 全权决定；框架保证 AI 有此能力（context 含完整参数）。

**关键不变量**：
- 编译出的 SQL 必须 past-only（`lag` / 以当前行为结尾的窗口，
  无 `lead`，无跨未来 join）。
- 右值只能是常量或已注册 feature 列；**禁止** feature 算术。
- 时间算子 `held_for` / `within` 要求完整 N 行非 NULL 才判真。

### 2.4 run 组件

**职责**：
- 执行编译出的 SQL（DuckDB）。
- 按 bar 跑 trade state machine（2% stop / next-open / 成本）。
- 按标的、按月汇总（零开仓月保留）。
- 发布 run 报告到 `runs/<name>/<date>/`。

**不做**：
- 不做仓位 / 杠杆 / 保证金 / 账户净值 / CAGR / HWM。
- 不做组合优化 / 资产池晋级。
- 不做 live trading。

**关键不变量**：
- 2% stop 是**触发器**，不是最终净损失上限。
- 同根同时触及止盈/止损 → 亏损方优先。
- 一标的一笔；持仓期间忽略新入场信号。
- 最后一根 bar 上排队的入场 → 作废。
- 数据结束时还持仓 → 在最后一根收盘平仓。

### 2.5 oci client 组件

**职责**：
- `lyra pull`：按 `config.yml` 拉取所需数据集。
- `lyra push`：把 `strategies/` / `runs/` 上传 OCI。
- `lyra backup`：一键同步（pull + push + 冲突检测）。
- `lyra list`：列出 OCI 上的 datasets / strategies / runs。
- 凭证管理：PAR URL 优先；可选 OCI auth（`~/.lyra/credentials`）。

**不做**：
- 不做"OCI 版本管理"（snapshot id 由本地分配，OCI 只存文件）。
- 不做"OCI 权限管理"（那是 OCI 控制台的事）。
- 不做"OCI 多桶路由"（`config.yml` 里一个 bucket 一个 prefix 就够）。

**关键不变量**：
- 凭证不进 git、不进 run 报告。
- push 前必须本地校验（SHA256 + 大小 + 文件清单）。
- push 是**幂等**的（同 snapshot id + 同内容 → 不重复上传）。

## 3. 数据流

```
OCI (raw CSV / Parquet)
        │
        ▼  lyra pull
local data/raw_csv/ + data/raw_parquet/  (不可变, SHA256 校验)
        │
        ▼  lyra clean
local data/bronze/...  (清洗后的 1m, 单文件外部表)
        │
        ▼  lyra aggregate --minutes 5 60
local data/ohlcv_5m/ohlcv_5m.parquet + data/ohlcv_1h/ohlcv_1h.parquet
        │  (单文件外部表 —— 0002 D4 已废弃目录级 <snapshot_id> 层级)
        ▼  lyra features --minutes 5 60
local data/features/5m/<instrument>.parquet + data/features/60m/<instrument>.parquet
        │  (每标的一个 Parquet, 版本入元数据 —— 0003 v0.7)
        ▼
OCI (lyra/data/market/ + lyra/data/features/)  ← 可选 push, 供多机复用
        │
        ▼  lyra run --strategy <yaml>
local runs/<name>/<date>/
   ├── run_meta.json  (strategy, 时间窗, 标的, feature snapshot, git commit)
   ├── trades.csv     (逐笔交易)
   ├── monthly.csv    (逐标的逐月)
   └── report.md      (人类可读)
        │
        ▼  lyra push
OCI (lyra/runs/)
```

## 4. 核心不变量（跨组件）

| # | 不变量 | 来源 |
|---|---|---|
| I1 | 每个 feature 在 `bar_close_time` 时可用 | moneta / nova 一致 |
| I2 | 信号在 closed bar 确认、T+1 open 成交 | moneta / nova 一致 |
| I3 | 2% 强制不利退出（相对实际开仓价） | nova 2026-11-03 确认 |
| I4 | 同根同时触及止盈/止损 → 亏损方优先 | nova 2026-11-03 确认 |
| I5 | 一标的一笔；持仓期间忽略新入场 | moneta / nova 一致 |
| I6 | 零开仓月份保留 | moneta / nova 一致 |
| I7 | 年化分数 = 算术和 ÷ 完整日历年 | moneta / nova 一致 |
| I8 | 参数固定，不做扫描 | nova 2026-11-03 确认 |
| I9 | 右值 = 常量或已注册 feature 列；禁止 feature 算术 | nova 2026-11-03 确认 |
| I10 | 编译 SQL past-only | moneta / nova 一致 |
| I11 | 本地 OCI 镜像（`data/` `strategies/` `runs/` **`alpha/`**）可重建，且**默认在仓库外**（B13） | Lyra 新增 |
| I12 | 凭证不进 git / 不进 run 报告 | Lyra 新增 |
| I13 | 改 feature 计算 → FEATURE_VERSION +1 | moneta / nova 一致 |
| I14 | 改 trade 语义 → 必须更新 I1-I7 表 + 决策文档 | Lyra 新增 |
| I15 | git 里**不**出现 alpha 路径：`alpha/` 全部、`strategies/` 下任何方向文件夹内容、`runs/` 全部 | `0001` 新增 |
| I16 | core 不 import 任何具体 alpha 模块（只 import 通用加载点） | `0001` 新增 |
| I17 | OCI 文件**分两级**：**(a) Immutable**（`data/**`、`runs/**`、`strategies/**/vNN.yaml`、`alpha/features/**`）同 path 同 sha256 幂等，不同 sha256 报错；**(b) Append-only**（`strategies/**/hypothesis.md`、`lessons.md`、`index/*.json`）允许内容向前推进（新 ⊇ 旧），push 校验超集，否则报错（B9 两级规则） | `0001` 新增 |

## 5. 边界（与 moneta / nova 的对比）

| 边界 | moneta | nova | lyra |
|---|---|---|---|
| 策略语言 | YAML | YAML | **YAML**（放宽 feature-vs-feature） |
| 参数 | 可扫描（`run_matrix.py` 3 成本档） | 固定 | **固定** |
| 特征数 | 305/270 列 | ~20 个注册 | **~20 个注册 + alpha 扩展点** |
| OOS gate | 有（`oos_token.py`） | 无 | **无** |
| SHA256 目录 | 无 | 有 | **无** |
| FROZEN_CORE | 无 | 有 | **无** |
| OCI pull | 有（`extract_oci.py`） | 无 | **有**（核心 feature） |
| OCI push | 无 | 无 | **有**（核心 feature） |
| Alpha 边界 | 无 | 无 | **有**（OCI 为 source of truth） |

## 6. 技术选型

| 维度 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12+ | 与 moneta / nova 一致；TA-Lib wheel 可用 |
| 数据引擎 | DuckDB | Parquet 原生支持；past-only SQL 表达力足够 |
| 特征计算 | NumPy / pandas + TA-Lib | 标准；TA-Lib 的 PSAR/Supertrend 是参考实现 |
| 策略表达 | YAML (PyYAML) | 与 moneta / nova 一致 |
| OCI 客户端 | `requests` + PAR URL（默认）；`oci` SDK（可选） | PAR URL 最简单；SDK 用于 push 时避免签名 |
| 测试 | pytest | 与 moneta / nova 一致 |
| 打包 | `pyproject.toml` + `requirements.lock` | 与 nova 一致；lock 文件锁定所有传递依赖 |
| Lint | ruff | 与 nova 一致 |

## 7. 目录结构（目标态）

```
lyra/
├── README.md
├── LICENSE
├── AGENTS.md
├── pyproject.toml
├── requirements.lock
├── .gitignore
├── .github/workflows/checks.yml
├── config/
│   ├── config_example.yml
│   └── config.yml              (gitignored)
├── docs/
│   ├── background.md
│   ├── requirements.md
│   ├── hld.md                  ← 本文
│   ├── open-questions.md
│   ├── decisions/
│   │   ├── TEMPLATE.md
│   │   ├── 0001-repo-and-oci-split.md
│   │   ├── 0002-ohlcv-data-sync.md       (待写)
│   │   ├── 0003-feature-builder.md       (待写)
│   │   ├── 0004-yaml-compiler.md         (待写)
│   │   ├── 0005-trade-engine.md          (待写)
│   │   ├── 0006-metrics-and-runner.md    (待写)
│   │   ├── 0007-oci-push-and-backup.md   (待写)
│   │   ├── 0008-migration-and-regression.md (待写)
│   │   └── 0009-polish.md                (待写)
│   └── proposals/
│       ├── oci-alpha-layout.md
│       └── alpha-boundary.md
├── src/lyra/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── common.py
│   ├── data.py                 ← 对应 R6
│   ├── features.py             ← 对应 R3
│   ├── catalog.py              ← 对应 R3.1
│   ├── indicators.py           ← 标准特征实现（Supertrend 递归等）
│   ├── compiler.py             ← 对应 R2
│   ├── config.py               ← 对应 R7 (config.yml 解析)
│   ├── trades.py               ← 对应 R4
│   ├── metrics.py              ← 对应 R5
│   ├── runner.py               ← 对应 R5
│   ├── oci.py                  ← 对应 R7 (pull/push/backup)
│   └── doctor.py               ← lyra-doctor
├── strategies/
│   └── examples/               ← 开源示例（alpha 全在 OCI）
│       ├── trend_hold.yaml
│       ├── ema_pullback.yaml
│       └── mean_reversion.yaml
├── tests/
│   ├── test_data.py
│   ├── test_features.py
│   ├── test_compiler.py
│   ├── test_trades.py
│   ├── test_metrics.py
│   ├── test_oci.py
│   └── fixtures/
└── scripts/
    ├── check_semantics.py
    └── research_round.py
```

## 8. 推进顺序（按 feature 流）——**唯一事实来源**

> README 和 background 对推进顺序的描述一律以本节为准；
> 任何顺序调整只在本节修改，并在修订记录留痕。

一个 feature = 一个 commit = 一个决策文档 = 一组测试。
推进前**必须**先写决策文档（`docs/decisions/TEMPLATE.md` 模板），
决策文档里要回答：做什么 / 为什么 / 边界 / 不变量 / 测试 / 回滚。

**为什么 0002 先于 0003**：数据同步是 Lyra 的主功能（R7 / HLD §1），
先有数据通道，核心组件才能接真实数据；0003-0006 期间用 fixture 数据
即可自证语义，不阻塞。

| # | Feature | 决策文档 | 状态 |
|---|---|---|---|
| 1 | repo + OCI split | `0001-repo-and-oci-split.md` | ✅ 已写 |
| 2 | OCI pull + clean + aggregate | `0002-ohlcv-data-sync.md` | ✅ 已完成（2026-11-07，真实数据端到端 + 批次1(2026-11-07) 对抗性审查 D1–D6 全修复，v1.1） |
| 3 | Feature builder（标准 + alpha 扩展点） | `0003-feature-builder.md` | ⬜ 进行中（v0.1 骨架，moneta/nova 借鉴扫描回填中） |
| 4 | YAML compiler（含 feature-vs-feature） | `0004-yaml-compiler.md` | ⬜ 待写 |
| 5 | Trade engine（2% stop / next-open / 成本） | `0005-trade-engine.md` | ⬜ 待写 |
| 6 | Metrics + runner | `0006-metrics-and-runner.md` | ⬜ 待写 |
| 7 | OCI push + backup | `0007-oci-push-and-backup.md` | ⬜ 待写 |
| 8 | 332 策略迁移 + 回归 | `0008-migration-and-regression.md` | ⬜ 待写 |
| 9 | Polish（README / CI / config_example） | `0009-polish.md` | ⬜ 待写 |

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿。 |
| 2026-11-05 | 0.2 | §8 标注为**唯一事实来源**，补"为什么 0002 先于 0003"的理由；README / background 改为引用本节。 |
| 2026-11-05 | 0.3 | §2.3 移除"不生成新策略（future campaign）"冲突行，补"策略演进"块（context / new-version / compare / merge / push-direction）对齐 R12 + 版本树 + AI 自由交叉；§7 目录树补 0008/0009（ZH 缺 0008、EN 缺 0009，0007 误用 └──）；**§4 不变量表补齐 I15-I17**（原只列到 I14，但 AGENTS/0001 都引用 I15-I17，hld 作骨架应自洽）。 |
| 2026-11-06 | 0.4 | 批次2 对抗性 review 修复：I17 改**两级**（Immutable/Append-only，L1）；I11 补 `alpha/`（L5）。 |
| 2026-11-07 | 0.5 | **0003 v0.7 对齐**（批次2 红队 D1/D5/D6/D3 接受后的 hld 同步）：① §2.1 市场层缓存路径由历史草稿 `data/market/<m>/<snapshot_id>/` 改为 0002 实际产出的单文件外部表 `ohlcv_5m/ohlcv_5m.parquet` / `ohlcv_1h/ohlcv_1h.parquet`（0002 D4 已废弃目录级 snapshot，hld 早期措辞为草稿，标注以 0002 为准）；② §2.2 features 组件：发布路径改 `data/features/<m>/<instrument>.parquet` 单文件、版本入 Parquet 元数据、关键不变量"snapshot id 单调整数"改"派生字符串入元数据"、Warm-up NULL 收紧对齐 0003 F2；③ §3 数据流图同步（bronze→ohlcv_5m/1h 单文件→features 单文件）。注：§4 L148/155/179 的 **OCI push（0007）snapshot id** 属 0007 未定语义，本轮**不**改（0007 未写，避免越权改 0007 范围），留待 0007 决策时对齐 |
