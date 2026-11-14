# Lyra 低 Token 多 AI 迭代——平台使用问题与修改建议

> **任务**：① 从系统平台角度检查是否有遗漏、#126 新增代码是否引入新问题；② 站在"平台使用者"角度，评估"有限 token 下最大化迭代次数"的两个模式——**A. 单 track 低 token 循环**（无 coding AI）与 **B. web AI 综合 + coding AI 落地**（多 direction 批量迭代），给出详细修改建议。
>
> **范围**：只针对 Lyra；中文；含 [实测] 数据。
>
> **日期**：2026-11-15（v1.74 之后）

---

## 一、平台角度自检结论（#126 新代码有没有引入问题）

**结论：无新增代码问题；但发现 3 个平台使用面的遗漏（详见 §三）。**

| 检查项 | 结果 |
|---|---|
| `python -m pytest -q` | **362 passed**（含 #126 的 7 个回归） |
| `pyflakes lyra/ tests/` | 干净 |
| `adopt_branch` 与 prune 交互（[读码]） | 良性：prune 后同 slug 重新 adopt 会追加一条 `activate` 事件，replay 后该分支重新 active——语义正确（"重新启用该分支"） |
| `submit --track --branch` 的 fail-closed 顺序（[实测]） | 校验→adopt→run 三段各自独立 fail-closed，任一段失败不留半截状态（6 项对抗已实锤，见 #126 ACTION_LOG） |
| run_meta 归因（[实测]） | `branch=v01, track_id=t_demo, spec_id=<AI id>` 三字段对齐；`context --track` 正确显示 |
| **遗漏 ①** | `submit` 把**完整 report.md** 打进 stdout——21 品种 run 的 report 是 **90KB ≈ 2.5 万 token**，web AI 根本消费不动（§三 P0-1） |
| **遗漏 ②** | 没有"track 历史精华"的紧凑视图——AI 学习只能靠 context 里每个分支 1 行 + 自己翻 report.md（§三 P0-2） |
| **遗漏 ③** | 模式 B（web AI 综合 + coding AI 落地）没有对应的平台支撑：没有多 direction 的紧凑输入，也没有"结构化建议文件"的校验入口（§三 P0-3） |

---

## 二、一轮循环的 token 成本实测（问题定量）

| 工件 | 实测大小 | 约 token | web AI 一轮能否消费 |
|---|---|---|---|
| `lyra context <dir>`（无 track） | 4.2 KB | ~1.2k | ✅ 轻松 |
| `lyra context <dir> --track T`（空 track） | 4.5 KB | ~1.2k | ✅ 轻松 |
| `context` 含 8 个分支全 YAML + 每个 run 1 行 | 估计 15-25 KB | ~4-7k | ✅ 可消费 |
| **`report.md`（1 品种, 82 个月）** | ~90 KB | **~2.5万** | ❌ **爆了** |
| `report.md`（21 品种, 1743 行月表） | 同上量级×21 | **更大** | ❌ **不可能** |
| lessons（最近 5 条） | <1 KB | <300 | ✅ |

**核心矛盾**：#126 修的 #1 是"AI 看不到完整结果"——修法是把 report.md 全量打进 stdout；但 **90KB 的完整报告对 web AI 就是噪音**，一轮循环 2-3 万 token 全耗在读报告上，"有限 token 多迭代"直接违背。正确修法不是"给更多"，而是**分层**：默认给**结论层**（<1KB），需要时才给**明细层**（按月/按品种切片）。

---

## 三、修改建议（按优先级）

### P0-1 【必须】report 分层：默认摘要，明细按需

**问题**：`submit` 把整份 report.md（83-90KB）打进 stdout，web AI 一轮烧 2.5 万+ token 且仍"看不完"（超出窗口就截断=假完整）。

**建议**：
1. `submit` 默认只打印 **digest**（从 metrics.json 生成，控制在 ~1KB）：
   - 每品种 1 行：`trades / net / annualized / win% / expectancy`（现有一行，保留）
   - 跨品种：min / median / max（annualized、win%、expectancy）
   - **结构结论**：几个品种正 EV / 几个负 EV / 最好与最差品种 / 是否有 >0 的稳健组合
   - 月表只给 **3 行**：最好月 / 最差月 / 最近 3 个月
   - 一行指针：`full report: runs/<run_id>/report.md`（coding AI 或人可查）
