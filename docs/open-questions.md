# 开放问题（Live Questions）

> **English**: [open-questions.en.md](./open-questions.en.md)
>
> 这份文档是**活的**：每个问题要么被决策文档关掉，要么被升级成
> 新的决策文档。不要在这里做决策（决策进 `docs/decisions/`）。

## 当前开放

| # | 问题 | 倾向 | 状态 |
|---|---|---|---|
| O1 | snapshot_id 用整数还是时间戳？ | **定案（0002 v0.5）**：0002 **放弃目录级 snapshot_id**，采用**单文件外部表**（`all_data.parquet` / `ohlcv_5m.parquet` / `ohlcv_1h.parquet`）+ DuckDB catalog 命名视图；数据版本溯源以 **raw 层 OCI 对象 md5** 为唯一事实来源（I20）。整数 vs 时间戳的选型问题**随机制废弃而关闭**（批次7 D4：此前 ACTION_LOG 宣称已关闭但本文档仍留白，属文档断层） | **已关闭**（`0002` v0.5 + 批次7 D4） |
| O2 | `runs/` 按 strategy_id 还是按日期分组？ | **定案（0007 D7，用户裁决 2026-11-10）**：OCI 规范布局取 **`runs/<direction>/<track_id>/<run_id>/`**（对齐 R12 tracks，按方向 + track 分组，非日期/strategy_id）；0006 的**本地工作区**布局 `runs/<name>/<YYYYMMDD>/<run_id>/` 保持不变（暂存区），`push` 负责映射到规范 OCI 路径 | **已定案**（`0007` D7，实现期落地） |
| O3 | alpha feature 按 family 分子目录吗？ | 不（文件名=注册名） | 待 `0003` 决策 |
| O4 | `index/*.json` 进 git 作为只读镜像吗？ | 不进（0001 I15：`runs/` 全部 + alpha 路径不进 git；index 是派生物，可重建） | **已关闭**（0001） |
| O5 | PAR URL 90 天过期怎么办？ | **定案（0002）**：PAR 由用户侧管理（过期重新生成、更新 `config.yml`）；`lyra pull` 遇 403/404 给出"PAR may have expired"诊断；`lyra-doctor`（0009）常规体检检测 PAR 可用性 | **已关闭**（`0002` §2） |
| O6 | 支持 S3 / GCS 吗？ | 不 | 已关（OCI 唯一） |
| O7 | feature-vs-feature 比较放宽后，332 策略里有几个用到？ | 0（全部是 feature-vs-constant） | 待 `0004` 验证 |
| O8 | supertrend 的 contract card + golden test 样例先做哪个？ | supertrend（最复杂） | 待 `0003` 决策 |
| O9 | 本地 `strategies/examples/` 放几个开源示例？ | 3（trend_hold / ema_pullback / mean_reversion） | 待 `0009` 决策 |
| O10 | `lyra-doctor` 要检查哪些项？ | 见下 | 待 `0009` 决策 |
| O11 | 跨代交叉的代数如何计算？（如 v02a × v04b 的新分支算第几代？） | **已定（用户）**：算**最新一代的下一代**，即 `max(parent 代数) + 1`（v02a×v04b → 第 5 代） | **已关闭**（用户 2026-11-06） |
| O12 | 同父母多变异方案 / 同策略不同参数的命名如何区分？ | **已定（用户）**：所有版本名后可追加 `_1` `_2` … 序号，用于区分相同策略的不同参数 / 不同变异方案（如 `v04ab_1`、`v04ab_2`） | **已关闭**（用户 2026-11-06） |
| O13 | 并发活跃分支数上限（Active Branch Cap）？ | **2026-11-06 定案（用户）：每方向全局 8**（防 AI 靠无限 fork 规避 kill criteria；超额必须显式 prune）。**2026-11-08 用户裁决修订：cap 按 track 计，每 track 8 个 active branches，tracks 之间互不挤占**（"互不影响"优先；取代 11-06 的方向级全局语义）。落点：requirements R12（v0.16）、oci-alpha-layout §2.3、综合稿 §9 | **已关闭（2026-11-06 定案；2026-11-08 修订语义，终态）** |
| O14 | 标的代码清单与标识规范？ | **已定（用户）**：代码格式**继承 moneta** 的 `BASE_QUOTE` 约定（`XAU_USD`/`XAG_USD`/`EUR_USD`/`BTC_USD` 等，非 `GOLD`/`WTI`）；moneta 无单一 21 标的清单文件，**权威完整清单在 0002 数据同步时从 moneta 实际数据文件枚举确认** | **已关闭**（用户 2026-11-06；清单枚举归 0002） |
| O15 | `financing_per_day` 的 "elapsed day" 如何定义？ | **已定（用户）**：严格按**交易日**计，**周末不计**，**新年/圣诞等市场节假日也不计**（即 elapsed = 持仓区间内的交易日数，非物理日历天） | **已关闭**（用户 2026-11-06） |
| O16 | 332 legacy 策略引用的 feature 中，**20 个不在 lyra 0003 registry**（326/332 至少引用 1 个缺失项）。是否扩展 0003？ | **0004 实施时核实（2026-11-08）**：lyra registry 仅 134 feature；332 策略引用 24 个 feature，**4 个命中**（`sma_alignment_6_24`/`sma_cross_up_6_24`/`sma_cross_down_6_24`/`utc_hour`），**20 个缺失**（见下）。缺失项分三类：(A) **参数 gap** 1 个 — `rsi_14`（lyra 有 `rsi_{6,12,24,60,120}` 但无 14）；(B) **命名漂移** 8 个 — nova 的 `psar_direction/psar_flip_{up,down}`↔lyra `psar_bullish/bearish`、`supertrend_direction/supertrend_flip_{up,down}`↔lyra `supertrend_bullish/bearish`、`breakout_{up,down}_24`↔lyra `breakout_{up,down}`、`failed_breakout_{up,down}_24`↔lyra `failed_breakout_{up,down}`；(C) **真缺失** 11 个 — `range_position_24`(888)、`close_sma24_distance_atr`(316)、`efficiency_24`(300)、`ema_alignment_6_24`(194)、`close_ema60_distance_atr`(182)、`range_atr`(146, lyra 有 `bar_range_atr`)、`relative_volume_24`(106)、`return_6_atr`(60)、`range_width_atr_24`(28) 等 | **已决（2026-11-11 用户三裁决，#100）**：B 类 10 改名注册为 nova 规范名（无 alias）；`rsi_14` 不新增、改 rsi_12 重跑；ATR 基 24→12；C 类 9 新增。详见 0008 决策稿 v0.2 D 表。 |
| O17 | 0005 financing 天数应按自然日还是交易日？ | **0006 锁定默认口径 + 批次4 C2 契约重构（2026-11-09，用户委托我按推荐裁决并记录）**：**默认 per-trade 自然日**——确定性强、仅依赖数据（无需外部交易日历）、保持 0005 的 nova cross-check（diff=0）有效，且符合用户"轻量、不过度工程"立场；**批次4 C2**：O15（交易日口径）的合规出口由旧的扁平 `trading_days=<n>` + `--financing-days`（对多笔交易无差别扣同一天数，已在 #88 移除）重构为**每笔交易**计数器 `simulate(plan, bars, trading_days_for=counter)`（`counter(entry, exit) -> float`），0006 可在此接入真实交易日历逐笔计 R4/O15 交易日。"接入真实交易日历（按周末/假日逐笔计数）"仍为**后续增强**（非 0006 缺陷，引擎侧支持已就位）。O15 维持关闭（用户 11-06 定案），此处不改写其裁决。 | **已收口（0006 锁定默认口径 + #88 C2 契约就位，2026-11-09）** |

