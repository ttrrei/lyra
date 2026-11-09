# 0006 — 指标 + 运行管线（R5 + 可复现运行 + O17 融资接口收口）

> **English**: [0006-metrics-and-runner.en.md](./0006-metrics-and-runner.en.md)
>
> 本决策文档覆盖 0006 的范围：**R5 指标**（口径已冻结）+ **运行管线**
> （`lyra run`，把 0004 编译出的信号 + 0005 逐 bar 交易引擎组装成可复现的
> 逐标的评测）+ **报告与运行产物** + **可复现性（I5）** + **O17 融资逐笔计数接口收口**
> （R4 交易日合规未收口，见 D6/批次1-H1）。
> 本 feature **不做** R12 交互式工作流（track/context/compare/merge）——它构建
> 在 0006 的运行产物之上，单独成文（见 D1）。

## 元信息

| 字段 | 值 |
|---|---|
| ID | 0006 |
| 标题 | 指标 + 运行管线（`lyra run` + R5 指标 + 报告 + 可复现运行） |
| 状态 | 已实现 |
| Owner | `ttrrei` |
| 创建日期 | 2026-11-08 |
| 相关提案 | `docs/proposals/`（无——本 feature 由 R5 + O17 驱动） |
| 相关需求 | `docs/requirements.md` §R5（指标）、§R6/R7（数据 + 运行产物） |
| 相关 HLD | `docs/hld.md` §1、§6、§8 |
| 相关决策 | 0002（数据合约 / 快照）、0003（特征 + 快照身份 / FEATURE_VERSION）、0004（YAML 编译器 → 信号 SQL）、0005（逐 bar 交易引擎，`trade()`/`simulate()`） |
| 未决项处置 | O17（融资日基准）：本 feature 收口**逐笔计数接口能力**（每笔可单独计日）；**R4/O15 交易日口径合规未收口**，默认自然日为显式已知偏差（H1 挂起，见 D6/未决项）；O-0005-1（融资日基准未决项）相应**部分关闭** |

**修订记录**

| 日期 | 变更 | 触发 |
|---|---|---|
| 2026-11-08 | v1：文档 + 代码初稿 | 0006 落地 |
| 2026-11-08 | v2：**对齐 R5**——代码期对抗性自检发现初稿 D4/I15/B3/H5/§5 引入 Sharpe / profit factor（R5 明确禁止、nova 亦无）。重写 D4/I15/B3/H5/§5 测试表为 R5 冻结集（`avg_bars_held` + 逐月行 + 报告元数据），新增 `test_metrics_forbidden_fields_absent`；代码本就按 R5 实现，仅文档纠偏 | 代码期对抗性自检 H5 |

## 1. 问题

策略条件已被 0004 编译成确定性信号 SQL，已被 0005 在逐 bar 粒度撮合成交易。
但**没有任何东西把它们组装成一个可复现、有指标口径、有报告、有产物
身份的运行**（R5 + I5）。没有它，无法判断任何"方向"是否有效，R12 工作流
无从谈起。0006 补上这个缺失环节：**`lyra run`**。

## 2. 背景

- **nova 的对应实现**：`nova/src/nova/runner.py`（逐标的、信号→交易→
  `summarize`、per-instrument 隔离）+ `nova/src/nova/metrics.py::summarize`
  （`trade_count` / `net_trade_return_sum` / `annualized_trade_return_score` /
  `mean_net_trade_return` / `win_rate` / `yearly_net_trade_return_sum` /
  `monthly_entries` / `every_full_month_has_entry` / `passes_initial_screen`）。
  nova **不计算 Sharpe / profit factor / CAGR / HWM**（与 R5 一致）；nova 是
  **authoritative 移植源**：指标公式照搬，只把信号来源从内置 `entry_long` 列
  换成 0004 编译 SQL 的输出，把 nova 内置撮合换成 0005 的 `simulate()`。
