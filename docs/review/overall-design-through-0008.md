# Lyra 从总体设计到 0008 的整体对抗性检验

> **English:** [overall-design-through-0008.en.md](./overall-design-through-0008.en.md)

## 结论

Lyra 的主链路已经从 OCI 数据同步延伸到特征构建、受限 YAML 编译、逐标的回测、指标报告、OCI 推送，以及 12 个正式研究方向的迁移回归。0001–0008 均已按 `ACTION_LOG` 记录完成；0007 的真实 OCI 桶验收已通过，0008 的 12 个正式方向也完成 validate 和 21 标的运行。核心执行约束清楚，过去窗口、下一根可观察开盘成交、2% 强制不利退出、逐标的报告等关键语义有测试支撑。

但当前实现**尚不能支撑承诺中的互不影响的多 AI 策略搜索闭环**。最严重的缺口集中在 0007：默认 context 会合并同方向所有 track，hypothesis 的“冻结”只保存旧哈希却继续读取当前文件；run 产物默认写入的目录与 context 扫描目录不同，官方 `v01` 策略的 `spec_id` 也不能映射回分支，比较还可能跨方向取数。另有 O12 明确允许的 `_1` 分支名被代码拒绝。全项目验收基线仍残留错误的“332 个策略 YAML”兼容要求，融资日口径在需求与已裁决实现之间不一致。

因此，**可进入 0009 Polish，但不应把当前状态描述为整体 R10 已通过或多 AI 搜索闭环已验收**。建议 0009 在整理 README、CI、doctor 和安装方式时，优先修复或明确接收本报告的 P1 项，并同步失效需求和双语文档。本报告不改运行时代码；本轮只修正中央行动日志的当前状态块，并新增本报告双语版本。

## 范围与验证

对照 `docs/requirements.md` R0–R12、`docs/hld.md` §8、0001–0008 决策文档、OCI alpha 布局提案、当前 `ACTION_LOG` 与对应代码，沿完整链路检查数据契约、时间与融资语义、策略编译、运行身份、track 隔离、OCI 发布和迁移验收。

- `.venv/bin/python -m pytest -q`：**305 passed**。
- `.venv/bin/python -m pyflakes lyra tests`：通过，无输出。
- 隔离临时目录探针复现了 track 串读、hypothesis 基线漂移、跨方向 run 命中、`_1` 分支名拒绝和 feature 输出路径越界。
- 对两种交易日计数 callback 做了行为探针：固定指纹相同，但 Fri→Mon 的实际返回值不同。
- 只读检查默认运行目录：`~/.lyra/runs` 有 24 个 `metrics.json`，workflow 默认扫描的 `~/.lyra/default/runs` 有 0 个；已归档的正式方向 run `spec_id` 为 `directions_pullback_reentry`，而对应分支文件名是 `v01.yaml`。
- 本轮没有向 OCI 写入或重新执行真实桶验收；R10 桶验收依据 ACTION_LOG #105/#106 的既有记录。

## 端到端阶段审查

| 阶段 | 设计责任 | 对抗性结论 |
|---|---|---|
| 0001 repo / OCI split | core、alpha 和本地镜像边界 | 主原则明确；当前路径约束能防止常规 alpha 路径进入 git。 |
| 0002 pull / clean / aggregate | 拉取、校验、清洗、聚合 | 主数据链已运行；clean 会拒绝空/NULL 键，聚合保留 partial bar 并携带 `n_bars`，O18 已按用户裁决以 Lyra bar 集为准。feature 输出路径仍未继承同等严格的路径验证。 |
| 0003 feature builder | 固定参数注册、逐标的宽表 | 146 个 core features 已注册并完成全量重算；但路径穿越和多文件非原子发布仍是数据层风险。 |
| 0004 compiler | YAML 校验与 past-only SQL | SQL 窗口与因果性门禁清楚；未发现本轮新 look-ahead 缺口。 |
| 0005 trade engine | next-open、2% stop、逐标的一笔交易 | 核心撮合约束有测试；融资日默认值与 R4/O15 的需求文字不一致。 |
| 0006 metrics / runner | 运行、指标、报告、可复现身份 | 逐标的报告和产物校验较完整；默认输出路径、run/branch 关联、callback 指纹和 feature snapshot 身份仍不足以支持可信比较。 |
| 0007 push / backup / R12 | OCI 发布与多 track 研究流程 | PAR-only 和真实桶验收已收口；track context、run 发现和 O12 命名仍破坏多 AI 独立演进的核心承诺。 |
| 0008 migration / regression | 正式方向迁移与回归 | 12 个正式方向已验证；旧的 332 YAML 兼容基线仍留在 requirements，且 0008 双语决策文档存在过时结论。 |

