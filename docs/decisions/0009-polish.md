# 0009 Polish（设计决策稿）

> **English**: [0009-polish.en.md](./0009-polish.en.md)
> **状态**：设计定稿（2026-11-12）
> **版本**：v0.1 | **日期**：2026-11-12
> **Owner**：ttrrei
> **Related**：`docs/hld.md` §8 第 9 行；`docs/review/overall-design-through-0008.md` 处置表（R1/R2/R7/R8/R9 挂起项）；`docs/requirements.md` R10

## 0. 背景与范围

0009 是 HLD §8 构建顺序的倒数第二个阶段。它由两部分组成：

1. **收口 overall-design review 挂起项**（#109 处置）：
   - R1 — track context 合并渲染 + hypothesis 无内容快照（仅存 SHA256）
   - R2 — `lyra run` 默认输出 `~/.lyra/runs` 与 workflow 扫描 `<workspace>/runs` 不一致；官方 v01 的 `spec_id` 匹配不到任何 branch；compare 可跨方向/跨数据版本静默比较
   - R7 — feature 宽表逐标的直覆写，无 staging/原子发布；catalog 不校验版本一致性
   - R8 — `_counter_fingerprint` 仅 2 个固定探针，不同 counter 可同指纹
   - R9 — `feature_catalog_snapshot` 只是目录名列表，非数据身份
2. **R12 交付物**：README 按真实 CLI 重写、单 lockfile + Python 版本策略、CI、`lyra-doctor`。

**范围外**（明确不做）：0010 temp/ triage（下一阶段）；任何新增 feature/指标；并发/调度（R9 out-of-scope 维持）；重新裁决任何已定用户决策。

## 1. 决策清单

