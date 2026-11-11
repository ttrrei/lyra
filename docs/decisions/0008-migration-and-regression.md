# 0008 — 语料迁移 + 回归（回归完成 v0.3）

> **English**: [0008-migration-and-regression.en.md](./0008-migration-and-regression.en.md)
>
> 状态：**v0.3 回归完成（2026-11-11，三裁决落地 + 12 方向 × 21 标的回归 + cross-check，per ACTION_LOG #100）**
> v0.1 的三条推荐裁决（alias 表 / rsi_14 新增 / ATR 基分歧记录）
> **全部被用户 2026-11-11 最终裁决取代**（§2），见 §6 修订记录。

## 1. 范围勘误（为什么重写本文档）

2026-11-10 核查（用户质疑"332 不熟悉"后逐库实数）：

| 旧口径 | 事实 |
|---|---|
| "moneta 留下 332 个策略 YAML" | **错误**。moneta 无任何策略 YAML；132 S 系列是 Python 库（28 个有矩阵结果，3 标的 vs buy-hold）；200 研究批次 = 50 feature × 2 entry_model 模板笛卡尔积、7 句模板 hypothesis、**0 晋级**（纯统计尾部切分，非 AI 策略设计） |
| "332 策略 in-grammar 验证通过" | 实为 nova 仓库 **YAML 文件总数**：17 手写策略 + 146 campaign 实验快照 + 169 manifest/协议/其它 runs YAML |
| 真实独立策略数 | 按内容 sha256 去重约 **162–169**（169 为 0004 的口径：17 + 146 + 少量重复消除） |

**新范围（用户 2026-11-10 裁决，#99）**：

1. O16 20 缺口裁决落地 → 0003 v1.5（§2）
2. 12 方向正式库迁入 `strategies/directions/` + 回归（§3）
3. `strategies/temp/` 门禁（§4，**不进**回归集）
4. `background.md` 勘误（已完成）
5. AI 归类 = **0010**（0008 之后，HLD §8 新增行）

## 2. O16 缺口裁决（20 个语料 feature 名）

权威校验方法：`lyra.features.build_registry()`（134 注册特征）对照
163 个真实策略 YAML（17 手写 + 146 campaign）中出现的全部 feature 名
（24 个不同名，其中 20 个未注册）。

### D 表：逐条裁决（**用户 2026-11-11 三裁决，最终版**）

**裁决 1 — B 类（10）不再做 alias 表，直接改名注册（nova 名为唯一规范名）**：
用户裁决"保留 1 套语料库，优先 nova 名；moneta decom 时 mapping 一起
decom，不做映射表"。即 lyra 的 10 个旧注册名**删除**，改按 nova 语料名
注册（语义核验同 v0.1 表，全部一致）：

| lyra 旧名（删除） | 注册名（nova 规范） |
|---|---|
| `breakout_up` | `breakout_up_24` |
| `breakout_down` | `breakout_down_24` |
| `failed_breakout_up` | `failed_breakout_up_24` |
| `failed_breakout_down` | `failed_breakout_down_24` |
| `prior24_range_pos` | `range_position_24` |
| `path_eff_24` / `path_eff_60` | `efficiency_24` / `efficiency_60` |
| `rel_quote_activity` | `relative_volume_24` |
| `bar_range_atr` | `range_atr` |
| `prior24_width` | `range_width_atr_24` |
| `shift6_atr` | `return_6_atr` |

落地：`features.py` registry 改名（无 alias 层）；134→134 改名，
+9 新增 = **143**；`strategy_schema` / 编译器不动（名字直接查
registry）；moneta 语料名（若有差异）**不做**映射——moneta 在 decom。

**裁决 2 — `rsi_14` 不新增；受影响策略改写为 `rsi_12` 重跑（TODO）**：
用户裁决"rsi14 不新增，留 todo：mean_reversion 用 rsi12 重跑"。
`rsi_12` 已在 K8 网格内注册，零成本。受影响 nova 方向文件（TODO，
迁移 §3 时逐字改写 rsi_14→rsi_12 后重跑）：
`momentum_exhaustion.yaml`（8 处）、`pullback_reentry.yaml`（4 处）、`session_temporal.yaml`（2 处）。注：根级手写文件 `nova/strategies/ema_pullback.yaml`（4 处 rsi_14）不属 12 方向正式库、不在 0008 迁移范围，如需保留同样按 rsi_12 改写。temp/ 中含 rsi_14 的 24 条（实测 validate 失败集）等 0010 triage 时一并处理。

