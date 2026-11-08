# OCI 上的 Alpha 目录结构（提案）

> **English**: [oci-alpha-layout.en.md](./oci-alpha-layout.en.md)
>
> **状态**：提案（Proposal），待 review。
> **版本**：v0.9 | **日期**：2026-11-05
> **Owner**：ttrrei
> **Related**：`docs/decisions/0001-repo-and-oci-split.md`

## 0. 为什么需要这份提案

Lyra 的 core 开源（git），alpha 闭源（OCI）。两份内容必须**物理分离**
且**边界清晰**，否则：
- alpha 会被误提交进 git → 被均摊。
- core 会被误传到 OCI → 开源失去意义。
- AI 改 core 时不小心碰到 alpha → 语义漂移。

本提案定义 OCI 上的**完整目录布局**，作为 core 和 alpha 的物理边界。

## 1. 顶层布局

```
oci://<bucket>/lyra/
├── data/                 基础数据（可共享，可重建）
│   ├── raw_csv/          原始 CSV（OANDA / 其他源）
│   ├── raw_parquet/      原始 Parquet
│   ├── market/           清洗后的 OHLCV
│   │   ├── 1m/
│   │   ├── 5m/
│   │   └── 60m/
│   └── features/         特征宽表
│       ├── 5m/
│       └── 60m/
├── alpha/                自定义特征（闭源）
│   ├── features/
│   │   ├── *.py          特征实现
│   │   ├── contracts/    契约卡
│   │   │   └── *.md
│   │   └── tests/        golden tests
│   │       └── *.py
│   └── README.md         alpha 特征清单（人读）
├── strategies/           策略（闭源），按方向组织（见 §2.3）
│   ├── <direction>/      每个方向一个文件夹：hypothesis.md + lessons.md + vNN.yaml
│   ├── _new/             用户自建的方向
│   └── README.md         全部方向的清单（人读）
├── runs/                 运行结果（闭源）
│   ├── <strategy_id>/
│   │   ├── <YYYY-MM-DD>/
│   │   │   ├── run_meta.json
│   │   │   ├── trades.csv
│   │   │   ├── monthly.csv
│   │   │   └── report.md
│   │   └── ...
│   └── README.md         运行清单（人读）
└── index/                索引 / 清单（闭源，可选）
    ├── strategies.json   全部策略索引（id → 路径 → 摘要）
    ├── features.json     全部 alpha 特征索引
    └── runs.json         全部 run 索引
```

## 2. 各目录的详细规则

### 2.1 `data/`（基础数据）

**性质**：可共享、可重建、**非 alpha**。
**谁写**：`lyra pull` 从 OCI 拉；`lyra push-data` 可选地推回 OCI
（多机复用场景）。
**谁读**：`lyra run` 读 `data/features/`；`lyra clean` 读
`data/raw_csv/` `data/raw_parquet/`。
**版本管理**：`<snapshot_id>` 是单调递增整数（`000001`, `000002`, …），
由本地 `data.py` 分配。OCI 上同名同 snapshot_id 的文件**不可变**
（SHA256 在上传时记录，后续不覆盖）。

```
oci://<bucket>/lyra/data/raw_csv/
  EUR_USD/2019-01.csv
  EUR_USD/2019-02.csv
  ...
  XAU_USD/2019-01.csv
  ...
  _manifest/
    2026-11-05/
      manifest.json   {files: [{name, sha256, size, instrument}]}

oci://<bucket>/lyra/data/market/60m/000042/
  EUR_USD.parquet
  XAU_USD.parquet
  ...
  manifest.json       {snapshot_id, source_snapshot_ids, instruments,
                       sha256_per_file, created_at}

oci://<bucket>/lyra/data/features/60m/000042/
  EUR_USD_core.parquet
  EUR_USD_trend.parquet
  EUR_USD_momentum.parquet
  XAU_USD_core.parquet
  ...
  manifest.json       {snapshot_id, market_snapshot_id, FEATURE_VERSION,
                       feature_list, sha256_per_file, created_at}
```

