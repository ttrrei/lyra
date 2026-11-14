# 0010 — temp/ 策略迁移分诊（Triage）

> **English**: [0010-temp-triage.en.md](./0010-temp-triage.en.md)（待补）
>
> 范围：`strategies/temp/` 下 146 nova campaign + 132 moneta S 系列的
> promote / archive 分诊（HLD §8 第 10 行，#99 新增）。
>
> **用户裁决（2026-11-14）**：
> 1. nova 迁移件使用**独立 track id `nova`**（不复用方向级 v01 的默认空间，
>    不与任何 AI 工作 track 混淆）；
> 2. moneta S 系列**无 direction 归属，不拆进任何 direction，保留在 temp 下**
>    （只登记、不迁移）；
> 3. 本工作**同时要求程序正确与内容正确**；自检 → 对抗性检查 → 内容检查，
>    修复后对改动内容再做一轮同样三查（防止修复引入新 bug）。

## 1. 输入盘点（已核实，2026-11-14）

| 语料 | 数量 | 形态 | 现状 |
|---|---|---|---|
| nova campaign | **146** YAML + 146 meta.json | `temp/nova_campaign/<family>/<20位hex>/{strategy.yaml,meta.json}` | 0008 只读索引，未迁移 |
| moneta S 系列 | **132** 条记录 | Python 库（moneta 仓库内，**未拷贝进 lyra**），temp 下仅 `_index.json` | 0008 只读索引，verdict=null |

已核实事实（非推测）：
- 146 个 `id` **全部唯一**（0 重复），可安全映射为分支名；
- id 形态：`*_p1_rNN` 主族 + 1 个特例 `directions_volatility_expansion`
  （**内容 = 正式库 `strategies/directions/volatility_expansion/v01.yaml` 逐字节相同**，
  是 nova 侧对正式基线的 campaign 副本）；
- `lyra validate`（registry feat-6/154 列实测）：**122 有效 / 24 无效**；
  24 个无效**全部**是 `rsi_14` 幽灵引用（0008 裁决：不注册 rsi_14，改写 rsi_12）；
- 146 全部 `timeframe_minutes: 60`（1h 单档）；
- 活体特征表 feat-6 含 `rsi_12`（154 列），**不含 rsi_14**；
- `classify_path`：`nova/vp1_r06.yaml` → **immutable**（I17 合法，可推送）；
- track 激活上限 **8/track（I21 机器门禁）**——见 §3.2 处置；
- pass_instruments 分布：0→12 / 1→9 / 2→9 / 3→14 / 4→26 / 5→11 / 6→13 /
  7→18 / 8→8 / 9→12 / 10→9 / 11→3 / 12→1 / 13→1（"pass" 语义见 nova 原始研究，
  仅作分诊参考，**不作为 lyra 结论**——O18 附加裁决要求一切以 lyra bar 集重算）。

## 2. 布局与身份（裁决落地）

```
strategies/directions/<direction>/
├── v01.yaml            # 方向级共享只读基线（0008 迁入，不动）
└── nova/               # track `nova` 的候选（0010 迁移落地）
    ├── vp1_r06.yaml    # 分支名 = v + 原始 id 的 rNN（id 唯一 → 无碰撞）
    └── ...
```

- **track id = `nova`**（满足 `_TRACK_ID_RE`，且语义 = 来源 provenance，
  对应"tracks 身份可以对应 AI/来源"的既有裁决）；
- 分支名取 `v<原始 rNN>`（如 `campaign_failed_breakout_p1_r06` → `vp1_r06`）：
  - 保留原始 id 的可追溯性（原 id 仍在 `provenance.source_id` 与 temp 索引）；
  - `vp1_r06` 匹配 `_VNN_RE`/`_BRANCH_RE`（I17 immutable、I21 可激活）；
  - 同方向内 rNN 实测**无碰撞**（146 id 唯一已验证）；
- 迁移件 YAML 头部追加 **provenance 注释块**（不改变任何机器字段）：
  源 id / 源路径 / content_sha256_12 / hypothesis / pass_instruments /
  triage 裁决 + 日期。**内容其余部分逐字节不动**（可 diff 审计）。

## 3. 分诊规则（三态）

