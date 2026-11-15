# Lyra — 本地 AI 使用手册（VS Code / Codex CLI / Copilot）

> 适用对象：有文件系统能力、能跑命令的 AI（Claude Code、Copilot CLI、Codex CLI、Cursor 等）
> 版本：v1.79 ｜ 更新：2026-11-15

---

## 一、平台是什么（30 秒）

Lyra 是一个**策略研究引擎**：
- 输入：一个 YAML 策略文件（条件 = feature + op + value，无代码）
- 处理：校验 → 登记分支 → 运行（DuckDB 跑 OHLCV）
- 输出：`report.md`（完整报告）+ `metrics.json` + 控制台摘要

**所有策略的"历史"都在 git 仓库里**——分支不可变，每次新策略都是新的 `vNN` slug。

---

## 二、核心命令速查

```
# 一次性初始化（只做一次）
python -m lyra.cli pull --config config/config.yml                  # 拉历史 OHLCV（~10min）
python -m lyra.cli pull-strategy --all --config config/config.yml   # 拉所有 direction 的 v01 baselines

# 查看某个 direction 当前状态（低 token）
python -m lyra.cli digest <direction> --config config/config.yml
python -m lyra.cli digest --all --config config/config.yml    # 所有 direction

# 查看某个 direction 的完整上下文（语法+特征清单+历史 lessons）
python -m lyra.cli context <direction> --config config/config.yml

# 验证一个策略文件（不运行，只校验）
python -m lyra.cli validate <your.yaml> --config config/config.yml

# 一步：validate → adopt → run
python -m lyra.cli submit <your.yaml> \
  --data-dir ~/.lyra/default/data \
  --alpha-dir ~/.lyra/default/alpha \
  --config config/config.yml \
  --track nova \
  --branch v02

# 多方向一次性（web AI 产出的 bundle 文件）
python -m lyra.cli apply-batch <bundle.yaml> \
  --data-dir ~/.lyra/default/data \
  --alpha-dir ~/.lyra/default/alpha \
  --config config/config.yml \
  --dry-run        # 预览（不写盘、不运行）
python -m lyra.cli apply-batch <bundle.yaml> \
  --data-dir ~/.lyra/default/data \
  --alpha-dir ~/.lyra/default/alpha \
  --config config/config.yml \
  --run            # 真正 apply + run
```

---

## 三、标准工作流（单 direction）

### 第 1 步：读现状
```bash
python -m lyra.cli digest mean_reversion --config config/config.yml
```
输出示例（低 token，一屏）：
```
direction: mean_reversion
hypothesis: A close more than 2 ATR from its 24-bar mean may revert.
active branches: v01 (baseline), v02 (rsi_6 < 30 + sma_6 > sma_24)
v01: trades=142 ann=+0.31% win=44%
v02: trades= 88 ann=+0.52% win=49%  [top]
```

### 第 2 步：读语法（如需）
```bash
python -m lyra.cli context mean_reversion --config config/config.yml
```
输出包含：
- 该 direction 的 hypothesis
- 146 个可用特征名（FEATURE_VERSION=6）
- 完整 YAML 语法说明
- **一个可直接复制的模板**（末尾的 `Template` 段落）

### 第 3 步：写策略 YAML
基于 `context` 的模板，修改条件，写成一个单独 `.yaml` 文件（**放哪都行**——
下面用 `scratch/mr_v02.yaml`；`submit` 会校验通过后把它 **adopt 到该 track 的正式路径**
workspace 里的 `strategies/<direction>/<track>/vNN.yaml`（即 `~/.lyra/default/strategies/<direction>/<track>/vNN.yaml`）并登记 index，你不用手动搬文件）：

```yaml
version: 1
id: mean_reversion_v02
direction: mean_reversion
hypothesis: >-
  RSI_6 超卖且 SMA_6 仍在 SMA_24 上方时，短期反弹概率更高。
timeframe_minutes: 60
entry:
  long:
    all:
      - {feature: rsi_6, op: lt, value: 30}
      - {feature: sma_6, op: gt, value: sma_24}
  short:
    all:
      - {feature: rsi_6, op: gt, value: 70}
      - {feature: sma_6, op: lt, value: sma_24}
exit:
  long: {feature: rsi_6, op: gt, value: 55}
  short: {feature: rsi_6, op: lt, value: 45}
  stop_loss_pct: 0.02
execution:
  commission_bps_round_trip: 0.2
  financing_bps_per_day: 0.1
# vNN ≥ 2 必须声明：
parent: v01
driven_by_lesson: >-
  v01 的 RSI 条件太宽松，加入 SMA 方向过滤后 trades 减少但 win rate 提升。
```