### 2.2 `alpha/`（自定义特征）

**性质**：**闭源**，是 alpha 的核心。
**谁写**：用户手动 `lyra push-alpha`；**不**由 `lyra run` 自动写。
**谁读**：`lyra features --extend-from <oci_path>` 加载。
**文件命名**：每个特征一个文件，文件名 = 注册名。
**契约卡**：每个特征必须带 `contracts/<name>.md`，内容包含：
  - 状态变量
  - 转移规则（伪代码 + 边界条件）
  - seed 规则
  - gap / flip 边界
  - 依赖的输入列
  - 参数（固定值）
**golden test**：每个特征必须带 `tests/test_<name>.py`，
至少覆盖：
  - 一段固定输入 → 固定输出
  - warm-up NULL 行为
  - gap 行为
  - 边界 flip 行为

```
oci://<bucket>/lyra/alpha/features/
  my_trend_filter.py
  my_momentum_pulse.py
  contracts/
    my_trend_filter.md
    my_momentum_pulse.md
  tests/
    test_my_trend_filter.py
    test_my_momentum_pulse.py
  README.md
```

### 2.3 `strategies/`（方向 + 版本树）

**核心思想**：策略的**一级组织单元是方向（direction / research family）**，
不是单个策略文件。一个方向 = 一个可检验的市场假设（"为什么这个机会
可能存在 + 预计持续多久 + 成本为何不会吃掉它 + 什么结果会让我们放弃
这个假设"）。在这个方向上，策略以**版本树**的形式演进：
**v01 的 run 结果 + 失败诊断可以推导出多个候选演进方向**（分支），
AI 对比多个分支的实际表现后，综合判断**继续哪个分支、剪掉哪个、
或者从两个分支各取一部分合成新分支**（类基因算法的变异/交叉）。
迭代是 alpha 的**主要生产过程**，不是"跑完看一眼"；
**单线程深搜会陷局域最优，所以分叉是一等能力，不是例外**。

**性质**：**闭源**，是 alpha 的核心。
**谁写**：**用户和 AI 都是一等写作者**，走同一套命令：
`lyra push-direction <dir>` / `lyra push-strategy <yaml>`；
`lyra new-version <direction>` 从指定父版本派生模板（可多次调用，
形成多个分支）；`lyra merge <new> --from <a> --from <b>` 从两个分支
合成新分支（交叉）。
**谁读**：`lyra run --strategy <path_or_oci_ref>`；
`lyra show-direction <direction>` 把 hypothesis + lessons + 版本树
一次性呈现；`lyra compare <direction> [--siblings]` 把同一父版本下
各分支的 run 摘要并排对比（AI 综合判断的输入）。

**AI 效率要求（一等需求）**：AI 参与迭代时，所需上下文必须
**自包含在方向文件夹内**，不得依赖读整个 repo 或翻历史 run 文件：

- `lyra context <direction>` 一次性输出一份**上下文包**（单文件，
  AI 直接读这一个文件即可开写）：
  1. `hypothesis.md` 全文
  2. `lessons.md` 的**最近 N 段**（默认 5，`--all` 看全部）
  3. **活跃分支**的最新 vNN.yaml 全文 + `parent` / `driven_by_lesson`
     字段
  4. **同层兄弟分支的 run 摘要对比表**（各分支年化分数 / 零开仓月 /
     失败场景分类——AI 做"继续哪个分支"判断的输入，不需要自己翻
     runs/ 目录）
  5. 最近一次 run 的完整摘要（年化分数 / 零开仓月数 / 失败集中的
     场景分类，来自 report.md，不需要 AI 自己读 trades.csv 全文）
  6. 本方向用到的 feature 清单 + 参数（来自 catalog，不需要翻
     `features.py`）
