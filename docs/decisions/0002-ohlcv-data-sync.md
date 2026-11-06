# 0002 — OHLCV 数据同步（OCI pull + 落盘 + 聚合）

> **English**: [0002-ohlcv-data-sync.en.md](./0002-ohlcv-data-sync.en.md)

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0002` |
| 标题 | OHLCV 数据同步（OCI pull + 落盘 + 聚合） |
| 状态 | **提案**（待用户审批） |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-06` |
| 相关提案 | — |
| 相关需求 | `docs/requirements.md` R1 / R2 / R4 |
| 相关 HLD | `docs/hld.md` §8（构建顺序第 2 步） |
| 取代 | — |

## 1. 问题

Lyra 需要一个**确定性的原始数据入口**：从 OCI 拉取 OHLCV 原始数据，
落成可复现的本地 Parquet，作为 0003 feature builder 的输入。
同时按用户要求，**在 config yml 里预留将来 push 策略 / 自定义
feature 的 PAR 位置**（0007 使用，本 feature 只占位、不使用）。

## 2. 背景

> 三代谱系（moneta → nova → lyra）的完整"为什么"在
> `docs/background.md`；本节只引用其中 moneta 的数据管线部分。

- **moneta 怎么做的**（`pipeline/extract_oci.py`，已生产验证）：
  1. 从 `config/setting.yml` 读 `oci.par_url`（一个 **PAR prefix URL**）；
  2. `GET <par_url>/?fields=name,size,md5,timeModified&limit=1000`
     **列对象**，用 `nextStartWith` 分页直到取完；
  3. 对每个对象 `urljoin(base, name)` 拼出对象 URL，`GET` 流式下载
     到 `data/raw_zips/`；**按 size 幂等**（本地存在且大小一致则跳过）；
  4. 解压所有 zip 的 CSV 到**扁平** `data/raw_csv/`（冲突加 `_N` 后缀，
     重跑先清顶层旧 CSV）；对象名做 **path-traversal 防护**
     （按 path 组件判断，`EUR..USD.csv` 这类合法名不误杀）；
  5. HTTP 层带 retry/backoff（429/5xx，GET 幂等才重试）。
  6. 下游 `aggregate_ohlcv.py`：1m bronze Parquet（UTC，
     `instrument,time,mid_o,mid_h,mid_l,mid_c,volume`）按 UTC 边界
     聚合成 5m/1h，带 `n_bars` 标记部分 bar。
- **为什么不用 OCI 签名（oracledb signer）**：moneta 已经证明
  **PAR prefix URL 足够**——零 SDK 凭证、零 region 配置、
  下载端只需 `requests`；凭证管理留在用户侧（`config.yml`，
  gitignored）。签名方案需要 `tenancy/region/key` 三件套进本地
  环境，换来的只是"push 免 PAR"，而 push 侧（0007）本来就要
  独立设计写权限模型（B9 两级）。**结论：pull 用 PAR（沿用 moneta
  机制），push 的访问方式留待 0007 再定**——但 yml 现在就为
  push 预留 PAR 占位（见 §3.1）。
- **O5（PAR 90 天过期）在本 feature 定案**：PAR 由用户侧管理
  （过期后重新生成并更新 `config.yml`）；`lyra pull` 失败时给出
  **明确的过期诊断**（403/404 + "PAR may have expired" 提示）；
  `lyra-doctor`（0009）在常规体检里检测 PAR 是否仍可用。

## 3. 方案

### 3.1 做什么

**CLI**（`lyra/` 包随本 feature 创建）：

```
lyra pull [--data-root DIR]     # 唯一用户入口：拉取 + 解压 + clean + aggregate
lyra clean   <raw_csv_dir>      # 调试用独立入口（复用 pull 内部步骤）
lyra aggregate <bronze>         # 调试用独立入口（复用 pull 内部步骤）
```

`clean` / `aggregate` 不是独立交付物，是 `lyra pull` 的内部步骤
（可单独调用仅为调试）；用户日常工作流只有一条命令：`lyra pull`。

**重跑语义（防派生缓存陈旧）**：**只有 raw 下载层做幂等跳过
（I20）**；`clean` 与 `aggregate` 每次 `lyra pull` **恒重算并覆盖
输出**（不做"输出已存在即跳过"）——bronze/5m/1h 全部是 raw 的
确定性函数（I18），重算成本 ≈ 一次 DuckDB 扫描，而"输出已存在即
跳过"会在 bronze 被删/损坏时**静默丢数据**（批次3 A1）。

