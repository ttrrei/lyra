# temp/ — 待归类候选池（0010 AI triage 的输入）

> **English**: [README.en.md](./README.en.md)

本目录存放**历史语料候选**，等待 0010（AI 归类）按方向归档。**它不是
正式策略库，不进 0008 回归门禁，不允许被 `lyra run` 直接执行。**

## 内容

| 子目录 | 来源 | 数量 | 形态 | 状态 |
|---|---|---|---|---|
| `nova_campaign/` | ttrrei/nova `runs/research_campaign/` | 146 | YAML + meta.json | 每个已跑 21 标的全历史矩阵；pass 分布见 `_index.json` |
| `moneta_s_series/` | ttrrei/moneta `strategy/` | 132（只读引用，未拷贝代码） | Python lib | 28 个有矩阵结果（3 标的 vs buy-hold）；多为单指标规则 |

不收录：moneta SR-20261031-200 研究批次（50 feature × 2 entry_model
模板笛卡尔积，7 句模板 hypothesis，0 晋级，纯统计尾部切分——已确认无
迁移价值，仅作档案留在 moneta 仓库）。

## 规则

1. **只读**：temp/ 里的策略不得被 `lyra run` / `lyra compile` 直接消费；
   提升必须走 0010 triage → 复制到 `strategies/directions/<family>/vXX/`。
2. **不进 0008 门禁**：0008 回归只覆盖 `directions/` 正式库与已 promote
   的版本。
3. **meta.json 是 triage 的唯一输入契约**：`id / family / hypothesis /
   pass_instruments / total_instruments / source_repo / source_path /
   content_sha256_12`。
4. **verdict 三态**：0010 对每条给 `promote` / `drop` / `archive` 之一；
   `promote` 触发复制 + 0007 track 流程；`drop` 保留文件但标 verdict；
   `archive` 可删。
5. **新增语料**：后续任何"待归类"的策略一律先进 temp/，不得直接入
   directions/。

## 来源快照

- nova campaign：2026-11-10 从 `/home/ubuntu/work/nova`（rev `38b0195`）
  只读拷贝 YAML + 生成 meta.json。
- moneta S 系列：只读引用 `/home/ubuntu/work/moneta`（rev `67896d6`），
  **不拷贝代码**（alpha 与仓库边界原则）。
