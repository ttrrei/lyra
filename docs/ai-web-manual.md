# Lyra — Web AI 使用手册（无文件系统 / 无代码能力）

> 适用对象：网页版 AI（ChatGPT、Claude Web、Gemini 网页等），只能"读文本 + 写文本"
> 版本：v1.79 ｜ 更新：2026-11-15
> 核心机制：web AI **只写一个 bundle 文件**（文本），本地/编码 AI 跑 `apply-batch` 完成剩下的全部

---

## 一、你和平台的分工

```
┌─────────────┐   读 digest/context（文本）    ┌──────────┐
│   你 (web)  │ ─────────────────────────────→ │  Lyra   │
│  只写文本   │ ←───────────────────────────── │  (平台)  │
└─────────────┘   写一个 bundle 文件（文本）    └──────────┘
        │
        │  把 bundle 文件内容贴给本地/编码 AI
        ▼
   本地 AI 跑 `lyra apply-batch <bundle> --run`
        │
        ▼
   你拿到 report（文本），继续下一轮
```

**你（web AI）永远只做两件事**：
1. **读**平台给你的文本（digest / context / 上一轮 report）
2. **写**一个 bundle 文件（YAML 文本），贴给本地 AI 去跑

你**不需要**跑命令、**不需要**碰文件系统、**不需要**写 Python。

---

## 二、一次迭代的完整流程

### 步骤 A — 让本地 AI 把"现状"读给你

给本地 AI 发：
> 跑 `lyra digest --all --config config/config.yml`，把输出原样贴给我。

本地 AI 会贴回一屏文本，例如：
```
mean_reversion      | v02 top: trades=88 ann=+0.52% win=49%
momentum_exhaustion | v02 top: trades=61 ann=+0.41% win=47%
range_trading       | v01 only: trades=142 ann=+0.31%
...
```

### 步骤 B — 需要某方向细节时，读 context

> 跑 `lyra context mean_reversion --config config/config.yml`，把输出原样贴给我。

context 会给你：
- 该 direction 的 **hypothesis**（一句话策略假设）
- **146 个可用特征名**
- **YAML 语法说明**
- 一个**可直接复制的模板**

### 步骤 C — 你写 bundle（多方向一次性）

你基于上面读到的信息，**对多个 direction 各写一个策略**，合并成一个 bundle 文件。
**bundle 格式**（这是你唯一要产出的东西）：

```yaml
version: 1
directions:
  # ── direction 1 ──
  - direction: mean_reversion
    track: nova
    branch: v03
    parent: v02
    driven_by_lesson: >-
      v02 加入 SMA 方向过滤后 win rate 提升，这轮再加 rsi_12 收紧入场
    strategy: |
      version: 1
      id: mean_reversion_v03
      direction: mean_reversion
      hypothesis: >-
        RSI_6 与 RSI_12 同时超卖且短期均线向上时，均值回归更可靠。
      timeframe_minutes: 60
      entry:
        long:
          all:
            - {feature: rsi_6, op: lt, value: 30}
            - {feature: rsi_12, op: lt, value: 40}
            - {feature: sma_6, op: gt, value: sma_24}
        short:
          all:
            - {feature: rsi_6, op: gt, value: 70}
            - {feature: rsi_12, op: gt, value: 60}
            - {feature: sma_6, op: lt, value: sma_24}
      exit:
        long: {feature: rsi_6, op: gt, value: 55}
        short: {feature: rsi_6, op: lt, value: 45}
        stop_loss_pct: 0.02
      execution:
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1

  # ── direction 2 ──
  - direction: momentum_exhaustion
    track: nova
    branch: v03
    parent: v02
    driven_by_lesson: >-
      v02 用 ATR 阈值判衰竭，这轮加 RSI 背离确认
    strategy: |
      version: 1
      id: mom_exhaust_v03
      direction: momentum_exhaustion
      hypothesis: >-
        ATR 扩张配合 RSI 顶背离时，动量衰竭反转概率最高。
      timeframe_minutes: 60
      entry:
        long:
          all:
            - {feature: atr_24, op: gt, value: atr_60}
            - {feature: rsi_12, op: lt, value: 70}
        short:
          all:
            - {feature: atr_24, op: gt, value: atr_60}
            - {feature: rsi_12, op: gt, value: 30}
      exit:
        long: {feature: rsi_12, op: gt, value: 40}
        short: {feature: rsi_12, op: lt, value: 60}
        stop_loss_pct: 0.02
      execution:
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1
```

### 步骤 D — 贴给本地 AI 跑

