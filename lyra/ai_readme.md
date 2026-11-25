# Lyra — AI Research Loop (Web/Chat AI Edition)

This document is for **AI agents without filesystem access** (web chat, Claude,
ChatGPT, Gemini, etc.) that read and write strategy YAML files and execute
`lyra` commands to run strategies.

> **Principle**: The AI writes strategy YAML. Everything else — validation,
> compilation, execution, trade simulation, metrics — is handled by `lyra`.
> The AI never writes Python. The AI never touches the codebase.
> **Core Contract (Decision 0012)**: Research progresses via diverse candidate
> pools (3–4 structurally distinct candidates per batch), never through
> single-line parameter micro-tuning.

---

## 1. Setup (once)

```bash
# Clone & install
git clone git@github.com:ttrrei/lyra.git
cd lyra
.venv/bin/pip install -e .

# Pull historical data (first time only, ~10 min)
lyra pull --config config/config.yml

# Pull existing strategy baselines (v01 for all 12 directions)
lyra pull-strategy --direction momentum_exhaustion --config config/config.yml
lyra pull-strategy --direction trend_continuation --config config/config.yml
# … repeat for each direction you want to work on
# (see: lyra list --prefix "strategies/" --config config/config.yml)
```

> **Data location**: `~/.lyra/default/data/`. Pass `--data-dir ~/.lyra/default/data`
> to commands that need it (`apply-batch`, `run`, `submit`). Do not copy data.
> **Data boundary**: AI accesses only the Research window and authorized feedback
> summaries. Sealed Holdout data (reserved boundary) is never directly accessible.

---

## 2. The Loop (every iteration)

This is the **complete** workflow. Research iterates in batches of 3–4 candidates.

### Step A — Read current state (compact reading protocol)

To prevent context bloat and focus on diversity:
1. First read the compact history digest:
   ```bash
   lyra digest <direction> --track <track_id> --config config/config.yml
   ```
   Shows: direction hypothesis, active pool branches (up to 8 seats) with latest
   scores, pruned memory, and recent lessons.
2. Read the full context only when setting up a new track or referencing the grammar:
   ```bash
   lyra context <direction> --track <track_id> --config config/config.yml
   ```
3. **Reading Protocol**: In each round, inspect:
   - The compact whole-pool digest (`lyra digest`);
   - Full YAMLs for only 3–4 most relevant candidates;
   - 1 instructive failure retrospective (pruned branch);
   - Recent lessons memory.

### Step B — Propose 3–4 structurally distinct candidates (Batch bundle)

Write **one batch bundle YAML** containing 3–4 candidate branches.

**The Golden Rule: No Pure Parameter Micro-tuning (Decision 0012)**:
- **PROHIBITED**: Simply tweaking numeric thresholds (e.g. RSI 30→35), altering
  smoothing windows (e.g. SMA 20→25), or presenting parameter variants as structural
  innovations.
- **REQUIRED**: Explain the structural difference relative to in-pool candidates in
  plain text.
- **Recommended batch mix**:
  - 2 new hypotheses (e.g. novel indicator, regime conditioning);
  - 1 logical combination (e.g. sweep combined with volume/momentum filter);
  - 1 mechanism replacement (e.g. replace static exit with dynamic volatility exit).
- **Cost consistency**: All 4 execution cost fields (`spread_bps`, `slippage_bps_per_side`,
  `commission_bps_round_trip`, `financing_bps_per_day`) must match the track baseline
  **exactly**, including the difference between omitted (`null`) and explicit `0`.
  The baseline is the shared, read-only direction file `strategies/<direction>/v01.yaml`.
- **Structure report**: `apply-batch` reports AST complexity and compares each candidate
  with active siblings. `identical`, `parameter_only`, `structural_change`, and
  `exit_structure_changed` are diagnostic labels; they do not reject candidates.
- **Scope**: All candidates in a batch must target the **same direction and track**.

### Step C — Preview, Apply, and Run

```bash
# 1. Preview (dry-run: parse + compile + preflight; zero writes)
lyra apply-batch batch-0001.yaml --config config/config.yml --dry-run

# 2. Adopt & Run all candidates across all instruments
lyra apply-batch batch-0001.yaml --config config/config.yml --run \
  --data-dir ~/.lyra/default/data
```