## 发现

### P1 — 策略搜索闭环与验收口径风险

#### R1. 默认 context 会合并所有 track，且读取当前 hypothesis 而非 track 冻结版本

**证据：** `lyra/workflow.py:461–506` 中 `render_context()` 先读取方向级 `strategies/<direction>/hypothesis.md`，再根据可选的 `track` 参数过滤 track。调用方不传 `track` 时，`list_tracks()` 的全部结果都会被输出。`create_track()` 仅在 `tracks/<direction>/<track>.json` 保存创建时的 hypothesis SHA256；没有保存 hypothesis 内容，也没有在渲染时校验当前文件是否仍匹配该 hash。

**复现：** 临时 workspace 建立 `weak_ai` 与 `strong_ai` 两个 track 后，不带 `track` 调用 `render_context()`，输出同时含两个 track。随后修改共享 hypothesis，`weak_ai` 的旧 baseline hash 与 context 显示的当前 hash 不同，context 仍包含修改后的文字。

**影响：** 默认命令不满足 R12 的隔离语义；不同 AI 会读到彼此的分支摘要和 lessons。方向 hypothesis 变化后，旧 track 继续按新文本工作，却仍显示旧 baseline，无法确认各 track 是在同一冻结假设上演进。

**建议：** 面向单个 AI 的 context 必须要求明确 track 或在唯一 track 时才允许省略；跨 track 合并只通过用户显式触发的 synthesize。创建 track 时保存不可变 hypothesis 快照（或可验证的内容对象），渲染时读取该快照并校验 feature / engine baseline。

#### R2. run 产物无法可靠关联回 branch；比较会漏数据或混入其他方向

**证据：** `runner._default_out()` (`lyra/runner.py:351`) 默认输出到 `~/.lyra/runs`；CLI workflow workspace 则由 `lyra/cli.py:854–858` 解析成 `~/.lyra/<workspace>`，`_runs_for_branch()` 只扫描 `<workspace>/runs/*/*/*/metrics.json` (`lyra/workflow.py:563–577`)。该函数只按 `spec_id` 与 branch slug 匹配，传入的 `direction` 没有参与过滤。0008 正式策略 YAML 的 `id/spec_id` 是 `directions_<name>`，而文件分支名是 `v01.yaml`。本地 run manifest / metrics 也不含 track_id。

**复现：** 当前默认目录中有 24 个 run metrics，而 workflow 扫描目录为 0；对 `pullback_reentry/v01` 的查询返回空。隔离探针另建 `direction=crypto, spec_id=v01` 的 run，查询 `fx/v01` 仍命中该 run。

**影响：** 按 R12 的正常顺序“context → run → compare”执行时，正式 v01 的真实结果不可见；即使目录修正，相同 slug 的其他方向结果仍可能污染比较。不同时间窗、timeframe 或 feature snapshot 的 run 也未被分组/校验，`compare --siblings` 不能保证在比较同一实验条件。track 归属缺失进一步令本地 run 无法证明由哪个 AI/track 产生。

**建议：** 统一 runner 输出根目录与 workspace；run 创建时显式记录策略文件身份、direction、branch、track、窗口和 feature snapshot；比较按这些身份字段精确关联，并对不兼容的 run cohort 拒绝混比。

#### R3. O12 已批准的 `_1` / `_2` 分支名被 workflow 和 OCI 分类器拒绝