**代码新增**：

| 文件 | 职责 |
|---|---|
| `lyra/config.py` | 加载 config 结构；真实值在 **`config/config.yml`（gitignored）**，仓库内只有 `config_example.yml`（B10） |
| `lyra/oci_client.py` | PAR 列对象（分页）+ 对象下载（流式、retry、**md5 优先 / size 回退** 幂等、path-traversal 防护）——机制沿用 moneta，幂等判断比 moneta 强（moneta 仅用 size，list 已取 md5 却未用） |
| `lyra/pull.py` | 拉取 + 解压 + 扁平化（moneta `extract_all_zips_to_csv` 等价） |
| `lyra/clean.py` | **moneta `load_data.py` 等价语义**：① `is_complete` 过滤 ② 按 `(instrument, time)` 去重 ③ **确定性存活行选择**（payload 非空列数降序 → 源文件名 → 原行序）→ bronze 1m Parquet（契约见 §3.3） |
| `lyra/aggregate.py` | 1m → 5m/1h（moneta 等价，`time_bucket` UTC 边界，`n_bars` 保留） |
| `lyra/cli.py` | typer 入口（`lyra` command） |
| `tests/` | §5 全部用例 |

**config 预留（用户要求）**——`config/config_example.yml` 的
`oci:` 段现在就有 3 个 PAR 位置：

```yaml
oci:
  # ---- pull（本 feature 使用）----
  data_par_url: "https://<ns>.compatibility.<region>.oraclecloud.com/<bucket>/<prefix>/"
  # ---- push（0007 使用，本 feature 只占位不读取）----
  strategies_par_url: "https://.../strategies-upload/"   # 策略 YAML + lessons
  features_par_url:     "https://.../features-upload/"   # 自定义 feature + contract card
```

### 3.2 不做什么

- **不做 push / 备份**（0007）——PAR 占位只出现在 yml 与 config
  模型里，本 feature 的代码不读取、不校验它们。
- **不做 feature builder / compiler / trade engine**（0003-0005）。
- **不做 OOS 机制 / 数据增删改**——pull 是只读下载 + 本地派生。
- **不做 OCI signer**（本 feature 范围内）——push 侧 0007 再评估。

### 3.3 边界

- **输入契约**（与 moneta 真实数据核对过）：
  - OCI 上为 zip 归档，内含 CSV；
  - **必需列**：`instrument, time, is_complete`（moneta
    `load_data.py` 的硬校验）；
  - **可选列**（缺了 NULL 填充）：`volume, mid_o, mid_h, mid_l,
    mid_c, bid_*, ask_*`（真实 CSV 共 15 列）；
  - `time` 为 **UTC、1m 粒度**；**非 1m 粒度输入 → 拒绝并报错**
    （聚合语义依赖 1m bronze，防呆）；
  - `instrument` 命名继承 moneta `BASE_QUOTE`（O14）；**完整清单（O14
    交付物，批次5/6 真实数据已验证，共 21 个）**：

    | # | instrument | # | instrument |
    |---|---|---|---|
    | 1 | AUD_USD | 12 | NZD_USD |
    | 2 | BCO_USD | 13 | SPX500_USD |
    | 3 | BTC_USD | 14 | UK100_GBP |
    | 4 | CN50_USD | 15 | US30_USD |
    | 5 | DE30_EUR | 16 | USD_CAD |
    | 6 | ETH_USD | 17 | USD_CHF |
    | 7 | EUR_USD | 18 | USD_JPY |
    | 8 | GBP_USD | 19 | WTICO_USD |
    | 9 | HK33_HKD | 20 | XAG_USD |
    | 10 | JP225_USD | 21 | XAU_USD |
    | 11 | NAS100_USD | | |

    **权威来源是数据本身**（`SELECT DISTINCT instrument FROM bronze`，或
    `Catalog.instruments()`）；此表是 2026-11-06 真实 moneta 数据的枚举
    快照，供 0003 编写测试与验证卡片时引用。清单可扩展（新标的进数据即
    生效，无需改代码——0002 全链路按 `instrument` 列泛化，不硬编码清单）。
  - **`data_par_url` 必须是 prefix 级** PAR（不是 bucket 级），
    防止把 push 目录（strategies/features）一并拉进本地 data/。