This operates under **all-or-nothing** semantics: if any candidate in the bundle is
invalid, the whole batch is rejected and nothing is written.
Every real submission first preserves the original bundle bytes under
`~/.lyra/<workspace>/research-batches/_intake/` before decoding or parsing (Decision
0018). After a successful parse, a bundle with one safe direction/track is moved to
`research-batches/<direction>/<track>/batch-NNNN.yaml` with its `batch-NNNN-result.md`
sidecar; malformed, mixed, or unsafe submissions are kept under
`research-batches/_unparsed/unassigned/` with the failure reason. The result records
rejections, adoption/run counts, run IDs (or failure reasons), and leaves a
branch-decision slot for the researcher. Dry-runs create no intake or archive at all.
Archive failures print a warning and do not change the apply/run result.

### Step D — Analyze, Prune, and Record Lessons

1. Review run outcomes via `lyra digest <direction> --track <track_id>` and
   `lyra report <run_dir>`.
2. Inspect sibling comparisons:
   ```bash
   lyra compare <direction> --track <track_id> --siblings
   ```
3. **Manage the 8-seat pool**: If a branch fails its hypothesis or adds uncompensated drag,
   explicitly prune it to free active capacity:
   ```bash
   lyra prune <direction> --track <track_id> --branch <branch_slug> \
     --reason "Explain why this mechanism failed"
   ```
4. Append lessons to track memory:
   ```bash
   lyra lesson <direction> --track <track_id> \
     "L2: <Mechanism X> failed due to overtrading; <Mechanism Y> improved selectivity on indices; explore <Direction Z>." \
     --config config/config.yml
   ```

---

## 3. Commands reference (for AI use only)

| Command | Purpose |
|---------|---------|
| `lyra digest <dir> --track T` | **Read**: compact 1-screen pool summary (primary decision tool) |
| `lyra context <dir> [--track T]` | **Read**: reference context (hypothesis + features + grammar + full track) |
| `lyra apply-batch <bundle.yaml>` | **Batch Write**: validate and adopt 3–4 candidates (all-or-nothing) |
| `lyra apply-batch <b.yaml> --run --data-dir D` | **Batch Write + Run**: adopt and evaluate whole batch end-to-end |
| `lyra compare <dir> --track T --siblings` | **Compare**: horizontal evidence table across sibling runs |
| `lyra prune <dir> --track T --branch vNN` | **Prune**: retire a failed branch with reason (frees an 8-cap slot) |
| `lyra lesson <dir> "<text>" --track T` | **Learn**: record empirical lessons in track append-only memory |
| `lyra tracks <dir> --create <id>` | **Create**: initialize a research track |
| `lyra tracks <dir> --list` | **Read**: list existing tracks and active capacity (N/8) |
| `lyra report <run_dir>` | **Read**: re-render a past run's full report |
| `lyra validate <file>` | **Validate only** (single file syntax check) |
| `lyra doctor` | **Diagnose**: check environment + data integrity |

> **Single-branch commands** (`lyra submit`, `lyra new-version`) remain supported for
> legacy single tests, but the standard research protocol is `lyra apply-batch`.

---

## 4. Batch Proposal Bundle Specification

The web-AI packages 3–4 candidates into a single YAML file. The examples
below use the **open-source example strategies in `strategies/examples/`**
as the template — copy `strategies/examples/rsi_pullback/v01.yaml` (direction
`mean_reversion`) and change the structural variants; never just tweak
numbers.