**证据：** `docs/open-questions.md` O12 已关闭，明确允许 `v04ab_1`、`v04ab_2` 等同一策略变体命名。但 `lyra/workflow.py` 的 `_BRANCH_NAME_RE = ^v\d+[a-z]*$` 与 `lyra/oci_push.py` 的 `_VNN_RE = ^v\d+[a-z]*\.yaml$` 都不接受下划线。

**复现：** 对 `v04ab_1` 分别运行 workflow 命名规则和 OCI 文件分类规则，均返回不匹配；`new_version()` 会 fail closed。

**影响：** 同一方向 / 父分支的多个参数变体无法按用户已定规则创建或推送。若改名为字母后缀，不能表达 O12 要求的参数变体序号。

**建议：** 让创建、merge、push 分类器、schema 与 tests 共享同一份 O12 版本名 grammar，并覆盖 `_1`、`_2` 以及非法后缀。

#### R4. Requirements 的“332 策略 / 17 feature 名不变”验收基线已被 0008 裁决取代

**证据：** `requirements.md` R2、R10、R11（中英文）仍要求 332 个策略 YAML 原样运行，并写着 17 个 feature 名保持不变。0008 #99 已核实 332 是 Nova 仓库 YAML 文件总数，其中只有 17 个手写策略、146 个 campaign 快照，其余 169 个是 runs/manifest 等文件；Moneta 没有 332 个策略 YAML。#100 又裁决了 10 个名称直接改名注册、`rsi_14` 不加入并改用 `rsi_12`、ATR 基准 24→12，并增加 feature。0008 实际正式迁移范围是 12 个方向策略；146 个 campaign 属于 temp/，后续由 0010 triage。

**影响：** 需求文档要求的对象和兼容语义不再对应项目实际范围；完整 R10 不能通过 `validate` 332 个文件来判定。R10 还要求 `lyra-doctor`，但 CLI 当前无此命令，且 0010 的 temp/ triage 尚未发生。虽然测试通过、12 个正式方向运行完成、R10 真实桶门禁已通过，**整体 R10 仍未满足现行文档全部条款**。

**建议：** 0009 应按用户裁决重写 R2/R10/R11 的迁移验收对象与兼容声明，区分 12 个正式方向、146 个 temp campaign、非策略 YAML；明确 doctor 完成前 R10 不整体签收，并将新标准同步中英文。

#### R5. 融资日需求仍写交易日，已裁决实现默认自然日；“5m/1h 无可观察差异”的解释不成立

**证据：** `requirements.md` R4 和 `open-questions.md` O15 仍规定周末及市场假日不计融资日；O17 / 0006 D6 则把默认值裁定为逐笔自然日，代码 `trading_days_for=None` 走自然日。0006 D6 解释“当前 5m/1h 粒度没有可观察影响”，但融资按 entry/exit 时间差计算，不是按 bar 数计费。0005 已有 Fri→Fri 的自然日 7 天与交易日 override 5 天的对照测试。

**影响：** 行为选择虽然已有记录，但 requirements 仍是相反的规范性条款；调用者无法从需求基线判定正确输出。自然日与交易日会改变非零 financing 的 trade return，时间粒度不会消除这一区别。

**建议：** 不在本报告重新裁决用户已确定的默认值；应把 R4/O15 改写为明确例外/被 O17 supersede，并修正“无可观察差异”的解释。同步 CLI / API 的实际支持边界及双语文档。

#### R6. instrument 被直接拼入 feature 文件名，可写出配置数据根目录

**证据：** `clean._clean_sql()` 拒绝 NULL / 空 instrument，但不限制路径分隔符；`features.feature_path()` (`lyra/features.py:887–897`) 将 instrument 直接拼成 `<instrument>.parquet`，`run_features()` 随后直接写到该路径 (`lyra/features.py:964–970`)。

**复现：** `feature_path('/tmp/lyra-data', 60, '../../../../../../tmp/lyra-review-escape').resolve()` 得到 `/tmp/lyra-review-escape.parquet`，位于数据根目录之外。