2. 新增选项 `--report digest|full|none`（默认 `digest`；`full` = 现在行为，供 coding AI/人用）。
3. **切片查询**（可选，P1）：`lyra report <run> --instrument X --months 6`——按品种/按近 N 月切出子表，AI 追问某个品种细节时才花 token。

**改动面**：`lyra/cli.py`（submit stage 4 + report 命令加选项）、`lyra/workflow.py` 或独立 `lyra/summary.py`（从 metrics.json 生成 digest，纯函数、可测）。**不改引擎、不改 schema、不 bump FEATURE_VERSION。**

---

### P0-2 【必须】`lyra digest`：track 历史精华（AI 学习的主输入）

**问题**：AI 第 N 轮想"从 v01-v08 里学"，现在只能读：context 里每分支 1 行 + 8 份 report.md（≈20 万 token）。没有"这个 track 试过了什么、哪个最好、为什么、下一步该往哪"的紧凑视图。

**建议**：新增命令

```bash
lyra digest failed_breakout --track t_demo
```

输出（目标 **<3KB**）：
```
# digest — failed_breakout / t_demo
hypothesis: (frozen, 1-2 行截断 + sha)
branches: v01..v08 (8/8 active; pruned: v03)
## branch results (每分支最新 run，一行)
v01  SPX500_USD  703t  net=-0.126  ann=-0.018  win=0.58  → 结论: 负EV, 止损太松
v02  SPX500_USD  651t  net=+0.041  ann=+0.006  win=0.61  → 结论: 止损收紧后转正
v05  ...
best: v04 (median ann +0.021, 4/6 品种正EV)
worst: v01 (全品种负EV)
## lessons (last 5)
2026-11-14: v01 win 58% 但负 EV — v02 收紧止损
...
## what changed between neighbors (可选)
v01→v02: stop_loss_pct 0.02→0.012; +trend filter
next: 8/8 满额 — 先 prune 最差的再开新分支
```

实现要点（全部已有数据，零新状态）：
- 每分支最新 run 的 metrics.json（`_runs_for_branch` 已有）
- lessons 文件（已有）
- 分支间 diff：`diff` 两个 YAML 的键值（简单文本 diff，或只列 `entry/exit/stop_loss_pct` 的关键差异）
- 8 上限状态：`count_active_branches` 已有

**这是"有限 token 多迭代"的核心**：一轮学习输入 = context(1.2k) + digest(1k) ≈ **2-3k token**，而不是 20 万。

---

### P0-3 【必须】模式 B 支撑：多 direction 综合输入 + 结构化建议文件

**用户目标**：web AI（能有限读 repo）→ 产出**一个多 direction 的综合建议文件** → coding AI 按它把更新落到各 direction/track 的 yaml → 跑 → 完整记录 → 下轮。

平台需要补的三块（缺一环就断）：

**① 综合输入**：`lyra digest --all`（或 `lyra digest --directions a,b,c`）
- 每 direction/track 一段（复用 P0-2 的单 track digest，拼起来）
- 头部加"全局事实"：feature 列表 + version + 引擎版本 + 每 track 的 best/worst 一行
- 目标：10 个 track 也控制在 **~20KB（≈6k token）**——web AI 一次读完所有 track 的历史与教训
- 这就是 web AI 写综合建议文件的**唯一必需输入**（它不需要读代码）

**② 结构化建议文件协议**（新约定，文档化在评估文档/AGENTS）：
web AI 产出的综合文件用**固定 YAML 结构**（不发明新语法，只复用已有 schema 词汇）：

