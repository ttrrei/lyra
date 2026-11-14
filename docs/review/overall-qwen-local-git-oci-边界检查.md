# lyra Git / OCI 边界检查（alpha 策略同步）

> 审查对象：`strategies/directions/*/nova/*.yaml`（121 个未提交 YAML）为何既未进 git、也未进 OCI。
> 结论先行：**这不是 `.gitignore` 一处笔误，而是「alpha 边界」在规范、`.gitignore`、git 实际内容、OCI 镜像、CI 五处彼此不一致**。你的直觉是对的——这批文件当前处于「哪个持久层都不保证收留」的悬空状态。

---

## 0. 你看到的 143 个未提交文件，到底是什么

精确核对（`git ls-files --others --exclude-standard` 展开目录到文件）：

| 组成 | 数量 | 说明 |
|---|---|---|
| 未跟踪 untracked | **125** | 其中 **121 个是 `.yaml`** |
| 已修改 modified | **18** | 含我上一轮的 core 改动（`lyra/*.py`、`tests/*`、`requirements.lock` 等） |
| **合计** | **143** | 与你看到的一致 |

121 个 alpha YAML 全部落在 7 个方向下，形态固定为 `strategies/directions/<direction>/nova/vNN.yaml`：

```
strategies/directions/failed_breakout/nova/v101..v120.yaml   (19)
strategies/directions/market_structure/nova/v101..v116.yaml  (16)
strategies/directions/mean_reversion/nova/v101..v120.yaml    (20)
strategies/directions/range_trading/nova/v101..v120.yaml     (20)
strategies/directions/trend_continuation/nova/v101..v119.yaml (20)
strategies/directions/volatility_expansion/nova/v101..v119.yaml (19)
strategies/directions/volume_activity/nova/v101..v107.yaml    (7)
```

这 121 个文件的来源与意图是明确的（见 `docs/decisions/0010-temp-triage.md`）：
- 它们是 **0010 triage** 从 `strategies/temp/nova_campaign/` **promote** 出来的候选；
- 归入 **独立 track id = `nova`**（0010 §2：不复用方向级 v01 的默认空间）；
- 0010 明确写了「`classify_path`：`nova/vp1_r06.yaml` → **immutable（I17 合法，可推送）**」，以及验收项「迁移可被 `push-strategy` 正常 staging（干跑）」。

**也就是说：按项目自己的裁决，这批文件的目的地是 OCI（经 `push-strategy` / `push-direction`），而不是 git。** 下面逐条看它为什么没到 OCI，以及为什么它反而会落进 git。

---

## 1. 边界「应该」长什么样（设计规范，四处文档）

| 文档 | 关于 `strategies/`（alpha）的裁决 |
|---|---|
| `AGENTS.md` §Alpha boundary | **OCI contains alpha only**：custom features + **all strategy YAMLs** + all runs + data。**Git contains core only**。**"Never commit alpha paths to git. CI checks this."** 且 B14：`strategies/examples/` 是 git 里**唯一**被跟踪的 strategies 子树 |
| `docs/proposals/oci-alpha-layout.md` §2.3 | `strategies/`（方向 + 版本树，含 `vNN.yaml` + `hypothesis.md` + `lessons.md`）**性质：闭源，是 alpha 的核心** |
| `docs/decisions/0007-oci-push-and-backup.md` | Part A：`push` / `backup`(=`sync`) / `push-strategy` / `push-direction` 把本地**工作区根**的 strategies/runs 持久化到 OCI（I17 两级幂等） |
| `docs/decisions/0010-temp-triage.md` | nova 候选 promote 到 `directions/<family>/nova/`，作为 **track `nova`** 的候选，目的地经 `push-strategy` 推 OCI |

规范意图非常一致：**alpha 策略 YAML = OCI 所有；git 只该有 `strategies/examples/`（+ 只读语料 `strategies/temp/`）；alpha 绝不该进 git，且 CI 要兜底。**

---

## 2. 实际长什么样（五处事实）

### 事实 1 — `.gitignore` 自相矛盾，把 alpha **放行进了 git**

`.gitignore` 的注释（L26-28）与文件头（B1）都写着「只跟踪 examples/ 与 temp/，**忽略一切真实方向文件夹及其 vNN.yaml / hypothesis.md / lessons.md**」。但同一文件的实际规则（L31-37）：

