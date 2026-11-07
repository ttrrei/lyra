# Lyra Requirements

> **中文**: [requirements.md](./requirements.md)
>
> This is Lyra's requirements baseline. Every feature decision doc
> (`docs/decisions/NNNN-*.md`) must explicitly reference a section here.
> Changes to the requirements themselves are also recorded here (revision
> history at the bottom).

## R0. One-sentence goal

Provide a **stable, lightweight, reviewable** strategy-research tool that
lets one person keep "trying + analyzing" strategies on a small AI budget
in spare time. It is **not** a product, and **not** a compliance/audit
system.

## R1. Research questions

- Given a set of instruments (forex / precious metals / crude oil /
  equity indices), can one **universal strategy** (same rules, same
  parameters, same cost assumptions) produce **actual monthly entry
  opportunities**?
- If yes, is its **annualized net-return score** (arithmetic sum of net
  trade returns ÷ full calendar years, 365.25 days/year) positive, and
  higher than comparable candidates?
- Each instrument is reported **separately**. No portfolio return, no
  Buy & Hold gate.
- "No edge" is a **legitimate** research outcome. The tool must surface
  it honestly, not inflate it.

## R2. Strategy language

- **YAML is the only strategy language.** No SQL, no Python, no eval, no
  callbacks, no external scripts.
- **Parameters are fixed.** Each feature's parameters are set at
  registration time. No parameter sweeps (anti-overfit). Want something
  new? Register a new feature.
- **Comparison operators**: `eq / ne / gt / gte / lt / lte`.
- **Temporal operators**: `all / any / not`, `held_for`, `within`,
  `after_event`.
- **Right-hand side**: a constant **or** another registered feature
  column. **Forbids** feature arithmetic (`+ - * /`), cross-instrument
  comparison, and arbitrary SQL fragments.
- **One strategy = one timeframe.** (No 60m entry + 5m exit combo.)
- **One strategy = one rule set**; `long` / `short` may be specified
  separately; conflicting conditions → neither opens.
- **Backward compatibility**: all 332 existing strategy YAMLs must run
  on the Lyra compiler with no syntax change.

## R3. Feature model

### R3.1 Standard features (open-source, ship with the repo)

Fixed registered names + fixed parameters. **Window parameters only
take the CFD grid {6, 12, 24, 60, 120}** (user decision 2026-11-07,
0003 K8: do not use the Wilder-era "14 ≈ 2 weeks" legacy parameter;
a narrow parameter surface suppresses overfitting into a narrow
parameter environment; **120 aligns with moneta `catalogue.py`'s
authoritative grid**). Initial list:

- Market data: `open / high / low / close / volume` (UTC-aligned)
- SMA: 6, 12, 24, 60, 120
- EMA: 6, 12, 24, 60, 120
- ATR: Wilder-ATR 6 / 12 / 24 / 60 / 120 (**24 = default
  ATR-normalization denominator**)
- NATR: `atr / close` normalized (6, 12, 24, 60, 120)
- RSI: 6, 12, 24, 60, 120
- PSAR: (0.02, 0.2) (exception: acceleration/extreme factors, not
  window parameters)
- Supertrend: (ATR window 24, multiplier 3) (**`talib.SUPERTREND`
  library implementation**, 0003 K1; the moneta/nova
  self-implementation reference serves as the golden cross-anchor)
- MACD (curated triplets, NOT full grid expansion): (6, 12, 6) /
  (6, 24, 6) / (12, 60, 12)
- ROC: 6, 12, 24, 60, 120
- STOCH: %K/%D, (fastk, slowd) ∈ {(6,6), (24,12), (60,24)} (slowk
  smoothing = 1)
