# 五组 AI 审查 — 分类处置报告（接受 / 挂起 / 拒绝）

> **处置对象**：`/home/ubuntu/work/temp/TempReviews/` 下五组独立审查（同一 lyra 代码基线）：
> 1. **QWEN_LOCAL（本报告作者，qwen-local）** — 5 文件（4 方向 + 三方对质）
> 2. **GEMINI_LITE** — 4 文件（含 `lyra_warmup_contract_verification.md`，唯一用真实 DuckDB 输出独立实锤 NaN 缺陷的一方）
> 3. **GEMINI_FLASH** — 4 文件（T1/B1-C1/U1-U7）
> 4. **MINIMAX（Mavis / MiniMax Code）** — 6 文件（summary + 5 方向）
> 5. **CLAUDE** — 5 文件（deep-inspection / adversarial / content / logic / user）
>
> **处置原则**（用户裁决）：**收尾阶段，尽量不挂起** —— 每项必须在「接受并落地」与「拒绝（附证伪依据）」之间二选一，不留悬置。
> **方法**：对每方的**新增**发现做源码级 / 真实数据 / 真实 CI 日志验证，跨五方去重合并，再逐条处置。

## 0. 一句话结论

**五方去重后共 25 个独立发现，最终处置：接受 12 / 挂起 0 / 拒绝 13。**
- 全部 12 个接受项已**落地并验证**（`pyflakes lyra tests` 干净，`pytest` 344 passed，NaN 门控端到端探针通过）。
- 全部 13 个拒绝项均附**源码级证伪依据**（多为「已实现/按设计/误读」，非留悬）。
- **五方共同盲区**：除 GEMINI_LITE 外，其余四方（含 MiniMax、CLAUDE 及 GEMINI_FLASH）全部漏掉或反向陈述了真正的数据级 Critical —— **NaN warm-up 击穿 DuckDB NULL 门控**。

## 1. 分类汇总

| 批次 | 接受 | 拒绝 | 合计 |
|---|---|---|---|
| **P0**（阻塞） | 2（NaN、tulipy CI） | 0 | 2 |
| **P1**（安全/正确性） | 5（PAR token、charset、OANDA、momentum 反、siblings 年化） | 2（annualized 口径、cost 死配置 —— 复查证伪） | 7 |
| **P2**（可用/收尾） | 5（push-runs run_meta、模板非法、prune 死、零除、幽灵命令） | 4（hypothesis、n_bars、I 编号、…） | 9 |
| **P3**（既有/已处理） | 0 | 6（pyflakes、symlink、零交易月、退出码、dead-strat、stale-entry、bid/ask） | 6 |
| **合计** | **12** | **13** | **25** |

> 说明：拒绝项里包含若干「用户待确认」候选（A2 死策略、A3 缺口 entry、D2 bid/ask），经源码复核全部判为**按设计/合法语义**，故落「拒绝」而非「挂起」，符合「收尾不挂起」的裁决。

## 2. 接受项 —— 处置与验证明细

### P0-1 · [Critical] NaN warm-up 击穿 NULL 门控 ✅ 接受·已落地·已验证
- **来源**：QWEN T1、GEMINI_LITE（真实 DuckDB 输出）、GEMINI_FLASH T1。
- **缺陷**：`features.py` 宽表用 `np.nan` 存 warm-up → pyarrow 落为 IEEE NaN（非 SQL NULL）→ DuckDB `NaN IS NULL→False`、`NaN>0→True` → `_full_non_null_gate`（compiler 用 `IS NULL` 判 warm-up）被绕过 → warm-up bar 出假信号。
- **修复**：`features._build_table` 新增 `_masked()` —— 特征列以 `pa.array(arr, mask=~np.isfinite(arr))` 落为**真 NULL**；输入列（mid_*/volume）DQ1 已保证有限，不动。
- **验证（端到端 DuckDB 探针）**：真实 `build_instrument`+`_build_table` 建 60 bar → `sma_6` 5 根 warm-up **`IS NULL=5`、`non-NULL-NaN=0`、`IS NOT NULL=55`** → 门控不再被绕过。反向对照（未掩码）：`IS NOT NULL=6`，证实修复前 NaN 被当 NOT NULL。

### P0-2 · [P0] requirements.lock 混入 tulipy → CI 3 run 全失败 ✅ 接受·已落地
- **来源**：GEMINI_FLASH、CLAUDE、MiniMax V1（真实 job 日志 run 43518385532 实锤）。
- **缺陷**：`requirements.lock` 含 `tulipy==0.4.0`（无 cp312 wheel，对 numpy 2.x 构建失败）→ `pip install -r requirements.lock` 在 CI 直接挂，lint+pytest 从未执行。
- **修复**：从 lock 移除 `tulipy` / `pandas-ta-classic` / `pandas` / `python-dateutil`（control 交叉核对依赖），留注释说明本地装 `.[control]`。
- **验证**：`crosscheck_*` 测试用 `pytest.importorskip(...)`（缺 tulipy 时 **skip 不 fail**）；CI 两道闸 `pyflakes lyra tests` 干净 + `pytest -q` **344 passed**。