- 写新版本的完整 AI 循环 = **读 1 个文件（context 包）→ 写 1 个文件
  （vNN+1.yaml，可多个分支）→ 各跑 1 次 run → 写 1 段（lessons.md）
  + 1 段判断（continue/prune/cross）**，全程不接触 repo 其他部分。
- 因此 `hypothesis.md` / `lessons.md` / `vNN.yaml` 的格式必须保持
  **对 LLM 友好**：固定小节、短句、每段自包含、关键数字直接写在
  文本里（不要求读者再去查表）。

**目录布局**（每个方向一个文件夹；12 个初始方向继承自 nova；
**方向集合是 open 的（extendable）**——初始 12 个只是起点，不是上限）：

```
oci://<bucket>/lyra/strategies/
  trend_continuation/
    hypothesis.md          方向假设（可检验命题 + 放弃条件）
    lessons.md             演进日志（每个版本的结果 / 教训 / 分叉判断）
    v01.yaml               首个假设策略
    v02a.yaml              分支 A：由 v01 的 lesson 推导的候选 1
    v02b.yaml              分支 B：由 v01 的 lesson 推导的候选 2
    v03a.yaml              分支 A 继续（AI 对比后判定 A 更优）
    v04ab.yaml             交叉：取 v03a 的 entry + v02b 的 exit
    ...
  failed_breakout/
    hypothesis.md
    lessons.md
    v01.yaml
    ...
  mean_reversion/
    ...
    momentum_exhaustion/
    pullback_reentry/
    range_trading/
    regime_transition/
    relative_strength/
    session_temporal/
    volatility_expansion/
    volume_activity/
    market_structure/
    _new/                    用户自建的方向（非初始 12 个）
      <new_direction>/
        hypothesis.md
        lessons.md
        v01.yaml
    README.md                全部方向的清单（人读：方向 / 假设 / 活跃分支 /
                             最新 run 日期 + 年化分数 / 状态）
```

**命名约定**：`v<代数><分支后缀>.yaml`。代数 = 树深度（v01、v02、v03…）；
后缀 = 分支 id（a/b/c/…；交叉分支用来源拼接，如 `ab`）。
分支 id 是**字母**不是数字，避免和代数混淆。
**跨代交叉的代数** = `max(父本代数) + 1`（v02a×v04b → 第 5 代）——最新父本的下一代。
**同策略不同参数 / 同父母多次变异**：任意版本名后可追加 `_1` `_2` … 序号
（如 `v04ab_1`、`v04ab_2`），用于区分相同策略的不同参数或不同融合方案。

**`hypothesis.md` 的固定结构**：

```markdown
# <direction> — 假设
- 命题：……（可检验，1-2 句）
- 为什么这个机会可能存在：……
- 预计持续多久 / 什么环境下失效：……
- 成本为何不会吃掉它：……
- 放弃条件（kill criteria）：**所有活跃分支**连续 N 轮演进
  （每轮 = 各分支一次新版本）年化分数 < X 且诊断显示同类失败
  → 停止该方向（单分支失败不构成 kill，先分叉再判断）
- 当前状态：active / paused / killed
- 活跃分支：v03a（其余分支已剪枝：v02b → pruned @ 2026-11-20，原因见 lessons）
- 历史：（每次改假设加一行，不删）
```

**`lessons.md` 的固定结构**（append-only，演进的主驱动；
每个版本一段 + 每个分叉判断一段）：

```markdown
## v02a (2026-11-20)
- 父版本：v01
- 改了什么：exit 从 fixed 12 bars → 条件化（range_position_24 回归）
- 驱动它的 lesson：v01 的失败集中在"突破后立刻反抽"的场景
- 结果：年化分数 +0.0012；零开仓月 3；失败场景分布……

## v02b (2026-11-20)
- 父版本：v01
- 改了什么：entry 加 session 过滤（UTC 开盘小时内）
- 驱动它的 lesson：v01 的亏损单 60% 出现在亚洲时段
- 结果：年化分数 -0.0004；零开仓月 5

## judgment (2026-11-21)
- 对比：v02a +0.0012 vs v02b -0.0004
- 判断：**continue v02a / prune v02b**
- 理由：v02b 的信号过滤过强（零开仓月 5），场景覆盖损失大于时段收益
- v03 候选：A（v02a 的 exit 条件化继续收紧）/ B（v02a + v02b 的
  session 过滤做弱版，only 过滤亏损时段）
```

