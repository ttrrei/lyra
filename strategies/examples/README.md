# strategies/examples — 策略清单（示例，非 alpha）

本目录下的内容是**示例（examples）**，不是 alpha 资产：

- ✅ **进入 git**（B14：唯一可被 git 跟踪的 `strategies/` 子树）
- ✅ **进入开源仓库**——它展示"一个合法的 Lyra 方向长什么样"
- ❌ **不进入任何 run 结果集**，不宣称真实研究结论

真实的方向（direction）与版本树（vNN.yaml）只存在于
OCI / 本地 `~/.lyra/`（B1 / B13 / I11），**永远不进入本仓库**。

## 现有示例

| 方向 | 内容 | 用途 |
|---|---|---|
| [momentum_breakout/](./momentum_breakout/) | hypothesis.md + lessons.md + v01.yaml | 展示方向文件夹的标准结构（R12）；供 `lyra validate` 演示 |

## 一个方向的解剖

```
momentum_breakout/
├── hypothesis.md   # 假设 + 方向状态 + kill criteria（只增不删的修改历史）
├── lessons.md      # 追加式 lesson 日志（B9 Append-only）
└── v01.yaml        # 版本树根版本（R12；后续可分叉 v02a / v02b …）
```