- BBANDS: %B + bandwidth, window (24, 60, 120), std = 2
- ADX / PLUS_DI / MINUS_DI: 24, 60 (trend-strength family, 2 points only)
- CCI: 24, 60
- WILLR: 24, 60
- MFI: 24, 60 (volume-weighted money flow)
- CMO: 24, 60
- OBV + `obv_slope_24` (cumulative volume + 24-bar slope)
- LINEARREG_SLOPE (normalized slope): 24, 60
- KAMA (adaptive moving average): 24
- **v0.9 additions (P0 gap fill)**:
  - DEMA (double exponential MA): 6, 24, 60
  - TEMA (triple exponential MA): 6, 24, 60
  - HMA (Hull MA): 24, 60
  - MOM (n-bar momentum = close diff): 6, 24, 60
  - Rolling StdDev (price dispersion): 24, 60
  - Z-Score (standardized price position): 24, 60
  - Efficiency Ratio @60 (v0.8 has eff_24): 60
  - Donchian @60 (prior60_high / prior60_low; v0.8 has prior24_*): 60
- **v1.1 additions**: Heikin Ashi (`ha_o / ha_h / ha_l / ha_c`, K7 self-implementation, recursive transform, no window parameter, warmup 16)
- **Parked (with rationale, not forgotten)**:
  - Keltner (= EMA±2×ATR; BBANDS already covers the "mean ± n-volatility band" signal)
  - Choppiness (= 100×LOG(SUM(TR)/MAXHIGH−MINLOW); a composite of ATR+Donchian, not an independent signal)
  - Relative Volume / VWMA (v0.8 rel_quote_activity already covers relative-volume signal)
  - PPO (normalized MACD variant, redundant); TRIX / ULTOSC / AROON / TSI / SMI (niche momentum variants, parameter surface too large)
  - CMF / EFI / PVT / VHF (volume-direction ratios, overlapping with MFI/OBV)
  - Vortex / QQE / RSX / VFI / Squeeze / Schaff / Ichimoku / Inside Bar / Williams Fractal (need self-implementation or parameter explosion; Heikin Ashi shipped in v1.1)
  - CORREL / BETA (no natural reference series in a single-instrument universe)
  - HT_* (overfitting risk); CDL* (needs a statistical pre-screen first)
- Semantic / structure: `sma_cross_up_6_24 / sma_cross_down_6_24`,
  `sma_alignment_6_24 ∈ {-1, 0, 1}`, `rsi_divergence_up / down`,
  `psar_bullish / bearish`, `supertrend_bullish / bearish`
- Research primitives (v2, settled): prior-24-bar high/low/range/
  position/width, breakout / failed-breakout predicates, 6-bar ATR-
  normalized displacement, bar range/ATR, relative quote activity,
  UTC opening hour, 24-bar path efficiency

### R3.2 Custom (alpha) features — Python is the floor

- **All custom features are written in Python** (not DSL / pseudocode /
  operator algebra).
- Each feature must carry a **contract card**: state variables, transition
  rule, seed rule, gap/flip boundary, dependent input columns.
- Each feature must carry a **golden test**: fixed input → fixed output,
  pinning the semantics.
- Code + contract card + golden test are **alpha and live in OCI only**,
  never in git.
- The git side keeps only a clean **extension point**:
  `lyra.features.load_from(directory)` — standard features ship with the
  repo; alpha features load from an OCI-mounted path at runtime.

### R3.3 Causality

- Each feature is available at `bar_close_time`. "per-bar" does not
  prohibit EMA/PSAR from using history; it only prohibits using the future.
- Compiled SQL must be **past-only**: `lag` / windows ending at the
  current row; no `lead`, no forward joins.
- Warm-up NULLs are **retained**, not arbitrarily removed. `held_for` /
  `within` require a full N-row non-NULL window to be true (conservative
  convention inherited from the starter).

## R4. Execution contract (trade engine)

- **Close-confirm signals, fill at the next observed open.**
- **2% mandatory adverse exit** (relative to the actual entry fill):
  - Long: price ≤ entry × (1 − 0.02) triggers before the next open.
  - Short: price ≥ entry × (1 + 0.02) triggers before the next open.
  - Gap/slippage losses may exceed 2%. **2% is a trigger, not a cap on
    final net loss.**
