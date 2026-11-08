# 决策文档：YAML Compiler（含 feature-vs-feature）

> **English**: [0004-yaml-compiler.en.md](./0004-yaml-compiler.en.md)

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0004` |
| 标题 | YAML Compiler（策略验证 + past-only SQL codegen） |
| 状态 | **已实施（2026-11-08）+ 批次 2 对抗性复核已处置（H1–H4/M1–M4 全接受，v0.4）**——用户裁决定稿后，本轮已落地：`lyra/strategy_schema.py`（YAML 安全加载 + schema 校验 + AST + StrategySpec + 未知键/类型/alias 严格化）、`lyra/compiler.py`（确定性 past-only SQL codegen + CompiledPlan + plan_hash 范围固化）、`lyra/cli.py` 的 `validate`/`compile` 命令、`tests/test_compiler.py`（50 测试全绿，含 live DuckDB 时序断言 + 批次 2 回归 22 项）。边界判定不变（确定性输入 / 廉价 validate / past-only SQL / per-instrument 归 runner）。**注意**：332 legacy 策略的 feature 缺口见 `open-questions.md` O16（阻塞 0008，不阻塞本编译器） |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-08` |
| 相关提案 | `docs/proposals/vectorbt-and-multi-ai-strategy-search.md` |
| 相关需求 | `docs/requirements.md` R2 / R3 / R12 |
| 相关 HLD | `docs/hld.md` §2.3 / §4 / §8 |
| 取代 | 无 |

## 1. 问题

Lyra 需要把受限 YAML 规则安全、确定地转为 DuckDB 可执行的 past-only 信号 SQL，并尽早拒绝未知特征、非法表达式和不兼容 timeframe。若把 YAML 直接拼成 SQL，任意 SQL/未来数据/特征算术会破坏 R2、I9、I10 与结果可审计性。

## 2. 背景

- 0003 已发布 5m 与 1h Catalog feature views（`features_5m` / `features_1h`），包含原始 `mid_o/mid_h/mid_l/mid_c` 与标准/alpha 特征；0004 应消费它们，而不读取/执行用户写的 SQL。
- HLD §2.3 把 `validate` 与 YAML → DuckDB SQL codegen 归到 strategy/compiler 组件；查询执行、交易状态机和报告分别属于后续组件。
- `requirements.md` R2 允许 `eq/ne/gt/gte/lt/lte`、`all/any/not`、`held_for`、`within`、`after_event`，右值为常量或另一个已注册 feature；禁止 feature arithmetic、跨标的比较和任意 SQL。
- 文档/样例存在需要 0004 明确收口的语法漂移：README 展示 `exit.feature.when` / `time_bars` 且没有方向字段；Lyra tracked example 使用 `stop_loss_pct` / `take_profit_pct` / `max_holding_bars` / `direction`；Nova 的只读 YAML 样例使用 `family` 和 `exit.long/short`。本决策建议规范化兼容别名，并在实施前把可用 332 YAML inventory 逐个映射；不得声称未跑过的 332 项兼容。
- `docs/proposals/vectorbt-and-multi-ai-strategy-search.md` 建议把 AI track 留在策略/runner 层。Compiler 对传入 YAML 与路径保持无关，不依赖 AI provider 或 VectorBT。

## 3. 方案

### 3.1 做什么

**输入与 API**