> 把上面这个 bundle 存成 `bundle.yaml`，先跑
> `lyra apply-batch bundle.yaml --data-dir ~/.lyra/default/data --config config/config.yml --dry-run`，
> 把预览结果贴给我。确认没问题后再加 `--run` 跑，把每个 direction 的 report 贴给我。

本地 AI 跑完会把**每个 direction 的完整 report** 贴回来。

### 步骤 E — 你读结果，进入下一轮

看 report 里每个 direction：
- trades / annualized / win rate
- 与 parent 版本比是进步还是退步
- `low-sample` 标记（trades < 20 别急着下结论）
- `stop%`（止损触发率）

然后**回到步骤 C**，写下一轮 bundle（branch 变成 v04，parent 指向 v03 或最优分支）。

---

## 三、bundle 规则（写错会被整批拒绝）

| 规则 | 说明 |
|---|---|
| **整批 fail-closed** | bundle 里**任意一条**校验失败 → **整批零写**（不会半应用） |
| 每条要有 `direction` | 且必须与 strategy 内的 `direction` 一致 |
| `branch` 是新 slug | 分支不可变，改策略就换新 `vNN` |
| vNN≥2 要 `parent` + `driven_by_lesson` | 否则被拒 |
| `stop_loss_pct: 0.02` | **冻结**，不可改 |
| 特征必须来自 context 清单 | 未知特征名 → 拒绝（会有 did-you-mean 提示） |
| 未知 YAML 键 | **拒绝**（不忽略） |
| `timeframe_minutes` | 只能 `5` 或 `60` |

> **为什么这样设计**：web AI 一次提 3 个方向，1 个写错时，如果平台只应用另外 2 个，
> 磁盘上就会出现"你只提了一半"的脏状态。整批拒绝让你下次可以**修正那一条后重提整批**，
> 永远干净。

---

## 四、给 web AI 的 Prompt 模板（直接贴）

```
你是 Lyra 策略研究 AI（无文件系统，只读写文本）。

我（用户）会给你一段方向清单 + 每个方向的 digest/context 文本。
你的任务：
1. 读懂每个 direction 的 hypothesis 和历史分支表现
2. 为**每个** direction 写一个**新分支**策略
   - branch 用当前最高分支 +1（如最高 v02 → 你写 v03）
   - 必须声明 parent（指向最高分分支）和 driven_by_lesson（一句话）
   - 只用给定特征清单里的特征
   - stop_loss_pct 固定 0.02
   - 只改你意图改的条件
3. 把所有方向的策略合并成**一个** bundle 文件（格式见下），输出为纯文本

bundle 格式：
version: 1
directions:
  - direction: <d1>
    track: nova
    branch: <vNN>
    parent: <vMM>
    driven_by_lesson: <一句话>
    strategy: |
      version: 1
      id: <d1>_<vNN>
      direction: <d1>
      hypothesis: <一句话假设>
      timeframe_minutes: 60
      entry:
        long:
          all:
            - {feature: ..., op: ..., value: ...}
        short:
          all:
            - {feature: ..., op: ..., value: ...}
      exit:
        long: {feature: ..., op: ..., value: ...}
        short: {feature: ..., op: ..., value: ...}
        stop_loss_pct: 0.02
      execution:
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1
  - direction: <d2>
    ...
```

---

## 五、Token 效率建议

| 场景 | 用哪个命令 | 为什么 |
|---|---|---|
| 决定看哪个方向 | `digest --all` | 一屏全 direction，最省 token |
| 深入某个方向 | `digest <direction> --track nova` | 单方向 + 单 track |
| 需要写策略前 | `context <direction>` | 语法+特征+模板一次到位 |
| 读结果 | report（本地 AI 已打印） | 别重新 dump，用已贴的 |

> **省 token 的核心**：`digest` 给"决策视图"，`context` 给"写作视图"。
> 先 digest 挑方向，再只对挑中的方向拉 context，不要一上来就 context 全部 12 个方向。

---

## 六、完整一次循环示例（对话体）

**你**：跑 `lyra digest --all` 贴给我。
**本地AI**：（贴 12 行 digest）
**你**：mean_reversion 和 momentum_exhaustion 看起来有戏。
把这两个的 `context` 贴给我。
**本地AI**：（贴两段 context，各含 hypothesis+特征+模板）
**你**：（思考后）好，我给你写一个 bundle，两个方向各一个 v03：
`<把上面的 bundle 文本贴出来>`
**本地AI**：先 dry-run 预览……全部通过。现在 `--run`……
（贴两个 direction 的 report）
**你**：mean_reversion v03 比 v02 好（win 49%→53%）。momentum v03 退步了。
下一轮：mean_reversion 继续推进 v04，momentum 回退思路换 RSI 背离。
`<贴下一个 bundle>`
……（循环）
