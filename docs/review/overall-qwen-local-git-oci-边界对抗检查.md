# lyra Git / OCI 边界 —— 自检 + 对抗检查

> 前置：上一轮我按 B1 裁决（所有 strategy = alpha，只进 OCI）"修复"了边界并报告"已完成 / 泄漏风险消除"。
> 本轮任务：**自检**（逐条验证那些声称是否成立）+ **对抗检查**（站在怀疑者视角专找漏洞与绕过）。
> **诚实结论：上一轮的"已完成 / 三处关口全部站岗 / 边界已修好"是过度乐观，对抗检查抓到 3 个我漏掉或说错的硬伤。**

---

## 一、自检：逐条验证上一轮的声称

| 上一轮声称 | 验证方式 | 结果 |
|---|---|---|
| 121 个 nova 已在 OCI | `lyra list --prefix strategies` | ✅ 134 对象（133 YAML + readme），121 nova 在位 |
| 133 已 push 成功 | 重推 `push-direction failed_breakout` | ✅ `0 upload, 20 skip`（I17 幂等实锤真在远端，非假成功） |
| `git add -A` 不再收集 alpha | `git add -n -A \| grep directions` | ✅ 0 个（**这条真成立**） |
| directions/ 全部 ignored | `git check-ignore` | ✅ 命中 `strategies/*` |
| 12 个 v01 移出 git 跟踪 | `git ls-files strategies/directions/` | ✅ 0（当前跟踪） |
| CI gate 双态自测 | 模拟泄漏文件 | ✅ 当前 PASS、模拟 FAIL |
| 无遗漏 hypothesis/lessons | `find directions/ -type f ! -name '*.yaml'` | ✅ 空（133 全 yaml） |
| 344 测试 / pyflakes | 实跑 | ✅ 全绿 |

**自检通过的项都是"未来方向"的防护（防 nova 再进 git、数据真在 OCI）——这些确实成立。**
**但自检同时暴露：上一轮从没查"已经发生的泄漏"和"temp/ 这个边界例外"。**

---

## 二、对抗检查：抓到的 3 个硬伤

### 🟥 P0 — F1：12 个 v01 基线已在 GitHub 历史里，**永久泄漏（不可逆）**
- **证据**：`git log origin/main -- 'strategies/directions/**'` → `origin/main` 全历史含 **12 个 `directions/*/v01.yaml`**（源 commit `f6bd2e4`「0008(a) landed」，已 push 到 `github.com/ttrrei/lyra`）。
- **内容非占位**：v01 含**真实 alpha 逻辑**（`supertrend_direction` + `psar_flip` + `after_event{bars:3,condition}`），是可用策略，非样板。
- **为什么上轮"修复"没堵住**：`git rm --cached` + `.gitignore` + CI gate **全部只作用于"未来"**——它们挡住"以后别再提交 alpha"，但**挡不住已经 push 进 GitHub 历史的 12 个 v01**。任何人 `git clone` 或翻历史都能拿到。
- **上轮的错误**：我把"急性泄漏风险已消除"当成了边界已修好。实际 121 个 nova（未来方向）确实安全了，但 **12 个 v01（过去）是已公开事实**。
- **不可逆性**：需 `git filter-repo` / BFG 改写 main 全历史 + 强制推送 + 所有克隆方 re-clone；若仓库有 fork / CI 缓存，需协同清理。**这是高风险全局操作，需你明确授权。**

