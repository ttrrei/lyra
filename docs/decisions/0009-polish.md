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
| D8 | **lock + Python 策略**：`pyproject.toml` `requires-python` 加上界 `>=3.11,<3.13`（开发基线 3.12）；**单一 `requirements.lock`**（`pip-compile` 从 `pyproject.toml` 依赖生成，唯一锁文件；不另造 `requirements.txt`，避免两个依赖来源）；生成脚本 `scripts/make_lock.sh` 记录方法 | 收口 R12 |
| D9 | **CI**：`.github/workflows/ci.yml` — py3.11 + py3.12 矩阵；**TA-Lib 是 C 库依赖**（`pyproject.toml` 核心依赖之一），CI 需先 `apt-get install` 对应系统库（或 `pip install` 预编译轮子，若目标平台有），再 `pip install -r requirements.lock` → `pyflakes` → `pytest -q` | 收口 R12 |
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

## 4. 验收（0009 完成判据）

- [ ] R1/R2/R7/R8/R9 五项挂起项全部有实现 + 回归测试
- [ ] README 与真实 CLI 一致（无 `src/`、无占位命令）
- [ ] `pyproject.toml` `requires-python` 有上下界；`requirements.lock` 存在且 CI 用它安装
- [ ] `.github/workflows/ci.yml` 在 GitHub Actions 上绿（或本地等价验证）
- [ ] `lyra-doctor` 在本机开发环境全绿
- [ ] 全仓 `pytest -q` 绿 + pyflakes 干净
- [ ] `requirements.md` R10 双语签收标注（D11）
- [ ] ACTION_LOG 状态块 + 0009 决策稿双语成对 + HLD §8 第 9 行刷新

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-12 | 0.1 | 初版设计定稿：D1–D11 决策表 + 关键设计说明 + 测试计划 + 验收判据。 |
| 2026-11-12 | 0.2 | 设计自检修正：D8 改为 `pyproject.toml` 上下界 + 单一 `requirements.lock`（不另造 requirements.txt）；D9 补 TA-Lib C 库依赖的 CI 前置；D10 拆两级（硬失败=环境/配置类，警告=数据/运行状态类），避免未 pull 前 doctor 必红。 |