### 第 4 步：运行
```bash
python -m lyra.cli submit scratch/mr_v02.yaml \
  --data-dir ~/.lyra/default/data \
  --alpha-dir ~/.lyra/default/alpha \
  --config config/config.yml \
  --track nova \
  --branch v02
```

**退出码含义**：
- `0` = 成功（报告已打印）
- `1` = 校验失败 或 运行失败（不写盘、不登记分支）

### 第 5 步：读报告 + 记录
`submit` 成功后会把完整 `report.md` 打印到 stdout。
重点看：
- 每个 instrument 的 trades / annualized / win rate / net sum
- `stop%` 列（止损触发率）
- `low-sample` 标记（trades < 20 时）

---

## 四、多方向批量（web AI 产出的 bundle）

当 web AI 一次性给出 3 个方向的策略时，它会写一个 **bundle 文件**：

```yaml
version: 1
directions:
  - direction: mean_reversion
    track: nova
    branch: v03
    parent: v02
    driven_by_lesson: >-
      v02 加入 SMA 过滤有效，进一步加 rsi_12 < 40 收紧入场
    strategy: |
      version: 1
      id: mean_reversion_v03
      direction: mean_reversion
      hypothesis: ...
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

  - direction: momentum_exhaustion
    track: nova
    branch: v03
    parent: v02
    driven_by_lesson: ...
    strategy: |
      version: 1
      id: mom_exhaust_v03
      direction: momentum_exhaustion
      ...
```

**本地 AI 执行**：
```bash
# 先预览（安全，零写盘）
python -m lyra.cli apply-batch bundle.yaml \
  --data-dir ~/.lyra/default/data \
  --config config/config.yml \
  --dry-run

# 确认无误后 apply + run
python -m lyra.cli apply-batch bundle.yaml \
  --data-dir ~/.lyra/default/data \
  --alpha-dir ~/.lyra/default/alpha \
  --config config/config.yml \
  --run
```

**退出码**：
- `0` = 全部成功
- `1` = 某条策略校验失败（整批零写）
- `3` = 运行硬失败
- `4` = 运行部分失败（某 instrument 失败，其余成功）

---

## 五、本地 AI 的 Prompt 模板

> 直接把以下 prompt 贴进 Claude Code / Copilot CLI 即可启动一个完整的迭代循环：

```
你是 Lyra 策略研究 AI。你有一个 direction 来迭代策略。

direction: <direction_name>
track: <track_id>
当前分支：v02（最高分）

你的任务：
1. 运行 `lyra digest <direction>` 读现状
2. 运行 `lyra context <direction>` 读语法和特征清单
3. 基于上面的 hypothesis 和历史 lessons，写一个**新的 v03** 策略
   - 必须声明 `parent: v02` 和 `driven_by_lesson: <一句话>`
   - 只能使用 context 中列出的特征
   - `stop_loss_pct: 0.02` 不可改
   - 只改你意图改变的条件，其他字段保持模板默认
4. 把 YAML 写到任意临时路径（如 `scratch/mr_v03.yaml`）——`submit --branch` 会 adopt 到 workspace 正式路径
5. 运行 `lyra submit`（完整参数见上方命令速查）
6. 读取 stdout 中的 report，告诉我：
   - 每个 instrument 的 trades / annualized / win rate
   - 与 v02 相比是进步还是退步
   - 下一步建议（1-2 句话）
```

---

## 六、重要规则（不要违反）

| 规则 | 说明 |
|---|---|
| `stop_loss_pct: 0.02` | **冻结**，不可改（I3 设计） |
| `v01` 是 baseline | **保留 slug**，你的候选从 v02 开始 |
| 分支不可变 | 要改策略就写新的 `vNN`，永远不覆盖 |
| `parent` + `driven_by_lesson` | vNN≥2 **必须**声明，否则被拒绝 |
| `direction` 字段 | 必须与 track 所在 direction 一致 |
| 未知 YAML 字段 | **直接拒绝**（不忽略） |
| `timeframe_minutes` | 只能 `5`（5m 数据）或 `60`（1h 数据） |