| O18 | **lyra 与 nova 的 1h bar 覆盖不一致**（0008 cross-check 发现，2026-11-11）：OHLC 重叠部分逐 bar 全等（同源），但 lyra 21 根/日（部分时段/周六缺口、SPX 周 bar 数异常高）、nova 24 根/日（SPX 仅 3 根/2 天）。导致 cross-check 笔数/entry_price 3% 偏移、bars_held 40% 差异。 | **待数据 owner 裁决**：确认两侧 raw 数据来源与聚合/去重规则，决定以哪侧 bar 集为准（影响 0008 cross-check 残差与未来 nova→lyra 数值可比性）。不阻塞 0008 签收（信号 direction/exit_reason 已 100% 一致）。 |
## O16 详情：332 策略的 feature 缺口（2026-11-08 核实）

**背景**：`requirements.md` R10/R11 的验收标准是"332 legacy 策略全部 `lyra validate` 通过"。
0004 编译器实现 + 自检时（2026-11-08）逐一对照 lyra registry 发现：
**332 策略里有 326 个至少引用 1 个不在 lyra 0003 registry 的 feature**。
这不是 0004 编译器的 bug —— 编译器按 registry 正确 fail-closed（未知 feature 即报错）；
缺口在 0003 的 feature 覆盖。