- 新增 `lyra/compiler.py`；在现有 CLI 接入 `lyra validate <strategy.yaml>` 和 `lyra compile <strategy.yaml>`。`validate` 完成安全 YAML parse、schema/feature/timeframe 检查和 SQL codegen；`compile` 输出规范化 SQL 与参数/摘要供人工检查。两者都不执行交易 SQL。
- `compile_strategy(strategy_path, catalog, feature_registry) -> CompiledPlan`。`CompiledPlan` 至少含 SQL、绑定参数、时间视图、已解析 feature 清单、策略摘要/hash、执行元数据（止损/止盈/持有时限/成本）；后续 runner 才负责用 DuckDB 执行信号 SQL。
- 每个查询以 `time` 排序，保留 `instrument` 与时间列；由 run/runner 逐标的调用。Compiler 不做跨标的窗口或比较。view 由 `timeframe_minutes` 只能解析到 Catalog 已有的 5m/1h view；其它 timeframe fail-fast。
- feature/列名只接受 Catalog/Registry 中已知名称及白名单 OHLC alias；通过 DuckDB identifier quoting 输出。常量使用 query bind parameters，不拼接到 SQL 文本。

**规范化 YAML 模型（提案）**

- `version: 1` 指**YAML schema 版本**，不表示方向版本树的 v01/v02。`id` 必须是安全 slug；`timeframe_minutes` 必须匹配存在的 feature view；`entry.long` 和/或 `entry.short` 是表达式树。
- `direction` 是规范字段。兼容旧 YAML 时可接受 `family` 作为别名；若两者同时出现且不相等则拒绝。`parent(s)`、`driven_by_lesson`、`inherited` 是审计元数据，保留但不进入 SQL。单文件 compiler 不负责改写/创建轨道或版本树。
- 比较叶节点沿用 `{feature: <左列>, op: <enum>, value: <常量或已知列名>}`。数字/布尔标量是常量；字符串只可解析为白名单原始列（`open/high/low/close` 映射到 `mid_o/mid_h/mid_l/mid_c`）或 Registry feature，不支持自由字符串 literal。未知字符串即未知列错误。
- `all` / `any` 接受非空列表；`not` 接受一个子表达式。数值列允许全部比较符；布尔列只允许 `eq/ne`；类型不匹配报含 YAML path 的校验错误。
- `held_for: {bars: N, condition: expr}`：current row + 前 N−1 个 observed rows 都为 TRUE 才为 TRUE；窗口不完整或含 NULL 输出 NULL；完整窗口中存在 FALSE 则 FALSE。
- `within: {bars: N, condition: expr}`：最近 N 个 observed rows（含 current）都可判定且至少一个为 TRUE 才为 TRUE；窗口不完整/含 NULL 输出 NULL；完整窗口没有 TRUE 则 FALSE。
- `after_event: {bars: N, event: expr, condition: expr}` 提案继承 Nova DESIGN 的含义：event 恰在 N 个 observed rows 前为 TRUE，后续 N 行（含 current）condition 全 TRUE 才在当前 close 确认。SQL 用过去 `lag(event, N)` + 以 current row 结束的 N 行窗口；event 与 condition 的 NULL 不得变成 TRUE。该语义仍需由 0004 fixtures 覆盖后实现。
- `exit.long` / `exit.short` 表示方向对应的 feature exit。为兼容 README，`exit.feature.when` 可被规范化为两方向同一退出表达式；`time_bars` 兼容为 `max_holding_bars`。tracked example 的规范字段优先。若 `stop_loss_pct` 缺省，trade engine 必须使用强制 2%；若 YAML 明写该字段，只接受 `0.02`，不得通过策略 YAML 关闭/放宽强制 stop。`take_profit_pct` 可选；成本字段只校验范围和类型，计算留给 0005。
- Strict schema：重复 YAML key、未知 key、递归 alias、NaN/Infinity、非整数/非正 `bars`、空组合、未知 feature 和不匹配 timeframe 一律 fail-fast；错误至少报告文件路径和 YAML 字段。

**SQL 代码生成**

