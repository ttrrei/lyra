# Action Log（中央行动日志）

> **English**: [ACTION_LOG.en.md](./ACTION_LOG.en.md)
>
> **历史归档**：#1–#133（2026-11-05 至 2026-11-15）的完整记录已冻结在 [ACTION_LOG.archive.md](./ACTION_LOG.archive.md)（英文：[ACTION_LOG.archive.en.md](./ACTION_LOG.archive.en.md)）。其他文档引用的旧编号都在归档里，查法：`grep -n "#113" docs/ACTION_LOG.archive.md`。
>
> 本文件是 Lyra 的**中央行动日志**：一条简短的时间线，只回答"做了什么、为什么、结果如何、详情在哪"。细节不写在这里：决策写进 `docs/decisions/`，审查写进 `docs/review/`，代码差异看 git。

## 维护规则（决策 0011）

1. **何时记**：只有产生实际变更（代码 / 文档 / 配置 / 策略），或形成重要决策、审查结论时才记。纯讨论、分析、排查而没有变更，不记。
2. **记多长**：每条 2–4 句话（约 600 字以内）：做了什么、为什么、结果、详情在哪。技术过程、测试清单、审查接受/拒绝明细放进 `docs/decisions/` 或 `docs/review/`，日志里只放指向它们的路径。
3. **只增不删**：新条目追加在下面"条目"表的最后一行，编号在上一条基础上加 1；被推翻的条目不删，追加新条并写明"推翻 #N"。
4. **一张表、一套账**：所有条目放进同一张表，列为 `# | 日期 | 类别 | 内容 | 落点`；类别取 decision / doc / review / fix / code 之一。
5. **当前状态**：只写"项目现在是什么状态"，不超过 10 行；状态变化时**原地覆盖**，不写历史，不保留"上一次更新"。它是本文件唯一允许原地修改的位置。
6. **中英同步**：`ACTION_LOG.md` 与 `ACTION_LOG.en.md` 在同一次改动里一起更新，信息一致即可，不要求逐字翻译。

## 当前状态（Current state）

| 项 | 值 |
|---|---|
| 更新于 | 2026-11-22 |
| 阶段 | 计划 2/3（执行计划 2）全部完成：C3（决策 0013 可比性解耦）与 C4（决策 0014 跨标的摘要与中位数排序）均已落地。 |
| 代码 | 419 passed, 2 skipped；`pyflakes` 与 `alpha-gate` 干净；`doctor` 0 fail/0 warn。 |
| 进行中 | 计划 2 收口交接（HANDOFF.md 已更新，冒烟证据已保存至 workspace）。 |
| 下一步 | 批量候选研究计划 3/3（commit C5，决策 0015：结构指纹与成本锁定；可选收口 exit-month 诊断）。 |
| 待用户输入 | 审阅计划 2 成果，确认启动计划 3。 |
| 未决问题 | O1–O18 均已关闭或已裁决；exit-month 诊断移交计划 3 §2.0。 |

## 条目（#134 起）