```gitignore
strategies/*                 # 忽略 strategies 的"子项"（不忽略目录本身）
!strategies/examples/
!strategies/examples/**
!strategies/temp/
!strategies/temp/**
!strategies/directions/      # ← 反包含！把 alpha 方向文件夹重新纳入
!strategies/directions/**    # ← 反包含！vNN.yaml / hypothesis.md / lessons.md 全部可被 git 跟踪
```

`!strategies/directions/**` 是**否定（反包含）规则**，效果是：`strategies/directions/` 下**所有**文件（含 `nova/vNN.yaml`）都**不再被忽略** → **可被 `git add` 提交**。

验证（`git check-ignore`）：
```
$ git check-ignore -v strategies/directions/failed_breakout/nova/v101.yaml
.gitignore:37:!strategies/directions/**   .../failed_breakout/nova/v101.yaml
# 退出码 0 = "这条匹配的是反包含规则" → 该文件【未被忽略】→ 可提交
```

**急性风险**：此刻若执行一次 `git add -A`，**121 个 alpha `nova/vNN.yaml` 会被全部加入暂存区并随 `git commit && git push` 进 GitHub**（remote 为 `https://github.com/ttrrei/lyra`）。这正是 `AGENTS.md` 反复警告的「alpha 被误提交进 git → 被均摊」事故。

```
$ git add -n -A | grep -c 'directions/.*nova/'
121
```

### 事实 2 — alpha 已经在 git 里（12 个 v01 种子被跟踪）

```
$ git ls-files 'strategies/directions/**'
strategies/directions/{failed_breakout,market_structure,mean_reversion,
  momentum_exhaustion,pullback_reentry,range_trading,regime_transition,
  relative_strength,session_temporal,trend_continuation,
  volatility_expansion,volume_activity}/v01.yaml      # 共 12 个，全部被 git 跟踪
```

且 `git ls-files 'strategies/directions/**' | grep -vE '/v01\.yaml$'` **为空**——即 git 里**只有 v01 种子**，没有 vNN>1、没有 `hypothesis.md`/`lessons.md`。

- 这 12 个 v01 是 **0008 迁移**（commit `f6bd2e4`）从 nova 逐字拷贝进来的「方向级共享只读基线」。
- 但 `AGENTS.md:90` 白纸黑字：**"Never commit alpha paths to git"**；`oci-alpha-layout.md §2.3`：`vNN.yaml`（v01 也是 vNN）= **闭源 alpha**。
- **结论**：「v01 基线入 git」是 0008 的一次**裁决**，但它与 `AGENTS.md` / 布局文档的边界定义**直接冲突**。这是规范层（AGENTS.md vs 0008 裁决）的矛盾，不是实现 bug。

### 事实 3 — OCI 推送的「源」是 `~/.lyra/<ws>` 镜像，而这批文件不在镜像里

`cli.py` 的 `push_strategy` / `push_direction`（L700-770）**不读 git 工作树**，而是读「规范工作区根」：

```python
root = _workspace(config)                 # = ~/.lyra/<workspace>/
local_root = root / "strategies" / direction
if not local_root.is_dir():
    typer.secho(f"no strategies/{direction}/ at {local_root}", err=True); return
staging = _staging_slice(root, direction, include_runs=...)
```

而 OCI 本地镜像 `~/.lyra/default/strategies/` 的现状是：

```
$ find ~/.lyra/default/strategies -name '*.yaml' | wc -l
0
$ find ~/.lyra/default/strategies -type d -name nova
（空）
```

即镜像里 **`strategies/` 一个 YAML 都没有**（镜像只有 1649 个文件，全部是 `runs/` 的运行产物，`0010*` 系列 run）。

**结论**：这 121 个 `nova/vNN.yaml` **只存在于 git 工作树**（`/home/ubuntu/work/lyra/strategies/directions/*/nova/`），**既不在 git 对象库（未 add），也不在 OCI 镜像（`~/.lyra/default/strategies/` 为空）**。它们是一次性落在工作树的孤立副本。若工作树被清理 / `git clean`，且镜像/OCI 从未收留过，它们就**丢失**；反之，若有人 `git add -A`，它们就**泄漏**。两头都不安全。

### 事实 4 — "CI checks this" 是空头支票

`AGENTS.md:90` 称「Never commit alpha paths to git. **CI checks this.**」，但 `.github/workflows/ci.yml` 的全部步骤只有：`checkout → setup-python → pip install → pyflakes → pytest`。**没有任何** alpha-in-git 扫描（无 `git ls-files | grep directions/`、无 secret/alpha 路径检查、无 pre-commit hook）。