- 输出固定列：`instrument`, `time`, `entry_long`, `entry_short`, `exit_long`, `exit_short`；缺失方向入口/出口表达式统一输出 FALSE。run engine 对信号只以 SQL TRUE 判真；FALSE 与 NULL 不得开仓。
- comparator 只由 enum 映射到固定 SQL token；所有列名先由 Catalog/Registry 解析再引用。没有 SQL 片段字段，不接受 callback、UDF、Python 或 Jinja。
- 时间窗口必须 `PARTITION BY instrument ORDER BY time ROWS BETWEEN <N-1> PRECEDING AND CURRENT ROW`；`after_event` 仅用 `lag` 与 past-only window。禁 `lead`、未来范围窗口、未来 join、向后填充未来数据。
- warm-up NULL 保留；`not(NULL)` 仍为 NULL。比较计算不 `COALESCE` 为 TRUE；完整 N 行门禁防止 `held_for` / `within` 用未成熟窗口意外触发。
- `all/any/not` 语义由 AST builder 递归生成；不以 SQL 文本拼接用户输入。常量顺序稳定，SQL/参数可重现。

**涉及文件（实现时）**

`lyra/compiler.py`、`lyra/cli.py`、`tests/test_compiler.py`、策略 schema/fixture（如有必要拆 `lyra/strategy_schema.py`）、决策文档及其双语对；不改 0003 feature semantics，不加入 VectorBT。

### 3.2 不做什么

- 不执行生成 SQL，不跑 trade state machine，不实现止损/滑点/融资/指标，也不生成 monthly/yearly report（0005/0006）。
- 不做 `lyra run`、version tree orchestration、跨 AI track、pause/resume 或 cross-track synthesis；这些归 R12/OCI/runner 设计。
- 不做用户 SQL/Python/eval/callback，不支持 feature arithmetic、跨标的/跨 timeframe join、feature 参数搜索。
- 不把 VectorBT 当实现、运行依赖、结果 oracle 或 compiler 后端。
- 不在本 feature 自动读取任意路径外文件；通过 CLI 明示指定 YAML 和配置/alpha feature loader。具体 run 输出路径安全仍由 runner/OCI feature 落地。

### 3.3 边界与待收口项

- YAML path 可属于任意 AI track；schema 编译不从父目录猜测 AI/provider，也不访问其他 track。方向/轨道/parent 元数据作为结构化 metadata 保留。
- Compiler 只读取当前 timeframe 的 Catalog view 与 Registry manifest。alpha feature 必须通过通用 `lyra.features.load_from(directory)` 注册；不按模块名硬编码。
- 2% 强制 stop、cost 字段和 exit 配置由 schema 校验并随 `CompiledPlan` 传递；其成交时机、OHLC 歧义和损益计算由 0005 决定。
- 0004 实施前要冻结 README 与 tracked YAML 的 aliases；为 every accepted alias 加规范化测试，并取得/构造 332 YAML regression fixture。若 fixture 尚缺，0004 可按已核验 grammar 实现，但 332 全量兼容只能在 HLD §8 的 0008 宣称。
- 0003 批次1 review 暂挂 H1（路径穿越）与 H4（Catalog 原子可见性）按 #66 进入 0004/0007 边界：Compiler 对 instrument/column identifier 严格解析；Catalog 原子发布不由本 SQL compiler 独占，需与 0007 push 协同定案。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I8 | 特征参数注册后固定，不扫描 | HLD §4 / R2 |
| I9 | RHS 为常量或已注册 feature；无特征算术 | HLD §4 / R2 |
| I10 | 输出 SQL past-only | HLD §4 / R3.3 |
| I15 | alpha / 方向 YAML 不进 Git | HLD §4 / 0001 |
| I16 | core 不 import 具体 alpha module | HLD §4 / 0001 |
| I17 | 不改变 OCI immutable / append-only 语义 | HLD §4 / B9 |
| C1 | `held_for` / `within` 需要完整 N 个 observed、非 NULL 值才可能为 TRUE | HLD §2.3 / R3.3 |
| C2 | 只有 SQL TRUE 是候选信号；NULL 不会借 `not` 变成开仓条件 | past-only / warm-up contract |
| C3 | 每个策略只读一个 timeframe；无跨 instrument 窗口或比较 | R2 / HLD §2.3 |