```yaml
# proposal bundle — 由 web AI 生成，coding AI 消费
bundle: v1
generated_from: digest-all 2026-11-15
items:
  - direction: failed_breakout
    track: t_demo
    branch: v09            # 新分支 slug（coding AI 负责 8 上限：满了先 prune）
    based_on: v04          # 父分支（学习对象）
    lesson: "v04 在 ETH/USD 上正EV，v09 复制其止损结构到 FX 对"
    strategy:
      version: 1
      id: fb_t_demo_v09
      direction: failed_breakout
      timeframe_minutes: 60
      entry: { ... }        # 必须是 submit 可校验的完整策略体
      exit: { ... }
      stop_loss_pct: 0.015
  - direction: mean_reversion
    track: t_mr
    branch: v03
    ...
```

- 好处：**AI 与 AI 之间传递的是结构化意图 + 完整策略体**，不靠自然语言转述（避免 coding AI 理解偏差）；每个 item 自带 lesson 字段 → 落地时 `lyra lesson` 自动记录（可加 `--from` 提示）。
- 校验入口（新增，小命令）：`lyra propose-check bundle.yaml`
  - 逐 item：track 存在 / branch slug 合法 / strategy 体过 `parse_strategy`+`compile_strategy`（复用 submit stage 1）
  - **不执行、不写盘**——纯校验，fail-closed，输出"哪些 item 可直接落地 / 哪些非法及原因"
  - coding AI 循环：`propose-check` → 对合法 item 逐个 `submit --track --branch`（每个 submit 自带完整记录：adopt + run + digest + lesson）
- 这是"不同级别 AI 协作"的**接缝**：web AI 出意图，coding AI 只执行命令，两边都不需要理解对方。

**③ 完整记录**（已有，确认覆盖）：每个 item 的落地 = adopt（分支文件）+ run（report.md/metrics.json/run_meta）+ lesson（track 记忆）——全部进 push/pull 范围（#123 H1 已修），跨机不丢。**无需新增。**

---

### P1-1 feature 字典（原 #4，模式 A/B 都受益）

146 个 feature 只有名字，AI"学历史"时看到 `failed_breakout_up_24` 不知道它是什么。
**建议**：`lyra features --describe <name>` + `context` 里每个 feature 追加 ≤15 字的中文说明（从 features 注册处的 docstring 提取，无则标 `(no doc)`）。
- token 成本：146 × ~20 字 ≈ 3KB——可接受，且**一次性**投入换来每轮迭代的理解质量。
- 来源：`lyra/features.py` 各 feature 的注册名旁多数已有描述性注释，抽出来即可（需要人工补全缺的，一次性）。
- 不改 feature 计算 → **不 bump FEATURE_VERSION**。

### P1-2 lesson 结构化（让"记录"可被机器再消费）

现在 `lyra lesson` 是自由文本。建议加两个可选项：
```bash
lyra lesson failed_breakout --track t_demo --branch v04 --verdict best "..."
```
- `--branch`：这条教训关于哪个分支（digest 里按分支聚合时能用）
- `--verdict`：`best|worst|neutral`（digest 排序用）
向后兼容：都可选，老 lesson 照常显示。落盘格式追加尾部元数据（append-only 不破）。

### P1-3 迭代配额护栏（防止"8 分支满额"卡死低 token 循环）

低 token AI 最容易忘的事：track 满了。`digest`（P0-2）已经打印 `8/8 — 先 prune`；再补一条：`submit` 在 cap 已满且 branch 是新 slug 时，报错信息**直接给可执行命令**：
`ERROR: track full (8/8). 回收一条: lyra prune failed_breakout --track t_demo --branch v01`
（现状是通用报错，AI 要自己拼命令，多烧一轮对话。）

### P2（可选，不阻塞）

| 项 | 说明 |
|---|---|
| `lyra report <run> --instrument X --months N` 切片 | AI 追问细节时才花 token（见 P0-1③） |
| 自动 `run_summary.md` | run 目录里自动落一份 ≤1KB 摘要（与 digest 同源），供 coding AI 批量读取 |
| 多轮"对照"模式 | `lyra compare <dir> --track T --focus <instrument>`：只比一个品种的各分支，省 token |
| proposal bundle 归档 | `lyra propose-check` 通过后的 bundle 存 `tracks/<dir>/<track>.proposals.jsonl`（append-only），形成"AI 意图史"，进 push 范围 |

---

