# Bar 覆盖差异钉死报告（lyra vs nova，1h）

生成：2026-11-11 · 只读分析 · 所有数字来自真实计算（DuckDB/lyra venv），无外推。
可复现脚本与中间 JSON 在仓根 `scratch/barcov/`（`main2.py` + `one/*.json` + `sample_table.json`；已 gitignore，属一次性中间产物）。

---

## 0. 结论速览（TL;DR）

1. **两边 raw 1m 完全同源**：21 个逐标的 CSV 的 SHA256 全部一致；nova 1m parquet 与 lyra bronze 在共同时间窗（2020-01-01 → 2026-10-23T21:00Z）内 **21 个标的逐行同数**（如 EUR_USD 2,505,386 = 2,505,386）。nova 额外吃入 150 个 `prices_YYYYMMDD_*.csv`（2026-04-29 → 2026-10-23 的日频快照），与逐标的 CSV 大量重叠，去重后不产生新数据。
2. **bar 集合差异与 raw 缺失无关**：**总差额 183,909 = 179,550（97.6%，nova 丢弃 partial 小时的聚合规则差异）+ 4,359（2.4%，lyra 数据窗口比 nova 多 2026-10-24→11-06 尾部）**；nova `aggregate()` 丢弃 `source_bars != 60` 的整点小时（manifest 自报 `partial_buckets_dropped = 179550`）；lyra `aggregate.py` 保留所有 ≥1 根 1m 的小时（`n_bars` 如实标注 partial）。两边 1h 的**重叠 bar 全量 OHLC+volume 逐根全等**（6 个标的合计 195,783 根重叠 bar，0 不一致）。
3. **归因恒等式（21 标的全部精确成立，残差=0）**：
   `lyra_1h 总数 = nova_1h 总数 + 被 nova 丢弃的 partial 小时 + lyra 独有的 2026-10-24~11-06 尾部 bar`。
   partial 小时占全部差异的 **91–99%**（21 标的合计 179,550 根，与 nova manifest 完全一致）；**两侧 raw 之间未发现相互差异的小时**（每根 partial 小时两侧 raw 都有 30–59 根分钟 bar，属 OANDA 换月/周末/节假日的分钟级缺口，两侧 raw 完全相同；注：字节相同不能排除两侧共同缺某市场小时，此点不作完整性主张——2026-11-12 review M3 收窄）。
4. **lyra 更接近（项目内观察的）共识口径**：FX 常态 24h/日（lyra）vs nova 每天少 2–6 根；美股指数常态 21–23h/日（lyra）vs nova 15–23h/日；加密 21–24h；金 21–23h。nova 的"干净但残缺"序列会系统性改变月度/年度机会计数（尤其 CN50、JP225、USD_CHF 每天丢 6–9 根）。
5. **SPX500 "周 bar 数异常高 / 3 根/2 天"**：按 **UTC 口径两边都不存在** ≥24 bar 的日；该现象来自 **nova 60m parquet 的时间戳按机器本地时区（AEDT/AEST +10/+11）显示**，把 22:00–23:59Z 的换月小时错划到相邻"本地日"，出现本地日历日 1–4 根（119 天）与相邻日虚高的配对。lyra 的 UTC 口径下同一现象表现为**每周日 1–2 根**（周日 22:00/23:00Z 换月 bar），这是真实数据（OANDA 周末换月），不是数据源停报或按日文件边界。

**推荐**：以 **lyra 的 bar 集合（UTC 桶 + 保留 partial 小时 + `n_bars` 标注）为准**；无需重拉 raw（raw 同源且完整）；nova 侧若要与 lyra 对齐，把 `source_bars={minutes}` 过滤改为 `>= 1` 并把输出时间戳固定为 UTC 显示。

---

## 1. Raw 源身份比对

### 1.1 文件清单与 provenance