## 5. 测试（**已实施** — `tests/test_compiler.py`，50 测试全绿（含 live DuckDB 时序断言 + 批次 2 回归 22 项））

下表是 0004 §5 计划矩阵；**已实现**的列在 `tests/test_compiler.py`（同名或等价断言），
未单列的（`timeframe_and_instrument_partition`、`duckdb_fixture_truth_table`、`all_available_legacy_yaml`）
已合并进现有测试（partition 由 DuckDB 断言覆盖、truth table 即三个 `*_executed_against_duckdb`、
legacy 332 回归归 0008 — 见 O16）。

| 测试 | 场景 | 状态 |
|---|---|---|
| `test_compiler_compiles_registered_feature_vs_constant` | 标量和各比较符映射正确，参数绑定与 SQL token 安全 | ✅（all_six_ops + constant_binds_parameter） |
| `test_compiler_compiles_feature_vs_feature` | RHS 注册列解析；未知列和类型错拒绝 | ✅ |
| `test_compiler_rejects_sql_injection_and_duplicate_yaml_keys` | SQL-like value、未知 key、重复 key 不可绕过 AST | ✅ |
| `test_compiler_nested_boolean_operators` | nested all/any/not 和 SQL NULL 三值逻辑 | ✅ |
| `test_compiler_held_for_full_window_and_null` | N 行边界、warm-up、NULL、N−1/N/N+1 断言 | ✅（+ `held_for_executed_against_duckdb`） |
| `test_compiler_within_requires_full_non_null_window` | 有一次 TRUE、全 FALSE、不完整/含 NULL 三种路径 | ✅（+ `within_executed_against_duckdb`） |
| `test_compiler_after_event_exact_age_and_past_only` | event 恰 N 行前、N 个后续条件、 off-by-one、NULL 与未来扰动 | ✅（+ `after_event_executed_against_duckdb`） |
| `test_compiler_timeframe_and_instrument_partition` | 5m/1h view 选择、跨标的不泄漏窗口 | ✅（合并：view 断言 + DuckDB `PARTITION BY instrument`） |
| `test_compiler_yaml_alias_normalization` | direction/family、close/mid_c、README exit aliases 规范化；冲突拒绝 | ✅（3 个 alias 测试 + direction_family_conflict） |
| `test_compiler_duckdb_fixture_truth_table` | 执行生成 SQL 与独立参考期望逐行一致，信号只在 close 确认 | ✅（三个 `*_executed_against_duckdb`） |
| `test_compiler_all_available_legacy_yaml` | 可用迁移语料 compile 全过；正式 332 语料在 0008 全回归 | ⏳（332 归 0008 — O16 缺口阻塞） |

**附加安全测试**（对抗自检发现）：
- `test_compiler_state_event_only_eq_ne` — STATE/EVENT 只允许 eq/ne。
- `test_compiler_rejects_mandatory_stop_widen` + `test_compiler_rejects_exit_level_stop_widen` — 2% stop 不可放宽（execution 与 exit 两条路径）。
- `test_compiler_rejects_nested_temporal` — 时间算子不可嵌套。
- `test_compiler_rejects_unknown_feature` / `test_compiler_rejects_bad_timeframe`。
- `test_compiler_deterministic_*` — 同输入同输出（SQL + params + plan_hash）。
- `test_compiler_param_count_matches_question_marks_all_fixtures` — SQL `?` 数 == 绑定参数数（防参数错位回归）。

## 6. 回滚

- 代码层面：revert 0004 compiler commit（模块、CLI 接入、schema、tests）；feature builder / Catalog 文件不回滚。
- 数据层面：编译不写 OCI、不变更 Parquet/策略/run；没有运行结果或文件需要删除。
- 兼容性：旧 YAML 源文件保持原样；回滚后可由上一代工具继续读取。若公开 SQL 输出格式后发生 breaking change，应升级 compile plan 版本并保留旧 YAML。