- **lyra 的数据模型**（已就绪）：
  - `lyra build` 产出特征宽表 Parquet（0003），`catalog.Catalog` 注册
    `feature_tables`（view → 路径 → kind）。
  - 0004 `compile_sql(spec)` 产出 `SELECT instrument, time, entry_long,
    entry_short [exit_long, exit_short] FROM <spec.view> ORDER BY instrument, time`；
    `spec` 携带 `stop_loss_pct` / `direction` / `max_holding_bars` / 成本
    （slippage/commission/financing bps）/ `view`。
  - 特征宽表（0003）**含 OHLCV**，故 runner 从同一 view 取 OHLC bar + 信号。
  - 0005 `simulate(plan, bars, *, trading_days=None)`（`bars` 为含 OHLC + 4 个
    布尔信号键的 dict 序列）已逐 bar 撮合，`Trade.net_return` 为净收益字段，
    支持 `trading_days` 覆盖（O15/O17）。
- **R5 指标口径（已冻结，见 requirements §R5）**：见附录 A 的 D4。
- **O17 融资日基准**：0003 D10 已定"per session_day + 日历日"，0005 引擎已支持
  `trading_days` 覆盖；0006 让 runner 按每笔交易的 entry/exit bar 时间逐笔计日（默认
  自然日）——**收口的是逐笔计数接口能力，R4 交易日合规未收口**（见 D6，批次1-H1 纠偏）。
- **用户立场**（延续多轮）：轻量、不过度工程（B6）；0005 已确立"单一可复用
  引擎 + 多方向并行研究"的形态，0006 延续之。

## 3. 方案

### 3.1 做什么

**新增文件**：
- `lyra/metrics.py` —— R5 指标纯函数（`annualized_return` / `win_rate` /
  `expectancy` / `avg_bars_held` / `_monthly_rows` / `compute_metrics`），
  口径见 D4；**不计算 Sharpe / profit factor / CAGR / HWM / Sortino**（R5 明确
  禁止）；对空 / 单笔 / 全亏 / 全赢 / 跨度 0 全部安全（返回 `None`/`0.0`，不抛错）。
- `lyra/runner.py` —— 运行管线：
  1. 解析策略 YAML → `StrategySpec`（复用 0004 `strategy_schema` + `compiler`）。
  2. `sql = compile_sql(spec)`；DuckDB 查询 `spec.view` 得到逐 bar 的
     `instrument/time/OHLC/entry_long/entry_short`。
  3. **逐标的处理**（D3，批次1-M1：非真实 streaming，仅 I16 隔离）：每个 instrument
     在独立 DuckDB 作用域内取 bar+信号，直接作为逐 bar **dict 序列**喂给
     `simulate(plan, bars, trading_days_for=<None 逐笔自然日 | 用户注入的交易日计数器>)`，得 `Trade[]`
     （扁平 `--financing-days` 已移除，0004 C2）。
  4. 逐标的汇总 `compute_metrics`（D4）；**绝不跨标的合成**（I7）。
  5. 写运行产物（D8）+ 报告（D7）+ 可复现性清单（D5）。
- `lyra/cli.py` —— 新增 `lyra run`（+ `lyra report` 复用产物重渲染）子命令。

**修改文件**：
- `lyra/trade_engine.py` —— **不改语义**，仅确认 `simulate(..., trading_days=...)`
  已是 0006 的融资入口（0005 批次3 已实现）。
- `pyproject.toml` —— 无新核心依赖（duckdb / numpy / pyarrow 已在 0003/0004）。

**运行产物布局**（D8，本地镜像，`~/.lyra/<workspace>/runs/` 或仓库 `runs/`，
均 gitignored per repo policy）：
```
runs/<name>/<YYYYMMDD>/<run_id>/      # 批次1-H3：按 run_id 作用域，互不覆盖
  manifest.json      # D5 可复现性清单 + 全部四个产物 SHA256
  signals.parquet    # 逐 bar 信号（instrument,time,side,...）；零行也写出
  trades.parquet     # Trade[]（0005 输出）；零行也写出
  metrics.json       # 逐标的 + summary（D4）；入 manifest 哈希（批次1-M2）
  report.md          # D7 人读报告
```