**影响：** 含恶意或损坏 instrument 值的导入数据可使 feature builder 覆盖数据目录外的目标文件。当前 OCI source-of-truth 不等于所有导入 CSV 内容可信。

**建议：** 在 clean 边界限制 instrument 为允许的单路径组件；写入前对 resolved target 做 `is_relative_to(data_root)` 校验，并拒绝符号链接逃逸。

### P2 — 可复现性、发布原子性与文档收尾

#### R7. 多标的 feature generation 逐文件覆盖，失败会暴露混合版本

**证据：** `run_features()` 每算完一个 instrument 就直接覆盖最终 Parquet；没有 staging、完整标的集 manifest 或原子发布步骤。`Catalog.upsert_feature_views()` 通过 `features/.../*.parquet` glob 注册外部表，不检查所有文件的 `feature_version` / `version_string` 是否一致，runner 也没有全标的一致性门禁。

**影响：** 版本升级或磁盘错误期间中断，会留下部分新文件、部分旧文件；DuckDB 的宽表视图仍会读到该集合。用户可能得到不完整或跨版本的标的结果，且 failure 后不容易恢复上一代完整数据。

**建议：** 写入 generation staging，验证预期 instrument 集和一致版本元数据后再发布；Catalog / runner 对不一致 generation fail closed。

#### R8. `trading_days_for` 的固定样本指纹无法唯一识别 callback 行为

**证据：** `runner._counter_fingerprint()` (`lyra/runner.py:124–152`) 只探测 2024-01-01→2024-01-08 和同日区间。自定义 callback 可以在这两个点返回相同结果、在真实持仓区间返回不同值。

**复现：** 两个纯函数在 canonical 两个样本上都返回 5 / 0，因此 fingerprint 相同；对 Fri 2024-01-05→Mon 2024-01-08，一个返回 0、另一个返回 1。run_id 会把相同 fingerprint 放入身份 payload。

**影响：** 两个会对实际交易收取不同融资成本的 run 可以共享相同 callback fingerprint；run_id 的“所有输出依赖均进入身份”承诺不成立。有限探测不能证明任意 callable 的整体语义。

**建议：** 接受具名、版本化的确定性日历/计数器，并要求其内容 hash 或显式 identity token；不要用少量输入采样作为任意 callback 的行为证明。

#### R9. `feature_snapshot_id` 实际只是 catalog view 名称列表，不是 feature 数据快照身份

**证据：** `runner.py:257` 将 `Catalog.views()` 序列化作为 `feature_catalog_snapshot`；`Catalog.views()` 只返回 schema/view 名称 (`lyra/catalog.py:126–140`)，该值随后写入报告/metrics 的 `feature_snapshot_id`。它不包含各 Parquet 的 SHA256、feature `version_string` 或 alpha feature 源码摘要。`data_digest` 被纳入 run_id，但没有作为可审查 digest 写入 manifest。

**影响：** feature 文件或内容变了，报告里的 `feature_snapshot_id` 仍可能一样；AI 无法单靠 context / run report 确认比较的 runs 使用相同数据与 alpha 代码。run_id 的内容哈希降低了身份碰撞，但没有替代可解释的来源证据。

**建议：** snapshot 身份应覆盖每个实际输入文件的相对路径与 SHA256、feature registry/version 和 alpha module/contract hashes；将 digest 清单写入 run manifest，并由 track baseline 引用。

#### R10. 0008 中英文决策稿仍有过时的 O18 与 R10 状态

**证据：** `0008-migration-and-regression.en.md` §3.1 仍称 bar 集是“100% aggregation-rule-driven”，实际归因是 179,550（97.6% 聚合差异）+ 4,359（2.4% 窗口尾部）；修订历史仍写 O18 parked。中英文 0008 §5 都仍写 R10 real-bucket acceptance held #98，但 ACTION_LOG #105/#106 已记录真实桶验收通过并签收 0007。英文 0008 revision 0.3 仍把 O18 写成 parked。该文档不符合 #103 所记的中英同步处置结果。

**影响：** 读英文决策稿会得到错误归因和过时验收状态，和权威 action log、中文正文冲突，削弱 migration review 的审计可信度。

