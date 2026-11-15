# UsageLastReview 两份四视角审查 — 处置与验证记录

日期：2026-11-15 ｜ 处置：#132 ｜ 验证：`pytest` **397 passed**、`pyflakes` 干净、alpha-gate 通过、Phase-0 五项 P1 逐一攻击验证

用户指令：评估 `/home/ubuntu/work/temp/TempReviews/UsageLastReview` 下的改动；以 ① 开发者自检 ② 红队对抗 ③ 使用者 ④ 金融从业者四视角看；**不必全部执行，不正确的拒绝并给理由**；评估距离最终可用有多近。

## 0. 两份文件的关系
- **文件 1** `lyra-four-lens-review.md`：D/R/U/F 四视角，给出"3 条立即做"。
- **文件 2** `lyra_four_perspective_deep_review_2026-11-15.md`：更严谨（带精确行号+代码链接），Phase 0 列出 **5 个 P1**。
- 文件 2 的 5 个 P1 **逐一验证全部为真**（见 §3），是本轮最高价值来源。文件 1 的多数 F/D/U 项被实施（§2）。

## 1. 判定总表（每条都对照真实代码验证后判定）
| 编号 | 声称 | 判定 | 处置 |
|---|---|---|---|
| DEV-01/RED-01 | 分支后缀正则不一致 → `v02_1` 绕过谱系门禁 | **属实** | 新增 `branch_generation()` 单解析器；门禁与 `new_version` 都用它 |
| DEV-02/USER-01 | prune 后同字节再 adopt 误报成功 | **属实** | `adopt_branch` 先判 active/pruned/orphan，pruned/orphan 拒绝 |
| DEV-03/RED-05 | batch 策略缺 direction 非 fail-closed | **属实** | preflight 强制 `spec.direction`，缺失整批拒绝 |
| DEV-04/RED-06 | batch `strict=False` 把部分失败当 run ok | **属实** | 读 `RunResult.instrument_failures` → PARTIAL + **exit 4** |
| RED-02 | `prune_branch` 缺 direction/track 校验 | **属实** | `track_index_path` 加校验+workspace 包含；`prune_branch` 同 |
| USER-04 | `digest --all --track` 忽略 track | **属实** | 按 track 过滤各方向，缺该 track 的方向标 skipped |
| F-1 | 报告缺 stop% | 属实 | 报告加 stop% 列（0% 标 inactive）+ payload |
| F-2 | 低样本不提示 | 属实 | 报告加 low-sample 标记 + ai_readme"择优偏差" |
| F-3 | 默认成本=0 未提示 | 属实 | 模板/示例非零成本 + 报告成本行(全零警示) + validate/compile 告警 |
| F-4 | 融资日基准不明 | 属实 | 报告 `financing day basis` + ai_readme |
| F-5 | 相关性聚合未说明 | 属实 | ai_readme"勿把相关品种相加" |
| FIN-03 | quote model 未声明 | 属实 | 报告 `quote model` + 范围行（交易级非账户级） |
| FIN-04 | volume 语义未说 | 属实 | ai_readme"volume=报价/成交活跃度，非成交量" |
| U-3 | `pull-strategy --all` 便利 | 属实 | 新增 `--all`（遍历本地已知方向逐个拉） |
| D-1 | features.py 注释与代码不符 | **属实** | 注释对齐（Python 补丁排除/numpy 保留） |
| D-2 | moneta 文件是否入库 | **属实·已满足** | 确认 lyra 仓库无 moneta 内容 |

## 2. 拒绝（带理由）
| 编号 | 拒绝理由 |
|---|---|
| F-2b sample-aware score | 改动**冻结的 R5 指标**（`annualized = 算术和/日历年`），属设计变更，非收尾 |
| F-2c / forward OOS | 结构性（样本外机制），1-2 天独立阶段，非本轮 |
| F-3b config 作唯一成本源 | 结构性；config 的 `run:` 段**从未被读取**，改成本来源需独立设计 |
| F-1b stop_atr_multiple | 触及**冻结的 I3 2% 价格止损**设计 |
| RED-03 校验过的 lesson 引用 | 需要稳定的 lesson/run-ID 方案，独立阶段 |
| DEV-05 adopt/index 完整事务协议 | 单文件写已原子、orphan 已可检测，完整恢复命令属独立阶段 |
| R-4 保留 YAML 注释 | `hypothesis:` 字段才是设计归宿 |

> 全部拒绝项均为"不在收尾阶段 / 触及冻结边界 / 需独立设计阶段"，而非"不做"。

## 3. Phase-0 五项 P1 的攻击验证（红队实测）
| 攻击 | 修复前 | 修复后 |
|---|---|---|
| `new-branch v02_1`（无谱系，parent 是 v01） | **绕过**（被接受） | 拒绝"v02_1…requires v01 parent + 1 lesson" |
| `new-branch v01_1` | 绕过 v01 保留 | 拒绝"v01_1…is reserved" |
| `v02_1` + 正确谱系 | — | 接受（正常路径不破） |
| prune v02 → 同字节再 adopt | 误报成功（分支仍 inactive） | 拒绝"previously pruned…new slug" |
| `--direction ../evil` | 裸 `WorkflowError` 冒到 cap 计数 | 干净 preflight 错误（零写） |
| batch 策略缺 direction | run_meta 读 None（归因腐坏） | 整批拒绝（零写） |
| batch 部分失败（`--instrument bad`） | `run ok` | **PARTIAL + exit 4** |
| `prune --direction ../x` | `validate_ident` 放行 | `track_index_path` 拒绝 |

## 4. 四视角结论
- **开发者**：无回归（397 passed、pyflakes 干净、alpha-gate 通过）；新增均为**收紧**（更严的门禁/校验/退出码），无放宽。
- **红队**：5 个 P1 全部堵死并攻击验证；`typer.Exit` 被 `except Exception` 正确捕获（批量循环语义健全）。
- **使用者**：`digest --all --track` 真正按 track 过滤；`pull-strategy --all` 一行拉全；报告 stop%/成本/quote-model 让数字"自己说明自己"。
- **金融从业者**：报告现在自带 **quote model / cost model / 范围(交易级非账户级) / 融资基准 / 低样本 / 相关性** 警示；ai_readme"如何解读这些数字"防择优偏差。

## 5. 距离"最终可用"还有多远
作为"**web-AI 写 YAML + 调命令**"的策略研究**应用平台，已经闭环可用**：低 token digest、单提交、多方向 apply-batch、lesson 记忆、OCI 上传/下载全部自洽。剩余是**独立设计阶段**的工作（feature 字典、forward OOS、结构化 lesson 引用、完整 orphan 恢复命令）——**都不阻塞进入 AI 学习阶段**。

## 6. 触及文件
`lyra/workflow.py`、`lyra/cli.py`、`lyra/runner.py`、`lyra/features.py`、`lyra/ai_readme.md`、
`strategies/examples/{rsi_pullback,momentum_breakout}/v01.yaml`、
`tests/test_workflow.py`、`tests/test_batch.py`、`tests/test_runner.py`、
`docs/ACTION_LOG.md`+`.en.md`、本文件。