**策略 YAML 的元数据**（vNN 文件头部）：

```yaml
version: 1
id: trend_continuation_v03a
direction: trend_continuation
parent: trend_continuation_v02a          # v01 无此项
driven_by_lesson: "v02a 的失败集中在 X 场景"  # 一句话，指向 lessons.md
hypothesis: A PSAR flip confirmed for three observed bars ...
timeframe_minutes: 60
# ... entry / exit / execution 与 nova 兼容 ...
```

**交叉分支额外声明**（AI 声明，用于审计追溯，不是约束 AI 的玩法）：

```yaml
id: trend_continuation_v04ab
parents: [trend_continuation_v03a, trend_continuation_v02b]   # 交叉来源
inherited: {entry: from_v03a, exit: from_v02b}                # 各部分来源（AI 声明）
```

**交叉由找策略的 AI 全权决定（用户决策）**：从两个（或多个）分支里取什么、
怎么合成，**完全由 AI 自由决定**——可以是整块继承，也可以是逐参数混合、
甚至改造参数；框架**不限制**交叉的粒度。框架的职责是**保证这个 AI
有这个能力**：`lyra context` 包已包含活跃分支的**完整 YAML + 参数**，
AI 可读取并自由组合。审计靠 AI 在 `inherited` / `driven_by_lesson` 里
**声明来源**（可追溯，但不强制"只能整块"）。

> **边界（I8 不变）**：AI 的"改造"能力**严格限定于策略层**——阈值常量、
> 比较操作符、时间算子（`held_for.bars` / `within.bars`）、entry/exit 结构。
> **严禁改动特征注册名及已注册特征的底层参数**（`sma_6_24` → `sma_7_25`
> 这类属于 I8 违规，`lyra validate` 会拒绝）。特征要变 = 注册新特征（alpha
> 侧走 contract card + golden test），不是在策略 YAML 里改数字。

**分支生命周期**：`active`（在演进）→ `pruned`（剪枝，文件保留、
`lyra run` 不再默认选中）→ 或作为 parent 被交叉继承。
剪枝**不删除文件**（B6/B12 延伸）；同一代数可有多个活跃分支并行。
**Active Branch Cap（O13，2026-11-08 用户修订：每 track 8）**：每条
**track** 同时 active 的分支数 ≤ 8，tracks 之间名额互不挤占（多 AI
互不影响；单 track 防无限 fork 的原意仍满足）；超额必须显式 prune。
（2026-11-06 原定为每方向全局 8，被 2026-11-08 裁决取代。）

**AI tracks（用户裁决 2026-11-08）**：方向内可含多条 track，布局：

```
strategies/<direction>/
  hypothesis.md            方向假设（各 track 固定一个只读快照版本）
  tracks/<track_id>/
    lessons.md             本 track append-only 演进日志
    v01.yaml, v02a.yaml, … 本 track 候选版本（每 track ≤ 8 active）
  reviews/<review_id>.md   用户暂停后生成的跨 track 只读综合报告
runs/<direction>/<track_id>/<run_id>/   run 按 track 归属
```

- `track_id` ↔ 一个 AI 研究员（研究身份）；**不改变** validate /
  compile / run / report 的任何机器行为与门禁。
- 多 AI 可同/不同方向并行；基座（数据/特征/catalog/compiler/CLI）
  共用一套；无调度器/文件锁/并发协调（R9 维持）。
- 本布局与 `lyra context --track` 在 0005/0006 落地时实现；0004
  compiler 保持 track 无关（只消费传入 YAML + catalog）。

**迭代循环（Lyra 的核心工作流，支持分叉）**：