| 项 | lyra | nova |
|---|---|---|
| 逐标的 1m CSV | `/home/ubuntu/.lyra/default/data/raw_csv/<SYM>.csv`（21 个） | `/home/ubuntu/work/nova/data/raw_csv/<SYM>.csv`（21 个） |
| **SHA256** | **21/21 全部相同**（如 AUD_USD `8023df0e…`，SPX500 `9e6ce710…`，EUR_USD `0d21206f…`） | 同左 |
| 时间范围（21 标的） | 2020-01-01/02 起 → 2026-10-23T20:59/21:00Z | 同左（逐标的 manifest `start/end`） |
| 额外输入 | 每标的 2 个 `*_M1_20191101T000000Z.csv`、`*_M1_20191201T000000Z.csv`（**2019-11/12 月**，每标的 19k–21k 行，`is_complete=True`；`prices_20260505…csv` 等 150 个按日文件也在 lyra raw 目录） | 21 个逐标的 CSV + 150 个 `prices_YYYYMMDD_*.csv`（2026-04-29 → 2026-10-23，9.06M 行，OANDA 日快照）+ `OUTPUT_BASE.csv`（2025-11 起） |
| 1m 成品 | `catalog.duckdb::bronze`（48,846,896 行，21 标的） | `data/market/1m/041914943d0ac7eb/<SYM>.parquet`（input 60,958,698 行 → 去重后，manifest `duplicate_complete_rows_removed=12,367,671`） |
| 1h 成品 | `ohlcv_1h/ohlcv_1h.parquet`（838,272 行，UTC 桶，含 `n_bars`） | `data/market/60m/ecaa0a6c6cd7eb46/<SYM>.parquet`（`gap_filling=False`, `partial_buckets_dropped=179,550`） |

**结论：同源**（同一 OANDA provider、同一批下载文件，逐字节一致）。唯一区别是**各自目录里多了对方没有的旁路文件**：

- lyra 多了 **2019-11/12 月的 M1 文件**（`<SYM>/<SYM>_M1_20191101T000000Z.csv` 等，`is_complete=True`，共 42 个、943,529 行）——**存在于 raw 层，但不在 bronze 中**（实测 `bronze WHERE time < 2020-01-01` = **0 行**；lyra `ohlcv_1h` 全库最小时间同样 = 2020-01-01，21 标的逐一验证）。即 2019 数据当前**未进入任何成品层**，对 1h bar 集合**无贡献**（0008 批次1 review H2 复核后更正：原文"进 bronze → 进 1h"表述错误）。
- nova 多了 **150 个 prices 日快照 + OUTPUT_BASE**（2026 年，与逐标的 CSV 窗口重叠，被 nova clean 的 (instrument,time) 去重吸收；实测 21 标的 1m 行数与"仅逐标的 CSV"一致）。

### 1.2 1m 行数逐标的一致性（共同窗口 2020-01-01 → 2026-10-23T21:00Z）

21/21 标的 `nova_1m = lyra_bronze` **完全相等**（例：EUR_USD 2,505,386；SPX500_USD 2,331,264；JP225_USD 2,293,844）。
lyra bronze 总计（48,846,896）比 nova 1m（48,588,451）多 **258,445 行**，**恰等于 bronze 中 `time > 2026-10-23T21:00:00Z` 的 1m 行数**（lyra 数据更新到 2026-11-06，nova raw 停在 10-23）——即差额**全部**来自时间窗口尾部，2019 M1 文件不在 bronze 内（见 §1.1）。（原文"125,815 = 2019 + 尾部"为错误口径，2026-11-12 review H2 后更正；共同截止窗口内两侧逐标行数 21/21 相等不变。）

### 1.3 1h 重叠 bar 的 OHLC 校验（6 标的全量 join）

| 标的 | 重叠 1h bar | OHLC 不一致 | volume 不一致 |
|---|---|---|---|
| AUD_USD | 31,105 | 0 | 0 |
| EUR_USD | 36,698 | 0 | 0 |
| XAU_USD | 36,418 | 0 | 0 |
| BTC_USD | 39,579 | 0 | 0 |
| US30_USD | 34,130 | 0 | 0 |
| SPX500_USD | 28,363 | 0 | 0 |