### 3.2 不做什么（Out of Scope）

- **R12 交互式工作流**（track / context / compare / merge / new-version /
  lessons / hypothesis）——**不在本 feature**，单独成文（0007）。理由：它构建在
  0006 的运行产物之上（比较"两个 run 的 metrics.json"），体量大、需独立对抗性
  自检；且用户明确"轻量、基座一套、多方向并行"，工作流应建立在已验证的运行之上。
- **仓位/杠杆/保证金/账户权益/账户 CAGR**——R9 / I9（交易级研究，不做 sizing）。
- **OCI 推送 runs**（R7 的 push 部分）——本 feature 只写本地镜像；OCI push
  是 R7 独立 feature 的职责（0006 产物可被其消费）。
- **实盘/回测之外的执行**、**多策略并行编排**、**组合级合成**（I7 禁止）。

### 3.3 边界

- **读**：`catalog.duckdb` + 特征宽表 Parquet（`data/`，R6；`lyra build` 已产出）。
- **写**：`runs/<name>/<date>/`（本地镜像，R6/R7/B13；**不写 git**，R8 无副作用）。
- **与 alpha 边界**：0006 **只读** 已注册特征视图（0003 的 alpha 产物），不新增、
  不改 alpha 特征；`FEATURE_VERSION`（0003 D7）作为清单输入参与可复现性。
- **与 moneta/nova 兼容边界**：指标公式与 nova `metrics.py` 逐式一致（可交叉
  验证）；但信号来源（0004 编译 SQL）与引擎（0005 `simulate`）是 lyra 自己的，
  不与 nova 共享运行时。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I1 | 因果性：信号只由 past-only 窗决定（0004 保证，0006 不破坏） | I1 (HLD §4) / 0004 |
| I5 | **可复现**：同一清单（策略+数据+版本+参数+融资计数器身份）→ 同一 `run_id`、**确定性数据产物**字节一致（`signals/trades/report/metrics`）；任一输入变化 → 不同 `run_id`（见 D5）。**范围**：`manifest.json` 的 `generated_at`（wall clock）是**唯一被排除**的字段，不属于逐字节复现承诺——即契约是"确定性产物相同、生成时间戳可变"，并非所有产物含 manifest 逐字节一致（批次1-M4 明示） | I5 (HLD §4) / 本 feature 强化 |
| I7 | **逐标的**：每标的独立报告；**绝不**跨标的合成收益/权益/组合分 | I7 (HLD §4) |
| I8 | 月度机会数 = 实际开仓笔数（含零开仓月，计 0 而非剔除） | I8 (HLD §4) |
| I9 | 交易级研究：无 sizing/杠杆/保证金/账户权益/账户 CAGR | I9 (HLD §4) |
| I10 | 信号在收盘确认、下一可见开盘成交（经 0005 `simulate` 保证） | I10 (HLD §4) / 0005 |
| **I15**（新增） | **指标口径（R5 冻结）**：annualized = Σ净收益 / 日历年（365.25 天）；win_rate = 盈利笔/总笔；expectancy = 均值(net)；avg_bars_held = 平均持有 bar 数；逐月行 =（实际开仓次数 / 净收益和 / 胜率 / 平均持有 bar 数），零开仓月保留为 0。`score` = `annualized`。**禁止** Sharpe / Sortino / profit factor / CAGR / HWM / 组合合成 | 本 feature 新增 / R5 |
| **I16**（新增） | **逐标的隔离**：一次运行内每个 instrument 在独立 DuckDB 作用域 + 独立引擎实例处理；一个标的的失败不得静默吞掉（记入清单并报错），但**不**阻断其余已完成的标的汇总（除非 `--strict`） | 本 feature 新增 / I7 / B6（轻量） |

## 5. 测试

**指标（`lyra/metrics.py`）**：