```yaml
version: 1
bundle:
  # Candidate 1: New hypothesis — trend-bias confirmation (structural variant
  # adds the SMA(6) > SMA(24) uptrend-bias condition to the baseline entry)
  - direction: mean_reversion
    track: t_mr
    branch: v02a
    parent: v01
    driven_by_lesson: "L1: v01's rsi_pullback reverts in every regime; add trend-bias confirmation."
    hypothesis: "New hypothesis: long when RSI(6) < 30 while SMA(6) > SMA(24) — reversion only during uptrend context."
    strategy:
      version: 1
      id: mr_t_mr_v02a
      direction: mean_reversion
      timeframe_minutes: 60
      hypothesis: "RSI(6) mean reversion gated by SMA(6) > SMA(24) uptrend bias."
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
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1

  # Candidate 2: Logical combination — volume-weighted entry gate
  - direction: mean_reversion
    track: t_mr
    branch: v02b
    parent: v01
    driven_by_lesson: "L1: v01 reverts regardless of volume; require activity confirmation."
    hypothesis: "Logical combination: RSI(6) reversion plus relative volume above the recent average at entry."
    strategy:
      version: 1
      id: mr_t_mr_v02b
      direction: mean_reversion
      timeframe_minutes: 60
      hypothesis: "RSI(6) mean reversion gated by relative volume at entry."
      entry:
        long:
          all:
            - {feature: rsi_6, op: lt, value: 30}
            - {feature: relative_volume_24, op: gt, value: 1.2}
        short:
          all:
            - {feature: rsi_6, op: gt, value: 70}
            - {feature: relative_volume_24, op: lt, value: 0.8}
      exit:
        long: {feature: rsi_6, op: gt, value: 55}
        short: {feature: rsi_6, op: lt, value: 45}
        stop_loss_pct: 0.02
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1

  # Candidate 3: New hypothesis — z-score divergence confirmation
  - direction: mean_reversion
    track: t_mr
    branch: v02c
    parent: v01
    driven_by_lesson: "L1: v01 reverts on shallow RSI moves; require z-score divergence."
    hypothesis: "New hypothesis: long when RSI(6) < 30 while z-score(6) < -1 — avoid shallow-move reverts."
    strategy:
      version: 1
      id: mr_t_mr_v02c
      direction: mean_reversion
      timeframe_minutes: 60
      hypothesis: "RSI(6) mean reversion gated by z-score divergence."
      entry:
        long:
          all:
            - {feature: rsi_6, op: lt, value: 30}
            - {feature: zscore_6, op: lt, value: -1.0}
        short:
          all:
            - {feature: rsi_6, op: gt, value: 70}
            - {feature: zscore_6, op: gt, value: 1.0}
      exit:
        long: {feature: rsi_6, op: gt, value: 55}
        short: {feature: rsi_6, op: lt, value: 45}
        stop_loss_pct: 0.02
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1

  # Candidate 4: Mechanism replacement — SM6/24 alignment-state exit
  - direction: mean_reversion
    track: t_mr
    branch: v02d
    parent: v01
    driven_by_lesson: "L1: v01's fixed RSI exit cuts reversals too early; replace the exit mechanism."
    hypothesis: "Mechanism replacement: replace fixed RSI exit with SM6/24 alignment-state exit."
    strategy:
      version: 1
      id: mr_t_mr_v02d
      direction: mean_reversion
      timeframe_minutes: 60
      hypothesis: "RSI(6) mean reversion exited by SM6/24 alignment state instead of fixed RSI."
      entry:
        long:
          all:
            - {feature: rsi_6, op: lt, value: 30}
        short:
          all:
            - {feature: rsi_6, op: gt, value: 70}
      exit:
        long: {feature: sma_alignment_6_24, op: eq, value: -1}
        short: {feature: sma_alignment_6_24, op: eq, value: 1}
        stop_loss_pct: 0.02
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0.2
        financing_bps_per_day: 0.1
```

- **The Golden Rule: No Pure Parameter Micro-tuning (Decision 0012)**:
  - **PROHIBITED**: Simply tweaking numeric thresholds (e.g. RSI 30→35), altering smoothing windows (e.g. SMA 20→25), or presenting parameter variants as structural innovations.
  - **REQUIRED**: Explain the structural difference relative to in-pool candidates in plain text.
  - **Recommended batch mix**: 2 new hypotheses + 1 logical combination + 1 mechanism replacement.
  - **Cost consistency**: the four execution cost fields above are copied from the open-source example `strategies/examples/rsi_pullback/v01.yaml` (`spread_bps: 2` / `slippage_bps_per_side: 0.2` / `commission_bps_round_trip: 0.2` / `financing_bps_per_day: 0.1`); `stop_loss_pct` is the mandatory 2% lock item (not one of the four optional costs).
  - **Scope**: All candidates in a batch must target the same direction and track.

---

## 5. Practical Rules for AI Agents

1. **Batch iteration of 3–4 candidates**: Submit a single `apply-batch` bundle per round.
   Never iterate by submitting single-branch micro-adjustments.
2. **Prohibit parameter micro-tuning**: Do not submit candidates differing only by numeric
   constants (e.g. 30 vs 35, 12 vs 14). Structural differences must be declared and
   defensible.
3. **Execution costs are immutable**: Cost parameters (`spread_bps`, `slippage_bps_per_side`,
   `commission_bps_round_trip`, `financing_bps_per_day`) must be identical to the track baseline.
   Omitted and explicit zero are distinct for this check. A zero-cost batch emits a warning.
4. **Intra-track comparison only**: Sibling comparison and batches operate strictly within
   one direction and one track.
5. **The 8-seat pool limit (I21)**: Each track holds at most 8 active branches. Always prune
   inferior or refuted branches before applying a new batch.
6. **Always record a lesson**: Document what structural change was tested, what worked,
   what failed, and the next structural exploration direction.
7. **v01 is the immutable baseline**: Never modify or overwrite `v01.yaml`.

---

## 6. Example Complete Batch Session