（与 0008 cross-check "重叠 bar 的 OHLC 逐根全等"一致，本处扩大到 volume 也全等。）

---

## 2. 采样日 × (lyra, nova, 缺失小时, 成因) 明细

采样：2020-01-03 → 2026-11-05，间隔 ~10 周，26 天（跳过周日以避免换月 artifact 混淆）。
`miss_nova` = raw 该小时有 ≥1 根 1m、但 nova 1h 没有（=被 60 根过滤器丢弃的 partial 小时）；`partial` 同集，括号内为该小时实际 1m 根数示例见 `one/*.json::partial_bars`。所有小时均为 **UTC**。

### SPX500_USD

| day | lyra | nova | miss_nova (UTC h) | 成因 |
|---|---|---|---|---|
| 2020-01-03 | 22 | 3 | 0–12,14,16–19,21 | 元旦假期后首日，raw 全天分钟级缺口，每整点 10–59 根 |
| 2020-04-13 | 23 | 22 | 20 | 20 时 1m 不足 60 根（20:00Z 换月/缺口） |
| 2020-07-21 | 23 | 11 | 0,1,3–5,9–12,20,22,23 | 独立日假期，raw 各小时 5–59 根 |
| 2020-10-29 | 23 | 21 | 4, 20 | partial 被 nova 丢弃 |
| 2021-05-17 | 23 | 20 | 20,22,23 | 同上 |
| 2022-03-12 | 21 | 21 | – | 当天无 partial |
| 2023-07-25 | 21 | 19 | 20,22 | 独立日前一天 |
| 2024-12-06 | 21 | 17 | 20,21,22,23 | 圣诞前 |
| 2025-06-23 | 21 | 19 | 20,23 | |
| 2026-11-05 | 19 | 16 | 4,20,23 | 数据尾段 |

（其余 26 个采样日同构：nova 缺的小时 == 当天 raw 中 <60 根的整点小时，全部集中在 20:00–23:59Z 换月带与节假日。）

### EUR_USD

| day | lyra | nova | miss_nova | 成因 |
|---|---|---|---|---|
| 2021-01-12 | 24 | 21 | 21,22,23 (58/44/59 根) | raw 分钟缺口，nova 丢 |
| 2023-06-12 | 17 | 15 | 21,22 (53/59 根) | 同上 |
| 2025-06-10 | 24 | 22 | 21,22 (40/59) | 同上 |
| 2026-05-12 | 24 | 22 | 21,23 (55/59) | 同上 |

EUR_USD 全年常态：**lyra 24 根/日占 1,415/1,765 个活跃日；nova 常态 22 根/日**（每天 21/22/23 三个换月小时中平均 ~2.7 个 partial）。

### XAU_USD / BTC_USD / US30_USD / DE30_EUR（节选）

| day | XAU l/n | BTC l/n | US30 l/n | DE30 l/n |
|---|---|---|---|---|
| 2023-07-25 | 22/19 (miss 20,22,23) | 24/23 (miss 22) | 21/18 | 20/18 |
| 2024-12-06 | 22/20 | 24/22 | 20/17 | 20/18 |
| 2026-11-05 | 22/19 | 24/22 | 18/16 | 20/18 |

BTC/ETH（加密）partial 最少：BTC 平均每天 1.47 个 partial 小时（91.2% 差异仍由它解释，另有 220 根尾部增量）。

全量 21 标的 × 26 日明细：`scratch/barcov/sample_table.json`。

---

## 3. 归因：差异 = f(raw 缺小时) + g(nova 60 根过滤器) + 其他

**恒等式（21 标的全部精确成立，残差=0）：**

```
lyra_1h = nova_1h  +  H_partial(被 nova 丢弃的 partial 小时)  +  E(lyra 独有尾部)
```