| ID | 决策 | 依据 |
|---|---|---|
| D1 | **hypothesis 内容快照**：`create_track` 在 track JSON 中冻结 hypothesis **全文**（`hypothesis_snapshot`）+ 现有 SHA256；`render_context` 用快照文本渲染；若活文件已漂移（sha 不等）显式标注 "hypothesis has drifted since track creation (snapshot below is frozen)"，两者都展示 | 收口 R1 |
| D2 | **runs 目录统一**：`runner._default_out()` 默认值由 `~/.lyra/runs` 改为**从 `--config` 解析的 workspace 根下 `runs/`**（`<workspace>/runs`，与 0007 D7 规范路径、`push-runs` 一致）；`--out` 显式覆盖仍可用；`lyra run` 完成后在 run 目录写 **`run_meta.json`** 身份侧车：`{direction, branch, track_id|null, spec_id, strategy_path, run_id}` | 收口 R2 |
| D3 | **compare 身份与可比性**：`_runs_for_branch` 匹配改为 `run_meta.json` 身份优先、`spec_id` 回退（兼容旧 run）；`compare_siblings` 输出每 run 的 `data_digest` + `feature_version` 摘要，**digest 不全等时逐 run 标注 `comparable=false`**，汇总表顶部给出 "incomparable: N/M runs" 而不是静默并列 | 收口 R2/R9 |
| D4 | **feature 原子发布 + generation 门禁**：`run_features` 先写 `<data_root>/.features_staging/<layer>/`，全部标的完成后逐一 rename 到 `<data_root>/features/<layer>/`，最后写 **`features/<layer>/_generation.json`**（`{version_string, file_sha256: {...}, generated_at}`）；新增 `validate_generation(data_root)`：每个 `features/<layer>/*.parquet` 必须在当前 `_generation.json` 的 sha 表中且 `feature_version` 列一致，否则 `FeaturesError`（fail-closed）；`lyra features` 与 `lyra-doctor` 调用 | 收口 R7 |
| D5 | **counter 身份 token**：`trading_days_for` 可选携带 `__lyra_identity__ = "name/version"` 属性（命名+版本）；有则 run_id 记 `counter:<identity>`，无则沿用 2 探针指纹并记 `counter:unidentified:<fingerprint>`（行为指纹降级，明确标注非身份） | 收口 R8 |
| D6 | **feature snapshot 数据身份**：`feature_catalog_snapshot` 由"目录名列表"升级为**基于 D4 `_generation.json` 的摘要**——若存在则 `feature_snapshot_digest = SHA256(canonical({layer, version_string, file_sha256_map}))`（**零额外全量哈希**，复用 D4 已算好的逐文件 sha），并保留 views 名列表作可读字段；若缺 `_generation.json`（遗留数据）则回退到"目录名列表 + `legacy=true`"标注，**不**在 run 时对大表全量重哈希（`data_digest` 已覆盖消费列，run_id 安全）。digest 进入 run manifest 与 `_compute_run_id` payload（数据层换代 ⇒ run_id 变化） | 收口 R9 |
| D7 | **README 重写**：按真实 CLI 命令集（pull/clean/aggregate/features/build/validate/run/report + OCI 8 命令 + workflow 12 命令）与 B13 路径（`~/.lyra/<workspace>/…`）重写；删除 `src/`、`lyra-doctor` 占位等不实内容；安装段落与 D8 一致 | 收口 R12 |
| D8 | **lock + Python 策略**：`pyproject.toml` `requires-python` 钉 `>=3.12,<3.13`（开发基线 3.12；numpy 2.5.4 仅发 cp312 wheel，3.11 需旧 numpy，故不收 3.11）；**单一 `requirements.lock`**（`pip freeze` 从 3.12 venv 生成，唯一锁文件；不另造 `requirements.txt`，避免两个依赖来源）；生成脚本 `scripts/make_lock.sh` 记录方法 | 收口 R12 |
| D9 | **CI**：`.github/workflows/ci.yml` — **py3.12**（与 lock 对齐；TA-Lib 0.8.2 有 manylinux 预编译 wheel，无需 C 编译）；`pip install -r requirements.lock` → `pyflakes` → `pytest -q` | 收口 R12 |
| D10 | **`lyra-doctor`**：新增 CLI 命令，只读自检，**分两级**——**硬失败（exit 1）**：① Python 版本在策略区间 ② 核心依赖可 import ③ config 可解析且 4 槽位齐全；**警告（不阻断，打印 WARN 计数）**：④ catalog.duckdb 存在且 bronze/features 视图齐 ⑤ `validate_generation`（D4）通过 ⑥ 1 个标的 × 短窗 compile 冒烟（只 compile 不 run，写临时目录）。纯环境/配置问题才红，数据/运行状态缺失只黄不红，保证用户未跑 `lyra pull` 前 doctor 仍能作为"环境就绪度"探针使用，不强制阻塞 R10 验收 | 收口 R12 / R10 验收 |
| D11 | **R10 签收**：D7–D10 落地 + 全仓测试绿 + doctor 全绿后，`requirements.md` R10 双语标注"0009 完成、R10 全部验收项满足"（0008 签收状态保持） | R10 收口 |

## 2. 关键设计说明

### 2.1 D2 runs 目录统一的边界

- 只改**默认值**与**身份侧车**，不改 `--out` 显式行为，不破坏任何已落盘的旧 run。
- `push-runs` 的 `~/.lyra/runs` 兼容扫描保留一个版本（`LYRA_RUNS_ROOT` 环境变量 + 旧默认），避免已有 artifacts 失联；0010 起可移除。
- `run_meta.json` 由 CLI 层写（CLI 知道 config→workspace→direction/branch 上下文），runner 核心保持无 workspace 依赖。

### 2.2 D3 可比性判定

- 可比 = 同 `data_digest` **且** 同 `feature_version`。不同方向天然可比（同数据），同一方向不同参数（不同 strategy_yaml）也可比——差异只在策略本身，这正是 compare 要展示的。
- `compare` 仍只读；"incomparable" 只是标注，不阻断输出（人可判断）。

### 2.3 D4 原子发布语义

- staging 目录与目标同文件系统（同 `data_root` 下），`Path.rename` 即原子 move。
- 中途失败：staging 残留由下次 `run_features` 开头清理；目标目录保持上一次完整 generation，**永远不出现半新半旧**。
- `_generation.json` 是 `lyra-doctor`（D10 ④）与 0010 triage 的数据信任锚点。