- **clean 语义**（moneta `load_data.py` 等价；确定性是 I18 的前提）：
  1. `COALESCE(is_complete, FALSE) = TRUE` 过滤；
  2. 按 `(instrument, time)` 去重；重复行按**确定性存活行选择**取一行：
     payload 非空列数降序 → 源文件名 → 原行序（moneta 原文规则；
     防 `prices_*` backfill 与主 CSV 同键重叠）；
  3. 落 bronze 1m Parquet。
- **bronze schema（显式定义）**：bronze 1m Parquet 的列 = **输入
  CSV 列的并集**：
  - 必有：`instrument, time, volume, mid_o, mid_h, mid_l, mid_c`；
  - 依源：`bid_*, ask_*`（moneta 数据源有则保留）；
  - **不含 `is_complete`**（clean 已消费；bronze 内该行恒为 true，
    无信息量）。
  此 schema 是 0003 feature builder 的输入契约。
- **输出契约**：
  - `data/raw_zips/`（原始归档，重放来源）、
  - `data/raw_csv/`（扁平 CSV；**重跑前清顶层旧 CSV**（moneta 行为），
    子目录不动）、
  - `data/all_data/all_data.parquet`（bronze 1m）、
  - `data/ohlcv_5m/`、`data/ohlcv_1h/`（聚合，`time_bucket` UTC
    边界，`n_bars` 如实标记部分 bar）、
  - `data/catalog.duckdb`（**DuckDB 元数据 / 外部表 catalog**，274 KB
    纯 schema）：持有 `bronze` / `ohlcv_5m` / `ohlcv_1h` 三个 VIEW，
    分别指向对应 Parquet 文件。**数据仍在 Parquet（I18 单一事实来源）**，
    catalog 只是**命名入口**——0003/0005 直接 `SELECT ... FROM bronze`，
    不必记路径 / re-glob。catalog 可重建（`lyra catalog --refresh`，幂等
    `CREATE OR REPLACE VIEW`），**不是需备份的资产**（0007 push 的对象是
    Parquet，不是 catalog）。**永不进 git**（B13，仓库外）。
  全部在 `~/.lyra/<workspace>/` 或 `--data-root` 指定处（B13），
  **永不进 git**（B1）。
- **高效读 / 写契约（DuckDB）**：
  - **读**：clean / aggregate / catalog 全部走 **DuckDB 外部表 / VIEW**
    流式读 Parquet，**不把全表物化进内存**（批次6 A2/A3）；
  - **写**：clean 用 `COPY` 流式落盘；aggregate 用 `COPY (… ORDER BY …)`
    流式落盘且行序稳定（I18）；
  - **诚实边界（批次6 A6）**：aggregate 的 `time_bucket + ARRAY_AGG +
    GROUP BY` 分组工作集在 48M 行下实测峰值 ≈**10 GB**（这是 DuckDB
    哈希聚合的固有形态，非流式 bug、非内存泄漏）。"流式"指 bronze 读取
    与 clean COPY 不物化全表；**分组工作集不免费**——0003 设计更大
    feature 面时须据此规划内存。
- **凭证边界**：PAR URL 只出现在 `config.yml`（gitignored）；
  日志 / 报告 / run 摘要中**永不打印完整 PAR URL**（含签名参数）。
- **alpha 边界**：本 feature 不碰 `alpha/`、不碰策略、不碰
  `strategies/examples/`。

### 3.4 数据质量校验（DQ1–DQ3，fail-fast）

**动机**：moneta 的 `load_data.py` 只有 `is_complete` 过滤 + 去重，**不校验**
OHLC 内部一致性 / spread 方向 / volume 非负——脏数据（`bid > ask`、`l > h`、
负 volume）会静默流入 bronze，污染 0003 的全部特征与 0005 的全部回测。
nova 的 `data._validate` 有这些检查，lyra 在 moneta→nova→lyra 链条里把这一环
**显式固化**。

**时机**：clean 在 `is_complete` 过滤 + `(instrument,time)` 去重**之后**、
`COPY` 写 bronze **之前**执行（对"存活候选行"校验，避免被去重丢弃的行
误触发）。**fail-fast**：任何违反 → 抛 `DataQualityError`（列出每项违反数），
bronze 不写出。

**不变量**（每条 = "违反行"的 WHERE 表达式，NULL 比较天然排除部分行）：