```
   ┌──────────────────────────────────────────────────┐
   │  1. lyra context <dir>                           │
   │     读 hypothesis + lessons + 活跃分支 +          │
   │     兄弟分支 run 摘要对比                         │
   ├──────────────────────────────────────────────────┤
   │  2. lyra new-version <dir> --branch <suffix>     │
   │     从同一父版本派生 1~N 个候选分支模板           │
   │     （v0(N+1)a / v0(N+1)b / ...）                │
   │     AI/人 分别写入不同的演进假设                  │
   ├──────────────────────────────────────────────────┤
   │  3. 每个分支各跑一次 run                         │
   │     lyra run --strategy <dir>/v0(N+1)a ...       │
   ├──────────────────────────────────────────────────┤
   │  4. lyra compare <dir> --siblings                │
   │     AI/人 对比各分支 run 摘要 + 逐笔诊断          │
   ├──────────────────────────────────────────────────┤
   │  5. 写 lessons.md：每分支一段结果 + 一段 judgment │
   │     continue 哪些 / prune 哪些 / 是否交叉合成     │
   ├──────────────────────────────────────────────────┤
   │  6.（可选）lyra merge <new> --from <a> --from <b>│
   │     从两个分支各取一部分合成新分支（交叉）        │
   ├──────────────────────────────────────────────────┤
   │  7. lyra push-direction <dir>                    │
   │     上传新版本 + lessons 到 OCI                  │
   └──────────────┬───────────────────────────────────┘
                  ▼ 回到 1
```

**与 nova 的对比**：

| 维度 | nova | lyra |
|---|---|---|
| 一级单元 | 12 个平铺 YAML（`directions/*.yaml`） | **方向文件夹（extendable）**，每个含 hypothesis + lessons + vNN 版本树 |
| 方向集合 | 固定 12 个（README 明确"twelve fixed"） | **开放扩展**：初始 12 + `_new/` 自建 |
| 假设 | YAML 里一个 `hypothesis:` 字符串 | **独立 `hypothesis.md`**，含放弃条件 + 历史 + 活跃分支 |
| 迭代 | 无（一个方向一个 YAML，改了就改） | **版本树**：一个父版本可分叉多个候选分支；每版必须填 `parent` + `driven_by_lesson` |
| 多候选对比 | 无机制 | **`lyra compare --siblings`** + lessons 的 judgment 段（AI/人综合判断 continue / prune / cross） |
| 交叉（变异） | 无机制 | **找策略的 AI 全权决定**（整块 / 逐参数 / 改造，不限粒度）；框架保证 AI 有此能力（context 含完整 YAML+参数）；AI 在 `inherited` 声明来源供审计 |
| 失败诊断 | `runs/directions/review_findings.json`（事后审计） | **`lessons.md`（演进主驱动，事前写）** |
| 放弃方向 | 无机制 | `hypothesis.md` 里 `状态: killed` + kill criteria（**所有**活跃分支连续 N 轮失败）触发；单分支失败 → prune 而非 kill |
| 新建方向 | 无机制 | `strategies/_new/<name>/` + 同一套 hypothesis/lessons/vNN 结构 |

**方向集合的可扩展性（extendable）规则**：

- 初始 12 个方向是**种子（seed）**，不是封闭清单。nova 的 12 个方向
  本身就覆盖了"趋势 / 均值回归 / 结构 / 量 / 波动 / 时段 / 相对强度"
  等假设维度，但研究过程中会自然出现新的假设维度
  （例如"流动性缺口"、"跨时段传导"），方向集合必须允许生长。
- 新方向的准入标准（**软标准，建议而非硬门禁**）：**应该是一个可检验的
  独立市场假设**，尽量不与现有 12 个方向重复（即不应用现有方向的
  entry/exit 组合等价表达）。如果可以用现有方向表达，**建议**在那个方向
  里开新版本，而不是新建方向。Lyra 不建方向等价性检查器（保持"稳定 + 轻"）。