### 🟧 P1 — F2：146 个 `strategies/temp/nova_campaign/*.yaml` 仍在 git 里，**与"无例外"裁决冲突**
- **证据**：`git ls-files 'strategies/temp/**'` → **146 个策略 YAML**（`temp/nova_campaign/<family>/<hex>/strategy.yaml`，含真实 entry/exit 逻辑：`failed_breakout_down_24` / `range_position_24` 等）+ 148 json + 2 md。
- **冲突点**：你的裁决是"**所有 strategy 都算 alpha、都上 OCI、没有例外**"。但 0010 的既有裁决是"temp/ = 只读历史语料，留 git 供跨机/多 AI 读取"（`.gitignore` 特意 `!strategies/temp/` 反包含 + 我上一轮新加的 CI gate **恰好白名单放行 temp/**）。
- **对抗发现**：我的 CI gate 写成 `grep -vE '^strategies/(examples|temp)/'` → 它**主动放行**这 146 个策略 YAML。也就是说，按"无例外"标准，**gate 自己就在给 alpha 开绿灯**。
- **这是裁决冲突，不是 bug**：`temp/` 到底算不算 alpha？两种立场：
  - **立场 A（严格"无例外"）**：146 个也是 strategy → 移出 git、进 OCI、收紧 gate 只放行 `examples/`。
  - **立场 B（0010 语料例外）**：temp = 只读输入语料（来源 nova，非本项目 alpha 产物），留 git 供多 AI 读取；gate 放行 temp 是**有意**的。→ 那"无例外"要改口径为"除 examples/ 与 temp/ 只读语料外无例外"。
- **不能擅自选**：两者都合理，但**直接矛盾**，需你定。

### 🟨 P2 — F3：CI gate 可绕过 + 只挡未来
- **绕过路径**：仓库无 branch protection（直推 `main` 即绕过 CI）；PR 不合并则 gate 不拦已直推内容。
- **只挡未来**：gate 检查"当前树里被跟踪的文件"，对 F1 那种**已在历史**的泄漏无能为力。
- **定位修正**：CI gate 是"尽力而为的拦网"，**不是不可绕过的硬闸门**。上一轮把它描述成"兜底站岗"言过其实。

### ⚪ 次要 — 措辞/口径不严谨（非阻塞）
- 上一轮"round-trip 验证"实际只验了 `list` + 幂等，**没验 `pull`**；且 `pull-strategy` 走 `strategies_par_url` PAR listing 时返回 404（pull 侧 PAR/endpoint 问题，**非数据丢失**——`list`+skip 已证实在远端）。
- `lyra list` 能列出 134 但 `pull` PAR 404：**list 与 pull 走的 PAR/前缀可能不同**，建议单独排查 pull 通道（不影响本次 alpha 落地）。

---

## 三、对抗检查后，边界的真实状态（诚实版）

```
方向            防护是否真站岗
─────────────────────────────────────────────
未来: nova 进 git   ✅ .gitignore 放行已收回 + git add 收 0（真成立）
未来: 已跟踪 alpha  ✅ 12 个 v01 当前已 untrack
未来: 再提交 alpha  ⚠️ CI gate 可绕过(无 branch protection) + 只挡未来
过去: GitHub 历史   🟥 12 个 v01 已永久公开（0008 commit，不可逆）
例外: temp/ 146    🟧 与"无例外"裁决冲突，立场 A/B 待你拍板
数据: OCI 在位     ✅ 133 在位 + I17 幂等（真成立）
```

**一句话**：上一轮把"**未来的 nova 泄漏**"和"**已发生的 v01 公开**"混为一谈了。前者已真正解决，后者是既成事实且我的修复根本碰不到它。加上 temp/ 这个"无例外"的灰色地带——**边界没有"修好"，只是把最急的那一处补上了，另两处暴露为裁决/风险问题。**

---

## 四、待你裁决（我不擅自定）

1. **F1（P0，最高优先）**：12 个 v01 已在 GitHub 历史。**是否要**：
   - (a) `git filter-repo` 改写 main 历史移除 v01 + 强制推送（**高风险、需你授权、所有克隆方需 re-clone**）；或
   - (b) 接受"v01 基线已公开"（若你判断 v01 基线属可共享的"公开基线"，而非核心 alpha），只把**未来的 vNN>1 + nova + hypothesis/lessons** 守住；或
   - (c) 其它（如仓库整体转 private / 删除重建仓库）。
2. **F2（P1）**：146 个 `temp/nova_campaign/*.yaml` **算不算 alpha**？
   - (A) 算 → 移出 git、进 OCI、CI gate 收紧到只放行 `examples/`；
   - (B) 不算（0010 只读语料）→ 保留现状，把"无例外"改口径为"除 examples/ 与 temp/ 只读语料外"，并**在 gate/文档里显式写明这个例外**（消除"gate 给 alpha 开绿灯"的矛盾）。
3. **F3（P2）**：是否补强 CI gate 的抗绕过？（如：加 branch protection 要求 PR / required status check；把 gate 逻辑抽成可被本地 `pre-commit` 复用的同一脚本）

> 注：F1/F2 涉及**改写 git 历史**或**推翻 0010 既有裁决**，且相互独立——我等你逐条给出 (a/b/c) 与 (A/B) 的选择后再动手；F3 若你同意我可以直接做（低风险）。

---

## 五、用户裁决 + 落地结果（2026-11-14 晚）

用户三条裁决：
- **F1**：接受公开历史存在，但**当前 git 树必须干净**（不改写历史）。
- **F2**：`temp/` 应只留在本地；其**内容要转入 lyra 标准策略库（OCI）**；并让我核对 nova 是否有"原稿"——确认有，把 **nova 转 private** 即可让这批策略不丢。
- **F3**：gate 最好不要被绕过，能做就做；**GitHub Actions CI 也要能过**。

### 落地（全部完成并验证）

| 项 | 动作 | 验证 |
|---|---|---|
| **F1** | 当前 git 树 alpha-clean（12 v01 已 untrack、`strategies/directions/` ignored、`git add -A` 收 0 alpha）。不改写历史，按用户意愿接受公开部分。 | `git ls-files 'strategies/'` = **仅 examples/(5)**；`git check-ignore` 命中 |
| **F2 原稿安全网** | 核对 nova：146 个 temp 候选在 nova **146/146 有原稿**（`runs/research_campaign/<family>/experiments/<hash>/strategy.yaml`，content-sha 全匹配，0 缺失）。→ nova 转 private 即保住 | `content_sha256` 逐一比对 = 146 匹配 |
| **F2 OCI** | 新增 `lyra push-corpus`：把本地 `strategies/temp/` 候选池以 `strategies/corpus/<entry>/…` 形态推 OCI；分类器新增 corpus 规则（候选本体 immutable、`_index.json` append_only） | 实推 **296 upload/0 conflict**；重推 **0 upload/296 skip**（幂等实锤在远端）；`lyra list` strategies 共 **429 对象 = 133 directions + 296 corpus** |
| **F2 git 侧** | `git rm --cached strategies/temp/`（留本地盘 296 文件）；`.gitignore` 去掉 `!strategies/temp/**`（temp 现被忽略、留本地） | `strategies/temp/` ignored ✓；git tracked strategies = 仅 examples/ |
| **F3 gate 抗绕过** | gate 逻辑抽成 `scripts/alpha_gate.sh`（**CI 与本地 pre-commit 复用同一脚本**）；加 `scripts/git-hooks/pre-commit` 本地拦截；`core.hooksPath` 已指到该目录 | **负向测试**：强制暂存一个 alpha → hook 拦下（exit 1，清晰报错）；清理后 directions tracked=0 |
| **CI 绿** | ci.yml gate 步骤改为 `bash scripts/alpha_gate.sh`（当前树 examples-only → 通过） | 本地实跑 gate = OK；测试 345 绿、pyflakes 干净 |

> **F3 剩余**：branch protection（main 强制本检查为 required status check）是 GitHub **仓库设置**，需在 GitHub Settings → Branches 手动开；我已在脚本与本报告标注。这是真正"不可绕过"的最后一道，需你（或我代为，若你授权操作仓库设置）配置。
>
> **诚实边界（不变）**：F1 的 12 个 v01 **公开历史仍在**（用户接受，不改写）。本轮新增的防护全部是"未来方向"：当前树干净 + 本地/CI 双闸 + 抗绕过脚本 + temp 候选进 OCI 标准库、原稿在 nova（private 兜底）。