```
AI:  lyra digest mean_reversion --track t_mr --config config/config.yml
     → reads current pool: 1 active baseline (v01 — the open-source example
       `strategies/examples/rsi_pullback/v01.yaml`), 0/8 candidates, recent lessons

AI:  writes batch-0001.yaml — 3–4 structurally distinct candidates over the
     rsi_pullback shape (copy `strategies/examples/rsi_pullback/v01.yaml` as the
     base; execution costs copied identically from v01; `stop_loss_pct` stays
     the mandatory 2%):
       - v02a: New hypothesis (SMA(6) > SMA(24) trend-bias filter)
       - v02b: Logical combination (relative_volume_24 > 1.2 entry gate)
       - v02c: New hypothesis (z-score divergence confirmation)
       - v02d: Mechanism replacement (SM6/24 alignment-state exit)

AI:  lyra apply-batch batch-0001.yaml --config config/config.yml --dry-run
     → dry-run: all items VALID (parse + compile + preflight), 4 would adopt

AI:  lyra apply-batch batch-0001.yaml --config config/config.yml --run \
        --data-dir ~/.lyra/default/data
     → 4 adopted · 4 run ok (v02a, v02b, v02c, v02d)
     → archived under research-batches/mean_reversion/t_mr/batch-0001.*

AI:  lyra digest mean_reversion --track t_mr --config config/config.yml
     → v02a: fewer trades, positive on quiet ranges;
       v02b: higher participation, small negative edge;
       v02c: negative — z-score confirmation adds noise at 1h;
       v02d: needs review — alignment exit trades too rarely

AI:  lyra compare mean_reversion --track t_mr --siblings
     → reviews cross-branch evidence table

AI:  lyra prune mean_reversion --track t_mr --branch v02c \
        --reason "z-score confirmation adds noise at 1h; drop from pool."
     → track t_mr: 3/8 active branches (v02a, v02b, v02d retained)

AI:  lyra lesson mean_reversion --track t_mr \
        "L2: Trend-bias filter (v02a) improved win rate; volume gate (v02b) added drawdown; alignment-state exit (v02d) trades too rarely." \
        --config config/config.yml

AI:  lyra backup --config config/config.yml
      → syncs active tracks, runs, and strategies to OCI

→ loop continues with the next batch (proposing 3 new structural candidates into remaining capacity)…

## 7. Immutable Run Recovery

Runs are immutable by `run_id`. On another machine, `lyra run` checks the local
workspace first, then read-only checks the existing OCI backup layout before
running the strategy. A verified OCI hit is restored and reused; no strategy SQL
or simulation is repeated. If OCI lookup is unavailable, Lyra warns and proceeds;
a later backup conflict still blocks the upload.

If `lyra backup` reports an immutable run conflict:

1. Do not force-push or edit the OCI object.
2. Move **all local date directories** for that run ID into the track's
   `superseded-runs/` archive, preserving every copy.
3. With OCI reachable, rerun the same `lyra run` using the same strategy, data,
   `--name`, `--track`, and config. The read-only preflight restores and validates
   the OCI original before execution.
4. Run `lyra backup --dry-run` and confirm the run conflict is gone.

`lyra pull-runs` reads the canonical runs bucket/layout; these historical backup
objects are under the strategies backup bucket and use
`runs/<name>/<date>/<run_id>/`. If preflight cannot read that path, stop and keep
the local copies for manual comparison. Never overwrite the OCI run. To generate
a new artifact format for an old strategy, use a new branch slug; increment
`_ENGINE_VERSION` only when execution semantics change.

### 不可变 Run 恢复

Run 按 `run_id` 不可变。换机器后，`lyra run` 先查 workspace，再只读预检现有
OCI backup 路径；找到并校验通过就恢复复用，不会再次执行策略 SQL 或 simulation。
如果 OCI 查询不可用，Lyra 会告警并继续本地运行；之后 backup 若发现冲突仍会阻止上传。

若 `lyra backup` 报不可变 run 冲突：

1. 不要强推，也不要编辑 OCI 对象。
2. 将该 run ID 的**所有本地日期目录**移入 track 的 `superseded-runs/`，逐份保留。
3. OCI 可访问时，用相同策略、数据、`--name`、`--track` 和 config 重跑相同的
   `lyra run`。只读预检会在执行前恢复并校验 OCI 原件。
4. 执行 `lyra backup --dry-run`，确认该 run 冲突已消失。

`lyra pull-runs` 使用 canonical runs bucket/layout；历史 backup 对象实际位于
strategies backup bucket，路径为 `runs/<name>/<date>/<run_id>/`。若预检无法读取该路径，
停止操作并保留本地副本以供人工比较。绝不覆盖 OCI run。若要为旧策略生成新格式产物，
使用新的 branch slug；仅在执行语义变化时递增 `_ENGINE_VERSION`。