| # | 不变量 | 表达式（违反即报错） |
|---|---|---|
| DQ1 | mid OHLC 正值且内部一致（o,c ∈ [l,h]） | `mid_h < mid_l OR mid_h < mid_o OR mid_h < mid_c OR mid_l > mid_o OR mid_l > mid_c OR mid_o<=0 OR mid_h<=0 OR mid_l<=0 OR mid_c<=0` |
| DQ2 | 任一侧点同时存在 bid/ask 时 ask ≥ bid（**逐点列感知**：某点 `bid_p`+`ask_p` 都有则该点强制；完全无 bid/ask 列才整体跳过） | `bid_p IS NOT NULL AND ask_p IS NOT NULL AND ask_p < bid_p`（仅对 `bid_p`、`ask_p` 都存在的点 p 启用） |
| DQ3 | volume（若有）有限且非负 | `volume IS NOT NULL AND (volume < 0 OR NOT isfinite(volume))` |

**列感知（逐点）**：DQ2 对**每个**点 p 独立判断——只要 `bid_p` 与 `ask_p`
两列都存在，就对该点强制 `ask_p >= bid_p`；某点只有一侧（或两侧都无）则
跳过该点（`union_by_name` 下引用不存在的列是 binder error）。只有当输入
**完全没有任何** bid/ask 配对列时才整体不启用 DQ2。这样既不会拒绝合法的
partial quotes（只带部分点），也不会静默漏检 partial quotes 的反向 spread
（S1 自检发现并修复的边界）；DQ1/DQ3 的列是 `ALWAYS_PRESENT`，恒启用。

**真实数据验证（61,615,338 raw CSV 行，183 个真实 moneta CSV）**：
DQ1/DQ2/DQ3 全部 **0 违反**——fail-fast 在真实数据上不误伤，且把
"moneta 数据恰好干净"这件事从假设变成了**被代码强制的契约**。

**设计取舍**：不静默丢弃违反行（那会掩盖源数据问题），而是 fail-fast
让上游可见——0002 是数据入口，脏数据在这里被拦下比在 0005 回测里
以"策略结果诡异"的形式暴露便宜得多。

### 3.5 OANDA 回补 / 缺口填充（`lyra oanda`）

**动机**：`lyra pull` 只下载 **PAR 前缀里已存在**的对象——它没有
"按标的/时间窗口补缺失历史"的能力。moneta 的 `extract_oanda.py` 有
（从 OANDA API 拉 1m K 线，按 UTC 月分块、断点续传），这是 moneta→lyra
链条里 lyra 需要补的一环：I22 哲学是"gap 合法"，但**填 gap 的工具**
仍应由框架提供，而不是要求用户手写 API 调用。

**契约**（沿用 moneta 的成熟实现，独立重写）：

- **CLI**：`lyra oanda <instrument> --from <UTC> --to <UTC> [--dry-run] [--force]`
- **来源**：OANDA v3 `/v3/instruments/<inst>/candles`，1m 粒度，
  `price=MBA`（mid+bid+ask，对齐 bronze schema）。
- **5000 K 线分页上限**：OANDA 拒绝 `count` 与 `from`+`to` 同用、
  单页上限 5000——窗口按 `PAGE_SIZE-1` K 线分页，每页起点比上页末点
  提前 1 K 线（刻意重叠，下游 clean 的 `(instrument,time)` 去重消解）。
- **日历月分块 + 断点续传**：输出落 `raw_csv/<instrument>/
  <instrument>_<gran>_<YYYYMM>01T000000Z.csv`（每 UTC 月一文件）；
  已存在且非空的月份**默认跳过**（`--force` 才重拉），中断重跑自动续。
- **token 是秘密**：只在 gitignored 的 `config/config.yml` 的
  `oanda.api_token` 下，**永不进 git**（moneta 惯例）。空 token →
  `OandaConfigMissing`（响亮的失败，不是静默跳过）。`--dry-run` 不
  需要 token。
- **UTC 只**：无本地/DST 转换；所有时间戳 ISO-8601 `...Z`。
- **输出 schema**：与 bronze 输入契约完全一致
  （`instrument,is_complete,time,volume,mid_*,bid_*,ask_*`），
  经 clean 的递归 `**/*.csv` glob 自然被拾取（§3.3 边界）。

**与 §3.3 的耦合**：clean 的 CSV glob 从 `*.csv` 升级为 `**/*.csv`
（DuckDB 2.0 递归展开），使 per-instrument 子目录成为一等公民；
既有扁平 CSV 测试全部保持兼容（已验证 47 测试全绿）。