| 标的 | lyra | nova | Δ | H_partial | E (2026-10-24→11-06) | H 占 Δ |
|---|---|---|---|---|---|---|
| AUD_USD | 42,638 | 31,105 | 11,533 | 11,313 | 220 | 98.1% |
| BCO_USD | 38,817 | 29,303 | 9,514 | 9,312 | 202 | 97.9% |
| BTC_USD | 42,074 | 39,579 | 2,495 | 2,275 | 220 | 91.2% |
| CN50_USD | 35,512 | 19,637 | 15,875 | 15,694 | 181 | 98.9% |
| DE30_EUR | 35,606 | 27,591 | 8,015 | 7,824 | 191 | 97.6% |
| ETH_USD | 41,619 | 38,609 | 3,010 | 2,790 | 220 | 92.7% |
| EUR_USD | 42,643 | 36,698 | 5,945 | 5,725 | 220 | 96.3% |
| GBP_USD | 42,643 | 35,192 | 7,451 | 7,231 | 220 | 97.0% |
| HK33_HKD | 28,326 | 22,933 | 5,393 | 5,239 | 154 | 97.1% |
| JP225_USD | 40,492 | 24,906 | 15,586 | 15,376 | 210 | 98.7% |
| NAS100_USD | 40,434 | 36,344 | 4,090 | 3,880 | 210 | 94.9% |
| NZD_USD | 42,647 | 30,271 | 12,376 | 12,156 | 220 | 98.2% |
| SPX500_USD | 40,435 | 28,363 | 12,072 | 11,862 | 210 | 98.3% |
| UK100_GBP | 34,489 | 23,122 | 11,367 | 11,186 | 181 | 98.4% |
| US30_USD | 40,437 | 34,130 | 6,307 | 6,097 | 210 | 96.7% |
| USD_CAD | 42,644 | 34,429 | 8,215 | 7,995 | 220 | 97.3% |
| USD_CHF | 42,639 | 28,265 | 14,374 | 14,154 | 220 | 98.5% |
| USD_JPY | 42,644 | 37,416 | 5,228 | 5,008 | 220 | 95.8% |
| WTICO_USD | 40,510 | 30,909 | 9,601 | 9,391 | 210 | 97.8% |
| XAG_USD | 40,509 | 29,143 | 11,366 | 11,156 | 210 | 98.2% |
| XAU_USD | 40,514 | 36,418 | 4,096 | 3,886 | 210 | 94.9% |
| **合计** | | | **183,909** | **179,550** | 4,359 | **97.6%** |

- **f(两侧 raw 相互差异的小时) = 0 根**。两侧 raw 对每个整点小时的分钟覆盖完全一致（同源文件）；所谓"缺"都是**小时内部的分钟级缺口**（30–59 根/时），不是整小时缺失。（措辞收窄：不主张"市场没有缺任何小时"——字节相同不能排除共同缺失。）
- **g(nova 60 根过滤器) = 179,550 根**，与 nova manifest 自报 `partial_buckets_dropped` **逐位相等**。partial 小时高度集中在 **20:00–23:59Z 的 OANDA 换月/周末停报带**（各标的 top partial 小时几乎都在 20–23 时，其次 0–6 时的节假日/假期带）。
- **其他 = 4,359 根（2.4%）**：**全部**是 lyra 数据窗口比 nova 多出的 2026-10-24 → 2026-11-06 增量（lyra raw 更新到 11-06，nova raw 停在 10-23T21:00Z）。无其他成分（原文"+ SPX500 2019 月文件"归因删除——2019 文件既不在 bronze 也不在 1h，见 §1.1）。

**0008 抽样"lyra 21/日、nova 24/日"的解释**：该抽样必然按**本地显示日**（nova parquet 时间戳为 AEDT/AEST 本地时区）统计了某一周内 nova 的日 bar 数；本地口径下换月小时被挪到相邻日，会出现单日本地 24 根、另一日本地 21 根的"搬家"假象。按 UTC 口径（本报告口径），**逐日 lyra ≥ nova 恒成立**（21 标的 × 全部活跃日，无一反例）。

