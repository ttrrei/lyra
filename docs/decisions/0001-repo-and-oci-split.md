# 0001 — Repo 与 OCI 的分工（alpha 边界）

> **English**: [0001-repo-and-oci-split.en.md](./0001-repo-and-oci-split.en.md)

## 元信息

| 字段 | 值 |
|---|---|
| ID | `0001` |
| 标题 | Repo（git）与 OCI（Object Storage）的分工，alpha 边界的物理落地 |
| 状态 | **已实施（OCI 拉取/清洗/聚合 0002 完成）** |
| Owner | `ttrrei` |
| 创建日期 | `2026-11-05` |
| 相关提案 | `docs/proposals/oci-alpha-layout.md` |
| 相关需求 | `docs/requirements.md` §R6, §R7 |
| 相关 HLD | `docs/hld.md` §1.3, §2.5, §3, §4 (I11-I12) |
| 取代 | —（继承 `nova/docs/DECISIONS_2026-11-03.md` §2 的 git/OCI split，
  并把"OCI 同步"从"尚未实现"提升为"核心 feature"） |

## 1. 问题

alpha（自定义特征 + 策略 + 运行结果）是被动收入来源，不能开源。
core（数据管线 + 编译器 + 回测引擎 + 指标）应该开源，便于 review 和
贡献。本 feature 定义**这两类内容的物理边界**，以及让两者保持同步的
机制（OCI 双向同步），使 Lyra 的**主功能**就是"跟 OCI 保持同步"。

## 2. 背景

- **moneta**：个人仓库，没有 alpha/core 分离；OCI 只用于拉数据
  （`extract_oci.py`），不用于备份策略/run。
- **nova**：`DECISIONS_2026-11-03.md` §2 已确立 git/OCI split 的**方向**
  （git=开源代码，OCI=数据+alpha），但把"OCI 同步机制"列为
  "尚未实现 / next major build item"（§10）。也就是说 nova 只有**方向**，
  没有**机制**。
- **Lyra 的增量**：把"OCI 同步"从待办项升级为**核心 feature**（R7），
  并给出可落地的目录布局（`oci-alpha-layout.md`）和硬边界规则（B1-B14）。

## 3. 方案

### 3.1 做什么

1. **物理边界**：git 只放 core（代码 + 标准特征 + 开源示例 + 测试 + 文档 +
   `config_example.yml`）；alpha 全在 OCI（自定义特征 + 全部策略 + runs +
   基础数据）。
2. **OCI 目录布局**：按 `oci-alpha-layout.md` §1-§2 落地
   （`data/` `alpha/` `strategies/` `runs/` `index/`）。
3. **双向同步**：`lyra pull` / `lyra push` / `lyra backup` / `lyra list`
   四个子命令（实现细节见 `0002` 和 `0007` 决策文档）。
4. **凭证**：`config/config_example.yml`（in git）+ `config/config.yml`
   （gitignored）+ 可选 `~/.lyra/credentials`；PAR URL 优先。
5. **边界规则 B1-B14**：写成 `lyra-doctor` 的静态检查项 +
   一条 CI 检查（扫 git 里有没有 alpha 路径 / 凭证）。

### 3.2 不做什么

- 不做 OCI 版本管理 / 权限管理 / 多桶路由（见 `oci-alpha-layout.md` §2.5）。
- 不做 S3 / GCS 适配（Q6：OCI 是唯一存储）。
- 不做"alpha 特征的自动发现 / 注册"（用户显式 `--extend-from` 指定目录）。
- 不做 live trading / broker 集成（R9）。

### 3.3 边界

- **输入契约**：`config.yml` 的 `oci.*` 段（见 `config_example.yml`）。
- **输出契约**：本地 `data/` `strategies/` `runs/` 三个目录是 OCI 的镜像，
  **默认解析到仓库外**（`~/.lyra/<workspace>/…`，见 B13）；
  `strategies/examples/` 是 git 跟踪的开源示例，运行时不读不写（B14）。
- **OCI 边界**：`pull` 只读 `data/`（默认）；`push` 只写 `alpha/`
  `strategies/` `runs/`；**绝不**在 git 工作区写任何 alpha 文件。