### 2.4 D6 的实现路径

`run_strategy` 编译前已经打开 `catalog.duckdb`（读 views）；D6 在同一时刻读
`<data_root>/features/<layer>/_generation.json`（存在才读），把 digest 传给
`_compute_run_id`。缺失时走 legacy 回退，**不新增任何对大表的全量读**。

### 2.5 D6 与既有 run_id 的关系

- `data_digest`（0006 已有，覆盖消费列）保留；`feature_snapshot_digest` 覆盖**整个 feature 层**（所有标的文件），二者互补：前者保证"用到的数据变了 run_id 必变"，后者保证"数据层整体换了一代 run_id 必变"。
- `feature_version_string` 已含 registry/alpha/pandas/numpy 指纹，D6 只补**数据文件**维度。

## 3. 测试计划（新增/修改）

| 模块 | 新增用例 |
|---|---|
| test_workflow | `create_track` 冻结 hypothesis 全文；hypothesis 漂移后 `render_context` 用快照 + drift 标注；`_runs_for_branch` 走 `run_meta.json` 身份；旧 spec_id run 回退匹配仍工作 |
| test_workflow | `compare_siblings` 对 digest 不同的 runs 输出 `comparable=false` 标注 |
| test_features | staging 原子发布（模拟单标的失败 → 目标目录保持旧 generation 完整）；`validate_generation` 检测混代文件；snapshot digest 含逐文件 sha |
| test_runner | `run_meta.json` 侧车由 CLI 路径写入（cli 层测试）；counter `__lyra_identity__` 进入 run_id；无 identity 的 counter 记 `unidentified` |
| test_cli（新） | `lyra-doctor` 全绿路径 + 硬失败路径（exit 1）+ 警告路径（exit 0 但 WARN 计数>0） |

## 3a. 自检 / 对抗性检验记录

设计自检（v0.1→0.2）修正 4 处：D8 锁单源；D9 TA-Lib C 库前置；D10 两级 severity；D6 快照 digest 改从 generation manifest 派生（不重算大表）。

**对抗性检验发现（v0.2→0.3，已修正）**：
1. **（P1，已修）lock 与 CI 3.11 不兼容**：`requirements.lock` 由本地 **Python 3.12** venv 生成，其中 **numpy 2.5.4 仅发 cp312 wheel（cp311=0，仅 sdist）**；CI 矩阵含 3.11 会导致 numpy 安装失败或退回 C 编译。→ **支持面钉 3.12**：`pyproject` `>=3.12,<3.13`、CI 矩阵改单点 **py3.12**（与 lock 一致）。设计自检漏查了 numpy（只查了 pandas/duckdb/ta-lib 的 wheel）。
2. **（P3，已修）D4 陈旧文件**：原子发布后，若某 instrument 从数据集消失，旧 view 目录会残留其 parquet。→ `run_features` 发布时以 `instruments` 白名单清理 `layer_dir` 中非当前集的文件，保证 `validate_generation` 白名单准确、不产生假阳性 stale。
3. **（P3，已修）doctor compile 冒烟依赖 cwd**：`_default_example_strategy` 之前用**包安装位置**找 example yaml（非项目根），从安装态/CI 运行找不到。→ 改从 `lyra` 包位置向上探测项目根的 `strategies/examples/`，并回退到内置最小 RSI 策略，保证 compile 冒烟在任何工作目录都稳定。
4. **（P3，已修）doctor 重复加载 catalog**：compile 冒烟分支再次 `Catalog(cat_file)`。→ 复用已打开的 `cat` 句柄。
5. **（P3，已修）D3 `distinct_feature_generations` 语义**：原用 `len(set(ids))`（含 `None`），"部分有 identity"时数值误导。→ 改为 distinct **非空** feature_snapshot_id 计数；无 identity 的 run 用 `runs_without_data_identity` 单列表达。
6. **（P2，已修）D2 `run_meta` 身份匹配**：原 `_runs_for_branch` 的 run_meta 匹配分支只要求 branch 相等，可能把**其它方向**的 run 计入本方向。→ 加 `direction` 相等守卫（spec_id 回退分支的 H7 `spec_id` 等值约束保留）。
7. **（P2，已修）D2 push-runs 身份**：原只校验 branch。→ 增加 `direction` 校验，`direction=None` 的旧 manifest 仍兼容放行（backwards-compatible）。
8. **（P2，已修）`lyra run` 默认 out**：设计文档写 `<workspace>/runs`，但 `runner._default_out` 仍指向 `~/.lyra/<ws>/runs`（不同根）。→ CLI `run` 默认 out 显式置 `<workspace>/runs`（0007 D7 树），`runner` 内默认保留旧值以兼容库调用。
9. **（P2，已修）run_meta 的 `branch` 来源**：原用 strategy `id` 当 branch（`directions_momentum_exhaustion` 而非 `v01`）。→ CLI 从**文件名**取 `vNN[_variant]` 作为 branch，`--track` 提供 track 身份，与 workflow 分支语义一致。
10. **（P3，已修）README/HLD/requirements 的 "3.11–3.12" 表述**：随 #1 一并对齐为 3.12 单点。