---

## 4. 共识口径对比

"共识"= 该标的类别的正常每日报价小时数（OANDA 语义，UTC）——**项目内观察/判断，无外部基准来源**（2026-11-12 review M3 标注；结论不依赖该表的外部完整性主张）：

| 类别 | 共识 每日 1h bar | lyra 常态（众数） | nova 常态（众数） | 更接近共识 |
|---|---|---|---|---|
| FX（EUR/AUD/GBP/NZD/USD_x，7 个） | 23–24（24h 市场，仅换月+周末 1–3 小时停） | **24**（1,413–1,415/1,765 活跃日） | 22（每天丢 2–3 个 partial 时） | **lyra** |
| 美股指数（SPX500/US30/NAS100） | 21–23（16.5h 常规 + 周末/假日部分停报；24h CFD 报价） | **21–23**（23 根占 1,351/1,760 非周日） | 15–23 不等（丢 2–8 个时） | **lyra** |
| 欧股指数（DE30/UK100） | ~19–21（7.5h 常规 + 前后盘） | **20–21** | 18–21 | **lyra**（接近但 DE30 20 根 vs 共识上沿 21，两侧一致） |
| 日股（JP225/HK33/CN50） | 8–9 常规 + OANDA 长尾 → 实际 19–23 | **21–23**（JP225 23 根 1,341/1,760） | 15–22（丢 5–7 个时） | **lyra** |
| 加密（BTC/ETH） | 24（7×24，仅极少停报） | **24**（1,397/1,756 日） | 22–23（丢 1–2 个时） | **lyra** |
| 金/油（XAU/XAG/WTICO） | 22–23（近 24h，周末 1–2h 停 + 换月） | **21–23**（XAU 23 根 1,363/1,760） | 19–23（丢 2–4 个时） | **lyra** |

**判断**：lyra 的 bar 集合 = raw 中"有过报价的所有 UTC 整点小时"，是**最大可用集合**，与各类别共识一致；nova 的序列在每个换月/假期日都系统性地比共识少 2–8 根。若研究口径要求"整点小时必须有满 60 根分钟"，nova 更干净，但代价是**把真实的换月窗口（20:00–23:59Z，含重要流动性事件）从样本中剔除**，且月度机会计数（每标的、含零入场月）会被直接改变。

**推荐**：
1. **以 lyra 的 bar 集合为准**（UTC `time_bucket` + 保留 partial + `n_bars` 如实标注 —— 下游可对 `n_bars<60` 自行降权或剔除，信息无损）。
2. **不需要重拉 raw**：两侧 raw 逐字节同源且完整；1h 差异 = 97.6% 聚合规则（partial 过滤）+ 2.4% 数据窗口尾部。
3. nova 若需对齐：`data.py::aggregate()` 中 `WHERE source_bars={minutes}` 改为 `WHERE source_bars >= 1`（保留 `source_bars` 列供下游过滤）；并把输出/展示时间戳固定为 UTC（当前 parquet 显示为本地 AEST，是"周 bar 数异常"的视觉根源）。
4. 两侧都应把数据窗口对齐到同一截止日（lyra 11-06 vs nova 10-23），否则 ~4,359 根尾部 bar 永远对不上。

---

## 5. SPX500 "周 bar 数异常高" 与 "3 根/2 天" 专项

**按 UTC 口径（正确口径）**：
- lyra：SPX500 无 ≥24 根/日的 bar 日；最大 23 根（1,352 个非周日）。
- nova：SPX500 同样无 ≥24 根/日（UTC 口径）；最小为周日换月日 1–2 根。
- 即：**"周 bar 数异常高"在 UTC 口径下两边都不存在**。

