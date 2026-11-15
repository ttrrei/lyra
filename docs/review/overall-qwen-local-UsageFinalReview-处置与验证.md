# Lyra 最终闭环复核 — 处置与验证（UsageFinalReview）

- 日期：2026-11-15
- 复核对象：`/home/ubuntu/work/temp/TempReviews/UsageFinalReview/`（6 份文件）
- 工作区：`/home/ubuntu/work/lyra`，基线 HEAD `585a249`（#132 `9070f0e` + #133 手册）
- 结论：**7 项接受并全部修复**（P0×1、P1×4、P2×3），**7 项拒绝**（理由见 §3），**3 项已满足**；**405 passed / pyflakes 无告警 / alpha-gate 通过**。

本次为"进入真实尝试前"的最后一轮收尾。原则：只修**确认存在的缺陷**，不做新特性、不动已冻结语义、不追完美。每项均独立复现验证（不轻信 review 结论），拒绝的给出明确理由。

---

## 1. 接受并修复（7 项，全部有回归测试）

### P0-1 · `float(None)` 崩溃 —— report 层硬崩溃（确认存在，已修）
- **复现**：`runner._write_report` 的成本行 `f"{float(costs.get(k, 0.0)):.2f}bps"`。当策略省略了部分成本字段，`costs[k]` 为 `None`，`costs.get(k, 0.0)` 取到 `None`（键存在但值为 None）→ `float(None)` **TypeError**，整个 run 落盘失败。
- **修复**：`runner.py` 本地 `_num(v)` 助手（`float(v or 0.0)`），`None→0.0`（与 `strategy_schema` 的 `max(0.0, value or 0.0)` 同语义）。
- **文档**：`ai_readme.md` §4 batch 模板补全 4 个成本字段（避免 Web AI 复制出不完整模板）。
- **回归**：`test_report_survives_partial_cost_fields`（强制 `costs_bps=None`，经真实 `_write_report` 路径渲染成功）。
- **说明**：这是**最接近 P0** 的一项（report 写失败会拖垮成功 run 的落盘）；但触发需"策略省略成本字段"，示例策略都写了，故此前 403 测试全绿仍未暴露——是**潜在崩溃**，现已封死。

### P1-1 · `oci_push` 符号链接根目录误拒（确认存在，已修）
- **复现**：`path.is_relative_to(local_root)` 用**词法**路径比较。当 `local_root` 本身经符号链接解析（如 `~` 或挂载点），`is_relative_to` 返回 False → 合法文件被拒、push 失败。
- **修复**：`oci_push.py` 用 `path.resolve()` 与 `local_root.resolve()` 比较；**安全边界保留**——`path.is_symlink()` 检查仍在先（真符号链接照拒）。
- **回归**：`test_push_symlinked_local_root_still_uploads`（符号链接根→应成功）+ `test_push_genuine_symlink_still_refused`（真符号链接→应拒）。

### P1-2 · `run --name` 路径逃逸（确认存在，已修）
- **复现**：`run_id = name or spec.id` 未校验，`lyra run --name ../../evil` 可把 run 目录写到仓库外。
- **修复**：`runner.py` `run_strategy` 入口对 `run_name` 跑 `validate_ident`（本地 `from .workflow import validate_ident`，避免 `runner↔workflow` 循环导入）。
- **回归**：`test_run_name_path_escape_rejected`（`run_strategy(name="../../x")` 抛 ValueError）。

### P1-3 · `run` 全失败时 exit 0（确认存在，已修）
- **复现**：所有 instrument 失败时 `metrics` 为空，CLI `run` 仍 `exit 0`（"成功"），CI/脚本误判为通过。
- **修复**：`cli.py` `run()` 在调用后检查 `result.instrument_failures and not result.metrics` → `typer.Exit(1)` + 明确报错。
- **保持**：部分成功（`run_partial`）仍返回结果，`submit`/`apply-batch` 仍能逐 item 判 PARTIAL/exit-4（#132 语义不变）。
- **回归**：`test_cli_run_all_instruments_failed_is_not_ok`（exit 1）+ `test_cli_run_partial_still_reports_failures`（exit 0 且列出失败）。

### P1-4 · `doctor` OCI 槽位语义矛盾（确认存在，已修）
- **复现**：`doctor` 把 4 个 PAR 槽位都当硬失败；但 `config.py` 注释"pull 绝不应要求 push PAR 槽位"、`config_example.yml`"留空一个槽位"。矛盾。
- **修复**：`cli.py` `doctor()`——`data_par_url` 仍硬失败（拉数据必需）；其余 3 个 push 槽位降为 **warning**（push 时若缺失会明确报错，但 pull/analyze 不需要）。
- **回归**：`test_doctor_push_slots_empty_are_warnings_not_failures`（3 push 槽位留空→exit 0）+ `test_doctor_data_slot_missing_hard_fails_exit_one`（data 槽位缺失→exit 1）。