**结论**：兜底不存在。alpha 能否进 git 完全取决于 `.gitignore` 那两行——而那两行恰好是**放行**（事实 1）。

### 事实 5 — 0010 的「可推送」验收从未真正对 OCI 镜像生效

0010 要求「迁移可被 `push-strategy` 正常 staging（干跑）」。但 `push_strategy` 的源是 `~/.lyra/<ws>/strategies/<dir>`（事实 3），而镜像里该路径**不存在**（L719 会直接 `no strategies/{direction}/ at ...` 报错退出）。也就是说：即便你跑 `lyra push-strategy failed_breakout/nova`，它**读不到**这批工作树里的文件——因为它们在仓库树，不在镜像树。**推送路径与文件实际落点不在同一棵树。**

---

## 3. 问题定性：边界定义本身碎了，不是 `.gitignore` 一处笔误

把五处事实并排，矛盾是系统性的：

| 层 | 对 `strategies/directions/<dir>/nova/vNN.yaml` 的口径 | 现状 |
|---|---|---|
| 规范 `AGENTS.md` | **不进 git，进 OCI** | ✅ 意图 |
| 规范 `oci-alpha-layout.md` | **闭源 alpha，进 OCI** | ✅ 意图 |
| 裁决 `0008` | **v01 基线进 git**（与上面冲突） | ⚠️ 已入 git |
| `.gitignore` L36-37 | **`!directions/**` 反包含 → 可进 git** | ⚠️ 放行 |
| git 对象库 | **v01 已跟踪；nova/vNN 未跟踪但可 add** | ⚠️ 半泄漏 |
| CI | **声称检查 alpha-in-git** | ❌ 根本没查 |
| OCI 镜像 | **应有 strategies 树** | ❌ 空（0 yaml） |

**一句话**：同一个文件类别，规范说「只能进 OCI」，但 `.gitignore` 把它放行进 git、CI 不拦、OCI 镜像没收留——**三个「该拦住 / 该收留」的关口全都没站岗**。

---

## 4. 直接回答你的问题

> 「这些 strategy 文件原则上不应该是 sync 到 OCI 的吗？如果是 .gitignore 的问题，请详细检查 github 和 oci sync 的边界。」

1. **对，原则上该进 OCI**：`strategies/**` 是闭源 alpha，0010 明确把 nova 候选列为 OCI 目的地（`push-strategy` staging 验收项）。
2. **不只是 `.gitignore`**：`.gitignore` 的 `!strategies/directions/**` 只是「放行侧」的失误之一。更根本的是——
   - **规范自身冲突**：`AGENTS.md`（alpha 不进 git）vs `0008 裁决`（v01 进 git）。
   - **推送源错位**：`push-strategy`/`push-direction` 从 `~/.lyra/<ws>` 镜像读，而这批文件在工作树、镜像里是空的 → **推送命令根本够不到它们**。
   - **兜底缺失**：CI 声称检查 alpha-in-git 却没有实现。
3. **当前最大风险**：一次 `git add -A` + `push` 就会把 121 个 alpha YAML 推到 GitHub；而当前 OCI 镜像/远端对这批文件**零覆盖**，意味着它们也**没有安全备份**。

---

## 5. ✅ 已落地（2026-11-14，按你的裁决 B1：所有 strategy = alpha，无例外）

你已拍板「nova 迁移的全部算 alpha、都上 OCI、无例外」= **方案 B1**。已完整执行并验证：

| 步骤 | 动作 | 结果 |
|---|---|---|
| 1. 镜像 | `strategies/directions/<family>/` → 规范 OCI 形 `~/.lyra/default/strategies/<family>/{v01,nova/vNN}` | 133 文件（12 v01 + 121 nova） |
| 2. dry-run | 全 12 族 `push-direction --dry-run` | 133 upload / **0 conflict** / 0 unclassified（全判 immutable） |
| 3. **真实 push** | `lyra push-direction` 全 12 族 → `lyra-strategies` 桶 | **133/133 成功** |
| 4. 验证 | `lyra list --prefix strategies` | **134 对象**（133 YAML + readme），121 nova 确认在 OCI |
| 5. 堵 git 洞 | `.gitignore` 移除 `!strategies/directions/**` 反包含 | `directions/` 全部 ignored；`examples/`+`temp/` 仍可跟踪 |
| 6. 移出 alpha | `git rm --cached` 12 个 `directions/*/v01.yaml` | 磁盘保留、已在 OCI；git 不再跟踪任何 `directions/` |
| 7. **堵漏验证** | `git add -n -A \| grep directions` | **0 个**（急性泄漏风险已消除） |
| 8. CI 闸门 | `ci.yml` 新增 "Alpha-in-git gate"（strategies/ 只允许 examples/ + temp/） | 自测：当前 PASS；模拟泄漏正确 FAIL |
| 9. 提交 | 独立 commit `d3deeca`（边界修正，与 core 改动分离） | 已提交 |