- **Same bar hits both stop and target → losing side wins.**
- **At most one open position per instrument**; new entry signals are
  ignored while a position is held.
- **No re-entry on the exit bar**; may re-enter on the next bar if the
  entry condition holds.
- **Conflicting long/short conditions → neither opens.**
- **An entry scheduled on the last bar expires.**
- **A position still open at end of data exits at that last close.**
- **Costs**: flat round-trip commission fraction + financing fraction per
  **trading day** (elapsed = trading days in the holding interval;
  **weekends and market holidays — New Year / Christmas, etc. — are not
  counted**, not physical calendar days); spread/slippage are already in
  the fills, not double-counted.
  double-counted.
- **Return formula**: `direction × (exit_fill − entry_fill) /
  entry_fill` minus costs. **No** sizing, leverage, margin, equity, HWM,
  circuit breaker.

## R5. Metrics and reporting

- **Per instrument, per month** one row: actual entries, net-return sum,
  win rate, average holding bars.
- **Zero-entry months are retained** (explicit 0, not omitted).
- **Annualized score** = arithmetic sum of all trade net returns ÷ full
  calendar years (365.25 days/year).
- **Monthly opportunity** = actual entries (not signal appearances).
- **No portfolio synthesis**; no CAGR / HWM / Sharpe / Sortino.
- Reports must list: strategy name, timeframe, instrument list, time
  window, feature snapshot id, git commit, date.

## R6. Data and OCI

- **Base data is pulled from OCI** (PAR URL), not kept in git.
- Local layout (see `docs/proposals/oci-alpha-layout.md`):
  - `oci://<bucket>/lyra/data/raw_csv/`: raw CSVs (OANDA / other sources)
  - `oci://<bucket>/lyra/data/raw_parquet/`: raw Parquet
  - `oci://<bucket>/lyra/data/market/<minutes>m/`: cleaned OHLCV Parquet
  - `oci://<bucket>/lyra/data/features/<minutes>m/`: feature wide tables
- **Alpha boundary** (all OCI-only; layout in
  `docs/proposals/oci-alpha-layout.md`):
  - `oci://<bucket>/lyra/alpha/features/*.py`
  - `oci://<bucket>/lyra/alpha/features/contracts/*.md`
  - `oci://<bucket>/lyra/alpha/features/tests/*.py`
  - `oci://<bucket>/lyra/strategies/<direction>/{hypothesis.md, lessons.md, vNN.yaml}`
    (direction-folder organization, see R12)
  - `oci://<bucket>/lyra/runs/<name>/<date>/*`
- **Bidirectional sync** is Lyra's core feature (see R7).
- **OCI mirrors live outside the repository by default**: local `data/`
  `strategies/` `runs/` resolve to `~/.lyra/<workspace>/…`, **not**
  inside the git working tree (B13 anti-footgun).
- The local cache can be deleted and rebuilt (pull from OCI + recompute).
- Data integrity: SHA256 checks, deduplication (unique `(instrument,
  time)`), missing minutes treated as gaps (no synthetic fill).

## R7. OCI bidirectional sync (Lyra's core feature)

Lyra's **primary function** is to stay in sync with OCI:

- **pull**: fetch required datasets per `config.yml` (raw → market →
  features), cache locally, reuse by snapshot id.
- **push**: after a strategy run completes, upload runs / analysis to OCI;
  modified alpha features may be pushed back to OCI.
- **backup**: one-command `lyra sync` when local `strategies/` or `runs/`
  change.
- **Conflict policy**: `config.yml` decides (default: OCI is source of
  truth; local changes require explicit `--force-push`).
- **Credentials**: PAR URL preferred; optional OCI auth
  (`~/.lyra/credentials`). Credentials never enter git.

## R8. Non-functional requirements

- **Stable**: same input + same version → same output (bit-for-bit when
  DuckDB version matches).
- **Light**: core dependencies ≤ 15 Python packages; startup < 3s; a
  full 21-instrument H1 run < 5 min on a 16-core machine.