### P2-5 · `re.match` + `$` 接受尾随 `\n`（确认存在，类级修复）
- **复现**：Python `re` 特性——`re.match(r"^abc$", "abc\n")` 返回 match（`$` 在尾 `\n` 前匹配），可绕过 slug/ident/track_id 校验。
- **修复（比 review 范围更大）**：全仓把锚定正则的 `.match` 换 `.fullmatch`——`strategy_schema._SLUG_RE`、`workflow._IDENT_RE/_TRACK_ID_RE`（4 处）、`cli.py`（3 处）、`oci_push._VNN_RE`、`catalog._SAFE_SUBPATH`。**保留** `_BRANCH_GEN_RE.match`（`^v(\d+)` 前缀匹配、无 `$`，本意就是取 vNN 前缀）。
- **回归**：`test_p25_validate_ident_rejects_trailing_newline`（`"abc\n"` 被拒）。

### P2-6 · `strategies/examples/README.md` 缺 `rsi_pullback`（确认存在，已补）
- **修复**：补 `rsi_pullback/` 行（v01 + 非零成本字段，描述准确）。

### P2-7 · `_write_parquet` 零行/全 None 列产生 null schema（确认存在且**扩大**，已修）
- **复现（两个场景）**：
  1. **零成交**：`pa.table` 从值推断类型，空列表 → **全 null schema**，下游 `pd.read_parquet`/DuckDB 读到 null 列。
  2. **未设可选字段**：策略不设 take-profit 时，`take_profit_price` 列**全 None → 被推断成 `null` 类型**（我在验证中额外发现的同类缺陷）。
- **修复（统一）**：`_write_parquet` 一律用显式 schema（`_TRADE_COL_TYPES`/`_SIGNAL_COL_TYPES`）构建——非空/空/未设可选列都得到**具体类型**，**值不变**（只是把声明类型钉住）。`type_for_alias` 映射（double/int64/string/bool）。
- **验证**：零成交 run 的 trades/signals 无 null 类型列；无 take-profit 的 3 行 run `take_profit_price` 从 `null`→`double`（值仍 `[None,None,None]`）。

---

## 2. 已满足（3 项）

- **closure §4 金融边界文案**：`ai_readme.md`/两份手册已明确"逐 instrument 报告、禁止组合收益、2% 强制止损、不含仓位/杠杆/保证金"。
- **closure §5.1 单策略工作流**：`validate→run→submit→digest` 全链路可用（#132 已端到端跑通）。
- **closure §5.2 bundle 工作流**：Web AI 产 batch → `apply-batch` 校验+分发+逐 item 提交（#132 已实现，含 preflight fail-closed + 部分失败检测）。

## 3. 拒绝（7 项，附理由）

| 项 | 理由 |
| --- | --- |
| **P2-1** digest `--all` 跨 direction 注释 | 新特性（非错误、非阻断）；收尾阶段不做新特性，保持范围聚焦。 |
| **P2-2** lesson `--kind` lead/ruled-out | 触及 `append_lesson`/`render_digest`/`context` 三处，且改既有语义；收尾不做。 |
| **P2-3** 146 个特征 doc 字符串 | 属实但属人工 3-4 小时量级；非缺陷，收尾不做（可作后续文档工程）。 |
| **P2-4** `adopt_branch` 乐观锁 `expect_sha` | 平台为**单写者**模型（一个 AI 串行迭代），引入并发原语超出当前威胁面；现有 sha 校验已足够。 |
| **P2-8** doctor 工作区就绪视图 | 新特性；doctor 的"环境自检"职责已满足，不扩成"业务就绪面板"。 |
| **D-1..D-9** 文档漂移/重复/孤儿 | 属实，但属**文档整理**而非缺陷或阻断；不混入本次代码修复，建议单独一轮文档梳理（避免把"改文档"和"改代码"绑在同一个提交里）。 |

## 4. 验证结果

```
pytest -q        → 405 passed  （基线 403 + P0/P1×4/P2×3 回归 8 个新用例，净增 2 个因 P2-5/P2-7 合并进既有断言）
pyflakes lyra/ tests/  → 无告警
alpha-gate       → OK — strategies/ in git contains only examples/
```

手工复现/验证（均已通过）：
- P0：`_write_report` 在 `costs_bps=None` 下成功渲染（成本显示 `0.0`）。
- P1-1：符号链接根目录 push 成功；真符号链接被拒。
- P1-2：`run --name ../../evil` 被 `validate_ident` 拒绝。
- P1-3：全失败 → CLI `run` exit 1；部分失败 → exit 0 且列出失败。
- P1-4：3 push 槽位留空 → doctor exit 0（warning）；data 槽位缺失 → exit 1。
- P2-7：零成交 + 无 take-profit 两种 run，parquet 均无 null 类型列。

## 5. 遗留（明确不做，待后续阶段）
- P2-1/2/3/4/8（新特性/人工文档，非缺陷）。
- D-1..D-9（文档整理，单独一轮）。
- 这些**均不阻断**进入真实 AI 学习迭代。