**建议：** 更新两份 0008 决策稿的当前结论与 R10 状态；旧 revision row 可保留为历史，但需明确标注为当时快照，不应在 active conclusion 中继续使用。

#### R11. OCI 布局与认证文档仍保留旧方案，和已实施路径不一致

**证据：** `requirements.md` R6 仍描述 `raw_csv/raw_parquet/market/<minutes>m/features/<minutes>m` 和 `runs/<name>/<date>`；`docs/proposals/oci-alpha-layout.md` 仍标注“Proposal, pending review”，使用旧目录结构。当前 0002 使用 `raw_zips` 与 `ohlcv_5m/ohlcv_1h`，0007 D7 规定 OCI runs `runs/<direction>/<track_id>/<run_id>`。此外 `requirements.en.md` R7 仍说 OCI auth optional；0007 英文 D4 当前说明前留有 `auth_file optional`，而 M3 已被裁决拒绝。

**影响：** 不同语言和文档会教出不同的对象布局及认证能力；用户或后续 AI 按旧布局生成文件时可能推错桶或期待并不存在的 SDK/auth_file。

**建议：** 将 0002 / 0007 的已定目录和 PAR-only 规则提升为当前规范；旧 proposal 标注 superseded / historical，requirements 与 0007 英文当前段落同步中文裁决。

#### R12. 0009 进入前的开发者入口仍指向不存在的交付物

**证据：** README 的 Repository layout 仍列 `src/`、未开始的 tests 和 placeholder 决策文档；Getting started 安装 `requirements.lock` 并建议运行 `lyra-doctor`，但仓库没有 lock file、`.github/workflows` 内容或 `lyra-doctor` 命令。README 还保留“未使用 PAR 时 OCI credentials”说明，和 M3 拒绝冲突。CLI help 当前已有 pull 到 synthesize 的命令集，却没有对应的完整 README 命令参考。`config_example.yml` 已在 #104 提前更新，0009 无需重复将其当作未做项。

**影响：** 新开发者照 README 无法按指令安装/验收；版本可复现与 CI 门禁目前也没有所指向的 lock/workflow 文件。缺 `lyra-doctor` 使 requirements R10 尚未完成。

**建议：** 0009 以实际 CLI 和 B13 路径重写 README；明确唯一 lockfile 工具与 Python 版本策略，补 CI；决定 doctor 的范围并实现或修订 R10，移除被拒绝的 auth_file 路径。

## 本轮已修正的审查元数据

审查开始时，`ACTION_LOG` 当前状态块仍写“0007 等待 R10”、待处置 11-11 review 和旧融资待决；这与 #105/#106、#103、#107 相冲突。本轮已在中文与英文状态块中更新：0001–0008 已完成、0007 R10 已通过、0009 为下一阶段、无待用户输入；历史日志行保持 append-only。该项不列为未解决代码发现。

## 进入 0009 前的优先顺序

1. 先处置 R1–R3：恢复 track 隔离、实际 run→branch 发现/比较，以及用户批准的分支命名。
2. 修复 R6，并为 R7 增加 generation 一致性 / 原子发布保护。
3. 按既有用户裁决更新 R4、R5 与 R10–R11 中的验收和文档事实；不在文档修订中重新打开已定用户决策。
4. 0009 完成 README、lock、CI、doctor 的真实可执行入口，之后再宣称整个 R10 通过。
5. 将 R8–R9 作为 run provenance 的收口项；若 R12 比较在这些身份字段落地前使用，应标记为不可比较而不是静默给出结论。


---

## 处置记录（2026-11-12，lyra 开发 AI）

> 按 R1–R12 逐项给出 接受 / 挂起 / 拒绝 处置及落盘证据。无拒绝项。