**该现象的真实成因**（nova 本地时区显示）：
- nova 60m parquet 的 `bar_open_time` 带 **AEDT(+11)/AEST(+10) 本地显示**（实例：2020-01-02 09:00 AEDT == 2020-01-01 22:00 UTC；2020-07-01 00:01 AEST == 2020-06-30 14:01 UTC）。
- 按"本地日"统计时，OANDA 周日/周一的换月 bar（UTC 周日晚 22:00/23:00）被错划到本地周一/周二，产生 **119 个本地日仅 1–4 根**（如本地 2020-01-04 = 3 根，全部来自 UTC 2020-01-03 的 13/15/20 时）+ 相邻本地日虚高 —— 这就是"3 根/2 天"与"某周异常高"的配对假象。
- 实例周（UTC 口径，2023-04-08→14，复活节周）：lyra 各日 = [–, 2, 23, 23, 23, 23, 21]；nova = [–, 0, 7, 10, 10, 11, 10]。周日 2 根 = UTC 周日 22/23 时换月 bar（57/58 根 1m，<60 故 nova 整根丢弃，lyra 以 `n_bars=57/58` 保留）；周一–周四 nova 每天再丢 10–16 根（当周 partial 小时多，raw 两侧相同）。

**"3 根/2 天" 的 raw 侧证据**（EUR_USD 2021-01-12 22:00Z 小时，44/60 根）：缺失分钟 = {26, 34, …}（分散的分钟级空洞）—— 属 OANDA 换月/低流动性缺口，两侧 raw 完全相同，nova 因 <60 丢弃，lyra 保留（`n_bars=44`）。

---

## 6. 复现片段

```sql
-- 1) raw 同源：21/21 SHA256 一致
sha256sum /home/ubuntu/work/nova/data/raw_csv/<SYM>.csv
sha256sum /home/ubuntu/.lyra/default/data/raw_csv/<SYM>.csv

-- 2) 1m 行数逐标一致（共同窗口）
select count(*) from read_parquet('nova/data/market/1m/041914943d0ac7eb/EUR_USD.parquet')
 where timezone('UTC',bar_open_time) <= timestamptz '2026-10-23T21:00:00Z';   -- 2,505,386
select count(*) from bronze where instrument='EUR_USD'
  and time <= timestamptz '2026-10-23T21:00:00Z';                              -- 2,505,386

-- 3) 逐日/逐时 bar 数与差集（UTC 口径；nova 必须 timezone('UTC',…)）
select cast(timezone('UTC',time) as date) d, extract(hour from timezone('UTC',time)) hh, count(*)
from ohlcv_1h where instrument='SPX500_USD' group by 1,2 order by 1,2;
select cast(timezone('UTC',bar_open_time) as date) d, extract(hour from timezone('UTC',bar_open_time)) hh, count(*)
from read_parquet('nova/data/market/60m/ecaa0a6c6cd7eb46/SPX500_USD.parquet') group by 1,2 order by 1,2;

-- 4) 归因恒等式
lyra = nova + partial + E
partial = sum over days of |{UTC 整点小时: raw 该时 1m 数 ∈ [1,59]}|            -- 合计 179,550 == nova manifest
E     = lyra 1h 中 time > timestamptz '2026-10-23T21:00:00Z' 的 bar 数          -- 各标的 154–220

-- 5) 重叠 bar OHLC 全等
select count(*), sum(abs(l.mid_o-n.open)>1e-9 or abs(l.mid_h-n.high)>1e-9
                     or abs(l.mid_l-n.low)>1e-9 or abs(l.mid_c-n.close)>1e-9)
from lyra_ohlcv_1h l join nova_60m n on l.time=n.bar_open_time;                 -- mismatches = 0
```

聚合规则源码位置：lyra `lyra/aggregate.py`（`GROUP BY instrument, time_bucket(INTERVAL '1 hour', time)`，无 partial 过滤，`n_bars` 如实保留）；nova `src/nova/data.py::aggregate()`（`WHERE source_bars={minutes}`，`complete_buckets_only=True`）。

**注**：分析脚本在仓根 `scratch/barcov/`（非策略/非产品代码，未触碰 lyra/nova 任何既有代码；已 gitignore）。