- 新建方向放在 `strategies/_new/<name>/`，命名用 snake_case 动词短语
  （如 `liquidity_gap`、`cross_session_spillover`），避免与初始 12 个重名。
- 新方向与初始方向**完全同权**：同一套 `hypothesis.md` / `lessons.md` /
  vNN 版本树结构、同样的 B11/B12 约束、同样的 kill criteria 机制。
  初始方向没有特权，扩展方向也没有门槛溢价。
- 初始方向被 `killed` 后**不删除文件夹**，保留作为研究历史；
  其假设空间可以由新方向继承（在 `hypothesis.md` 的 History 里注明
  "继承自 <killed 方向>"）。
- 方向总数不设上限，但每个方向必须独立可运行、独立可放弃；
  禁止"方向之间共享状态"（方向是假设的容器，不是模块依赖的节点）。

**边界规则**（追加到 §3）：

| # | 规则 | 违反后果 |
|---|---|---|
| B11 | 每个方向文件夹必须含 `hypothesis.md` + `lessons.md`，缺一不能 push | 方向丢失假设或演进历史 |
| B12 | vNN.yaml（N≥2）必须含 `parent`（交叉分支为 `parents`）+ `driven_by_lesson` 字段，且指向同方向已存在的版本；pruned / killed 分支文件保留不删 | 版本树断裂，无法追溯"为什么这么设计" |

### 2.4 `runs/`（运行结果）

**性质**：**闭源**，是 alpha 的核心。
**谁写**：`lyra run` 完成后 `lyra push-run <run_id>`。
**谁读**：用户手动 `lyra pull-run <run_id>` 或 `lyra list runs`。
**不可变**：同一个 `<strategy_id>/<date>/` 目录一旦存在**不可覆盖**；
  重跑会生成 `<strategy_id>/<date>_2/`、`<date>_3/` 等。
**内容**：
  - `run_meta.json`：strategy 名、timeframe、标的清单、时间窗、
    feature snapshot id、git commit、日期、lyra 版本。
  - `trades.csv`：逐笔交易（entry_time, exit_time, direction,
    entry_fill, exit_fill, return, costs, …）。
  - `monthly.csv`：逐标的逐月（instrument, month, trades, net_return,
    win_rate）。
  - `report.md`：人类可读摘要。

```
oci://<bucket>/lyra/runs/
  trend_hold_v3/
    2026-11-05/
      run_meta.json
      trades.csv
      monthly.csv
      report.md
    2026-11-06/
      run_meta.json
      ...
  ema_pullback_short/
    2026-11-05/
      ...
  README.md
```

### 2.5 `index/`（索引，可选）

**性质**：**闭源**，但纯元数据（无业务数据）。
**谁写**：`lyra rebuild-index`（手动触发）。
**用途**：`lyra list strategies` / `lyra list runs` 时**不**逐个拉
文件，而是读一次 `index/*.json`。
**文件**：
  - `strategies.json`：`[{id, path, timeframe, summary, status,
    last_run, annualized_score}]`
  - `features.json`：`[{name, path, contract, version, created_at}]`
  - `runs.json`：`[{run_id, strategy, date, instruments, annualized_score,
    trades_count}]`

## 3. 边界规则（硬约束）