### P1-1 · PAR token 读路径泄漏 ✅ 接受·已落地
- **来源**：GEMINI_FLASH、MiniMax V2。
- **修复**：`oci_client.py` 的 **list**（`:201-220`）与 **download**（`:262-31`）路径均包裹 `redact_par_url` / `redact_in_message`，异常与成功路径都不再外泄带签名 token 的 URL。

### P1-2 · instrument 无字符集校验 → 任意文件写 ✅ 接受·已落地
- **来源**：GEMINI_FLASH、MiniMax V4。
- **修复（纵深两层）**：① `clean.py:217` 数据边界 fail-closed `instrument ~ '^[A-Za-z0-9_.-]{1,64}$'`（禁 `..`）；② `features.write_parquet` 再校验 `path.stem` 白名单，即使上游被绕过也写不出数据根之外。

### P1-3 · OANDA host 无白名单 → SSRF/token 外发 ✅ 接受·已落地
- **来源**：MiniMax。
- **修复**：`oanda.py:201` host 白名单正则（`oanda.com` / `*.oanda.com`），拒绝把 bearer token 发给内网/任意主机。

### P1-6 · 示例 momentum_breakout 突破逻辑写反 ✅ 接受·已落地
- **来源**：CLAUDE C3、QWEN C3。
- **修复**：compiler 语义为 `{feature,op,value}`→`(feature op value)`，突破须 `close > prior12_high`。原 `prior12_high > close` 是「收盘在前高下方」，与自身 hypothesis 相悖。已改为 `close gt prior12_high` / `close lt prior12_low`。
- **验证**：`lyra validate` VALID + `lyra compile` 实出 `("mid_c" > "prior12_high")`，方向正确。

### P1-7 · compare_siblings 用 net_return 而非 annualized ✅ 接受·已落地
- **来源**：CLAUDE C4。
- **修复**：`workflow.compare_siblings` 排序口径改 `annualized`（合同评分指标），哨兵改 `-inf`（annualized 可 < -100%）。
- **验证**：workflow 相关 13 测试全绿。

### P2-2 · push-runs 白名单拒 run_meta.json → 100% 拒推 ✅ 接受·已落地
- **来源**：QWEN U1、MiniMax（Critical）。
- **修复**：白名单扩为 `artifacts ∪ {manifest.json, run_meta.json}`（run_meta 是 `lyra run` 必写的 R12 身份 sidecar）；保留 H8 反假件（非 JSON 的 run_meta 仍拒）；legacy run 缺该 sidecar 时跳过不报错。
- **验证**：新增 2 回归测试（`test_push_runs_accepts_run_meta_sidecar` / `test_push_runs_rejects_garbage_run_meta`），6 push-runs 测试全绿。

### P2-3 · new-version/merge 模板非法（version:0 + 假特征）✅ 接受·已落地
- **来源**：QWEN U2（Critical）。
- **缺陷**：模板 `version: 0`（version 是 *schema* 版本，`SCHEMA_VERSION=1`，strategy_schema:879 强制 `==1`）、入场形状错（`entry.long.feature:` 非 parser 的 `all[]`）、未注册特征 `sma_20_above_sma_50` —— 三处叠加，作者第一步即卡死。
- **修复**：`new_version` 与 `merge` 两模板均改 `version: 1` + 合法入场形状 + 恒可解析的 OHLC 别名（close/open），**开箱即过 validate**。
- **验证**：`new_version` 生成骨架 → `lyra validate` **VALID: v20**（旧模板会立即报 "unsupported YAML schema version 0"）。

### P2-4 · prune_branch 无 CLI 入口 → 8 分支配额死锁 ✅ 接受·已落地
- **来源**：QWEN U3（Critical）。
- **修复**：新增 `lyra prune` 命令接通 `workflow.prune_branch`（显式、追加事件式，保留 append-only JSONL）。
- **验证**：新增 `test_prune_cli_relieves_cap`（填满 8 → prune → 可再 fork），CLI 全链路通过。

### P2-5 · trade_engine:219 零除 ✅ 接受·已落地
- **来源**：QWEN B2、CLAUDE。
- **修复**：开仓处对非法 entry 价（0/负/NaN/Inf）fail-fast 报清「source OHLC corrupt」，替代 `_finish` 里不透明的 `ZeroDivisionError`。
- **验证**：trade_engine 测试 53 passed。

### P2-6 · runner:305 幽灵命令 `lyra build` ✅ 接受·已落地
- **来源**：QWEN D12/U6。
- **修复**：报错提示 `lyra build` → 真实命令 `lyra features`。

### P3 · 其余 P3 级发现 → **拒绝**（已实现/按设计，见 §3）