- **Reviewable**: one commit + one decision doc per feature; tests cover
  causality / execution contract / metric definitions / data contracts.
- **Portable**: POSIX + Windows; no system packages (TA-Lib via wheel).
- **No side effects**: no git writes, no network (except OCI), no user-
  file modification outside explicitly declared local directories.

## R9. Explicitly out of scope

- Sizing, leverage, margin, equity, CAGR, HWM, Sharpe, Sortino
- Circuit breakers, account-level stop, recovery rules
- **autonomous / unbounded AI strategy generation** (unattended batch
  candidate generation, unconstrained automatic search). **Boundary
  note**: AI as a **bounded-iteration** first-class writer (writing vNN
  inside approved directions, with human review per version) is **in
  scope** — see R12. The distinction: whether there is a directional
  hypothesis constraint + per-version human review.
- Live trading / broker integration
- Distributed / multi-process / cloud-native
- Auto-scan of hundreds of indicators
- Portfolio optimization / asset-pool promotion / Buy & Hold gate
- Cross-timeframe combination (one strategy = one timeframe)
- OOS ledger / one-shot gate / trial_log (Moneta's old machinery, not
  inherited)

## R10. Acceptance

- `pytest -q` all green (causality / execution contract / metric
  definitions / data contracts).
- `lyra-doctor` all green.
- At least 3 strategies (long-only / short-only / long+short) run on
  21 instruments H1 full data, reports reviewable.
- All 332 legacy strategy YAMLs pass `lyra validate`.
- OCI pull/push passes one end-to-end run on a real bucket.

## R11. Compatibility

- **Backward-compatible with Nova**: the 332 strategy YAMLs run as-is;
  the 17 registered feature names are unchanged; the 2% stop semantics
  are unchanged.
- **Not compatible with Moneta**: Moneta's OOS ledger / trial_log /
  305/270-column feature tables are **not** Lyra's input contract; if
  migration is needed, use `lyra ingest --kind moneta` (future feature).

## R12. Directions and iteration (strategy organization model)

The **primary unit of strategy organization is a direction (research
family)**, not an individual YAML file. The initial 12 directions are
inherited from nova: `trend_continuation`, `failed_breakout`,
`mean_reversion`, `momentum_exhaustion`, `pullback_reentry`,
`range_trading`, `regime_transition`, `relative_strength`,
`session_temporal`, `volatility_expansion`, `volume_activity`,
`market_structure`.

**The direction set is open (extendable)**: the initial 12 are a seed,
not a closed list. Users may create new directions; a new direction
**should** be a testable, independent market hypothesis and ideally not
duplicate an existing one (soft standard; if expressible via an existing
direction, prefer a new version of that direction). New and initial
directions are fully peer.

- **One folder per direction**, which must contain:
  - `hypothesis.md`: testable claim + kill criteria + status
    (active / paused / killed) + active branches + change history
    (append-only).
  - `lessons.md`: append-only evolution log; one section per branch
    version (parent / what changed / the lesson that drove it / result)
    + one section per branching judgment (comparison /
    continue-prune-cross / reason).
  - `v01.yaml`, `v02a.yaml`, `v02b.yaml`, …: a **version tree** (one
    parent can spawn multiple candidate branches; crossover branches
    named like `v04ab.yaml`).
- **vNN (N≥2) must declare** `parent: <parent version id>` (crossover:
  `parents: [...]`) and `driven_by_lesson: <one line, pointing into
  lessons.md>`. v01 is exempt.
- **Multiple branches are first-class**: single-threaded deep search
  falls into local optima; a version's diagnosis should spawn
  **multiple** candidate evolution branches tried in parallel;
  `lyra compare --siblings` provides side-by-side run summaries of
  sibling branches for the AI/human to judge continue / prune / cross.
  Crossover (mutation): **fully decided by the strategy-finding AI**
  (whole-part / per-parameter / modified, granularity unrestricted); the
  framework's job is to make sure the AI has the capability (context
  includes the active branches' full YAML + parameters); the AI declares
  provenance in the YAML (`inherited` / `driven_by_lesson`) for audit.
  > **Boundary (I8 unchanged)**: modification applies only to the
  > **strategy layer** (thresholds / operators / temporal operators /
  > entry-exit structure); **changing a feature's registered name or
  > underlying parameters is forbidden** (e.g. `sma_6_24`→`sma_7_25`
  > is an I8 violation, `validate` rejects it). A changing feature =
  > a newly registered feature (contract card + golden test).
