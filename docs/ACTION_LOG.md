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
| 更新于 | 2026-11-26 |
| 阶段 | 计划 3/3 工程加固完成；OCI v02a/v02b 冲突已于 11-25 从 OCI 原件本地恢复，backup dry-run 0 conflicts；0019 复用加固已落地，仍未写 OCI。 |
| 代码 | 0019 落地复用产出提示、只读 `--verify` 三档验证、归属 fail-closed 与数值金标；465 passed / 2 skipped，`pyflakes` 与 `alpha-gate` 干净。 |
| 进行中 | 0019 中英决策、0016 修订行、双语 ACTION_LOG 与测试均已提交；Round 3 尚未开始。 |
| 下一步 | 准备 Round 3 候选供用户审阅，再完成 Round 3 闭环与终验收；工程侧加固已完成。 |
| 待用户输入 | OCI alpha/tracks 0 对象挂账待裁决；`runs_par_url` 指向独立 `lyra-runs` 桶，0017 预检只覆盖 strategies 桶（已报告用户，布局未改）。 |
| 未决问题 | O1–O18 均已关闭或已裁决。 |

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
| 142 | 2026-11-23 | doc | Task A（纯文档）：① 0012 v1.2 修订行+勘误，四成本字段名纠正为 `spread_bps` / `slippage_bps_per_side` / `commission_bps_round_trip` / `financing_bps_per_day`，注明 `stop_loss_pct` 为强制 2% 锁定项（C5 成本锁定以此为准）；② ACTION_LOG.en.md #134 恢复为 ac0150d 版完整英文，清除中文（0011 只增不删），Current state 恢复 OCI alpha/tracks 0 对象挂账到待用户输入行；③ ai_readme §4/§6 改用 strategies/examples/ 开源策略做范本（mean_reversion/t_mr 四候选 bundle 已 `lyra apply-batch --dry-run` 验证，复核 `lyra validate` 与 `lyra compile` 两示例均通过），0013 中英文档真实 run ID 改为 `<run_id_v02a/b/c>` 占位符；④ 0010 v1.1 追回 vp1_r06 命名规范、四层验证矩阵（用户裁决#3）、交付物清单；⑤ 补回 I5 直接覆盖测试 `test_data_digest_and_run_id_change_on_feature_perturbation`（feature 值扰动 → data_digest 与 run_id 变、market_data_snapshot_id 不变）。全套通过（pytest 420 passed/2 skipped、pyflakes 干净、alpha-gate OK）。Task A 完成，待用户确认后启动计划 3（C5，决策 0015）。 | `docs/decisions/0012*(.en).md`、`docs/decisions/0013*(.en).md`、`docs/ACTION_LOG*(.en).md`、`lyra/ai_readme.md`、`docs/decisions/0010*(.en).md`、`tests/test_runner.py` |
| 143 | 2026-11-23 | code | 完成计划 3 §2.0 的只读 exit-month 诊断：新增 `lyra exit-months <run_dir>`，按退出时间、标的汇总交易并为研究窗口内零交易月份补零行；字段使用 `exit_month_*` 前缀，不写回 `metrics.json`。该诊断独立于指标与执行语义，细节及覆盖见决策 0014 v0.2。 | `lyra/diagnostics.py`、`lyra/cli.py`、`tests/test_diagnostics.py`、`docs/decisions/0014*(.en).md` |
| 144 | 2026-11-23 | code | C5（决策 0015）落地批次护栏与留痕：`apply-batch` 现在锁定四项成本、限制 3–4 个同 direction/track 候选，并输出复杂度/结构关系；真实尝试归档 bundle、拒绝原因、运行状态与 run ID 到 workspace。全套回归 434 passed / 2 skipped，`pyflakes` 和 `alpha-gate` 通过；细节在 0015 与 `lyra/ai_readme.md`。 | `lyra/cli.py`、`lyra/strategy_schema.py`、`lyra/workflow.py`、`lyra/ai_readme.md`、`tests/test_batch.py`、`docs/decisions/0015*(.en).md` |
| 145 | 2026-11-23 | review | Pilot Round 2 已完成 3 候选运行、跨标的 compare、prune、lesson 与 workspace 归档；一支保留、两支淘汰。backup dry-run 发现 v02a/v02b 的 6 个历史 run 对象与 OCI immutable SHA 不同，因此未执行上传；详细校准数据仅在 workspace 报告，等待用户裁决冲突处理。 | `/home/coder/.lyra/default/research-batches/failed_breakout/pilot/pilot-round-2.md`、`batch-0003-result.md`、`tracks/failed_breakout/pilot.lessons.md`、OCI backup dry-run |
| 146 | 2026-11-25 | code | 决策 0016 落地本地 run 不可变与复用：先计算 run identity 并校验所有日期目录的完整产物，命中时跳过策略 SQL/simulation，损坏或歧义副本 fail-closed；新产物完整写入临时目录后原子发布。manifest 不再含 wall-clock `generated_at`，保留 R5/D5 要求的 git commit；OCI 原件比对与本地恢复记录在 HANDOFF，未上传任何对象。 | `lyra/runner.py`、`lyra/cli.py`、`tests/test_runner.py`、`docs/decisions/0016*(.en).md`、`docs/decisions/0006*(.en).md`、`docs/decisions/0013*(.en).md`、`HANDOFF.md` |
| 147 | 2026-11-25 | code | 决策 0017 增加跨机器 OCI 只读预检：本地 miss 后按 backup 原有路径查询，完整且无歧义的 run 会校验 SHA 后恢复复用；网络查询失败告警后继续，损坏、重复异字节副本或缺失对象 fail-closed。补充不可变冲突恢复手册与操作性错误文案；预检只读，不改变 OCI 布局或写入对象。 | `lyra/cli.py`、`lyra/runner.py`、`lyra/oci_push.py`、`lyra/ai_readme.md`、`tests/test_runner.py`、`tests/test_oci_push.py`、`docs/decisions/0017*(.en).md`、`docs/decisions/0007*(.en).md` |
| 148 | 2026-11-25 | code | 决策 0018 将真实 `apply-batch` bundle 的原始 bytes 先写入 workspace intake，再解析并路由至 direction/track 编号归档；损坏 UTF-8/YAML、混合或不安全身份转入 `_unparsed/unassigned` 并保存失败原因，归档故障仅 WARN，dry-run 继续保持零写入。现有编号归档 API 保持兼容；全套测试与门禁通过。 | `lyra/cli.py`、`lyra/workflow.py`、`tests/test_batch.py`、`docs/decisions/0018*(.en).md` |
| 149 | 2026-11-25 | doc | 文档一致性收尾：0015 中英追加 0018 修订指针，说明批次原文先入 `_intake/`、按单一身份路由、失败留档 `_unparsed/unassigned/`；0016 中英澄清 `+dirty` 属于确定性边界并显式继承 0006 M4 的已接受风险，0017 中英把 HLD 引用修正为 §4 I17 与 0007 的 I19/I20。`ai_readme` 的 apply-batch 归档段同步 0018；ACTION_LOG 当前状态的“下一步”已刷新，被空行拆开的条目表合并回单表以符合 0011“一张表、一套账”。未改任何代码，测试与门禁保持全绿。 | `docs/decisions/0015*(.en).md`、`docs/decisions/0016*(.en).md`、`docs/decisions/0017*(.en).md`、`lyra/ai_readme.md`、`docs/ACTION_LOG*(.en).md` |
| 150 | 2026-11-26 | code | 决策 0019 落地 run 复用加固：复用命中时若 manifest 的 git commit 与当前不同，追加 `note:` 提示（旧格式显示 `legacy`、git 不可用则跳过），仅提示不写文件；新增只读 `lyra run --verify`，在系统临时目录重算并按 IDENTICAL / DESCRIPTIVE_ONLY / NUMERIC_DIFFERENCE 三档报告（数值档退出码 2），不触发 OCI 预检、不写 `runs/`。复用前校验 run_meta 的 branch/track，不一致 fail-closed，旧格式缺字段 WARN 后继续；branch 覆盖全部复用路径，track 仅在 `--track` 可确定时生效（A3 范围）。新增数值金标与 run_id payload 固定测试，0016 追加测试名漂移修订行；A1–A3 核对记入 HANDOFF（7 个 commit 已在 origin、CI 绿，`runs_par_url` 指向独立 `lyra-runs` 桶已报告未改），全套 465 passed / 2 skipped，`pyflakes` 与 `alpha-gate` 干净。 | `lyra/cli.py`、`tests/test_reuse_hardening.py`、`docs/decisions/0019*(.en).md`、`docs/decisions/0016*(.en).md`、`docs/ACTION_LOG*(.en).md`、`HANDOFF.md` |
| 151 | 2026-11-26 | fix | 修正 #150 的数值金标可移植性：原实现钉 parquet 原始字节，而 parquet 的时间戳字符串随机器时区渲染（本地 +11 写 `11:00:00+11:00`，CI UTC 写 `00:00:00+00:00`），导致 CI 误报数值变化。按 0019 B4 允许的"内容摘要"改为规范化到 UTC 的逻辑行摘要（解析时间字符串再归一），指标数值金标不变；0019 追加 0.2 修订行。本地与 `TZ=UTC` 均通过，全套 465 passed / 2 skipped、门禁干净。 | `tests/test_reuse_hardening.py`、`docs/decisions/0019*(.en).md` |
