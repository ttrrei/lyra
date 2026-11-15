# Lyra — AI Research Loop (Web/Chat AI Edition)

This document is for **AI agents without filesystem access** (web chat, Claude,
ChatGPT, Gemini, etc.) that read and write strategy YAML files and execute
`lyra` commands to run strategies.

> **Principle**: The AI writes strategy YAML. Everything else — validation,
> compilation, execution, trade simulation, metrics — is handled by `lyra`.
> The AI never writes Python. The AI never touches the codebase.

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
> to commands that need it (`submit`, `run`). Do not copy data.

---

## 2. The Loop (every iteration)

This is the **complete** workflow. No other steps are needed.

### Step A — Read current state

```bash
lyra context <direction> --config config/config.yml
```

Returns a **self-contained document** with:
- `## hypothesis` — what this direction is about (from `hypothesis.md` or v01.yaml)
- `## features` — the complete list of available features (146)
- `## grammar` — the exact YAML schema + a copyable valid template
- `## track <id>` sections (if tracks exist) — frozen baseline, active branch
  YAMLs, and the latest lessons

If no tracks exist yet, the output will show only hypothesis + features +
grammar. That is expected.

**Lower-token alternative** (use this when you just need to decide what to
try next):

```bash
lyra digest <direction> --track <track_id> --config config/config.yml
```

~1 screen. Shows: hypothesis (one line), active branches with their latest
score, recent lessons (last 3 by default — use `--n-lessons N` for more).
Enough to say "try X" or "prune Y".

### Step B — Write the next strategy (as YAML)

Use the grammar + template from `lyra context` as your guide. The key rules:

1. **`version: 1`** — always. This is the YAML schema version, not the
   strategy version.
2. **`id`** — a unique name for this branch (e.g. `me_exhaustion_v03`).
3. **`direction`** — must match the direction you are working in.
4. **`parent`** — (required for vNN ≥ 2) the branch you are building on
   (e.g. `v02` or `v01`).
5. **`driven_by_lesson`** — (required for vNN ≥ 2) a short explanation of
   what you learned from the parent branch that motivates this change.
6. **`entry.long.all` / `entry.short.all`** — a flat list of
   `{feature, op, value}` dicts. Use only features from the registered list.
7. **`exit.long` / `exit.short`** — a single condition dict.
8. **`stop_loss_pct: 0.02`** — always include (2% hard stop).
9. **`max_holding_bars`** — number of bars to hold before forced exit.
10. **`execution`** — copy from the v01 baseline; do not change unless you
    have a specific reason.

**Temporal conditions** (optional, advanced):
You can use `within:` and `held_for:` to express "feature X stayed at value Y
for N bars" or "feature X crossed value Y within the last N bars". See the
grammar section in `lyra context` for exact syntax.

### Step C — Submit and run

```bash
lyra submit <your_file>.yaml \
  --data-dir ~/.lyra/default/data \
  --config config/config.yml \
  --track <track_id> \
  --branch <vNN>
```

This does: validate → adopt → run. If validation fails, you get a clear error
with the feature/column that is wrong and a hint (did-you-mean or
"run `lyra context`"). If the run succeeds, you get a **digest**
(per-instrument: trades, annualized, win rate, net sum) plus the full report
path on disk.

> **If the track does not exist yet**: run
> `lyra tracks <direction> --create <track_id> --config config/config.yml`
> before submitting.

### Step D — Record what you learned

```bash
lyra lesson <direction> --track <track_id> \
  "v03 (rsi 35/65, mhb=12): +4.47% ann, 896 trades. Wider entry > tighter exit.
   Next: try rsi 40/60 + efficiency filter" \
  --config config/config.yml
```

This is appended to the track's memory. The next AI (or your next session)
will see it in `lyra context` and `lyra digest`.

---

## 3. Commands reference (for AI use only)