- **Branch lifecycle**: `active` → `pruned` (files retained, never
  deleted) → or inherited by a crossover. Kill criteria apply to **all
  active branches** failing N consecutive rounds; a single failing
  branch = prune, not kill.
- **Evolution loop** (core workflow):
  `context` → `new-version --branch` (derive 1..N branch templates) →
  run each → `compare --siblings` → write lessons (one section per
  branch + one judgment section) → (optional) `merge` crossover →
  `push-direction`.
- **AI is a first-class writer**: same commands as the user; AI context
  must be self-contained in the direction folder — `lyra context
  <direction>` emits a single-file context bundle (hypothesis + last N
  lessons + active-branch vNN + **sibling-branch run-summary
  comparison table** + feature list); the AI write loop = read 1 file →
  write 1..N branch files → run each once → log 1 section + 1 judgment,
  never touching the rest of the repo.
- **Directions are labels, not independent sources of edge** (inherited
  consensus from the nova DECISIONS); "no edge" is an allowed conclusion;
  when kill criteria trigger, the direction is marked `killed` and the
  folder is retained (not deleted; extension of B6).
- **extendable**: new directions live under `strategies/_new/<name>/`,
  same structure as the initial 12; ideally testable and non-duplicative
  (soft standard); initial and extended directions are fully peer;
  killed directions are not deleted.

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft. Distilled from
  `nova/docs/DECISIONS_2026-11-03.md` and `nova/docs/DESIGN.md`;
  applicable parts of Moneta BRD/SAD folded into R4/R5. |
| 2026-11-05 | 0.2 | R6 alpha boundary switched to direction-folder layout; added **R12 Directions and iteration**
  (hypothesis / lessons / vNN version chain / kill criteria / iteration loop). |