**验收口径**：`git ls-files strategies/directions/` = 0；OCI `lyra list` = 134；CI gate 双态自测通过。至此三处关口（`.gitignore` 不放行、git 不跟踪、CI 拦）全部站岗，alpha 策略**只在 OCI**，git 仅保留 `examples/`（示例）与 `temp/`（只读语料）——与 `AGENTS.md` / `oci-alpha-layout` 规范完全自洽。

---

## 5.（原）处置建议（按 接受 / 挂起 / 拒绝 给决策）

> 说明：收尾阶段，我按「二选一、不挂起」给倾向，但**每一项都会改边界语义或动已裁决项**，需要你拍板方向后再动手。下面标注我**推荐**的处置。

### A. 【推荐接受】让 alpha 真正离开 git、进 OCI 镜像
- **改 `.gitignore`**：删掉 `!strategies/directions/` + `!strategies/directions/**`（L36-37），恢复「只放行 `examples/` 与 `temp/`」。这样 `directions/**` 重新被忽略，`git add -A` 不再收 alpha。
- **把 12 个已跟踪的 `directions/*/v01.yaml` 移出 git**：`git rm --cached`（保留磁盘文件）+ 提交，使 git 对象库不再有 alpha。
- **把 alpha 落到 OCI 镜像树** `~/.lyra/<ws>/strategies/<dir>/`，再 `lyra push-strategy` / `push-direction` 推到 OCI（这才是 0010 的既定目的地）。
- **加 CI 兜底**：`ci.yml` 增加一步 `git ls-files | grep -E 'strategies/(directions|[^e t])/'`（放行 `examples/`、`temp/`），有命中即 fail——把 `AGENTS.md:90` 的空头支票变成真闸门。
- 风险/代价：需你确认「v01 基线也该进 OCI 而非 git」这一**边界裁决反转**（它推翻了 0008 的一处落地）。

### B. 【二选一，取决于你对 v01 的立场】
- **B1（推荐）**：v01 基线**同样视为 alpha** → 走 A 全程（git 里不留任何 `directions/`）。最干净、与 `AGENTS.md` / 布局文档一致。
- **B2**：认定「v01 方向级只读基线 = 可共享的 core 资产」→ 那需要**改写规范**：在 `AGENTS.md` / `oci-alpha-layout.md` 明确「`directions/*/v01.yaml` 属 core、可入 git；`vNN>1`/`hypothesis`/`lessons`/`nova/` 属 alpha、只进 OCI」，并据此把 `.gitignore` 改成**精确放行 v01、忽略其余**，同时 CI 闸门只拦「非 v01」。更复杂、文档改动面更大，但保留了「基线可见」的现状。

### C. 【拒绝】把 121 个 nova YAML 直接 commit 进 git
- 直接违背 `AGENTS.md:90` 与布局文档的闭源定位；且它们本就该是 OCI 的 track `nova` 候选。**不采用。**

---

## 6. 一句话结论

**已解决（2026-11-14，按 B1 裁决落地，见 §5）**：你这批 121 个 `strategies/directions/*/nova/*.yaml` 原是**悬空的**——`.gitignore` 放行它们进 git（危险）、CI 没兜底（无拦网）、OCI 镜像却是空的（无收留）；根因是「alpha 边界」在规范/`.gitignore`/git 实际/OCI 镜像/CI 五处不一致。**现已**：133 个 strategy（含 121 nova + 12 v01）全部 push 上 OCI 并 `lyra list` 验证在位；`.gitignore` 不再放行 `directions/`；git 移除 12 个 v01 跟踪（`git add -A` 实测 0 个 alpha）；CI 加了真正的 alpha-in-git 闸门。三处关口全部站岗，边界与 `AGENTS.md` 自洽。