| Command | Purpose |
|---------|---------|
| `lyra context <dir> [--track T]` | **Read**: full context (hypothesis + features + grammar + branches + lessons) |
| `lyra digest <dir> --track T` | **Read**: compact 1-screen history (lower token cost) |
| `lyra tracks <dir> --create <id>` | **Create**: a new research track in this direction |
| `lyra tracks <dir> --list` | **Read**: list existing tracks |
| `lyra submit <file> --track T --branch vNN` | **Write+Run**: validate, adopt, and run a new strategy |
| `lyra lesson <dir> "<text>" --track T` | **Write**: record a lesson for future iterations |
| `lyra apply-batch <bundle.yaml>` | **Multi-write**: apply N strategies at once (all-or-nothing) |
| `lyra prune <dir> --track T --branch vNN` | **Write**: retire a weak branch (frees a slot in the 8-cap) |
| `lyra new-version <dir> --track T --branch vNN` | **Read**: derive a template for the next branch (both options required) |
| `lyra report <run_dir>` | **Read**: re-render a past run's full report |
| `lyra validate <file>` | **Validate only** (no run): useful for quick checks |
| `lyra doctor` | **Diagnose**: check environment + data integrity |

> **Not available** (commonly confused): `lyra history` (use `lyra context`),
> `lyra search` (use `lyra context` + feature list), `lyra metrics` (use
> `lyra digest` or `lyra report`).

---

## 4. Multi-direction AI (batch mode)

When a single AI needs to propose strategies for multiple directions at once
(e.g. a "master" AI coordinating specialist AIs), use `lyra apply-batch`:

**bundle.yaml** (the web-AI writes this file):
```yaml
bundle:
  - direction: momentum_exhaustion
    track: t_me
    branch: v05
    hypothesis: "Wider RSI + efficiency filter"
    parent: v04
    driven_by_lesson: "v04 efficiency filter worked; push rsi to 42/58"
    strategy:
      version: 1
      id: me_v05
      direction: momentum_exhaustion
      # … full strategy YAML (same fields as a standalone file)
      entry: { long: { all: [...] }, short: { all: [...] } }
      exit:  { long: {...}, short: {...}, stop_loss_pct: 0.02, max_holding_bars: 12 }
      execution: { spread_bps: 2, slippage_bps_per_side: 0.2 }

  - direction: trend_continuation
    track: t_tc
    branch: v03
    hypothesis: "…"
    parent: v02
    driven_by_lesson: "…"
    strategy:
      # … full strategy YAML
```

```bash
# Preview only (no writes, no runs)
lyra apply-batch bundle.yaml --config config/config.yml --dry-run

# Full apply (all-or-nothing: if any item is invalid, NOTHING is written)
lyra apply-batch bundle.yaml --config config/config.yml

# Apply + run all valid items
lyra apply-batch bundle.yaml --config config/config.yml --run \
  --data-dir ~/.lyra/default/data
```

> **All-or-nothing**: if item 3 of 10 fails validation, items 1, 2, 4–10 are
> also rejected. Fix item 3 and retry the whole batch.

---

## 5. Practical rules for AI agents

1. **One branch per iteration**. Write vNN → submit → read result → lesson →
   write vNN+1. Do not write multiple branches in the same session unless you
   are using `apply-batch`.

2. **Always record a lesson** after a run, even if the result was bad. The
   next AI needs to know what was tried and why it failed.

3. **Use `lyra digest`** to decide what to try next, not `lyra context`.
   `context` is the reference; `digest` is the decision tool.

4. **Feature names are exact**. `return_3` is not a feature; `return_6_atr`
   is. If you get "unknown feature", the error will suggest close matches.

5. **The 8-branch cap**: each track holds at most 8 active branches. When you
   need to prune, use `lyra prune` and record why in the lesson.

6. **v01 is the direction baseline** — never try to overwrite or modify it.
   All your work goes into vNN (N ≥ 2) under a track.

7. **Track IDs are permanent slugs**. Choose them thoughtfully (e.g. `t_me`
   for momentum exhaustion) — they appear in file paths and OCI object keys.

### Interpreting the numbers — do not over-trust them

These caveats are the difference between "the AI thinks it found alpha" and
"the AI understands what it actually measured". Read them before judging any
run:

- **`annualized` / `score` is a SUM, not a rate.** It is the net return of
  every trade divided by full calendar years — it is *not* annualised like a
  CAGR, and it is *not* a per-trade rate. A big number can come from a handful
  of big trades, not from a robust edge.
