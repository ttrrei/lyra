# Lyra — Quick Start（贴给任意 AI 的第一屏）

> 平台闭环：读历史 → AI 写 YAML → 跑 → 记结论 → 下一轮。
> 细节见 `docs/ai-local-manual.md` / `docs/ai-web-manual.md`。

## 名词（尖括号里写什么）
- **direction**：12 个固定方向之一（`lyra digest --all` 可看全部），如 `mean_reversion`
- **track**：你的研究轨，自命名一次后固定（如 `trial1`）；每个 direction 先建一次
- **branch**：`v01`=baseline 保留；你的候选从 `v02` 起，每轮 +1

## 本地 AI（有 FS）循环 —— 每轮 5 条命令
```bash
lyra tracks mean_reversion --create trial1        # 一次性：建 track
lyra context mean_reversion --track trial1        # 1 读：hypothesis+特征清单+历史 lessons
# 2 写：AI 改模板写 scratch/mr_v02.yaml（只改意图条件；stop_loss_pct: 0.02 不可改）
lyra validate scratch/mr_v02.yaml                 # 3 验：报错就改
lyra submit scratch/mr_v02.yaml --data-dir ~/.lyra/default/data \
  --track trial1 --branch v02                     # 4 跑：校验+登记分支+全品种运行+打印报告
lyra lesson mean_reversion --track trial1 "v02 结论一句话：…下一步…"   # 5 记：下轮 context 可见
```
一次性初始化：`lyra doctor` → `lyra pull`（拉数据，~10min）。
备份：`lyra push`。

## Web AI（无 FS）
1. 把 `lyra context <direction>` 的输出发给它（= 它的全部学习材料）
2. 让它按 bundle 格式产策略（参考 `docs/ai-web-manual.md` §bundle 样例）：
   `directions: [{direction, track, branch, parent: v01, driven_by_lesson, strategy: <完整YAML>}]`
3. 你执行：
```bash
lyra apply-batch bundle.yaml --dry-run                        # 预览（整批 fail-closed）
lyra apply-batch bundle.yaml --data-dir ~/.lyra/default/data --run
lyra lesson <direction> --track <track> "<结论>"
```

## 硬规则（违反即 INVALID）
- 特征名只能来自 context 清单；op 只有 `eq/ne/gt/gte/lt/lte`
- `stop_loss_pct: 0.02` 固定；`timeframe_minutes` 只 5 或 60
- branch 不可变：改策略 = 新 branch（v03），不许覆盖 v02
- 逐 instrument 看结果；**禁止把不同品种收益加总成"组合"**