| 测试 | 场景 |
|---|---|
| `test_metrics_annualized_calendar_years` | 净和 / 日历年；跨度 0 → `None`（不抛错） |
| `test_metrics_win_rate_zero_trades` | 无交易 → `0.0`（不是 NaN/抛错） |
| `test_metrics_expectancy_matches_mean` | expectancy == 均值(net) |
| `test_metrics_avg_bars_held` | 平均持有 bar 数；无交易 → `0.0` |
| `test_metrics_single_trade` | 单笔：win_rate=1 或 0；expectancy=该笔 |
| `test_metrics_all_loss` | 全亏：win_rate=0；annualized 为负 |
| `test_metrics_deterministic_and_score_equals_annualized` | 同一输入两次 `compute_metrics` 逐字段相等；`score == annualized` |
| `test_metrics_monthly_rows_zero_open_months_kept` | 窗口内每个自然月都出现；零开仓月保留为 0（I8） |
| `test_metrics_forbidden_fields_absent` | 结果中**无** sharpe / profit_factor / sortino / CAGR / HWM（R5 禁止） |

**运行管线（`lyra/runner.py`）**：

| 测试 | 场景 |
|---|---|
| `test_run_single_instrument_matches_engine` | 单标的 run 的 trades == 直接 `simulate` 结果（field-for-field，diff=0） |
| `test_run_multi_instrument_isolated` | 3 标的，互不串扰；每标的一个 `metrics.json` 条目；无组合分 |
| `test_run_reproducible_identical_manifest` | 同输入跑两次 → `manifest.json` + `metrics.json` + `trades.parquet` 逐字节/字段一致 |
| `test_run_reproducible_perturbation_fails` | 改策略参数/数据/版本之一 → `run_id` 变化（I5 失败即失败） |
| `test_run_id_covers_consumed_feature_values` | 策略消费的特征值（mid_c）变化 → `run_id` 变化；仅未消费列（volume）变化 → `run_id` 不变（批次1-H2） |
| `test_run_id_covers_trading_counter_behavior` | 两个行为不同的融资计数器 → `run_id` 不同（批次1-H2） |
| `test_run_dir_scoped_by_run_id_no_stale_trades` | 零交易重跑 → 独立 `run_id` 目录、零行 `trades.parquet`、`manifest` 不哈希到他人目录的旧 trades（批次1-H3/M2） |
| `test_run_manifest_hashes_metrics_json` | `metrics.json` 入 `manifest` 哈希且一致（批次1-M2） |
| `test_metrics_zero_open_month_in_middle` | 首尾有交易、中间零开盘月 → 该月全 0 行保留、首尾行正常（批次1-M5） |
| `test_run_monthly_zero_openings_counted` | 含零开仓月的数据 → 月度序列含 0 而非剔除（I8） |
| `test_run_empty_produces_zero_trades` | 无信号 → trades 空、metrics 安全、run 仍产出 manifest（不崩溃） |
| `test_run_manifest_sha256s` | `manifest.json` 内每个产物 SHA256 与文件实际哈希一致 |
| `test_run_financing_wired` | 开仓跨日的长头 → 融资按逐笔 entry/exit 计（`simulate` 默认 `trading_days=None` → **自然日**，H1 已知偏差）；短持 → 0；接口接受 `trading_days_for` 计数器（扁平 `--financing-days` 已移除，0004 C2） |
| `test_run_report_fields` | `report.md`/`metrics.json` 含 R5 全部指标字段 + 运行元信息（无 sizing/$ PnL） |
| `test_run_instrument_failure_isolated` | 一个标的数据异常 → 记入清单并可见；其余标的汇总不受影响（I16） |

**跨实现验证**：指标函数与 nova `lyra/metrics.py` 同输入交叉比对（口径一致）。

## 6. 回滚

- **代码层**：revert 0006 的实现 commit（`lyra/metrics.py`、`lyra/runner.py`、
  `lyra/cli.py` 的 `run`/`report`、相关测试）即可回到 0005；0005 `simulate` 的
  `trading_days` 参数在 0005 已独立存在，revert 0006 不影响它。