## 7. 审批

- [ ] 用户 review（本稿提出的语法别名、`after_event` 精确语义、2% stop schema 行为）
- [ ] AI review（另一模型）
- [x] 实施测试全绿（`tests/test_compiler.py` 50 测试 + 全仓 157 测试通过；pyflakes 干净）
- [ ] 332 策略回归通过（0008）— **阻塞于 O16**（20 个缺失 feature 待用户裁决）
- [ ] OCI 端到端（不适用于 compiler-only feature；OCI reader integration 若纳入另行列项）

## 8. 自检与对抗性自检

### 自检

- [x] 编译边界对齐 HLD：YAML → SQL，不执行 SQL/交易。
- [x] comparison 运算符仅走 enum，feature-vs-feature 走 Registry，不接受 arithmetic。
- [x] past-only 使用 lag / 向当前行结束的窗口，warm-up NULL 与 SQL 三值逻辑有明确规则。
- [x] 多 AI 与 VectorBT 没有混入 0004 核心范围。
- [x] 没有把旧 332 兼容写成已验证事实；指定 0008 全量 regression gate。

### 对抗性自检（文档级）

| 攻击点 | 发现 | 处置 |
|---|---|---|
| YAML `value: "x) OR TRUE --"` | 如果字符串直接拼 SQL，可改变所有标的信号 | 只接受有限类型或已注册列名；常量 bind，标识符 Registry 解析 |
| 重复键 `feature:` / `op:` | YAML parser 常见 last-key-wins 会让审计与实际语义不同 | parser 必须拒绝重复键 |
| `not` 包住 warm-up NULL | 若用 `COALESCE(..., FALSE)` 后取反，未成熟数据会变 TRUE | SQL NULL 三值逻辑保留；只以 TRUE 触发 |
| 窗口 off-by-one | `bars=N` 若生成 N PRECEDING 会多算 N+1 行 | 定义 current + N−1 preceding；针对 N−1/N/N+1 写断言 |
| after_event 查未来 | 用 `lead` 或回看未来确认事件会产生 lookahead | `lag(event,N)` + 后续 N 行当前结尾窗口；未来扰动不得改变历史信号 |
| 按 track 做每 AI 8 分支 | 0004 若读取 AI meta 可能偷偷扩展 cap | 0004 完全不负责 cap；cap 在版本树层实现（**2026-11-08 用户裁决：每 track 8，tracks 互不挤占**） |
| README 与策略 YAML schema 不一致 | 随意只支持一个格式会破坏示例或旧策略；盲目接受所有别名又会掩盖含义差异 | 本稿显式列别名与语义；实施前确认 332 语料并对 aliases 做 fixture 测试 |
| Compiler 把 `stop_loss_pct` 当作可放宽参数 | 会绕过 2% mandatory stop | 缺省由 trade engine强制 2%；显式值只允许 0.02，实际状态机归 0005 |

### 批次 2 对抗性复核处置（2026-11-08）

对 `docs/reviews/对抗性review-2026-11-08-批次2.md` 的 8 项（H1–H4 / M1–M4）逐条复核后
处置完毕，全部**接受**（M1 收敛、M4 最小）：

| 发现 | 判定 | 落点（代码 / 测试） |
|---|---|---|
| H1 STATE 布尔↔序数类型混淆 | 接受 | `strategy_schema._state_is_ordinal` + 比较叶门控；`test_h1_*` |
| H2 exit.take_profit_pct 丢失 | 接受 | `_normalize_exit_and_execution`（统一 ExecutionMeta）；`test_h2_*` |
| H3 exit 层成本/持仓绕过校验 | 接受 | `_check_opt_nonneg/_check_opt_positive_int`；`test_h3_*` |
| H4 未知字段被忽略 | 接受 | `_reject_unknown_keys` + 各层白名单；`test_h4_*` |
| M1 递归 alias→RecursionError | 接受（收敛） | `_materialize`（拒真·环、物化跨分支复用）；`test_m1_*` |
| M2 结构错误裸异常/CLI 只拦 parse | 接受 | 结构检查 + `cli.py` 统一 INVALID；`test_m2_*` |
| M3 元数据弱类型 | 接受 | `_validate_doc`（tfm 整数 / direction·parents·inherited 类型）；`test_m3_*` |
| M4 plan_hash 范围 | 接受（最小） | `compiler._plan_hash`（纳入 catalog snapshot、排除 execution）；`test_m4_*` |

