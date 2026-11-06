# Momentum Breakout — 假设

> **这是示例方向（example），不是 alpha 资产。**
> 它的作用是展示一个合法的 Lyra 方向文件夹长什么样：
> `hypothesis.md` + `lessons.md` + 版本树（`vNN.yaml`）。
> 真实的方向（direction）按 R12 创建，遵循同一结构。

## 假设（Hypothesis）

> 价格突破近期区间（range）并伴随区间位置确认时，短线动量有延续倾向。
> 反向突破失败（假突破）的亏损由 2% 硬止损封顶。

- **方向状态**：`active`（本示例仅作结构展示；真实方向按
  `active / paused / killed` 迁移，见 R12）。
- **Kill criteria（示例）**：所有活跃分支连续 3 轮（round）
  全部触发止损且无一次净利 ≥ 1R，则本方向 `killed`。
- **本示例不宣称任何真实研究结论**；数值仅为结构示范。

## 修改历史（只增不删）

- `2026-11-06`：创建示例方向（T3 骨架），供 `lyra validate` 与
  文档演示使用；不进入任何 run 结果集。