| 2026-11-05 | 0.3 | R12 made the direction set **extendable**: initial 12 are a seed, not a closed list; new-direction admissions bar + peer status + killed-not-deleted. |
| 2026-11-05 | 0.4 | R12 admissions bar settled as a **soft standard (option A)**: recommendation, not a hard gate. |
| 2026-11-05 | 0.5 | R12 added **AI as first-class writer + self-contained context** (`lyra context` single-file bundle; read 1 / write 1 / run 1 / log 1). |
| 2026-11-05 | 0.6 | R9 wording fixed: what is excluded is **autonomous / unbounded AI generation**; made explicit that **AI bounded iteration (R12) is in scope**, resolving the literal conflict with R12. |
| 2026-11-05 | 0.7 | R12 upgraded to a **version tree** model: branching (1 parent → N candidate branches), `compare --siblings` multi-branch comparison, `merge` crossover (mutation), branch lifecycle active/pruned, kill criteria now "all active branches failing N consecutive rounds"; naming `v<generation><branch-suffix>`. |
| 2026-11-06 | 0.8 | R12 crossover gains an **I8 boundary** (L2): the AI's modification capability is limited to the **strategy layer** (thresholds / operators / temporal operators / entry-exit structure); changing a feature's registered name or underlying parameters is forbidden (e.g. `sma_6_24`→`sma_7_25` is an I8 violation, `validate` rejects it); a changing feature = a newly registered feature. |
| 2026-11-07 | 0.9 | **R3.1 grid discipline (user decision, 0003 K8)**: window parameters only take the CFD grid {6,12,24,60} — no Wilder "14 ≈ 2 weeks" legacy parameter; a narrow parameter surface suppresses overfitting into a narrow parameter environment. ATR re-registered as 6/12/24/60 (24 = default normalization denominator), RSI as 6/12/24/60, SMA/EMA gain 12, Supertrend's ATR window 14→24; exception: PSAR (0.02,0.2) kept (not a window parameter). Prior-generation evidence: moneta `catalogue.py` `raise ValueError("window outside CFD grid")` for off-grid windows; nova's research features in practice all use 6/12/24/60. Synced with 0003 v0.5 (K6/K7/K8 + §3.4 + 24 tests) |
| 2026-11-07 | 0.10 | **R3.1 two updates (user directives)**: ① **grid adds 120** → {6,12,24,60,120}, **aligned with moneta `catalogue.py`'s authoritative grid**; ATR/RSI/SMA/EMA each gain a `*_120` variant. ② **Supertrend switched to the library** — measured evidence overturns the prior generations' assumption: the moneta/nova headers' "TA-Lib ships no Supertrend" is a stale-version misconception, and the **TA-Lib 0.8.2** both generations lock does ship `SUPERTREND` (a real import probe confirms it); a real-data dual-library parity test (SPX500_USD 1h, 5000 bars) shows the self-implementation and `talib.SUPERTREND` **match bar-for-bar 100%** → R3.1's Supertrend row changed from "self-implemented" to "`talib.SUPERTREND` library implementation + the moneta/nova self-implementation reference as golden cross-anchor". Synced with 0003 v0.6 (K1/K7/K8 + §3.4 + 25 tests) |
| 2026-11-07 | 0.11 | **R3.1 expanded standard-indicator set (user approved "recommended scope")**: added **13 families** — NATR / MACD (curated triplets 6_12_6/6_24_6/12_60_12) / ROC / STOCH (%K/%D) / BBANDS (%B + bandwidth, no raw bands) / ADX + PLUS_DI + MINUS_DI / CCI / WILLR / MFI / CMO / OBV (slope) / LINEARREG_SLOPE / KAMA. All window parameters restricted to the K8 grid {6,12,24,60,120} (the external suggestion list's 5/10/14/20 parameters are all rejected). Parameter-surface discipline: MACD curated triplets (not full grid expansion), trend-strength/momentum/oscillator families take 24/60 only, BBANDS/OBV use dimensionless forms. **Parked** (with rationale): PPO/TRIX/ULTOSC/AROON/STDDEV (redundant or niche), CORREL/BETA (no reference series in a single-instrument universe), HT_*/CDL* (overfitting risk / need a statistical pre-screen first). **Triggers I13: FEATURE_VERSION +1**. Synced with 0003 v0.8 (§3.4 + D4 gate + 34 tests) |
| 2026-11-07 | 0.12 | **R3.1 v0.9 fills the P0 gap (8 items)**: DEMA (6/24/60), TEMA (6/24/60), HMA (24/60), MOM (6/24/60), Rolling StdDev (24/60), Z-Score (24/60), Efficiency Ratio @60, Donchian @60 (prior24_* extended to prior60_*). **Parked additions**: Keltner (=EMA±2×ATR, BBANDS covers it), Choppiness (=ATR+Donchian composite transform), Relative Volume/VWMA (rel_quote_activity covers it), all P1 families (parameter surface too large or need self-implementation, deferred to batch 2). **Triggers I13: FEATURE_VERSION +1** (v0.8 already +1, this +1 more = cumulative +2). Synced 0003 v0.9 (§3.4 + 6 new tests) |
| 2026-11-07 | 0.13 | **R3.1 adds Heikin Ashi (user instruction; 0003 v1.1)**: `ha_o / ha_h / ha_l / ha_c` (4 columns), K7 self-implementation (TA-Lib has no HA), recursive transform with no window parameter (K8 N/A), warmup_bars=16 (safe lower bound for the recursive convergence); all K7 management discipline applies (registry `self_implemented: True` marker + contract card + golden test + I13). The parked-list "Heikin Ashi" entry is removed (shipped). **Triggers I13: FEATURE_VERSION +1 (2→3)**. Synced 0003 v1.1 (§3.4 + tests +2) |
