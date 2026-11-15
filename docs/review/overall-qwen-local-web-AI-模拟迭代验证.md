# web-AI 角色扮演模拟迭代 — 平台摩擦核验与修复（#130）

> 用户指令：以"只能读写文件 + 调 command、不会写 py 的 AI"身份，虚拟或真实地选一个方向，
> 模拟"创建策略→测试→看结果→学习→再创建"的完整迭代循环；每遇到一处摩擦就切回开发者身份
> 修复，直到循环无问题为止。
>
> 本文记录：模拟过程（真实数据实跑）→ 暴露的摩擦 → 逐处核验属实 → 修复 → 逐处验证。

---

## 1. 模拟环境

- **隔离 scratch workspace**：`~/.lyra/sim`（不污染真实 `~/.lyra/default`）
- **真实数据**：`~/.lyra/default/data`（catalog.duckdb + ohlcv + features）
- **方向**：`momentum_exhaustion`（继承自默认工作区的 v01 基线）
- **身份**：无 coding、无 FS 假设外的 web-AI——只能 `read` 文件、`write` YAML、调 `lyra` 命令

## 2. 模拟过程（4 轮，全链路成立）

| 轮 | 动作 | 结果 |
|----|------|------|
| 0 | `lyra context momentum_exhaustion` | 读 hypothesis + 146 features + grammar（**首行 `hypothesis: (none)` ← 摩擦#1**） |
| 1 | `tracks --create t_me` → 写 v02（mhb=6，收紧出场）→ `submit --track t_me --branch v02` | SPX500_USD 714 trades，annualized **-1.7%**，win 50.1% |
| 1' | `lesson`："v02 太快没用，放宽入场" | 记入 track memory |
| 2 | 写 v03（rsi 35/65 放宽入场，mhb=12）→ submit | 896 trades，annualized **+4.47%**，win 56.5% |
| 2' | `lesson`："放宽入场 > 收紧出场" | 记入 |
| 3 | 写 v04（rsi 40/60 + `efficiency_24 > 0.3` 质量过滤）→ submit | 677 trades，annualized **+5.12%**，win 56.7% |
| 3' | `lesson`："质量过滤 + 宽入场 = 最优" | 记入 |
| 4 | `digest`/`tracks --list`/文件树核对 | 3 个 active 分支、3 条 lesson、文件树干净 |

> 期间 AI 还真实踩到两处：`lyra history`（不存在命令，**摩擦#2**）、`return_3`（未知 feature，**摩擦#3**）。

## 3. 暴露的摩擦（逐一核验属实并修复）

### 摩擦#1 — hypothesis 缺失遮蔽方向语义

- **现象**：`context`/`digest` 首行 `hypothesis: (none)`，web-AI **不知道这个方向在做什么**。
- **核验**：`~/.lyra/default/strategies/*/` 下 **11/12 方向只有 `v01.yaml` 的 `hypothesis:` 字段、无 `hypothesis.md`**（`failed_breakout` 两者皆无）。原 `render_context`/`render_digest` 在 `hypothesis.md` 不存在时直接 `(none)`。
- **修复**：新增 `_fallback_hypothesis()`（读 `v01.yaml` 的 `hypothesis:` 字段）；`render_context`（no-track 分支 + track 无 snapshot 分支）与 `render_digest` 在无 `hypothesis.md` 时回退显示该字段并标 `(from v01.yaml)`；二者皆无才 `(none)`。
- **验证**：`context`/`digest` 现显示 v01 的 "A confirmed RSI retreat…"（非 `(none)`）。

### 摩擦#2 — 幽灵命令 `lyra history`

- **现象**：模拟中 `lyra history` → `No such command`，AI 卡住。
- **核验**：`lyra history` 从未实现；早期文档/AI_README 引用了它。**`lyra/ai_readme.md` 只存在于会话上下文、从未落盘**。
- **修复**：重建 `lyra/ai_readme.md`，全文以**真实命令面为准**（`context`/`digest`/`tracks`/`submit`/`lesson`/`apply-batch`/`prune`/`new-version`/`report`/`validate`/`doctor`），并显式列"常见混淆的**不存在**命令"（`history`/`search`/`metrics` → 对应真实命令）。
- **验证**：`lyra/ai_readme.md` 已落盘，命令面全真实。

### 摩擦#3 — unknown feature 无引导

- **现象**：`return_3`（非注册 feature，真实是 `return_6_atr`）→ 报错只说 "unknown"，AI 须盲猜 146 个名。
- **核验**：`strategy_schema._resolve_column` 只抛 "unknown feature or column"，无近名提示。
- **修复**：`_resolve_column` 报错新增 **did-you-mean**（按前缀/词干匹配注册表，给 ≤5 个近名）+ 无近名时提示 `lyra context` 查注册表。
- **验证**：`validate return_3` → `did you mean one of: return_6_atr`。

## 4. 验证汇总

- `python -m pytest -q` → **381 passed**（+6：hypothesis fallback×3 + `_fallback_hypothesis` 边界 + feature-hint×2）
- `pyflakes lyra/` → 干净（全包）
- 三处修复逐一实锤（见 §3 各"验证"）

## 5. 诚实边界

- **单标的**：模拟只出 SPX500_USD（方向 family 过滤所致，非 bug）——其他方向的可用标的由 catalog 决定。
- **`hypothesis.md` 缺失是数据现状**（11/12 方向无 .md）。本修复让 `context` **能显示** v01 的 hypothesis 字段，**不改数据**；是否生成 12 个 `hypothesis.md` 属**内容决策**，留待用户/AI 补写。
- **模拟 ≠ 真实 AI 的 token/上下文**：本模拟由有完整上下文的开发者扮演；真实 web-AI 每轮只拿到 `context`/`digest` 返回文本，token 预算更紧——这正是 #129 低 token 特性（`digest`/`submit --report digest`）要解决的。

## 6. 结论

**web-AI 迭代闭环（模式 A）在真实数据上跑通 4 轮，M1/M2/M3/D6/D7/D9/低 token 全部真实可用**；
模拟暴露的 3 处平台摩擦已全部核验属实并修复、加回归。平台已可进入 AI 学习阶段。