**真实数据未验证**：token 是秘密、API 需要网络，本批只做**离线可验证**
的部分（schema / 分页逻辑 / 断点续传 / DQ 兼容性）的单元测试；真实
OANDA 拉取留给用户在 `config/config.yml` 填 token 后跑一次
`lyra oanda GBP_USD --from ... --to ... --dry-run` 验证。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I18 | **数据可复现**：同一 OCI 对象集合（md5 集合一致）+ 同一代码版本 → bronze / 5m / 1h Parquet 的**数据内容逐行一致**（值 + 行序）；不承诺 Parquet 文件字节一致（文件级字节随 arrow 版本可变，moneta 同样不承诺）。前提：clean 的过滤/去重/存活行选择全部确定性（§3.3 clean 语义），pull 按对象名排序处理（顺序无关） | 本 feature 新增（R8 在数据层的具体化） |
| I19 | PAR URL 永不进入 git、日志、run 报告（脱敏为 host + path 前 2 段） | I12（凭证不进 git / 不进 run 报告）在数据层的延伸 |
| I20 | 对象下载幂等：**md5 一致即跳过**（moneta list 已返回 md5）；md5 不可用时回退 size 判断；同键不同内容必须被重下 | moneta 机制 + 强化（I11 可重建性的下载侧保证） |
| I21 | 聚合只用 `time_bucket` UTC 边界 + 窗口内已有 1m bar；`n_bars` 如实标记部分 bar（缺口合法）；open/close 取窗口首/末 bar。**`time` 实为 `TIMESTAMPTZ(UTC)`**（源带 `Z`，DuckDB 自动推断；下游读需 pytz，见 pyproject） | moneta `aggregate_ohlcv`（本 feature 固化）；**TIMESTAMPTZ 为真实数据端到端后确认（批次5 A7）** |
| I22 | 输入**原生分辨率必须 = 1m UTC**（防呆，I18 的前提）。判据：每标的**最小** bar 间隔 ≈ 1m（59–61s）。**市场缺口（bar 缺失）是合法的**——真实 1m 数据周末/休市/无成交会缺 bar（本数据集 73 万处 5m+ 缺口），不得据此拒绝；**5m/1h 原生分辨率**（最小间隔 ≥ 5m）才拒绝 | 本 feature 新增；**真实数据端到端后精确化**（原始"逐对 1m"误拒合法缺口，批次5 修正） |
| I23 | **数据质量（DQ1–DQ3，fail-fast）**：bronze 候选行必须满足 mid OHLC 正值且内部一致（o,c ∈ [l,h]）、两侧 quote 全有时 ask ≥ bid、volume（若有）有限且非负。任何违反 → `DataQualityError`，bronze 不写出。**真实 61,615,338 CSV 行 0 违反**（不误伤） | 本 feature 新增（nova `data._validate` 的等价固化；moneta 缺失、lyra 补回）；见 §3.4 |
| I1 | YAML 是唯一策略语言 | HLD §4（本 feature 不碰策略，天然满足） |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_oci_list_pagination` | 分页列表：多页 `nextStartWith` 取全、循环保护 |
| `test_oci_download_idempotent_md5` | md5 一致 → 跳过、不发请求（I20） |
| `test_oci_download_md5_mismatch` | 同 name 同 size 但 md5 不同 → 必须重下（I20 强化点） |
| `test_oci_unsafe_name_rejected` | `../evil`、绝对路径、`a:/b` 对象名被拒；`EUR..USD.csv` 合法通过 |
| `test_pull_zip_to_flat_csv` | 嵌套 zip → 扁平 CSV；冲突 `_N`；重跑清顶层旧 CSV、子目录不动 |
| `test_clean_is_complete_filter` | `is_complete` falsy / 缺失 → 行被过滤（moneta 语义） |
| `test_clean_dedup_deterministic` | 同 `(instrument,time)` 多源重叠 → 按"payload 非空列数 → 源文件名 → 行序"取唯一存活行；两次运行结果一致（I18） |
| `test_clean_non_1m_rejected` | 5m 原生分辨率输入（最小间隔 5m）→ 明确拒绝（I22 防呆） |
| `test_aggregate_5m_1h_utc` | 跨 5m/1h 边界的开高低收正确；`n_bars` 标记部分 bar（I21） |
| `test_aggregate_deterministic` | 同输入两次运行 Parquet **数据逐行一致**（I18，非文件字节） |
| `test_clean_bronze_schema` | bronze 列 = 输入并集（必含 7 列）；`is_complete` 不带入 bronze（A2） |
| `test_clean_recompute_overwrites` | 删 bronze 后重跑 `lyra pull`（raw 全幂等跳过）→ bronze 仍被重建（A1） |
| `test_par_expiry_diagnostic` | 403/404 → 报错含 "PAR may have expired" 提示（O5） |
| `test_par_url_redacted_in_logs` | 日志 / 异常消息中无完整 PAR URL（I19） |
| `test_clean_rejects_bad_mid_ohlc` | `mid_h < mid_l` 行 → `DataQualityError`（DQ1/I23） |
| `test_clean_rejects_negative_volume` | `volume < 0` 行 → `DataQualityError`（DQ3/I23） |
| `test_clean_rejects_inverted_spread` | `ask < bid`（两侧都有）→ `DataQualityError`（DQ2/I23） |
| `test_clean_rejects_partial_quote_inverted_spread` | partial quote（仅 bid_o/ask_o）`ask_o < bid_o` → `DataQualityError`（DQ2 逐点列感知，S1 自检） |
| `test_clean_accepts_partial_quote_valid_spread` | partial quote 合法 spread（`ask_o >= bid_o`）通过（DQ2 不拒合法 partial） |
| `test_clean_accepts_valid_data` | 良形行通过（DQ 不误伤） |
| `test_clean_picks_up_nested_oanda_csv` | `raw_csv/<inst>/*.csv` 子目录被递归 glob 拾取（§3.5） |
| `test_oanda_fetch_requires_token` | 空 token → `OandaConfigMissing`（§3.5，响亮失败） |
| `test_oanda_candles_to_rows_schema` | OANDA candle → 与 bronze 输入契约完全一致的行（§3.5） |
| `test_oanda_backfill_resume_skips_existing` | 已存在非空月份被跳过，不触发网络拉取（§3.5 断点续传） |

## 6. 回滚

- **代码**：revert 本 feature 的 commit（`lyra/` 新增模块独立，
  不影响 0001 的文档与骨架）。
- **数据**：本地 `data/` 是派生物，直接删；**OCI 侧零写操作**，
  无需回滚远端。
- **兼容性**：moneta / nova 不受影响（本 feature 只读 OCI、不 import
  任何 moneta/nova 代码，机制借鉴但代码独立实现）。

## 7. 审批

- [ ] 用户 review
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] 332 策略回归通过（如适用 —— 本 feature 不涉及）
- [ ] OCI 端到端跑通（**需要用户提供真实 PAR URL**）

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-06 | 0.1 | 初稿。定案：pull 用 PAR prefix URL（沿用 moneta 已验证机制）；O5 定案（PAR 用户侧管理 + 过期诊断 + 0009 doctor 体检）；yml 预留 pull/strategies/features 三个 PAR 位置（push 归 0007）。 |
| 2026-11-06 | 0.2 | **自检 + 对抗性 review（批次3）修复**：① 输入契约改为 moneta 真实列契约（必需 `instrument,time,is_complete`；mid/bid/ask 可选；真实 15 列）；② clean 语义补齐 moneta `load_data.py` 三规则（is_complete 过滤 / (instrument,time) 去重 / 确定性存活行选择），防 `prices_*` backfill 与主 CSV 同键重叠；③ 可复现性不变量从"逐字节"修正为"**数据逐行一致**"（文件字节随 arrow 版本可变，moneta 同口径），并定义其前提（确定性 clean + pull 按名排序）；④ 下载幂等升级为 **md5 优先 / size 回退**（moneta list 已取 md5 却未用）；⑤ 新防呆 I22：非 1m 粒度输入拒绝；⑥ 明确 `data_par_url` 必须 prefix 级；⑦ CLI 澄清（clean/aggregate 是 pull 内部步骤的调试入口）；⑧ 不变量编号改 **I18–I22**（0.1 误用 I2–I6，与 hld §4 已占用编号冲突）；⑨ 测试清单 9→12（补 md5 不匹配重下、is_complete 过滤、去重确定性、非 1m 拒绝）。 |
| 2026-11-06 | 0.3 | 批次3 红队两条真缺陷落地：**A1 派生缓存陈旧** → 定案只有 raw 层幂等，clean/aggregate 恒重算（否则 bronze 被删/损坏时静默丢数据）；**A2 bronze schema 未定义** → 显式定案 bronze 列 = 输入并集（必含 7 列，bid/ask 依源，**不含 `is_complete`**），作为 0003 输入契约；测试清单 12→14。A3–A5 记录为接受边界。 |
| 2026-11-06 | 0.4 | **真实数据端到端（moneta 真实 PAR，12 GB / 4884 万行）后精确化契约 + 修 4 个 fixture 测不到的偏差**：① **clean 重写为 DuckDB**（纯 Python 在 48M 行不可行）；② **I22 判据改为"原生分辨率 = 1m"**（每标的最小间隔 ≈1m），**市场缺口合法**——原"逐对 1m"误拒 73 万处真实缺口；③ `time` 确认为 **TIMESTAMPTZ(UTC)**（源 `Z` 推断）+ 下游读需 **pytz**（补进 pyproject）；④ `read_parquet(?)` 绑定参数统一 `str()`；⑤ `COPY` 加 `ORDER BY` 稳定行序（I18）。测试 14→24（补 gapped-1m 接受、5m 原生分辨率拒绝、COPY 确定性、空表 schema）。 |
| 2026-11-06 | 0.5 | **完整性审计 + DuckDB 高效读写 / catalog（批次6）**：① **完整性三层验证全过**——bronze/5m/1h footer 可读且 `num_rows` 与成功报告一致 + **全 row-group 解压扫描**（484/484 page 解码成功、扫到行数 == footer）+ raw 163/163 zip 与远端 PAR 逐对象 **md5+size** 全等 → **确认前面的系统中断无截断 / page 损坏 / 静默失败**；② **读路径统一为 DuckDB 外部表 / VIEW**——`_register_bronze` 由 `CREATE TABLE`（物化全表 48M 行）改为 `CREATE VIEW`（流式，A2）；③ **新增 `lyra/catalog.py`**——持久化 DuckDB catalog（`~/.lyra/default/data/catalog.duckdb`，仓库外，纯 schema 元数据），`bronze/ohlcv_5m/ohlcv_1h` 三 VIEW 命名入口，`lyra pull` 末步自动建、`lyra catalog` CLI 可重建（A3）；④ **诚实标注效率上界**——aggregate 分组工作集在 48M 行下实测峰值 ≈10 GB（DuckDB 哈希聚合固有形态，非 bug，非流式可消除），0003 设计大 feature 面时须据此规划（A6）。真实数据回归：视图改造后重跑 aggregate，5m/1h bars 与批次5 逐行一致（I18 成立）。测试 24→30（新增 catalog 6 个，含 VIEW 非 TABLE 断言）。 |
| 2026-11-06 | 0.6 | **批次7 外部红队 9 项全接受并修复**（0002 首次"第二个 AI"全面审查）：① **D1（Major）**`_quote` 正则阻断 Windows 路径 → 改 SQL 单引号转义 + 控制字符拒绝（R8 可移植性）；② **D2（Major）** `upsert_views` 无锁保护 → `try/except` + `warnings.warn`（"Best-effort"从注释变成代码）；③ **D3（Moderate）** `databackend.memory_limit`/`tmp` 未传入 DuckDB → 新增 `DatabackendConfig` + `open_limited_duckdb()`（`SET max_memory`/`threads`/`temp_directory`），全链路接入；**同轮修脚枪**：`config_example.yml` 的 1GB 示例改 16GB（真实数据需 ~10GB 工作集，1GB 会 OOM）；④ **D4（Moderate）** O1 文档断层 → `open-questions` 补裁决（0002 废弃目录级 snapshot_id，单文件外部表 + raw md5 溯源）；⑤ **D5（Moderate）** 21 标的清单未落盘 → §3.3 补清单表 + `Catalog.instruments()` 接口（权威来源是数据本身，清单可扩展）；⑥ **D6（Moderate）** `_validate_1m` 报错无明细 → 改返回违规标的 + 实测 min_gap_s；**拒绝"放宽到 60s 倍数"建议**（5m 原生 300s 恰是倍数会误放）；⑦ **D7（Minor）** 空表 naive timestamp → 统一 `pa.timestamp("us", tz="UTC")`；⑧ **D8（Minor）** catalog 相对路径 → `Path.resolve()`；⑨ **D9（Minor）** 无解压炸弹防御 → `MAX_EXTRACTED_MEMBER_BYTES`（8GB，真实最大 575MB）+ `ZipBombError`。**38 测试全绿**（新增 8 个），pyflakes 干净。批次7 review 文档（中英双份）补处置表 |
| 2026-11-06 | 0.7 | **0002 收口前自审 + 对抗性自审**：核验批次7 全部改动后抓出 **F1 真缺陷**——`Catalog.instruments()` 的 docstring 承诺"bronze 视图缺失/不可读时返回 []"，但 bronze parquet 被删/损坏时 `SELECT` 抛 `IO Error` 而非降级；修为 `except duckdb.Error: return []`，新增回归测试 `test_instruments_returns_empty_on_broken_catalog`（valid-then-delete 复现真实路径）。另 3 候选经核验为误报/挂起：run_pull 未显式 close 两个 count 连接（CPython refcount 兜底、非正确性 bug、改法会破坏 D2 测试结构→挂起待 0003 一并清理）/ `_count_rows` 文档引用（grep 证实用 DuckDB `COUNT(*)`，误报）/ `tmp/` 泄漏（DuckDB `temp_directory` 合法换页空间，误报）。**39 测试全绿**（+1），pyflakes 干净，真实数据回归 bronze/5m/1h = 48,846,896/9,986,167/838,272 与批次5 一致（I18 成立）、`instruments()`=21 核验。**0002 收口** |
| 2026-11-07 | 0.8 | **对比 moneta/nova 补齐两个真缺**（用户拍板：都补进 0002）。① **数据质量校验（§3.4，DQ1–DQ3，fail-fast）**：nova `data._validate` 有、moneta/lyra 无的 OHLC/spread/volume 校验被显式固化进 clean——在 is_complete 过滤 + 去重后、COPY 前对存活候选行校验，违反即 `DataQualityError`、bronze 不写出。列感知（DQ2 防 `union_by_name` binder error；v0.9 细化为逐点）。**真实 61,615,338 CSV 行 0 违反**（不误伤）。新增 I23。顺带修 1 个**测试 fixture 真 bug**：`test_aggregate.py` 的占位 bid/ask 是反的（bid_l > ask_l，物理不可能），被新 DQ 正确拒绝——fixture 改为 ask ≥ bid 的合法报价。② **OANDA 回补 / 缺口填充（§3.5，`lyra oanda`）**：moneta `extract_oanda.py` 有、lyra 无的"按标的/时间窗口补 1m 历史"能力被独立重写为 `lyra/oanda.py` + `lyra oanda` CLI——OANDA v3 分页（5000 K 线上限、每页 1 K 线重叠）、UTC 日历月分块、断点续传（已存在非空月份默认跳过）、token 只在 gitignored config（空 token 响亮失败）、输出对齐 bronze 输入契约。clean 的 CSV glob `*.csv`→`**/*.csv`（DuckDB 2.0 递归展开）使 per-instrument 子目录一等公民。**47 测试全绿**（+8），pyflakes 干净。真实 OANDA 拉取留给用户填 token 后验证（token 是秘密、需网络） |
| 2026-11-07 | 0.9 | **自检 + 对抗性复查两个新功能**（用户要求：先自检、再对抗性、最后 2019-11/12 实测）。**S1 真缺陷（已修）**：DQ2 列感知原为"8 列全有才启用"——partial quotes 输入（如只带 `bid_o`/`ask_o`）会**静默跳过** spread 校验，违背 fail-fast 意图（也漏掉 nova `not in (0,8)` 拒绝的场景）。改为**逐点列感知**：某点 `bid_p`+`ask_p` 都在则该点强制 `ask_p >= bid_p`（逐点 NULL guard 安全），只有完全无任何 bid/ask 配对列才整体跳过——既不拒合法 partial quotes、也不静默漏检反向 spread。新增 2 个回归测试（`test_clean_rejects_partial_quote_inverted_spread` + `test_clean_accepts_partial_quote_valid_spread`），5 边界情形全验证（partial inverted 拒绝 / partial valid 通过 / full inverted 拒绝 / full valid 通过 / quote-free 通过）。**对抗性复查 OANDA 模块**：月份计算（`_months_between` + 12 月进位）、分页（`PAGE_SIZE-1` 重叠去重）、resume（非空月跳过）、token 守卫（空 token → `OandaConfigMissing`）逐行核验，逻辑正确。**真实 OANDA 实测受阻（诚实记录）**：moneta 的 token（`config/setting.yml`，gitignored，practice 环境）在 practice 与 live 两个 host 都返回 **401 Insufficient authorization**——token 已过期/吊销（gen-1 旧 token），非代码问题。代码路径已通过 49 离线测试 + `--dry-run` + 真实 clean+DQ 验证；真实拉取需用户提供新 token。**49 测试全绿**（+2），pyflakes 干净。**0002 收口**，0003 就绪 |