- **Choice bias ("best of N" is overstated).** If you (or a previous AI)
  tried 10 parameter sets and this is the best one, its score is the maximum
  of 10 noisy draws — systematically inflated. Treat a single top result as a
  *candidate*, not a conclusion. More trials → the best one looks better even
  when there is no edge.
- **Low-sample flag.** The report marks instruments with **< 20 trades** as
  `⚠ <20 trades`. A "win rate" on 3 trades is noise, not a signal. Weight
  lessons toward the instruments with real trade counts.
- **Costs matter — a zero-cost backtest is optimistic.** The report prints the
  applied cost model (`commission`, `financing`, `spread`, `slippage`) and
  warns if all are zero. A positive result that only survives *after* costs
  are set is far more believable than a cost-free one.
- **Instruments are correlated — don't sum them.** Each instrument's number
  is reported separately (never summed into a portfolio). But if several
  instruments are the same underlying (e.g. SPX500 vs SPX500_USD, or two
  indices), a "multi-instrument" result is really one bet counted several
  times. Treat correlated instruments as one exposure, not several.
- **Financing is charged per calendar day.** For FX/CFD on margin this is
  reasonable; for an index or cash position the day count overstates the real
  cost. Read the `financing day basis` line in the report before comparing
  instruments with different holding periods.
- **The 2% stop is fixed (not volatility-normalized).** The report shows each
  instrument's **stop%** (share of trades stopped out). An instrument at 0%
  had an *inactive* stop — its tail risk was never cut by the design, so its
  losses can be gap-driven and larger than 2%.
- **This is trade-level research, NOT an account backtest.** The 2% stop is a
  per-trade *price* stop. It is NOT account equity 2% HWM drawdown, not a 2%
  risk-per-trade budget, not margin/leverage/liquidation protection, and there
  is no sizing, portfolio, or cross-instrument exposure model. Never describe
  a result as "the account won't drop more than X".
- **Quotes are mid + synthetic spread (FIN-03).** The engine models the
  long/short bid/ask branch in code, but the current runner feeds only *mid*
  OHLC — so fills are mid price ± a fixed `spread_bps`, not real broker bid/ask
  execution. Treat fills as a research assumption, not a live-quote simulation.
- **Volume is quote/tick activity, not traded volume (FIN-04).** If the source
  is OANDA candle data, `volume` is the *number of price updates* in the bar —
  a tick/quote-activity proxy. MFI / OBV / relative volume derived from it
  measure quoting activity, not real order flow or money in/out. Don't read a
  volume indicator as "money flow" without verifying the source.

---

## 6. Example complete session

```
AI:  lyra context momentum_exhaustion --config config/config.yml
     → reads hypothesis, features, grammar
     → sees no tracks yet

AI:  lyra tracks momentum_exhaustion --create t_me --config config/config.yml

AI:  writes v02_me.yaml (rsi 30/70 entry, mhb=6, based on v01)
     lyra submit v02_me.yaml --data-dir ~/.lyra/default/data \
       --config config/config.yml --track t_me --branch v02
     → digest: SPX500_USD 714 trades, annualized -1.7%, win 50.1%

AI:  lyra lesson momentum_exhaustion --track t_me \
       "v02 (mhb=6, rsi_exit=55/45): -1.7% ann. Too fast. Next: wider entry."

AI:  writes v03_me.yaml (rsi 35/65 entry, mhb=12)
     lyra submit v03_me.yaml --data-dir ~/.lyra/default/data \
       --config config/config.yml --track t_me --branch v03
     → digest: SPX500_USD 896 trades, annualized +4.47%, win 56.5%

AI:  lyra lesson momentum_exhaustion --track t_me \
       "v03 (rsi 35/65, mhb=12): +4.47% ann. Wider entry wins. Next: + quality filter."

AI:  writes v04_me.yaml (rsi 40/60 + efficiency_24 > 0.3)
     lyra submit v04_me.yaml --data-dir ~/.lyra/default/data \
       --config config/config.yml --track t_me --branch v04
     → digest: SPX500_USD 677 trades, annualized +5.12%, win 56.7%

AI:  lyra lesson momentum_exhaustion --track t_me \
       "v04 (rsi 40/60, efficiency>0.3): +5.12% ann. Best. Next: within() temporal."

→ loop continues…
```