- **数据层**：删除 `runs/` 下对应产物即可（可重跑重建）；`data/`、catalog 不动。
- **兼容性**：回滚后 0004/0005 仍可独立运行；moneta/nova 不受影响（lyra 自包含）。

## 7. 审批

- [x] 用户 review（用户指令"如需决定按推荐执行并记录"——见附录 A）
- [x] AI review（同会话自检 + 对抗性自检；见附录 B/C）
- [x] 测试全绿
- [x] 332 策略回归：N/A（本 feature 无 moneta 332 依赖；用合成数据 + 交叉 nova 口径）
- [x] OCI 端到端：N/A（0006 只写本地 runs 镜像；OCI push 是 R7 独立 feature）

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-08 | 0.1 | 初稿：R5 指标 + `lyra run` 管线 + 报告 + 运行产物 + 可复现性清单 + O17 融资收口；R12 工作流明确移出（→0007）。 |
| 2026-11-10 | 0.2 | **批次1 对抗性 review 处置**（H2/H3/M1/M2/M3/M4/M5 接受并落地、H1 挂起）：`run_id` 数据身份覆盖策略消费的全部特征列 + counter 行为指纹（H2）；run 目录按 `run_id` 作用域、零交易也写零行 Parquet、manifest 哈希全部四个产物（H3/M2）；D3 澄清非真实 streaming（M1）；D6/H1 口径纠偏为"接口能力已收口、R4 交易日合规未收口、默认自然日为显式已知偏差"；I5 明示 `generated_at` 为唯一排除字段（M4）；测试矩阵补 5 条批次1 回归。 |

---

## 附录 A：设计决策（含用户裁决落点）

**D1（范围——用户推荐执行）**：0006 = **执行核心**（`lyra run` + R5 指标 +
报告 + 运行产物 + 可复现性 + O17 收口）。**R12 交互式工作流移出**（→ 0007，
单独对抗性自检）。理由：工作流构建在 0006 运行产物之上；体量大；用户"轻量、
基座一套、多方向并行"；避免把 0006 变成"过渡工程"（用户 #73 对 codex 的批评）。

**D2（数据路径）**：runner 读 `catalog.duckdb` 注册的 `spec.view`（0004 编译 SQL
的目标）。OHLC bar 与信号同源于该 view（0003 宽表含 OHLCV）。**不新增数据管线**。

**D3（逐标的隔离）**：信号 SQL 一次查出全部 `(instrument,time,signals)` 行
（`plan.sql` 已投影 OHLC `mid_o/mid_h/mid_l/mid_c`，见 0004 C1），在 Python 侧
按 `instrument` 分组为逐 bar 的 **dict**（`instrument/time/mid_* /entry_*/exit_*`，
布尔信号），再**逐标的**喂 0005 `simulate(plan, bars, trading_days_for=...)`
（**bars 是 dict 序列，非 o/h/l/c/signals 分离数组**）。**绝不跨标的合成**（I7）。
> **批次1-M1（澄清）**：此处"逐标的"指 **I16 隔离边界**——每个 instrument 的
> `simulate`/metrics 异常被独立捕获并记录（`instrument_failures`），不静默拖垮
> 其余标的；但信号 SQL 是**单次跨标的查询**（数据级失败属整次 run 失败）。
> 实现并非"逐标的流式/游标"（当前 `fetchall` + `bars_by_inst` 全量驻留），大数据
> 集下的真流式/分批消费列为**后续增强**，不是本 feature 已交付契约。

**D4（指标口径，I15，R5 冻结）**：
- `annualized = Σnet / (span_days/365.25)`；跨度 0 → `None`。`score`（年化得分）
  与 `annualized` 同式（R5 "年化分数 = 净收益算术和 ÷ 完整日历年(365.25 天)"）。
- `win_rate = 盈利笔数 / 总笔数`（无交易 → `0.0`）。
- `expectancy = mean(net)`（无交易 → `0.0`）。
- `avg_bars_held = 平均持有 bar 数`（无交易 → `0.0`）。
- **逐月行**（研究窗内每个自然月）：`actual_entries`（实际开仓次数，零开仓月保留
  为 0 — I8）/ `net_return_sum`（该月净收益和）/ `win_rate` / `avg_bars_held`。