| # | 日期 | 类别 | 内容 | 落点 |
|---|---|---|---|---|
| 134 | 2026-11-22 | fix | `pull-strategy` / `pull-runs` 在 bucket 级 PAR 上列出返回 404（并误提示 PAR 过期）。原因：`_pull_direction` 以 `<par>/<prefix>/` 为列出地址，bucket 级 PAR 把它当作读取名为 `<prefix>/` 的对象；`push` 一直列根，不受影响。修复：改为列 PAR 根，沿用客户端 `<prefix>/<direction>/` 过滤，下载地址不变。新增 `_BucketRootPar` 回归测试（改动前 2 条失败、改动后通过），全仓测试、pyflakes、alpha-gate 通过。 | `lyra/cli.py`（`_pull_direction`）、`tests/test_oci_pull.py` |
| 135 | 2026-11-22 | decision | 日志治理 v1（决策 0011）：旧日志过大（中文约 157K / 英文约 261K 字符），#1–#83 与 #84–#133 分处两张表，状态块过时。旧日志整体冻结为 `ACTION_LOG.archive(.en).md`（`git mv`，仅加归档横幅）；新日志只保留规则、不超过 10 行的当前状态和 #134 起的简明条目；AGENTS.md 把"每个 working turn 必须记日志"改为"仅实际变更或重要决策/审查结论才记，每条 2–4 句，详情放 decision / review / commit"。未改任何代码，旧编号不变、可在归档中查到。 | `docs/decisions/0011-action-log-governance.md`、`docs/ACTION_LOG*.md`、`docs/ACTION_LOG.archive*.md`、`AGENTS.md` |
| 136 | 2026-11-22 | fix | 测试覆盖了真实数据：`tests/test_features.py::test_real_data_one_instrument` 在 `~/.lyra/default/data` 存在时直接对真实数据运行 `run_features(…, 60, instruments=["SPX500_USD"])`，而发布步骤会删除本次未出现的标的文件，所以跑完 pytest 后 1h 特征层只剩 SPX500_USD（5m 层不受影响），`lyra run` 因此只评估 SPX。修复：测试把真实 `ohlcv_1h` 软链进临时目录再运行，并断言真实 `features/ohlcv_1h` 的文件列表不变；已在合成数据上复现并验证（修复前剩 1 个标的，修复后 3 个都在）。已有环境的恢复方法：`lyra features --minutes 60`。 | `tests/test_features.py` |
| 137 | 2026-11-22 | code | `lyra doctor` 增加"特征层标的覆盖"检查：对每个已存在的 `features/<层>`，比较其 parquet 集合与对应 `ohlcv_<层>` 聚合里的标的集合，缺失或多余时给出 WARN 并提示 `lyra features --minutes N`。原因：#136 的事故里特征层被删减为 1 个标的，但 manifest 随之重写，原有的"generation 一致"检查看不出来。只增加警告，不改变退出码；新增 4 条测试，其中一条复现 #136 的事故（没有检查代码时该测试失败）。 | `lyra/features.py`（`layer_coverage`）、`lyra/cli.py`（`doctor`）、`tests/test_doctor.py` |
| 138 | 2026-11-22 | doc | 补全历史语料分诊决策 0010（补充标准结构与英文对 0010.en.md）并新建 AI 批量候选研究契约 0012（中英对）。规范历史 Nova/Moneta 278 条语料的分诊纳管（首轮单家族试点 + O18 重跑 + 8 席位门禁），并确立多候选批次研究契约（每批 3–4 候选、禁止纯参数微调、解释结构差异），防范单线爬山局部最优。未改动任何引擎代码，测试与门禁保持全绿。 | `docs/decisions/0010-temp-triage(.en).md`、`docs/decisions/0012-ai-batch-candidate-research(.en).md` |
| 139 | 2026-11-22 | doc | 重写 `lyra/ai_readme.md`（决策 0012 落地）：全面废除单分支迭代与调参示范，建立 3–4 候选批次提出、严禁纯参数微调、解释结构差异与 8 席位池化流转标准协议；示例完整替换为批次与剪枝闭环。0012 决策追加首轮 Pilot 实测结论修订行，未改动引擎代码，测试与门禁保持全绿。 | `lyra/ai_readme.md`、`docs/decisions/0012-ai-batch-candidate-research(.en).md` |
| 140 | 2026-11-22 | code | 行情数据快照 ID 与跨特征候选可比性解耦（决策 0013，commit C3）：在 `runner.py` 引入 `market_data_snapshot_id`（仅对 OHLC 基础列哈希），写入 metrics 与 manifest；`workflow._run_comparable_reason` 首位比较维度由 `data_digest` 替换为 `market_data_snapshot_id`，解除相同行情下不同特征候选被误判为不可比的限制；保留 `data_digest` 原有复现性职责。全套回归测试通过，真实 pilot 数据冒烟验证兄弟候选 `comparable=True`。 | `lyra/runner.py`、`lyra/workflow.py`、`lyra/cli.py`、`tests/test_runner.py`、`tests/test_workflow.py`、`docs/decisions/0013-market-data-snapshot-id(.en).md` |
| 141 | 2026-11-22 | code | 候选池摘要跨标的统计与兄弟比较中位数重排（决策 0014，commit C4）：`render_digest` 引入跨品种中位数（年化/净收益/期望值）、全宇宙盈利标的比例（含零交易与失败品种）、最差品种暴露及紧凑单行输出（8 分支 ≤5KB）；`compare_siblings` 与 CLI 排序机制改为按中位数年化收益降序重排，排除不可比分支，原单品种最高项保留为 `best_single_instrument` 并明确标注非综合分。全套回归测试通过，真实 pilot 数据冒烟验证中位数排序与摘要输出生效。 | `lyra/workflow.py`、`lyra/cli.py`、`tests/test_workflow.py`、`docs/decisions/0014-digest-cross-instrument-summary(.en).md` |