- **alpha 边界**：core 代码通过 `lyra.features.load_from(directory)` 加载
  alpha 特征，但**不 import** 任何具体 alpha 模块（保持 core 可独立运行）。
- **兼容边界**：moneta 的 332 策略 YAML 是 alpha（进 OCI），不是 core；
  Lyra core 必须能 `validate` / `run` 它们，但不**拥有**它们。

## 4. 不变量

| # | 不变量 | 来源 |
|---|---|---|
| I11 | 本地 OCI 镜像（`data/` `strategies/` `runs/` **`alpha/`**）可重建，且**默认在仓库外**（B13） | HLD §4 |
| I12 | 凭证不进 git / 不进 run 报告 | HLD §4 |
| I15 | git 里**不**出现 alpha 路径：`alpha/` 全部、`strategies/` 下任何方向文件夹内容、`runs/` 全部 | 本 feature 新增 |
| I16 | core 不 import 任何具体 alpha 模块（只 import 通用加载点） | 本 feature 新增 |
| I17 | OCI 文件**分两级**（B9）：**(a) Immutable**（`data/**`、`runs/**`、`strategies/**/vNN.yaml`、`alpha/features/**`）同 path 同 sha256 幂等，不同 sha256 报错；**(b) Append-only**（`strategies/**/hypothesis.md`、`lessons.md`、`index/*.json`）允许内容向前推进（新 ⊇ 旧） | `0001` 新增 |

## 5. 测试

| 测试 | 场景 |
|---|---|
| `test_git_has_no_alpha_paths` | 扫 git 跟踪文件，断言无 alpha 路径 / 凭证 |
| `test_config_example_has_no_secrets` | 断言 `config_example.yml` 无真实 PAR URL |
| `test_core_imports_no_alpha` | 断言 `src/lyra/*.py` 无 `import <alpha_feature>` |
| `test_pull_reads_only_data` | mock OCI，断言 `pull` 只请求 `data/` 前缀 |
| `test_pull_target_inside_repo_warns` | 目标路径在 git 工作区内 → 拒绝执行，除非 `--inside-repo`（B13） |
| `test_examples_not_touched_by_runtime` | `lyra run` 不得读/写 `strategies/examples/`（B14） |
| `test_push_is_idempotent` | 同 path 同 sha256 二次 push 不重复上传 |
| `test_push_rejects_sha_mismatch` | 同 path 不同 sha256 → 报错 |
| `test_credentials_not_in_run_meta` | 断言 `run_meta.json` 无 PAR URL / token |

## 6. 回滚

- 代码层面：revert 本 feature 的 commit；`oci.py` 是新增文件，删除即可。
- 数据层面：OCI 上的文件**不删**（两级不可变/追加，I17）；本地 `data/` 清缓存。
- 兼容性：回滚后 Lyra 退回"无 OCI 同步"状态，等价于 nova；
  332 策略仍可手动跑（本地 `strategies/` 保留）。

## 7. 审批

- [ ] 用户 review 目录布局（`oci-alpha-layout.md`）
- [ ] 用户 review 边界规则 B1-B14
- [ ] 用户 review 凭证管理方案
- [ ] AI review（另一模型）
- [ ] 测试全绿
- [ ] OCI 端到端跑通一次

## 8. 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-05 | 0.1 | 初稿。 |
| 2026-11-05 | 0.2 | I15 措辞修正：`strategies/active/` → 任何方向文件夹内容（与 R12 方向模型对齐）。 |
| 2026-11-05 | 0.3 | I11 加入"OCI 镜像默认在仓库外"（B13）；§3.3 输出契约补 B13/B14；§5 测试清单加 `test_pull_target_inside_repo_warns`、`test_examples_not_touched_by_runtime`。 |
| 2026-11-05 | 0.4 | B 规则引用统一为 **B1-B14**（§2/§3.1/§7 原残留 B1-B10）。 |
| 2026-11-06 | 0.5 | 批次2 对抗性 review 修复：I17 改**两级**（Immutable: data/runs/vNN/alpha；Append-only: hypothesis/lessons/index，新⊇旧），消除 lessons 迭代 push 死锁（L1）；I11 补 `alpha/`（L5）；§6 回滚"不可变"措辞对齐 I17。 |
