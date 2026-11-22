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
  **exactly**.
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

The web-AI packages 3–4 candidates into a single YAML file:

```yaml
version: 1
bundle:
  # Candidate 1: New hypothesis (Regime conditioning)
  - direction: failed_breakout
    track: t_fb
    branch: v02a
    parent: v01
    driven_by_lesson: "L1: v01 unconditioned sweeps generate excess noise; require regime filter."
    hypothesis: "New hypothesis: False breakout sweeps mean-revert only during low market efficiency."
    strategy:
      version: 1
      id: fb_t_fb_v02a
      family: failed_breakout
      timeframe_minutes: 60
      hypothesis: "Sweeps conditioned on low market efficiency (<0.35) mean-revert to range midpoint."
      entry:
        long:
          all:
            - {feature: failed_breakout_down_24, op: eq, value: true}
            - {feature: range_position_24, op: lt, value: 0.5}
            - {feature: efficiency_24, op: lt, value: 0.35}
        short:
          all:
            - {feature: failed_breakout_up_24, op: eq, value: true}
            - {feature: range_position_24, op: gt, value: 0.5}
            - {feature: efficiency_24, op: lt, value: 0.35}
      exit:
        stop_loss_pct: 0.02
        take_profit_pct: 0.02
        max_holding_bars: 12
        long: {feature: range_position_24, op: gte, value: 0.5}
        short: {feature: range_position_24, op: lte, value: 0.5}
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0
        financing_bps_per_day: 0

  # Candidate 2: Logical combination (Momentum exhaustion confirmation)
  - direction: failed_breakout
    track: t_fb
    branch: v02b
    parent: v01
    driven_by_lesson: "L1: v01 unconditioned sweeps suffer momentum continuation; require exhaustion check."
    hypothesis: "Logical combination: Sweeps combined with extreme RSI exhaustion (oversold/overbought) confirm reversal."
    strategy:
      version: 1
      id: fb_t_fb_v02b
      family: failed_breakout
      timeframe_minutes: 60
      hypothesis: "Sweeps with momentum exhaustion confirmation (RSI 12 extreme) mean-revert."
      entry:
        long:
          all:
            - {feature: failed_breakout_down_24, op: eq, value: true}
            - {feature: range_position_24, op: lt, value: 0.5}
            - {feature: rsi_12, op: lt, value: 30.0}
        short:
          all:
            - {feature: failed_breakout_up_24, op: eq, value: true}
            - {feature: range_position_24, op: gt, value: 0.5}
            - {feature: rsi_12, op: gt, value: 70.0}
      exit:
        stop_loss_pct: 0.02
        take_profit_pct: 0.02
        max_holding_bars: 12
        long: {feature: range_position_24, op: gte, value: 0.5}
        short: {feature: range_position_24, op: lte, value: 0.5}
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0
        financing_bps_per_day: 0

  # Candidate 3: Mechanism replacement (Dynamic volatility band exit)
  - direction: failed_breakout
    track: t_fb
    branch: v02c
    parent: v01
    driven_by_lesson: "L1: v01 static midpoint exit holds through reversals; test dynamic exit."
    hypothesis: "Mechanism replacement: Replace static range midpoint exit with dynamic Bollinger band percentile exit."
    strategy:
      version: 1
      id: fb_t_fb_v02c
      family: failed_breakout
      timeframe_minutes: 60
      hypothesis: "Dynamic volatility band exit captures impulse without holding through retracements."
      entry:
        long:
          all:
            - {feature: failed_breakout_down_24, op: eq, value: true}
            - {feature: range_position_24, op: lt, value: 0.5}
        short:
          all:
            - {feature: failed_breakout_up_24, op: eq, value: true}
            - {feature: range_position_24, op: gt, value: 0.5}
      exit:
        stop_loss_pct: 0.02
        take_profit_pct: 0.04
        max_holding_bars: 6
        long: {feature: bband_pctb_24, op: gte, value: 0.8}
        short: {feature: bband_pctb_24, op: lte, value: 0.2}
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
        commission_bps_round_trip: 0
        financing_bps_per_day: 0
```

---

## 5. Practical Rules for AI Agents

1. **Batch iteration of 3–4 candidates**: Submit a single `apply-batch` bundle per round.
   Never iterate by submitting single-branch micro-adjustments.
2. **Prohibit parameter micro-tuning**: Do not submit candidates differing only by numeric
   constants (e.g. 30 vs 35, 12 vs 14). Structural differences must be declared and
   defensible.
3. **Execution costs are immutable**: Cost parameters (`spread_bps`, `slippage_bps_per_side`,
   `commission_bps_round_trip`, `financing_bps_per_day`) must be identical to the track baseline.
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
AI:  lyra digest failed_breakout --track t_fb --config config/config.yml
     → reads current pool: 1 active baseline (v01), 0/8 candidates, recent lessons (L1)
     → protocol: inspects v01 YAML + L1 lesson ("unconditioned sweeps negative on 19/21 assets")

AI:  writes batch-0001.yaml (3 structurally distinct candidates:
       - v02a: New hypothesis (efficiency_24 < 0.35 filter)
       - v02b: Logical combination (rsi_12 momentum exhaustion)
       - v02c: Mechanism replacement (dynamic Bollinger percentile exit)
     All execution costs copied identically from v01 baseline.)

AI:  lyra apply-batch batch-0001.yaml --config config/config.yml --dry-run
     → dry-run: all items VALID (parse + compile + preflight), 3 would adopt

AI:  lyra apply-batch batch-0001.yaml --config config/config.yml --run \
       --data-dir ~/.lyra/default/data
     → 3 adopted · 3 run ok (v02a, v02b, v02c)

AI:  lyra digest failed_breakout --track t_fb --config config/config.yml
     → v02a: trade count down 20%, positive on SPX500/UK100
     → v02b: trade count down 65%, positive on CN50/HK33, cut drawdown
     → v02c: trade count increased, negative on 20/21 assets due to turnover drag

AI:  lyra compare failed_breakout --track t_fb --siblings
     → reviews cross-branch evidence table

AI:  lyra prune failed_breakout --track t_fb --branch v02c \
       --reason "v02c dynamic band exit increased turnover and fee drag, negative on 20/21 assets."
     → track t_fb: 2/8 active branches (v02a, v02b retained)

AI:  lyra lesson failed_breakout --track t_fb \
       "L2: Dynamic band exit (v02c) increases overtrading; regime efficiency (v02a) and RSI exhaustion (v02b) improve equities but fail on FX; next explore session temporal filtering." \
       --config config/config.yml

AI:  lyra backup --config config/config.yml
     → syncs active tracks, runs, and strategies to OCI

→ loop continues with next batch (proposing 3 new structural candidates into remaining capacity)…
```
