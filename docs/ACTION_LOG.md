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
| 阶段 | 0001–0009 按 HLD §8 已收口；web-AI 迭代闭环（`submit` / `apply-batch` / `digest` / `context`）已落地并验证（详见归档 #123–#133）。 |
| 代码 | 以 CI 和 `python -m pytest -q` 为准（通过数量随可选依赖而异）；`pyflakes lyra tests` 与 `alpha-gate` 必须干净。 |
| 进行中 | 日志治理 v1（决策 0011，#135）。 |
| 下一步（可选） | P2 增强：feature 字典、`lesson --kind`、`lyra doctor --no-config`；0010 temp/ triage；清理既有 mypy/ruff 债；生成 12 个 `hypothesis.md`（内容决策）。 |
| 待用户输入 | ① `git push` 是否已完成以 GitHub 为准（旧记录里的 `origin/main = 526f2ea` 已过时）。② 2026-11-22 列出 OCI 策略 bucket 时，`alpha/` 与 `tracks/` 下均为 0 个对象——alpha 特征代码和 track 基线如果只存在于旧机器上，仍需找回并备份。③ 是否做 P2 增强。 |
| 未决问题 | O1–O18 均已关闭或已裁决；GitHub branch protection 不开设（#127 裁决：本地 pre-commit + push main 后 CI + 私有仓库）。 |

## 条目（#134 起）

| # | 日期 | 类别 | 内容 | 落点 |
|---|---|---|---|---|
| 134 | 2026-11-22 | fix | `pull-strategy` / `pull-runs` 在 bucket 级 PAR 上列出返回 404（并误提示 PAR 过期）。原因：`_pull_direction` 以 `<par>/<prefix>/` 为列出地址，bucket 级 PAR 把它当作读取名为 `<prefix>/` 的对象；`push` 一直列根，不受影响。修复：改为列 PAR 根，沿用客户端 `<prefix>/<direction>/` 过滤，下载地址不变。新增 `_BucketRootPar` 回归测试（改动前 2 条失败、改动后通过），全仓测试、pyflakes、alpha-gate 通过。 | `lyra/cli.py`（`_pull_direction`）、`tests/test_oci_pull.py` |
| 135 | 2026-11-22 | decision | 日志治理 v1（决策 0011）：旧日志过大（中文约 157K / 英文约 261K 字符），#1–#83 与 #84–#133 分处两张表，状态块过时。旧日志整体冻结为 `ACTION_LOG.archive(.en).md`（`git mv`，仅加归档横幅）；新日志只保留规则、不超过 10 行的当前状态和 #134 起的简明条目；AGENTS.md 把"每个 working turn 必须记日志"改为"仅实际变更或重要决策/审查结论才记，每条 2–4 句，详情放 decision / review / commit"。未改任何代码，旧编号不变、可在归档中查到。 | `docs/decisions/0011-action-log-governance.md`、`docs/ACTION_LOG*.md`、`docs/ACTION_LOG.archive*.md`、`AGENTS.md` |
| 136 | 2026-11-22 | fix | 测试覆盖了真实数据：`tests/test_features.py::test_real_data_one_instrument` 在 `~/.lyra/default/data` 存在时直接对真实数据运行 `run_features(…, 60, instruments=["SPX500_USD"])`，而发布步骤会删除本次未出现的标的文件，所以跑完 pytest 后 1h 特征层只剩 SPX500_USD（5m 层不受影响），`lyra run` 因此只评估 SPX。修复：测试把真实 `ohlcv_1h` 软链进临时目录再运行，并断言真实 `features/ohlcv_1h` 的文件列表不变；已在合成数据上复现并验证（修复前剩 1 个标的，修复后 3 个都在）。已有环境的恢复方法：`lyra features --minutes 60`。 | `tests/test_features.py` |
