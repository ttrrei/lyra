# 开放问题（Live Questions）

> **English**: [open-questions.en.md](./open-questions.en.md)
>
> 这份文档是**活的**：每个问题要么被决策文档关掉，要么被升级成
> 新的决策文档。不要在这里做决策（决策进 `docs/decisions/`）。

## 当前开放

| # | 问题 | 倾向 | 状态 |
|---|---|---|---|
| O1 | snapshot_id 用整数还是时间戳？ | 整数 | 待 `0002` 决策 |
| O2 | `runs/` 按 strategy_id 还是按日期分组？ | strategy_id | 待 `0007` 决策 |
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
| O13 | 每方向并发活跃分支数上限（Active Branch Cap）？ | **已定案（用户 2026-11-06）：8**。含义：每方向**同时 active 的分支数上限**（防 AI 靠无限 fork 规避 kill criteria）；超额必须显式 prune。用户偏好上限留高（8） | **已关闭（决策，2026-11-06）** |
| O14 | 标的代码清单与标识规范？ | **已定（用户）**：代码格式**继承 moneta** 的 `BASE_QUOTE` 约定（`XAU_USD`/`XAG_USD`/`EUR_USD`/`BTC_USD` 等，非 `GOLD`/`WTI`）；moneta 无单一 21 标的清单文件，**权威完整清单在 0002 数据同步时从 moneta 实际数据文件枚举确认** | **已关闭**（用户 2026-11-06；清单枚举归 0002） |
| O15 | `financing_per_day` 的 "elapsed day" 如何定义？ | **已定（用户）**：严格按**交易日**计，**周末不计**，**新年/圣诞等市场节假日也不计**（即 elapsed = 持仓区间内的交易日数，非物理日历天） | **已关闭**（用户 2026-11-06） |

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