- **禁止** Sharpe / Sortino / profit factor / CAGR / HWM / 跨标的组合合成（R5/I7/I9）。
- **报告元数据**（R5 必须列出）：strategy 名、timeframe、标的清单、时间窗、
  feature snapshot id、git commit、日期（日期取数据窗，确定性；运行时刻仅入
  manifest）。

**D5（可复现性清单，I5）**：`manifest.json` 记录
`{run_id, strategy_yaml_sha256, FEATURE_VERSION, engine_version, compiler_version,
duckdb_version, data_snapshot_ids, params{stop_loss_pct,direction,max_holding_bars,
slippage/commission/financing_bps}, trading_days_basis, counter_fingerprint,
git_commit, generated_at}`；
`run_id = sha256(上述字段，除 generated_at)`。同清单 → 同 `run_id`；任一变化 → 变。
（扩展 0003 快照身份；对齐 nova `runner.py` 的 `run_id` 机制。）
> **批次1-H2（已落地）**：`run_id` 的数据身份覆盖**策略 SQL 实际消费的全部输入**，
> 不止 OHLC——`data_digest` 现含 `features_used` 各列值（改特征值、OHLC 不变 →
> `run_id` 必变）；融资计数器的**行为指纹** `counter_fingerprint`（用固定探针区间
> 求值）入 `run_id`（两个计费不同的计数器 → `run_id` 必不同）。匿名 Python 回调
> 无法凭源码复现，故以行为指纹为身份；若需可复现审计，调用方应提供可版本化的
> 交易日历并以其身份（版本/内容摘要）替代裸回调。

**D6（O17 融资日基准——接口能力已收口，R4 交易日合规未收口）**：0005 引擎的
`simulate(..., trading_days_for=None)` **已按每笔交易**用该笔 entry/exit 时间算日数
（`_day_count`：`trading_days_for=None` → 逐笔按时间戳算**自然日**；传计数器
`counter(entry,exit)->float` → 由 caller 逐笔定日数）。0006 runner **默认传 `None`**
→ 逐笔**自然日**融资；可传入 `trading_days_for` 计数器（**扁平 `--financing-days`
已移除**，0004 C2）。
> **批次1-H1（口径纠偏，重要）**：本 feature 此前措辞"O17 在此收口 / R4 兼容"
> **不准确**——O17 收口的是**逐笔计数接口能力**，但 **R4/O15 要求融资按交易日
> （周末与市场节假日不计）**，而默认自然日**不满足 R4**（持仓跨周末会多计融资）。
> 故正确表述为：**接口能力已收口**（每笔可单独计日，`trading_days_for` 已就位），
> **R4 交易日合规未收口**——需在融资费率非零时接入**可版本化的真实市场日历**并
> fail-closed，或用户正式裁定改用自然日（须同步修订 R4/O15 与双语文档）。
> 当前默认自然日为**显式已知偏差**（保持 nova field-for-field cross-check 基准），
> 不得再表述为"R4 已兼容"。

**D7（报告）**：`report.md` + `metrics.json`：逐标的指标表 + 跨标的 summary
（各指标的最小/中位/最大，**非合成**）+ 运行元信息（清单摘要）。**不含** sizing /
$ PnL / 账户 CAGR（I9/R9）。

**D8（运行产物）**：见 §3.1 布局。**全部四个规定产物**（`signals.parquet`、
`trades.parquet`、`metrics.json`、`report.md`）无条件写出并**全部**进
`manifest.json` 的 SHA256（批次1-M2：零行结果也写带固定 schema 的零行 Parquet；
`metrics.json` 此前漏哈希，现纳入且缺失即 fail-closed）。
本地镜像在 `~/.lyra/<workspace>/runs/`（B13：仓库外）或仓库 `runs/`（gitignored）。
> **批次1-H3（已落地）**：每个 run 目录**按 `run_id` 作用域**
> （`runs/<name>/<YYYYMMDD>/<run_id>/`），不同 `run_id` 绝不共享目录——零交易重跑
> 不可能继承/再哈希上一次 run 的 `trades.parquet`；哈希只能证明文件未损坏，
> 目录隔离保证文件**属于**该 `run_id` 的 manifest。