**核实方式**：对 nova 只读目录（`runs/research_campaign` 293、`strategies/directions` 12、
`runs/directions` 12、`strategies` 7）grep 全部 `feature:` 引用，与 `build_registry()`（134 feature）交叉比对。
24 个去重 feature：4 个命中，20 个缺失。缺失项按参考次数排序（次数=nova 中引用该 feature 的表达式数）：

| # | 缺失 feature | 引用次数 | 分类 | lyra 候选 |
|---|---|---|---|---|
| 1 | `range_position_24` | 888 | C 真缺失 | — |
| 2 | `close_sma24_distance_atr` | 316 | C 真缺失 | — |
| 3 | `efficiency_24` | 300 | C 真缺失 | — |
| 4 | `rsi_14` | 210 | **A 参数 gap** | `rsi_{6,12,24,60,120}` 无 14 |
| 5 | `ema_alignment_6_24` | 194 | C 真缺失 | （lyra 有 `sma_alignment_6_24`） |
| 6 | `close_ema60_distance_atr` | 182 | C 真缺失 | — |
| 7 | `range_atr` | 146 | C 真缺失 | `bar_range_atr`（口径需核对） |
| 8 | `supertrend_direction` | 112 | **B 命名漂移** | `supertrend_bullish/bearish` |
| 9 | `relative_volume_24` | 106 | C 真缺失 | — |
| 10 | `breakout_up_24` | 91 | **B 命名漂移** | `breakout_up` |
| 11 | `breakout_down_24` | 91 | **B 命名漂移** | `breakout_down` |
| 12 | `psar_direction` | 86 | **B 命名漂移** | `psar_bullish/bearish` |
| 13 | `psar_flip_up` | 78 | **B 命名漂移** | —（lyra 无 flip 事件） |
| 14 | `psar_flip_down` | 78 | **B 命名漂移** | —（lyra 无 flip 事件） |
| 15 | `return_6_atr` | 60 | C 真缺失 | — |
| 16 | `failed_breakout_up_24` | 39 | **B 命名漂移** | `failed_breakout_up` |
| 17 | `failed_breakout_down_24` | 39 | **B 命名漂移** | `failed_breakout_down` |
| 18 | `utc_hour` | 36 | 已命中 | `utc_hour` |
| 19 | `range_width_atr_24` | 28 | C 真缺失 | — |
| 20 | `supertrend_flip_up` | 2 | **B 命名漂移** | —（lyra 无 flip 事件） |
| — | `supertrend_flip_down` | 2 | **B 命名漂移** | —（lyra 无 flip 事件） |

**三类处置选项**（待用户裁决）：