以上修正已回归验证（见测试计划），无遗留 P1/P2。

## 4. 验收（0009 完成判据）

- [x] R1/R2/R7/R8/R9 五项挂起项全部有实现 + 回归测试
- [x] README 与真实 CLI 一致（无 `src/`、无占位命令）
- [x] `pyproject.toml` `requires-python` 有上下界（`>=3.12,<3.13`）；`requirements.lock` 存在且 CI 用它安装
- [x] `.github/workflows/ci.yml` 本地等价验证（py3.12：lock 安装 + editable install + `lyra` 入口 + pyflakes + pytest）
- [x] `lyra doctor` 在本机开发环境全绿（真实 config，0 hard fail + WARN）
- [x] 全仓 `pytest -q` 绿 + pyflakes 干净（327 passed）
- [x] `requirements.md` R10 双语签收标注（D11）
- [x] ACTION_LOG 状态块 + 0009 决策稿双语成对 + HLD §8 第 9 行刷新

> **11-12 批次1 review 追加（§3a 之后）**：H3 消费端 fail-closed generation 门禁
> 已实现（`lyra run` 读特征前校验 + 回归测试）；H4 doctor 四 OCI 槽位均硬失败
> （D10 语义）；H5 README 干净环境安装改为 build isolation（已实测通过）；
> M1 doctor Python 策略=3.12 单点 + 核心依赖补 numpy/TA-Lib；M2 本清单 + HLD +
> ACTION_LOG 同步；M3 命令名 `lyra doctor`、`lyra build`→真实管道命令、compile
> smoke 内置 fallback；M4 run_meta 写失败改为硬失败。详见 `docs/reviews/`。

## 5. D12 / D13 — track 级候选布局与逐 run 可比性判定（11-12 批次1 H1/H2，用户 2026-11-13 裁决"现在做"，**#112 已落地**：pytest 333 passed + 9 项对抗性探针全过 + CLI 全链路实测）

### D12. 候选文件归属 track（H1）

**布局**：
```
strategies/<direction>/
├── hypothesis.md                  ← 方向级共享（只读基线，冻结进每 track baseline）
├── lessons.md                     ← 方向级共享教训
├── v01.yaml                       ← 方向级基线（legacy 只读；所有 track 共享起点）
├── index/t<track>.jsonl           ← track 事件日志（不变）
├── <track_a>/v02a.yaml            ← track 拥有（H1 新增层）
├── <track_a>/v03.yaml
└── <track_b>/v02a.yaml            ← 与 track_a 的 v02a 同名共存（H1 核心）
```