| 编号 | 级别 | 处置 | 落盘证据 |
|---|---|---|---|
| R1 | P1 | **挂起（0009）** | 核实属实：`workflow.render_context` 合并全部 track，`create_track` 只存 hypothesis SHA256、render 时用当前文件文本。修复需"track 隔离 context + hypothesis 内容快照"两项设计，属 0009 track 系统收口范围；修复前 `render_context` 输出仅供人读，不参与任何持久化结论。 |
| R2 | P1 | **挂起（0009）** | 核实属实：`runner._default_out()`=`~/.lyra/runs`（runner.py:351），`workflow._runs_for_branch` 扫 `~/.lyra/<workspace>/runs/...`，官方 v01 的 `spec_id=directions_<name>` 不匹配任何 branch。修复=runs 目录统一 + run→branch/direction/track 身份字段 + compare 不可比标记，整体属 0009。 |
| R3 | P1 | **接受（已修）** | `_BRANCH_NAME_RE` 与 `_VNN_RE` 均改为 `v\d+[a-z]*(_\d+)?`（workflow.py / oci_push.py）；新增回归测试 `test_o12_variant_ordinal_branch_names_accepted`、`test_o12_variant_ordinal_suffixes_classify_immutable`。`lyra validate` 现接受 `v04ab_1`。 |
| R4 | P1 | **接受（已修）** | `docs/requirements.md` 与 `.en.md`：R2/R10/R11 三处 332/17 基线改为当前裁决口径（12 方向已落地、146 temp 待 0010 分诊、特征命名三条裁决、134→146+prior12），旧基线明确标注"已被取代"。 |
| R5 | P1 | **接受（已修，不重开裁决）** | requirements 双语 R4 成本行：划时代"per trading day"改为 O17/0006 裁决状态（默认 per-trade natural days + `trading_days_for` 合规口径），标注旧措辞已被取代。**未重新裁决**用户既定默认。 |
| R6 | P1 | **接受（已修）** | `features.feature_path` 增加 instrument 校验（拒绝 `.`/`..`/`/`/`\`/NUL）+ `root in resolved.parents` 逃逸断言，fail-closed；新增回归测试 `test_feature_path_rejects_instrument_traversal`。 |
| R7 | P2 | **挂起（0009）** | 核实属实：`run_features` 按标的直覆写、catalog 不校验版本一致性。修复=staging+原子发布+generation 一致性门禁，属 0009 发布语义收口；当前数据由单一 `lyra features` 进程产生，无并发写风险窗口。 |
| R8 | P2 | **挂起（0009）** | 核实属实：`_counter_fingerprint` 仅 2 个固定探针，不同 counter 可同指纹。修复=命名/版本化 counter 身份 token，与 R9 同属 run provenance 收口，0009 一并落地。 |
| R9 | P2 | **挂起（0009）** | 核实属实：`feature_snapshot_id` 仅目录名列表，非数据身份。修复=逐文件 SHA256+registry/alpha hash 入快照摘要，0009 run provenance 收口。落地前任何跨 run 结论按"不可比"处理（报告第 5 点）。 |
| R10 | P2 | **接受（已修）** | 0008 双语：§3.1 统一口径"183,909 = 179,550 (97.6%) + 4,359 (2.4%) 窗口尾"；revlog 0.3 "O18 parked" 标注为收口前历史快照；§5 R10 状态同步 #105/#106 签收事实。 |
| R11 | P2 | **接受（已修）** | requirements 双语 R6 布局改为 0002/0007 实际路径（raw_zips / ohlcv_5m/1h / lyra-features / lyra-runs 规范路径）；requirements.en R7 "OCI auth optional" 改为 M3 拒绝口径；`docs/proposals/oci-alpha-layout.md` 头部标注布局部分已被取代（设计原则仍有效）。 |
| R12 | P2 | **接受（0009 范围）** | 按定义即 0009 交付物：README 按真实 CLI 重写、单 lockfile + Python 版本策略、CI、`lyra-doctor` 范围决策与实现。`config_example.yml` 已在 #104 完成，不重复立项。 |

**结论**：3 项 P1 代码级问题（R3/R6 + R4 文档）与全部 P2 文档问题（R4/R5/R10/R11）已在本轮落盘；R1/R2/R7/R8/R9 挂起 0009 并在 0009 任务清单中登记；R12 本身即 0009 工作项。测试 308 passed，pyflakes 干净。