- **B 命名漂移（8 个）**：语义基本对应，但 `psar_flip_*` / `supertrend_flip_*`（"翻转当根"事件）
  lyra 无对应 EVENT feature —— 需要 0003 新增 flip 事件 feature，或把 nova 的 flip 用法改写
  为"当根 state 翻转"的等价的 within/after_event 组合（可能改变语义，需逐条核对）。
- **A 参数 gap（1 个：`rsi_14`）**：0003 增加 `rsi_14`（参数网格加 14）即解决。
- **C 真缺失（11 个）**：需在 0003 新增 feature（`range_position_24`、`efficiency_24`、
  `ema_alignment_6_24`、`*_distance_atr`、`relative_volume_24`、`return_6_atr`、`range_width_atr_24` 等），
  每个都要 contract card + golden test（0003 约定）。

**影响面**：
- **阻塞 0008 的 332 回归门禁**（R10/R11 要求 332 全部 validate 通过）。
- **不阻塞 0004 编译器本身**：编译器对"用已注册 feature 写出的策略"已完整可用
  （`lyra validate` / `lyra compile` 已落地，26+ 测试通过，含 live DuckDB 时序断言）。
- lyra tracked example `momentum_breakout/v01.yaml` 也引用 3 个缺失 feature
  （`range_high_12`/`range_low_12`/`range_position_24`），当前 `lyra validate` 会 fail-closed。
  已新增 `strategies/examples/rsi_pullback/v01.yaml`（只用已注册 feature）作为可 validate 的示例。

**建议路径（待用户确认，尚未执行）**：
1. 先收口 0003 v1.5：处置 B（命名映射 / 新增 flip 事件）→ A（`rsi_14`）→ C（11 个新 feature）。
2. 每加一个 feature 走 0003 既有流程（contract card + golden test + `FEATURE_VERSION` bump）。
3. 完成后 0008 的 332 回归门禁才有意义。

**用户待决策**：
- [ ] B 类：flip 事件新增 feature vs 改写为 within/after_event（可能改语义）？
- [ ] C 类：11 个真缺失 feature 是否全部纳入 0003 v1.5？优先级？
- [ ] `range_atr` 与 lyra `bar_range_atr` 口径是否等价（需核对 nova 定义）？

## O10 候选清单（lyra-doctor 检查项）

- [ ] Python 版本 ≥ 3.12
- [ ] 所有依赖可 import（按 `requirements.lock`）
- [ ] `config.yml` 存在且 `oci.par_url_read` 非空
- [ ] PAR URL 可达（HEAD 请求，超时 5s）
- [ ] PAR URL 有效期 > 7 天（否则提醒重新生成）
- [ ] 本地 `data/` 目录可写
- [ ] git 工作区干净（`git status --porcelain` 为空）
- [ ] git 里无 alpha 路径（B1）
- [ ] git 里无凭证（B2 / I12）
- [ ] core 代码无 alpha import（I16）
- [ ] 332 策略 YAML 全部 `lyra validate` 通过（如本地有）
- [ ] TA-Lib 可用（`import talib`）
- [ ] DuckDB 版本在 lock 文件内

## 已关闭（历史）