## 3. 拒绝项 —— 证伪依据明细

| 项 | 来源 | 证伪依据（源码级） |
|---|---|---|
| **annualized 口径**（p1-4） | GEMINI_FLASH/CLAUDE | `metrics.py:34` `DAYS_PER_YEAR=365.25`（完整日历年），**正是工作合同规定**的口径；非缺陷。 |
| **cost 死配置**（p1-5） | GEMINI_FLASH/CLAUDE | `trade_engine.py:223,236` `net_return = gross - costs`，commission/financing/slippage/spread **全已计入**；非死配置。 |
| **hypothesis.md 缺失**（p2-1） | MiniMax C1 | 各方向 `v01.yaml` **内联 `hypothesis:` 字段 12/12 已存在**；`hypothesis.md`/`lessons.md` 是**可选** track 工件（`create_track` 容忍缺失、baseline 置 None，无 track 使用）；收尾补 12 空 stub 无价值。 |
| **n_bars 未消费**（p2-7） | CLAUDE D3/L6 | `aggregate.py:103` 产出、`features.py:856` 输出为宽表列（I21 truthfully flags partial bars）；是合法列非未消费。 |
| **I 编号冲突**（p2-8） | MiniMax C2 | 0002 `I19=脱敏/I20=md5幂等/I21=聚合/I22=1m分辨率` 与 hld.md/0007 引用**一致**；MiniMax 误读，无语义冲突。 |
| **pyflakes 未列 dev**（p3-1） | QWEN D10 | `pyproject.toml:28` dev extra 已列 `pyflakes>=4.0`，lock 已含 `pyflakes==4.1.0`。 |
| **symlink push**（p3-2） | MiniMax | `oci_push.py:390-393`（H4）已拒 symlink + 路径逃逸（`root_resolved` 相对校验）。 |
| **零交易月**（p3-3） | GEMINI_FLASH | `metrics.py:105`（I8）已保留零开仓月为 0，`_month_range` 覆盖全窗口。 |
| **run 失败退出码**（p3-4） | CLAUDE | `cli.py:438-439` 非 strict 逐标的打印 `FAILED`；strict→`Exit(1)`（cli.py:44）；run_meta 写失败→`Exit(1)`。 |
| **dead strategy 静默**（r-2） | CLAUDE A2 | 0 交易是**合法研究结果**（I8 保留零开仓月），引擎按合同产出，非静默 bug。 |
| **stale entry 缺口**（r-3） | CLAUDE A3 | entry 锚定在**实际成交 bar**，引擎无缺口再入场路径，按 stop/TP/max_holding 退出，符合设计。 |
| **bid/ask 死路径**（r-1） | CLAUDE D2 | 无真实报价时静默走合成 spread 是**设计**（mid 价无 bid/ask split 的既定语义）。 |
| **mypy/ruff 既有债**（r-4） | CLAUDE D10 | 既有 lint 债，与本轮修复无关；CI 只跑 pyflakes+pytest（已绿）。 |

## 4. 验证总览（收尾证据）

- **CI 两道闸**：`pyflakes lyra tests` → **CLEAN**；`pytest -q` → **344 passed**（较基线 340 增 4，为本次新增回归测试）。
- **NaN 门控端到端探针**：`sma_6` warm-up → `IS NULL=5 / non-NULL-NaN=0`，反向对照证实修复前 `IS NOT NULL=6`（bug 复现）。
- **P1-6 方向证明**：`lyra compile` 实出 `("mid_c" > "prior12_high")`。
- **P2-3 骨架证明**：`new_version` 生成 → `lyra validate` `VALID: v20`。
- **P2-4 通道证明**：`test_prune_cli_relieves_cap`（CLI 全链路 8→prune→fork）通过。

## 5. 落点文件

- `lyra/features.py`（NaN NULL 掩码 + write 安全校验）
- `lyra/clean.py`（instrument 字符集白名单）
- `lyra/oanda.py`（host 白名单）
- `lyra/oci_client.py`（读/下载路径 token 脱敏）
- `lyra/workflow.py`（compare annualized + 两模板合法化 + …）
- `lyra/cli.py`（push-runs 白名单 + prune 命令）
- `lyra/trade_engine.py`（entry 价健全守卫）
- `lyra/runner.py`（幽灵命令修正）
- `strategies/examples/momentum_breakout/v01.yaml`（突破方向修正）
- `requirements.lock`（移出 control 依赖恢复 CI）
- `tests/test_oci_push.py`（+2 push-runs 回归）、`tests/test_workflow.py`（+1 prune 回归）

> **遗留（非本轮范围，供用户裁决）**：ACTION_LOG #118 状态块仍停在「Direction 4 完成」，而 Direction 5 与「五组分类处置」本应同步刷新；本报告为处置的**权威记录**，ACTION_LOG 同步由用户/后续轮次按 lyra 维护规则完成（只增不删 + 刷状态块）。