| # | 规则 | 违反后果 |
|---|---|---|
| B1 | git 里**不**出现 `alpha/`、`strategies/` 下任何**方向文件夹内容**（`hypothesis.md` / `lessons.md` / `vNN.yaml`）、`runs/` 任何内容 | alpha 泄露 → 被均摊 |
| B2 | `config/config.yml`（含 PAR URL）不进 git | 凭证泄露 |
| B3 | `lyra run` **不**自动 push（必须显式 `lyra push-run`） | 误推 alpha 到公共桶 |
| B4 | `lyra pull` 默认只拉 `data/`，**不**拉 `alpha/` `strategies/` `runs/` | alpha 误落到本地 |
| B5 | `alpha/features/*.py` 必须带 `contracts/<name>.md` + `tests/test_<name>.py` | 语义漂移 |
| B6 | 方向文件夹（含 `killed` 状态的）与分支文件（含 `pruned` 的）不可删除；只能更新 `hypothesis.md` 的状态字段并保留全部版本树 | 丢失研究历史 |
| B7 | `runs/<strategy>/<date>/` 不可覆盖（重跑生成 `_2` `_3`） | 丢失研究历史 |
| B8 | `index/*.json` 是**派生**的，可随时从 `alpha/` `strategies/` `runs/` 重建 | 一致性 |
| B9 | OCI 文件**分两级**：**(a) Immutable**（`data/**`、`runs/**`、`strategies/**/vNN.yaml`、`alpha/features/**`）同 path 同 sha256 → 幂等，不同 sha256 → **拒绝**；**(b) Append-only**（`strategies/**/hypothesis.md`、`strategies/**/lessons.md`、`index/*.json`）允许内容向前推进（新内容 ⊇ 旧内容），push 时校验"新 sha256 对应内容是新内容超集"，否则拒绝 | (a) 数据漂移 / 审计断裂；(b) 死锁——方向迭代无法同步 lessons |
| B10 | 凭证（PAR URL / OCI auth）只从 `config.yml` 或 `~/.lyra/credentials` 读，**不**从 env 读（避免 shell history 泄露） | 凭证泄露 |
| B13 | OCI 镜像（`data/` `strategies/` `runs/` **`alpha/`**）默认解析到**仓库外**（`~/.lyra/<workspace>/…`）；`lyra pull` / `lyra push` 若目标路径落在 git 工作区内，必须给出**显式警告并要求 `--inside-repo` 确认**（防呆，防 alpha 误入 git 工作区 / 误提交） | 误提交风险 ↑；`git status` 噪声 |
| B14 | `strategies/examples/`（开源示例）是 git 跟踪的**唯一** strategies 子树；`lyra` 运行时**不得**读/写它作为 alpha | 开源示例被当成 alpha 处理，或 alpha 混入示例 |
| B11 | 每个方向文件夹必须含 `hypothesis.md` + `lessons.md`，缺一不能 push | 方向丢失假设或演进历史 |
| B12 | vNN.yaml（N≥2）必须含 `parent`（交叉分支为 `parents`）+ `driven_by_lesson` 字段，且指向同方向已存在的版本；pruned / killed 分支文件保留不删 | 版本树断裂，无法追溯"为什么这么设计" |

## 4. 凭证管理

**推荐**：PAR URL（Pre-Authenticated Request），最简单，无 SDK 依赖。
  - PAR URL 在 OCI 控制台生成，有有效期（建议 90 天）。
  - PAR URL 只授权**读**；写需要另外的 PAR URL 或 OCI auth。
  - `config.yml` 里 `oci.par_url_read` 和 `oci.par_url_write` 分开。

**可选**：OCI SDK（`oci` Python 包），用于 push 时避免签名。
  - `~/.lyra/credentials`：OCI auth 文件（`[DEFAULT]` 段，
    `fingerprint` / `tenancy` / `user` / `key_file` / `region`）。
  - **不**用 env 变量（避免 shell history 泄露）。

## 5. 多机复用（可选）

**场景**：A 机 pull 数据 + 算特征，B 机直接 pull 特征跑策略。
**做法**：A 机 `lyra push-data` 把 `data/features/` 推回 OCI；
B 机 `lyra pull --kind features --minutes 60` 直接拉特征，跳过
clean + aggregate。
**注意**：`data/` 是**可共享**的（非 alpha），push 回 OCI 不违反
B1-B14 任何一条。

## 6. 开放问题