| # | 问题 | 决策 | 决策文档 |
|---|---|---|---|
| — | 要不要保留 OOS ledger？ | 不（R9） | `requirements.md` §R9 |
| — | 要不要保留 HWM 回撤？ | 不（只留 2% stop） | `background.md` §5 |
| — | 要不要保留 SHA256 目录名？ | 不（改用整数 snapshot_id） | `hld.md` §2.1 |
| — | 要不要保留 FROZEN_CORE？ | 不 | `hld.md` §1.5 |

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿。 |
| 2026-11-06 | 0.2 | O4 关闭（0001 I15 已界定 index 不进 git）；新增 **O11-O15**：跨代交叉代数公式、命名碰撞、Active Branch Cap、21 标的代码清单、financing 天数口径（均源自批次2 对抗性 review，待用户决策或后续 feature 闭环）。 |
| 2026-11-06 | 0.3 | 用户拍板：**O11** 定案（max+1）、**O12** 定案（`_1`/`_2` 后缀）、**O13** 定案（**Active Branch Cap = 8**）、**O14** 定案（继承 moneta BASE_QUOTE 格式，完整清单归 0002 枚举）、**O15** 定案（按交易日计，周末+节假日不计）；**O11-O15 全部关闭**。 |
| 2026-11-06 | 0.4 | **O5 关闭**（`0002` §2 定案：PAR 用户侧管理 + `lyra pull` 过期诊断 + 0009 doctor 体检）。**至此 O1–O5、O11–O15 全部关闭，无未决问题。** |
| 2026-11-08 | 0.6 | **O13 语义修订（用户 2026-11-08 裁决）**：Active Branch Cap 从"每方向全局 8"改为"**每 track 8 个 active branches，tracks 互不挤占**"（多 AI 互不影响；单 track 防无限 fork 原意仍满足）。O13 终态关闭；11-06 定案保留为历史。落点：requirements R12 v0.16、oci-alpha-layout §2.3、综合稿 §9。 |
| 2026-11-06 | 0.5 | **O1 正式补关闭**（批次7 D4）：0002 v0.5 已实际废弃目录级 snapshot_id（单文件外部表 + raw md5 溯源），但本文档此前仍写"待 0002 决策"，与 ACTION_LOG"O1 已关闭"矛盾——本轮把裁决落进本文档，消除断层。O2/O3 仍分别待 0007 / 0003。 |
| 2026-11-08 | 0.7 | 0004 编译器实施 + 自检时核实 **O16**：332 legacy 策略有 326 个引用至少 1 个不在 lyra 0003 registry 的 feature（24 去重 feature 中 4 命中 / 20 缺失，分 A 参数 gap / B 命名漂移 / C 真缺失三类）。O16 待用户决策，阻塞 0008 的 332 回归门禁；不阻塞 0004 编译器本身（已落地可 validate/compile 已注册 feature 的策略）。 |
| 2026-11-08 | 0.8 | 新增 **O17**：把 0005 O-0005-1（nova 自然日与 R4/O15 交易日口径冲突）纳入中央开放问题清单；保留已关闭 O15，只在 0006 锁定融资成本/报告口径前待裁决。 |
| 2026-11-09 | 0.9 | **O17 收口（0006 锁定，用户委托我按推荐裁决并记录）**：默认 per-trade 自然日（确定性强 / 仅依赖数据 / 保持 nova cross-check diff=0 / 符合轻量立场），`simulate(trading_days=<n>)` + `--financing-days` 提供平值交易日覆盖作为 O15 合规出口；交易日历逐笔计数列为后续增强（非缺陷）。O15 维持关闭不改写。 |
| 2026-11-09 | 1.0 | **O17 契约细化（批次4 C2，#88 处置）**：O15 交易日合规出口由旧扁平 `trading_days=<n>` / `--financing-days`（对多笔交易无差别扣同一天数，已移除）重构为**每笔交易**计数器 `trading_days_for(entry, exit)`——默认自然日（nova cross-check 基准）不变，0006 可在此接入真实交易日历逐笔计 R4/O15 交易日；"真实交易日历逐笔计数"仍为后续增强（引擎侧支持已就位）。O15/O17 裁决不推翻，仅契约 API 更新。 |
| 2026-11-10 | 1.1 | **O2 定案（0007 D7，用户裁决 2026-11-10）**：`runs/` OCI 规范布局取 `runs/<direction>/<track_id>/<run_id>/`（对齐 R12 tracks），取代原"strategy_id 分组"草稿；0006 本地工作区布局不变，`push` 负责映射。见 0007 D7。 |
| 2026-11-11 | 1.1 | 新增 **O18**：0008 cross-check 发现 lyra/nova 1h bar 覆盖不一致（重叠 OHLC 全等、覆盖集合不同），挂起待数据 owner 裁决；不阻塞 0008 签收。 |