**规则**：
1. **方向级 vNN.yaml = 共享基线，只读语义**：`new_version`/`merge` 不再写方向级；方向级文件仍可被读取（作为 parent / 基线）与 push。存量 12 个方向的 `v01.yaml` 原地不动（零迁移：`~/.lyra/default` 的 tracks 目录为空，无任何 track 数据）。
2. **重复检查 track 化**：`new_version` 的"分支已存在"检查改为**本 track 目录内**存在才拒绝；跨 track 同名合法（`strategies/<direction>/<track>/v02a.yaml` 互不冲突）。
3. **`_branch_file` 解析**：优先 `<track>/<branch>.yaml`，回退方向级（基线）；`--from` parent 同理（方向级基线永远是合法 parent）。
4. **runs 隔离**：`_runs_for_branch` 增加 `track` 参数——`run_meta.track_id` 匹配（无 track 参数时保留旧行为，供 `synthesize` 跨 track 读取并标注来源）。`context --track` 只列本 track runs（H1 核心诉求）。
5. **merge**：目标文件写本 track 目录；auto-name（下一个空 vNN）在**本 track + 方向级**集合上求空号。
6. **OCI 兼容**：`classify_path` 按文件名分类（`_VNN_RE` 匹配末段），`strategies/<dir>/<track>/vNN.yaml` 仍判 immutable，**无需改 oci_push**（已核对）。
7. **cap/事件日志**：不变（已 track 级）。

### D13. compare 逐 run 身份判据（H2）

1. **身份字段**：`metrics.json` 与 `manifest.json` 增加 `data_digest`（runner 已计算，仅入 run_id payload）与 `feature_version`（manifest 已有）。`run_meta.json` 不变（身份=归属；数据身份在 metrics）。
2. **判定**：`compare_siblings` 对参与比较的 run 集合判定 `comparable` = 所有 run 的 `data_digest` 相同 **且** `feature_version` 相同 **且** `feature_snapshot_digest` 相同（0009 D3 已有项保留为第三维）。任一 run 缺字段（legacy）→ `comparable=None`（unknown，不推定可比）并单列 `runs_without_data_identity`；有字段但互异 → `False` + 逐 run `incomparable_reason`（`data_digest`/`feature_version`/`feature_snapshot`）。
3. **逐 run 输出**：每个 run 行携带 `data_digest` / `feature_version` / `comparable`，AI 可看到"这个 run 为什么不能和那个比"。
4. **synthesize**：跨 track 合成显式列出 track 来源 + 每 run 身份字段（I22 显式入口，非隐式混入）。

### 测试计划（新增）
- H1：两 track 各自 `new_version v02` 成功（方向级文件互斥性解除）；`context --track` 不串读另一 track 的 runs；`--from` 指向方向级基线可用；OCI 分类对 track 子目录仍 immutable。
- H2：同 snapshot、不同 data_digest 的两 run → `comparable=False` + reason；缺 data_digest 的 legacy run → `comparable=None`；三字段全同 → `True`；metrics.json/manifest.json 含两字段。
- 回归：现有 `test_cap_is_per_track_not_global` 等 track 语义测试保持绿（布局只新增子目录层，不改变已有断言路径）。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-12 | 0.1 | 初版设计定稿：D1–D11 决策表 + 关键设计说明 + 测试计划 + 验收判据。 |
| 2026-11-12 | 0.2 | 设计自检修正：D8 改为 `pyproject.toml` 上下界 + 单一 `requirements.lock`（不另造 requirements.txt）；D9 补 TA-Lib C 库依赖的 CI 前置；D10 拆两级（硬失败=环境/配置类，警告=数据/运行状态类），避免未 pull 前 doctor 必红。 |
| 2026-11-12 | 0.3 | 对抗性检验（见 §3a）：修 **P1 lock/CI 3.11 与 numpy 2.5.4 不兼容**（支持面钉 3.12）；P2 `run_meta`/`push-runs` 身份匹配漏 `direction` 守卫；P3 D4 陈旧 instrument parquet 未清理（已实现 prune + 回归测试）、doctor compile 冒烟依赖 cwd、compare 可比性 `distinct_feature_generations` 语义、README/HLD/requirements 的 3.11–3.12 表述对齐为 3.12。全部回归验证。 |