**裁决 3 — ATR 归一化基统一重定基：ATR(14)→ATR(12)（K6 基变更）**：
用户裁决"ATR 参数 14 应按 12 替代，相关策略可重跑"。落地：
- `features.py`：`ATR_NORM 24 → 12`（12 在 K8 网格内；14 在网格外，
  不为语料破格加网格）；
- 受影响 K6 特征（`range_atr` / `range_width_atr_24` / `return_6_atr`）
  分母随之改为 ATR(12)；
- **C 类新特征 `close_ema60_distance_atr` / `close_sma24_distance_atr`
  也统一用 ATR(12) 分母**（nova 原始 ATR(14)/SMA(TR,14) 分母不采用；
  单一基 K6 优先——v0.1 的"已知分歧"注作废）；
- nova 受影响策略（用 ATR-14 系特征的阈值比较）在 §3 迁移重跑后，
  结果漂移属**预期**，记录进 cross-check 报告即可。

**C 类（9）— 真新增，0003 v1.5**：

| 新特征名 | 定义（对齐 nova `features.py` L50-87，分母按裁决 3 统一 ATR(12)） | 类型 |
|---|---|---|
| `psar_direction` | close > SAR ? +1 : −1（SAR 无效处 NaN）；与 {1,0}×2 的 bullish/bearish 值域不等价，**并存** | STATE |
| `supertrend_direction` | supertrend 方向 ±1（同上） | STATE |
| `psar_flip_up` | dir==+1 & dir₋₁==−1（事件布尔，warmup NaN） | EVENT |
| `psar_flip_down` | dir==−1 & dir₋₁==+1 | EVENT |
| `supertrend_flip_up` | 同 flip 语义，supertrend 方向序列 | EVENT |
| `supertrend_flip_down` | 同 flip 语义 | EVENT |
| `ema_alignment_6_24` | sign(ema6−ema24) ∈ {+1,−1,0} | STATE |
| `close_ema60_distance_atr` | (close−ema60)/**ATR(12)** | VALUE |
| `close_sma24_distance_atr` | (close−sma24)/**ATR(12)** | VALUE |

共 **9 个新注册特征 + 10 个改名** → `FEATURE_VERSION` 4→5（I13）。
`rsi_14` 按裁决 2 **不在**本表（不新增）。

## 3. 12 方向正式库迁移

目标结构（0007 H5 命名 `^v\d+[a-z]*$` 自洽）：

```
strategies/directions/<family>/v01.yaml   # 从 nova/strategies/directions/*.yaml 逐字拷贝
```

回归门禁：
1. `lyra validate` 12/12 通过（B 类改名 + C 类新特征就绪后；rsi_14 文件
   按裁决 2 改写为 rsi_12）
2. `lyra run` 12 方向 × 21 标的 × 1h，报告可审（R10 验收的 ≥3 条
   long-only/short-only/long+short 条件由本步满足）
3. 与 nova 同策略 field-for-field cross-check（沿用 0005/0006 方法）

## 3.1 回归执行结果（2026-11-11，#100 收尾）

### 门禁 1：validate ✅
12/12 通过（rsi_14→rsi_12 改写后）。

### 门禁 2：lyra run 12 方向 × 21 标的 × 1h ✅
12/12 方向全部 `OK`（run 归档于 `~/.lyra/runs/directions_*/20261111/`，每方向
21 标的全覆盖、metrics 报告可审）。注：特征表按 v1.5 registry 全 21 标的重算
（`feat-5-40e9ea7b446f8e13`）。

### 门禁 3：与 nova cross-check ⚠️ 完成，但有数据层发现

方法：同一策略（trend_continuation，无 rsi/ATR 漂移项）USD_JPY 全历史对照，
按 entry_time 对齐 902 笔共同入场。

| 字段 | 结果 | 判定 |
|---|---|---|
| direction（同入场时间） | **100% 一致** | 信号逻辑一致 ✅ |
| exit_reason | **100% 一致** | 出场判定一致 ✅ |
| entry_price | 97% 一致，3% 偏移 1 bar（±1 小时内） | 见数据层发现 ⚠️ |
| 交易笔数 | nova 1431 vs lyra 1612 | 数据覆盖差异 ⚠️ |

**数据层发现（非 0008 代码问题）**：lyra 与 nova 的 OHLC 在重叠部分
**逐 bar 完全一致**（USD_JPY 同窗口 OHLC 全等），但：
1. **bar 覆盖不同**：lyra 21 根/日（24h 中有 3 根缺失，如周六全天缺失、
   部分时段缺口），nova 24 根/日。同源性未确认（lyra 的 SPX 甚至出现
   115 根/周的数据，nova 仅 3 根/2 天）。两侧 raw_csv/parquet 来源与
   去重规则不一致——**需数据 owner 裁决**（新 O 项挂起）。
2. 3% 的 entry_price 偏移 1 bar、约 40% 的 bars_held 差异、net_return
   不逐笔相等——均由 bar 覆盖/窗口差异传导（前窗特征值不同 → 信号 bar
   集合不同 → 入场价与持仓时长不同）。**信号方向与出场原因 100% 一致
   证明编译器/交易引擎语义正确**。

**rsi_12 漂移量化（裁决 2 TODO 闭环）**：momentum_exhaustion USD_JPY
全历史——lyra(rsi_12) 177 笔 net −0.0271 vs nova(rsi_14) 168 笔 net
−0.0602。方向同（均负）、量级漂移符合"参数改写"预期，记录在案。
（rsi_14 版如需精确复现，属 0010 对 temp/ 24 条 rsi_14 实验的处置范围。）

**结论**：0008 §3 回归门禁按修订后范围完成；cross-check 的残余差异全部
归因于数据层 bar 覆盖差异（O18，**2026-11-11 已深挖并关闭**——深挖报告 `0008-bar-coverage-analysis.md`：raw 逐字节同源、差异 100% 来自 nova `source_bars<60` 过滤器 + 显示时区假象；**用户裁决以 lyra bar 集为准**，nova 侧结果进入 lyra 必须重算），非 0008 代码
缺陷。0008 可签收。

## 4. temp/ 门禁（不进回归集）

已落地骨架（#99）：`strategies/temp/{README.md,README.en.md,
nova_campaign/(_index.json + 146×{strategy.yaml,meta.json}),
moneta_s_series/(_index.json)}`。

0008 只要求：
1. `lyra validate` 对 temp/ 146 条 YAML 全量跑一遍，**只记录**
   通过/失败统计进报告（不作为门禁 fail）；
2. 改名 + C 类新特征就绪后，temp/ 146 条中失败数应显著下降
   （基线：当前失败于未注册 feature；rsi_14 仍失败——裁决 2，等 0010）。

## 5. 不在 0008 范围

- AI 归类 / promote（**0010**）
- moneta 200 研究批次（确认无迁移价值，档案留 moneta）
- moneta S 系列代码重写（Python 库；0010 triage 只对"值得保留"的
  少数做 YAML 重表达，不在本 feature）
- R10 真实桶验收（维持挂起，#98）

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-10 | 0.1 | 范围修订稿：勘误"332"口径；O16 20 缺口 B/C 重分类（**B 10 alias + C 10 新增**）；补 ATR 归一化基（14 vs 24）已知分歧注；`close_*_distance_atr` 两条入 C 类；temp/ 骨架引用；0010 拆分。 |
| 2026-11-11 | 0.2 | **用户三裁决最终版**（取代 v0.1 推荐预填）：① B 类 10 个**改名**注册（nova 名规范，无 alias 表，moneta 名不映射）；② `rsi_14` **不新增**，受影响 3 个方向文件（momentum_exhaustion/pullback_reentry/session_temporal）改写 rsi_12 重跑（TODO）；③ ATR 归一化基 **24→12**（替代语料 ATR(14)，K6 基变更；C 类距离特征同基）。C 类 10→**9**。注册数 134→**143**；FEATURE_VERSION 4→5。 |
| 2026-11-11 | 0.3 | 回归收尾：§3.1 门禁 1/2/3 执行结果入档（validate 12/12；run 12×21 全 OK；cross-check：direction/exit_reason 100% 一致，entry_price 97% 一致、残余归因数据层 bar 覆盖差异→挂起 O18；rsi_12 漂移量化入档）。 |