**未决项（H1）**：融资日基准当前为**自然日**（0005 `_day_count`，`trading_days_for=None`
时按每笔 entry/exit 时间戳算）——**接口能力已收口，但 R4 交易日合规未收口**
（见 D6 批次1-H1 纠偏）。接入**可版本化的真实交易日历**（按实际交易日计数、周末/
节假日不计）需在融资费率非零时 fail-closed，或由用户正式裁定改用自然日并同步修订
R4/O15——这是**后续增强 / 用户裁决项**，不是
缺陷；0006 以"逐笔**自然日**"为当前默认口径（显式已知偏差，见 D6 H1），
`simulate(trading_days_for=...)` 计数器入口已在 0005 就绪，无侵入可切换到
真实交易日历。

## 附录 B：自检

**B1 契约引用核对**：R5（指标表）逐字段核对 D4 ✓；R6/R7（数据读/产物写）
核对 §3.3/D8 ✓；R9/I9（无 sizing）核对 §3.2/D7 ✓；I5/I7/I8/I10 核对 §4 ✓；
O17/O-0005-1 收口核对 D6 ✓。
**B2 数据模型核对**：`compile_sql` 输出列（instrument/time/entry_long/entry_short）
与 runner 消费一致 ✓；OHLC 同源自 view ✓；`simulate(signals)` 契约
（1/-1/0 逐 bar）与 D3 一致 ✓。
**B3 口径核对**：D4 每式对照 nova `metrics.py::summarize`
（`annualized_trade_return_score` / `win_rate` / `mean_net_trade_return` /
`monthly_entries` / `every_full_month_has_entry`）逐式核对，一致 ✓；nova 亦
**无 Sharpe / profit factor**，与 R5 一致 ✓。
**B4 不变量闭环**：I1/I5/I7/I8/I9/I10（引用）+ I15/I16（新增）覆盖 §5 全部测试 ✓。
**B5 范围核对**：R12 明确移出（D1）✓；out-of-scope（§3.2）与用户"轻量"一致 ✓。
**B6 回滚核对**：revert 0006 回到 0005，0005 `trading_days` 独立不受影响 ✓。
**自检结论**：发现并在正文/附录修正 2 处（`score` 与 `annualized` 同式的显式
声明 D4；`trading_days` 日历日 vs 交易日的"未决项"显式化 D6）。无阻塞问题。

## 附录 C：对抗性自检

**H1（高）逐标的失败被静默吞 → 汇总失真**
- 反驳/处置：**接受**，加 I16：一个标的失败记入清单并可见，`--strict` 时阻断；
  默认不阻断其余已完成的汇总（B6 轻量）。测试 `test_run_instrument_failure_isolated`。
- 残余风险：低。

**H2（高）`annualized` 跨度 0 / 单 bar → 除零**
- 处置：**接受**，D4 显式"跨度 0 → `None`"；测试 `test_metrics_annualized_calendar_years`。
- 残余风险：低。

**H3（高）跨标的合成（I7 违反）——runner 图省事算了个组合**
- 处置：**拒绝该做法**；D3/D7 明确"绝不合成"，summary 只用最小/中位/最大；
  测试 `test_run_multi_instrument_isolated` 断言无组合字段。
- 残余风险：低。

**H4（中）可复现性"同清单同输出"被浮点/字典序/时间戳破坏**
- 处置：**接受**，D5 `run_id` 排除 `generated_at`；parquet 写入固定行序
  （instrument, time）；测试 `test_run_reproducible_identical_manifest` +
  `test_run_reproducible_perturbation_fails`。
- 残余风险：低。

