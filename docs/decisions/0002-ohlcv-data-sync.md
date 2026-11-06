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
lyra pull [--data-root DIR]     # 拉取原始 OHLCV（zip/CSV）→ 本地 data/
lyra clean  (内部步骤)          # 校验 schema + 落 bronze 1m Parquet
lyra aggregate (内部步骤)       # 1m → 5m / 1h（UTC 边界，n_bars 标记）
```

**代码新增**：

| 文件 | 职责 |
|---|---|
| `lyra/config.py` | 加载 `config/config_example.yml` 结构（真实值在本地 `config.yml`） |
| `lyra/oci_client.py` | PAR 列对象（分页）+ 对象下载（流式、retry、size 幂等、path-traversal 防护）——机制沿用 moneta |
| `lyra/pull.py` | 拉取 + 解压 + 扁平化（moneta `extract_all_zips_to_csv` 等价） |
| `lyra/clean.py` | schema 校验 → bronze 1m Parquet（列契约见 §3.3） |
| `lyra/aggregate.py` | 1m → 5m/1h（moneta 等价，`n_bars` 保留） |
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

- **输入契约**：OCI 上为 zip 归档，内含 CSV（moneta 同构：
  `instrument,time,mid_o,mid_h,mid_l,mid_c,volume`，UTC 时间，
  1m 粒度，instrument 命名继承 moneta `BASE_QUOTE`，O14）。
- **输出契约**：
  - `data/raw_zips/`（原始归档，重放来源）、
  - `data/raw_csv/`（扁平 CSV）、
  - `data/all_data/all_data.parquet`（bronze 1m）、
  - `data/ohlcv_5m/`、`data/ohlcv_1h/`（聚合，含 `n_bars`）。
  全部在 `~/.lyra/<workspace>/` 或 `--data-root` 指定处（B13），
  **永不进 git**（B1）。
- **凭证边界**：PAR URL 只出现在 `config.yml`（gitignored）；
  日志 / 报告 / run 摘要中**永不打印完整 PAR URL**（含签名参数）。
- **alpha 边界**：本 feature 不碰 `alpha/`、不碰策略、不碰
  `strategies/examples/`。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I? | 同一 PAR 内容 + 同一代码版本 → 本地 Parquet 逐字节可复现（pull/clean/aggregate 全确定性，无随机、无时钟写入数据） | 本 feature 新增（R8 在数据层的具体化） |
| I? | PAR URL 永不进入 git、日志、run 报告（脱敏为 host + path 前 2 段） | 0001 凭证边界延伸 |
| I? | 对象下载幂等（size 一致即跳过），重跑不改变已有本地文件 | moneta 已验证机制 |
| I? | 聚合只用 UTC 边界 + 窗口内已有 1m bar；`n_bars` 如实标记部分 bar | moneta `aggregate_ohlcv` |
| I1 | YAML 是唯一策略语言 | HLD §4（本 feature 不碰策略，天然满足） |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_oci_list_pagination` | 分页列表：多页 `nextStartWith` 取全、循环保护 |
| `test_oci_download_idempotent` | 已存在且 size 一致 → 跳过、不发请求 |
| `test_oci_unsafe_name_rejected` | `../evil`、绝对路径、`a:/b` 对象名被拒；`EUR..USD.csv` 合法通过 |
| `test_pull_zip_to_flat_csv` | 嵌套 zip → 扁平 CSV；冲突 `_N`；重跑清旧 |
| `test_clean_schema_validation` | 缺列 / 类型错 → 明确报错；全绿 → bronze Parquet |
| `test_aggregate_5m_1h_utc` | 跨 5m/1h 边界的开高低收正确；`n_bars` 标记部分 bar |
| `test_aggregate_deterministic` | 同输入两次运行 Parquet 逐字节一致 |
| `test_par_expiry_diagnostic` | 403/404 → 报错含 "PAR may have expired" 提示（O5） |
| `test_par_url_redacted_in_logs` | 日志 / 异常消息中无完整 PAR URL |

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