| 裁决 | 条件 | 落地 |
|---|---|---|
| **promote** | `lyra validate` 通过（122） | 复制到 `directions/<family>/nova/v<NN>.yaml` + provenance 注释 + temp 索引记 verdict |
| **archive** | 24 个 rsi_14 无效件 + 12 个 pass=0 无效件（实际 24+12 中按实测拆分，见 triage 报告） | **留在 temp**（只读保留，不改写源）；temp 索引 verdict=archive + 原因；TODO 注：改写 rsi_12 后可重审 |
| **duplicate** | `directions_volatility_expansion`（= 正式 v01 逐字节同） | 不迁移；索引 verdict=duplicate_of_baseline |
| **keep-in-temp** | moneta S 系列全部 132 | 不拆 direction、不迁移（用户裁决 2）；索引 verdict=keep_in_temp + 原因（Python 形态 + 无 direction + 28 个有 matrix 结果者全部 3 标的、多数负于 buy-hold，历史结论按 O18 附加裁决不可直接沿用） |

> **内容正确性说明**：nova 的 `pass_instruments` 是 nova bar 集上的研究结论。
> O18 附加裁决（2026-11-11）：一切进入 lyra 的结果必须在 lyra bar 集上重算。
> 因此 0010 的 triage 报告**只陈述 lyra 侧事实**（validate 通过/失败、
> 迁移后重跑结果），nova 的 pass 数仅作为 provenance 记录，不作为筛选依据。

## 3.1 迁移后重跑（内容检查的核心）

- 迁移后对**每个 promote 件**在 lyra 活体数据（feat-6 + catalog，21 标的 1h）
  执行 `lyra run --track nova --name <分支名>`，产物落 `runs/<direction>/nova/<run_id>/`；
- 报告逐件：交易数 / annualized / win_rate（R5 冻结集），逐标的隔离（I7/I16）；
- **禁止跨标的求和**（universal = 逐标的报告，工作合同）；
- 重跑失败（数据覆盖/引擎错误）的件单独列出，**不静默**。

## 3.2 I21 上限（8 active/track）处置

`nova` track 的候选远超 8——I21 的"8 active 上限"是**研究推进的机器门禁**
（防单个 AI track 无限膨胀），不是语料归档上限。处置：
- 迁移 = 文件入库 + 索引登记（**全部 122 件激活会违反 I21**）；
- 因此：track `nova` 的 `active_branches` **只激活 triage 头部候选**
  （按 validate 通过 + lyra 重跑 annualized 排序的**前 8**），其余 114 件
  以文件 + 索引形式存在（inactive），后续用 `lyra tracks --prune` 显式轮换；
- 此处置写入 triage 报告并在 `tracks/<direction>/nova.lessons.md` 记录，
  不改 I21 常数（改门禁需用户裁决，本轮不改）。

## 4. 验证矩阵（用户要求的四层）

1. **自检**：迁移脚本 dry-run → 实迁 → 复跑幂等；122 件 validate 全绿；
   diff 审计（迁移件 vs temp 原件：仅 provenance 注释差异）；
   全仓测试 + pyflakes 回归。
2. **对抗性检查**：至少覆盖——特例 id（directions_volatility_expansion）
   不产生重复分支、rsi_14 件未泄漏进正式库、分支名/track id 全部过
   `validate_ident`/`_VNN_RE`、classify_path 全 immutable、I21 只激活 8、
   temp 原件零改动（before/after sha256 对账）、provenance 注释未破坏 YAML
   语义（validate 前后 plan_hash 一致）、moneta 零文件生成、
   迁移可被 `push-strategy` 正常 staging（干跑）。
3. **内容检查**：§3.1 全量重跑 + 抽样人读（每个方向至少 1 件的
   hypothesis ↔ YAML 条件 ↔ 重跑结果三方一致）+ 报告数字与 run 产物对账。
4. **修复后复查**：任何检查触发的修复，其改动文件重跑 1–3 全量
   （防止修复引入新 bug）。

## 5. 交付物

- `scripts/triage_0010.py`（或等价脚本，幂等、可重放）
- 122 个迁移件 + provenance 注释
- `temp/nova_campaign/_index.json` / `temp/moneta_s_series/_index.json`
  的 `verdict` 字段更新（只增字段，不删原有）
- `docs/reports/0010-triage-report.md`（+ .en.md）：三态清单 + 全量重跑表
- HLD §8 0010 行 ✅ + ACTION_LOG 状态块与条目（双语）