## 四、改完后的两个模式长什么样（目标态）

### 模式 A：单 track 低 token 循环（无 coding AI）

```
每轮 token 预算 ≈ 4-6k（输入）+ 1-2k（AI 输出 YAML）
──────────────────────────────────────────────
① lyra context <dir> --track T          (~1.2k tok)  语法/模板/特征(带说明)
② lyra digest <dir> --track T           (~1k tok)   历史分支+结论+教训+上限状态
③ AI 写一条新策略 YAML（人落盘 /tmp/ai.yaml）
④ lyra submit /tmp/ai.yaml --data-dir ... --track T --branch vNN
   → 校验→adopt→run→digest(≤1k tok)      完整报告在 runs/ 供人查
⑤ AI 写一条 lesson（人跑）
   lyra lesson <dir> --track T --branch vNN --verdict best "..."
→ 回到 ①（下一轮的 ② 已经包含新分支+新教训）
```

**对比现状**：现在一轮 ≈ 1.2k + 2.5万(report 全量) ≈ **2.6 万 token**；改后 ≈ **5k**——同样预算迭代次数 **×5 以上**。

### 模式 B：web AI 综合 + coding AI 落地（多 direction 批量）

```
阶段 1（web AI，一次会话）:
  lyra digest --all                      (~6k tok，10 track 也装得下)
  → 生成 proposal bundle.yaml（结构化，每 item 自带完整策略体+lesson）

阶段 2（coding AI，无人值守脚本式）:
  lyra propose-check bundle.yaml         → 哪些 item 合法
  for 合法 item:
    lyra submit <item.strategy> --track <T> --branch <slug> --report digest
    lyra lesson <dir> --track T --branch <slug> "<item.lesson>"
  lyra push                              → 全量上 OCI（分支+runs+tracks）

阶段 3（web AI，下一轮）:
  lyra digest --all                      → 看到所有新分支结果 → 下一份 bundle
```

**分工原则**：web AI 只出**意图 + 完整策略体**（它不需要 FS/coding）；coding AI 只执行**命令序列**（它不需要研究判断）；平台保证每个 item 的落地都有完整记录、跨机可恢复。**两种 AI 都不需要理解对方，接缝是 bundle.yaml + 命令面。**

---

## 五、落地顺序建议

| 顺序 | 项 | 理由 | 改动面 |
|---|---|---|---|
| 1 | **P0-1 report 分层**（digest 默认 + `--report` 选项） | 直接砍掉 90% 的无效 token；改动小、纯展示层 | cli.py + summary 函数 |
| 2 | **P0-2 `lyra digest`（单 track）** | 模式 A 的学习主输入；全用已有数据 | workflow.py + cli.py + 测试 |
| 3 | **P0-3 bundle 协议 + `propose-check`** | 模式 B 的接缝；校验复用 submit stage 1 | cli.py + 协议文档 + 测试 |
| 4 | P0-3① `digest --all` | 依赖 P0-2 | cli.py |
| 5 | P1-1 feature 字典 | 一次性投入，长期收益 | features 提取 + context |
| 6 | P1-2/P1-3、P2 | 打磨 | 小 |

全部项**不动引擎、不动 schema、不 bump FEATURE_VERSION、不碰 alpha 边界**；每项可独立 commit + 回归测试，风险低。

---

## 六、诚实边界

1. **数据质量是天花板**：8/12 direction 有 I5 幸存者偏差、成本假设（I9）、单月样本（I18）——AI 迭代再快，学的是同一批数据里的信号，**迭代次数 ≠ 证据强度**。digest 里应保留这些标注（hypothesis 冻结快照已有）。
2. **token 省下来的钱不自动变成更好的策略**：低 token 循环提高的是**尝试次数**，判断好坏仍靠"多品种稳健正 EV"这条线（R5 指标不变）。
3. **bundle 协议是人机契约**：web AI 若自由发挥写 bundle（发明字段），`propose-check` 会 fail-closed 拒绝——这是特性不是缺陷，但要求 prompt 里给 web AI 固定模板（context 语法段已给出策略体模板，bundle 模板同理需在文档/AGENTS 固化）。