**H5（高）指标集与 R5 / nova 不符：初稿 D4/I15 引入 Sharpe / profit factor，
但 R5 明确"不做 CAGR / HWM / Sharpe / Sortino"，nova `summarize` 也无这两项**
- 处置：**接受并纠正**。代码期对抗性自检发现：`lyra/metrics.py` 已按 R5 冻结集实现
  （无 Sharpe / profit factor），但**决策文档初稿**（D4 / I15 / B3 / H5 / §5 测试表）
  仍写了 Sharpe / profit factor / median——文档与代码不一致，且文档本身违反 R5。
  已重写 D4 / I15 / B3 / H5 / §5 测试表，对齐 R5 冻结集
  （`trade_count` / `net_return` / `annualized` / `win_rate` / `expectancy` /
  `avg_bars_held` / 逐月行），并新增 `test_metrics_forbidden_fields_absent` 锁定
  "无 sharpe / profit_factor / sortino / CAGR / HWM"。
- 残余风险：低（代码本就正确；文档已与代码 + R5 对齐并测试锁定）。

**H6（中）O17 "收口"名不副实：runner 用日历日，若 O17 要交易日则没真收口**
- 处置：**部分接受**——0006 以日历日实现并**显式声明**为已收口口径，保留
  `trading_days` 覆盖入口；"交易日历"列为**后续增强**（未决项），不是缺陷。
  这与 0003 D10 / 0005 的渐进策略一致（不阻塞）。
- 残余风险：低（口径已显式，不误导）。

**H7（中）bar dict 的信号列与 0005 `simulate` 的 `bar.get("entry_long")` 消费
  契约可能错位（列名/布尔性）**
- 处置：**接受**，D3 显式：runner JOIN 后产出的每个 bar dict 必含 0005 契约的 4 个
  信号键（`entry_long/entry_short/exit_long/exit_short`，布尔）+ 4 个 OHLC 键
  （`mid_o/mid_h/mid_l/mid_c`）+ `instrument`/`time`；0004 已保证
  `entry_long`/`entry_short` 互斥（`not both true` 测试）。
  测试 `test_run_single_instrument_matches_engine` 锁定（field-for-field diff=0）。
- 残余风险：低。

**M1（中）报告缺"零开仓月"信息 → I8 只体现在指标、报告看不出**
- 处置：**接受**，D7 报告含"月度机会数（含 0）"序列；测试 `test_run_monthly_zero_openings_counted`。
- 残余风险：低。

**M2（低）`lyra report`（复用产物重渲染）边界不清**
- 处置：**接受**，§3.1 明确 `report` = 读现有 `runs/` 产物重渲染，不改数据；
  与 `run` 解耦。
- 残余风险：低。

**M3（低）`runs/` 落在 gitignored `runs/` 还是 `~/.lyra/` 二选一未定**
- 处置：**接受**，D8：默认 `~/.lyra/<workspace>/runs/`（B13 仓库外），
  `--out` 可指仓库 `runs/`（gitignored）；二者互斥、都不进 git。
- 残余风险：低。

**M4（低）`run_id` 排除 `generated_at` 但包含 `git_commit`——dirty tree 时不稳**
- 处置：**接受**，dirty tree 时 `git_commit` 取 `HEAD^{short}+dirty` 标记，
  仍确定性（同一 dirty 状态同标记）；跨机器不可比时以本地 `run_id` 为准（与
  0003 快照身份同理）。
- 残余风险：低。

**P1（低）`compute_metrics` 空输入返回 dict 而非抛错，可能被误用为"有交易"**
- 处置：**接受**，空输入返回 `{"trade_count": 0, ...}`，字段明确；测试覆盖。
- 残余风险：低。

**对抗性自检结论**：7 高/中 + 4 中/低全部处置；2 处**接受**为显式约定（H5 inf
序列化、H6 日历日口径），其余**接受并加测试/不变量**（H1→I16、H2/H4/H7/M1）或
**拒绝该做法**（H3 跨标的合成）。无阻塞缺陷；实现按附录 A 约定执行。
