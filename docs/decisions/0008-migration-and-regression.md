# 0008 — 语料迁移 + 回归（范围修订版 v0.1）

> **English**: [0008-migration-and-regression.en.md](./0008-migration-and-regression.en.md)
>
> 状态：**待写 → 范围修订稿 v0.1（2026-11-10，per ACTION_LOG #99）**
> 上一版范围（"332 策略迁移"）已被勘误取代，见 §1。

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

### D 表：逐条裁决（本稿按推荐预填，实现前需用户最终确认）

**B 类（10）— 同物异名，alias 表映射，不改已注册名**：

| 语料名（nova） | lyra 现名 | 语义核验 |
|---|---|---|
| `breakout_up_24` | `breakout_up` | close > prior24 high，一致 |
| `breakout_down_24` | `breakout_down` | close < prior24 low，一致 |
| `failed_breakout_up_24` | `failed_breakout_up` | wick 穿 prior high 收盘回内，一致 |
| `failed_breakout_down_24` | `failed_breakout_down` | 一致 |
| `range_position_24` | `prior24_range_pos` | (close−prior_low)/prior_range，一致 |
| `efficiency_24` | `path_eff_24` | \|Δc\|/Σ\|Δc\|，一致（lyra 注释即 nova efficiency 契约） |
| `relative_volume_24` | `rel_quote_activity` | volume/SMA(volume,24)，一致 |
| `range_atr` † | `bar_range_atr` | 公式同 (h−l)/ATR，但 **ATR 基不同**（†） |
| `range_width_atr_24` † | `prior24_width` | 公式同 prior_range/ATR，**ATR 基不同**（†） |
| `return_6_atr` † | `shift6_atr` | 公式同 \|c−c₋₆\|/ATR，**ATR 基不同**（†） |

† **ATR 归一化基分歧（已知，记录在案）**：nova 用 **ATR(14)**
（`close_sma24_distance_atr` 甚至用 SMA(TR,14)），lyra 按 K6 用
**ATR(24)**。三行 † 特征的数值域因此**不逐点相等**——策略里的阈值
比较（如 `range_atr < 1.5`）行为会轻微漂移，属 O-0005-1 同类"已知
分歧"，随 cross-check 记录，**不**视为 alias 错误。若 0010 triage
发现某策略结果对该分歧敏感，再决定是否注册 ATR-14 变体（默认不）。

B 类落地方式：在 `strategy_schema.py` 增加 **alias 表**（语料名 →
注册名），编译器先查 alias 再查 registry；**不**改 134 个已注册名
（R11：17 个已注册 feature 名不变）。

**C 类（10）— 真新增，0003 v1.5**：

| 新特征名 | 定义（对齐 nova `features.py` L50-87） | 类型 |
|---|---|---|
| `psar_direction` | close > SAR ? +1 : −1（SAR 无效处 NaN）；lyra 的 bullish/bearish 是 {1,0}×2，值域不等价 | STATE |
| `supertrend_direction` | supertrend 方向 ±1（同上，不等价于 bullish/bearish） | STATE |
| `psar_flip_up` | dir==+1 & dir₋₁==−1（事件布尔，warmup NaN） | EVENT |
| `psar_flip_down` | dir==−1 & dir₋₁==+1 | EVENT |
| `supertrend_flip_up` | 同 flip 语义，supertrend 方向序列 | EVENT |
| `supertrend_flip_down` | 同 flip 语义 | EVENT |
| `ema_alignment_6_24` | sign(ema6−ema24) ∈ {+1,−1,0} | STATE |
| `close_ema60_distance_atr` † | (close−ema60)/ATR(14)（nova L69；† ATR 基同 B 类注） | VALUE |
| `close_sma24_distance_atr` † | (close−sma24)/SMA(TR,14)（nova L66-68，分母是 TR 均值非 ATR） | VALUE |
| `rsi_14` | RSI(14)（TA-Lib，K8 网格外特例：语料兼容） | VALUE |

共 **10 个新注册特征** → `FEATURE_VERSION` 4→5（I13）。
`close_*_distance_atr` 按 nova 原始分母实现（ATR-14 / SMA(TR,14)），
不套 lyra 的 atr_24 基——它们是 C 类新特征，有完整实现自由度，
**不做**归一化基替换。
`ema_alignment_6_24` 与 `rsi_14` 在 B/C 边界：**按真新增处理**（lyra
没有对应物）。

> 注：`rsi_14` 是 K8 网格（6/12/24/60/120）外的参数值。裁决依据：
> 语料兼容优先；若用户拒绝破格，改为 alias `rsi_14 → rsi_12` 不可行
> （参数语义不同），则该策略 YAML 需改写——0010 triage 时按 drop 处理。
> **默认：新增 rsi_14。**

## 3. 12 方向正式库迁移

目标结构（0007 H5 命名 `^v\d+[a-z]*$` 自洽）：

```
strategies/directions/<family>/v01.yaml   # 从 nova/strategies/directions/*.yaml 逐字拷贝
```

回归门禁：
1. `lyra validate` 12/12 通过（B 类 alias + C 类新特征就绪后）
2. `lyra run` 12 方向 × 21 标的 × 1h，报告可审（R10 验收的 ≥3 条
   long-only/short-only/long+short 条件由本步满足）
3. 与 nova 同策略 field-for-field cross-check（沿用 0005/0006 方法）

## 4. temp/ 门禁（不进回归集）

已落地骨架（#99）：`strategies/temp/{README.md,README.en.md,
nova_campaign/(_index.json + 146×{strategy.yaml,meta.json}),
moneta_s_series/(_index.json)}`。

0008 只要求：
1. `lyra validate` 对 temp/ 146 条 YAML 全量跑一遍，**只记录**
   通过/失败统计进报告（不作为门禁 fail）；
2. alias 表 + C 类新特征就绪后，temp/ 146 条中失败数应显著下降
   （基线：当前全部失败于未注册 feature）。

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