| # | 问题 | 当前倾向 |
|---|---|---|
| Q1 | snapshot_id 用整数还是时间戳？ | **整数**（单调递增，简单） |
| Q2 | `runs/` 按 strategy_id 分组还是按日期分组？ | **按 strategy_id 分组**（研究视角） |
| Q3 | `alpha/features/` 要不要按 family 分子目录？ | **不**（文件名 = 注册名就够） |
| Q4 | `index/*.json` 要不要进 git（作为只读镜像）？ | **不进**（alpha 边界） |
| Q5 | PAR URL 90 天过期，过期后怎么办？ | `lyra-doctor` 检测 + 提醒重新生成 |
| Q6 | 要不要支持 S3 / GCS（未来）？ | **不**（OCI 是当前唯一存储） |

## 7. 审批

- [ ] 用户 review 目录布局
- [ ] 用户 review 边界规则 B1-B14
- [ ] 用户 review 凭证管理方案
- [ ] 用户 review 多机复用方案
- [ ] AI review（另一模型）
- [ ] 落决策文档 `0001-repo-and-oci-split.md`

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿。 |
| 2026-11-05 | 0.2 | §2.3 `strategies/` 重写：一级单元改为**方向文件夹**（hypothesis + lessons + vNN 版本链），新增 B11/B12 边界规则，对比 nova 的 12 平铺 YAML，明确"迭代是 alpha 的主要生产过程"。 |
| 2026-11-05 | 0.3 | §2.3 新增**可扩展性（extendable）规则**小节：初始 12 是种子而非封闭清单；新方向准入标准（可检验 + 不可被现有方向推导）；`_new/` 命名规则；新旧方向同权；killed 方向不删除。对比表加"方向集合"一行。 |
| 2026-11-05 | 0.4 | 新方向准入标准定为**软标准（A 方案）**：可检验独立性是建议而非硬门禁，Lyra 不建方向等价性检查器。 |
| 2026-11-05 | 0.5 | 清除旧 `active/` `archived/` 模型残留：顶层目录树改为方向文件夹；B1 改为"git 不出现 `strategies/` 下任何方向文件夹内容"；B6 改为"方向文件夹（含 killed）不可删除"。 |
| 2026-11-05 | 0.6 | 新增 **B13**（OCI 镜像默认在仓库外 `~/.lyra/<workspace>/…`；落进 git 工作区必须 `--inside-repo` 显式确认，防 alpha 误入工作区/误提交）与 **B14**（`strategies/examples/` 是 git 跟踪的唯一 strategies 子树，运行时不得当作 alpha 读写）。 |
| 2026-11-05 | 0.7 | 全文 B 规则引用统一为 **B1-B14**（§5 多机复用、0001 决策文档、AGENTS.md 原残留 B1-B10）。 |
| 2026-11-05 | 0.8 | §2.3 明确 **AI 是一等写作者** + **AI 效率要求**：上下文自包含于方向文件夹，`lyra context <direction>` 输出单文件上下文包；AI 写循环 = 读1/写1/跑1/记1，不接触 repo 其他部分；hypothesis/lessons/vNN 格式保持 LLM 友好。 |
| 2026-11-05 | 0.9 | §2.3 升级为**版本树**模型（用户决策：单线程深搜会陷局域最优）：一个父版本可分叉 1~N 个候选分支（`v02a`/`v02b`），`compare --siblings` 兄弟分支 run 摘要对比，`merge --from <a> --from <b>` 交叉（`inherited` 声明来源），分支生命周期 active→pruned（文件保留不删），kill criteria 改为所有活跃分支连续 N 轮失败；context 包第 4 项改为兄弟分支 run 摘要对比表；B12 措辞从 `supersedes` 改为 `parent`/`parents`。 |
| 2026-11-06 | 0.10 | 批次2 对抗性 review 修复：B9 改**两级**（Immutable data/runs/vNN/alpha + Append-only hypothesis/lessons/index，新⊇旧），消除 lessons 迭代 push 死锁（L1）；B13 补 `alpha/`（L5）；§2.3 交叉段补 **I8 边界**（改造仅限策略层，禁改特征底层参数，L2）。 |