**验证**：0004 专项 50/50、全仓 157/157 绿、pyflakes 干净；nova+lyra 169 个真实策略
YAML 对新校验 **0 个**回归失败（165 仍失败于既有 O16 unknown-feature，4 失败于既有
STATE op 门控，二者范围外）。M1 处置特别记录：**不拒绝所有 alias**——语料用 `&id001`
把同一条件 factor 到多空两侧是合法写法（8 个文件），改为只拒真·环并物化复用。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-08 | 0.4 | **批次 2 对抗性复核处置（2026-11-08）**：对 `对抗性review-2026-11-08-批次2.md` 的 H1–H4 / M1–M4 逐条复核，**全部接受**（M1 收敛、M4 最小）。修复：H1 ordinal-vs-boolean 类型门控（`_state_is_ordinal`，`sma_alignment_6_24` 只接受 {−1,0,1}、布尔状态只接受 true/false）；H2/H3 exit 与 execution 元数据统一到同一 `ExecutionMeta` 校验器（`_normalize_exit_and_execution`，take_profit_pct 进入 CompiledPlan、负成本/零持仓被拒）；H4 各 mapping 层未知键白名单（`_reject_unknown_keys`）；M1 递归 alias 改为遍历栈检测真·环并 SchemaError、跨分支 alias 复用物化为独立副本（`_materialize`，保留语料 `&id001` 合法用法）；M2 entry/exit/after_event 非 mapping → SchemaError + CLI 统一 INVALID；M3 timeframe/direction/parents/inherited 严格类型；M4 plan_hash 纳入 feature_catalog_snapshot、明确排除 execution 元数据。新增 22 项回归（`test_h1_*`…`test_m4_*`），0004 专项 50/50、全仓 157/157 绿、pyflakes 干净；nova+lyra 169 个真实策略 YAML 对新校验 0 回归失败。 |
| 2026-11-08 | 0.3 | **实施完成（2026-11-08）**：落地 `lyra/strategy_schema.py` + `lyra/compiler.py` + `lyra/cli.py`（`validate`/`compile`）+ `tests/test_compiler.py`（28 测试全绿，含 live DuckDB 时序断言 N−1/N/N+1、NULL gate、after_event exact-age、param/`?` 数不变式）。对抗自检修复 3 处：DuckDB 2.0 named-window-with-frame 不能被 >1 函数引用 → 改 inline window；temporal condition 内联到 2 个 SQL 位置导致参数错位 → 每处独立 emit；`exit.stop_loss_pct` 放宽未被拒绝 → 补 execution 与 exit 两条路径的 2% 强制。332 语料回归归 0008（O16 缺口阻塞）。 |
| 2026-11-08 | 0.2 | **用户裁决定稿（2026-11-08）**：接受当前边界判定（含综合稿 §5 收口：确定性输入、廉价 validate、past-only SQL、per-instrument 归 runner；git commit 只作 provenance；track 不入 SQL AST）。状态改为"定稿，待排期开发"；对抗自检的 cap 行同步 2026-11-08 每 track 8 语义。本轮未实施代码。 |
| 2026-11-08 | 0.1 | 初稿：确定 compiler 边界、建议 grammar/SQL 生成策略、测试矩阵与文档级对抗性自检；待用户审阅后才能实现。 |
