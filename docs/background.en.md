# Background: moneta → nova → lyra

> Companion to [background.md](./background.md) (Chinese version).
> This document explains **why Lyra exists**. You do not need to read
> moneta or nova code before reading this; by the end you should be able to
> answer "why start a new repo (lyra) instead of continuing to modify nova".

## 0. In one sentence

Lyra is the **third** implementation of the same research goal (universal
strategy discovery on forex / precious metals / crude oil / equity indices).
The first two solved "does it run" and "can we verify it", but neither
solved "can I keep researching on a small AI budget in spare time".

## 1. Moneta (first generation)

**Window**: 2026-10-19 → 2026-10-31 (~2 weeks)
**Repo**: `ttrrei/moneta`
**Goal**: build a working backtest rig from scratch and get the
"data → features → strategy → backtest → report" path working end-to-end.

**What it did**:

- Data pipeline: `extract_oci.py` (OCI PAR download + unzip → CSV),
  `extract_oanda.py` (OANDA gap-fill / historical backfill), `load_data.py`
  (CSV → `all_data.parquet` + DuckDB catalog), `aggregate_ohlcv.py`
  (1m → 5m/1h), `indicators.py` (feature engine, TA-Lib + custom).
- Shared backtest engine: `engine.py` (accounting + metrics, long & short, tested).
- Strategy layer: `strategy_lib.py` (shared data/eval core), a few
  `strategy_*_lib.py` (S-01 RSI, S-05 Supertrend, S-06 EMA spread).
- Matrix runner: `run_matrix.py` (3 instruments × 2 windows × 3 cost tiers
  → `strategy/results/`).
- OOS governance: `oos_token.py` (data-layer holdout gate, fail-closed),
  `oos_ledger.json` (one-shot holdout ledger), `trial_log.md`
  (best-of-N discipline).
- Research campaign: 50 feature ideas, 200 strategies (2 rounds × 100),
  **0 promotions**.
- 305/270-column feature wide tables, Parquet + DuckDB.

**What it got right**:
- Causality protection (1h features use `m.close_time >= h.close_time`
  as-of join; signals confirmed on a closed bar, filled at T+1 open).
- Shared engine + test coverage (6 quality gates on indicators, metric
  definitions, pipeline units).
> **Erratum (2026-11-10)**: earlier text said "332 strategy YAMLs".
> Verified: moneta has **no strategy YAMLs at all** — its 132 S-series
> strategies are Python libraries (`strategy/*_lib.py`, 28 with matrix
> results), and its 200 research strategies (SR-20261031-200) are a
> 50-feature × 2-entry_model template Cartesian product with 0
> promotions. "332" is actually the total number of YAML *files* in the
> nova repo (17 hand-written strategies + 146 campaign experiment
> snapshots + 169 manifest/protocol/other runs YAMLs), not a strategy
> count; deduplicated by content there are ~162–169 distinct strategies.

**Why it stopped**:

1. **Research goal did not converge.** 50 features + 200 strategies with
   0 promotions means "how many indicators" is not the bottleneck;
   "how many **different types** of strategies can we explore in the
   same CPU time" is.
2. **Search space concentrated on familiar indicator combinations** —
   no real directionality.
3. **OOS ledger / trial_log / 305-column wide tables** are good
   mechanisms, but too heavy for "spare time + small AI budget": every
   one-line change required re-walking token mint → ledger reservation
   → holdout flow.
4. Engineering effort skewed toward "research feature development"
   instead of "research efficiency / strategy discovery capability".

**Assets left** (inherited by nova):
- Validated trade semantics (2% stop / next-open / losing-side priority /
  warmup-NULL behavior).
- 132 S-series strategies (Python libraries, 28 with matrix results;
  see erratum — not YAML; listed in lyra
  `strategies/temp/moneta_s_series/` pending 0010 triage).
- 17 registered features with their names and parameters.
- OCI PAR download in `extract_oci.py` (portable to Lyra).

## 2. Nova (second generation, 2026-11-01 → 2026-11-03)

**Window**: ~3 days
**Repo**: `ttrrei/nova`
**Goal**: port moneta's core semantics **as-is** into a **new repo**,
drop OOS / ledger / trial_log governance, and make "run one strategy,
inspect trades" a **light** operation.

**What it did** (see `nova/docs/DECISIONS_2026-11-03.md` §9):

| # | Component | Landed as |
|---|---|---|
| 1 | Data (OCI) | `data.py`: archive + hash + dedup + UTC aggregate |
| 2 | Features | `features.py` + `catalog.py` + `indicators.py` (Supertrend recursion) |
| 3 | Compiler | `compiler.py` + `config.py` (YAML → past-only SQL) |
| 4 | Trade engine | `trades.py` (2% stop / next-open / costs) |
| 5 | Metrics + runner | `metrics.py` + `runner.py` |
| 6 | Migration | 17 hand-written + 146 campaign snapshots verified in-grammar |
| 7 | Polish | `cli.py` + `doctor.py` + `audit.py` |

**What it got right**:
- The 4 core components' semantics are **identical** to moneta — no drift.
- All 332 YAML files (17 hand-written + 146 campaign snapshots + 169
  other runs YAMLs; see §1 erratum) pass the nova compiler: 0 failures,
  0 unregistered features, 0 unsupported operators.
- Tests cover causality / temporal confirmation / long-short fills /
  adverse gaps / costs / monthly zeros / data contracts / reproducibility.

**Why it stopped** (user's exact words from the 2026-11-03 DECISIONS doc):

> "Nova, driven by ChatGPT, has a simplistic core and over-engineered
> periphery — locks and the like. But the core functionality, e.g.
> downloading data from OCI storage or uploading strategy backups, is
> basically absent."

Specifically:

- **Over-engineered periphery**:
  - SHA256 snapshot directory names (e.g. `22d25208bac99177`) —
    meaningless to the owner.
  - `FROZEN_CORE.sha256` hard-fail guard — any change invalidates every
    historical run.
  - 761-line `manifest.json` artifact-hash list.
  - Three "governance" modules: `store.py` / `audit.py` / `doctor.py`.
- **Missing core functionality**:
  - **OCI bidirectional sync is entirely absent** (no pull / push / backup).
  - **Alpha boundary is not engineered** (no loading point for custom
    features, no strategy upload, no run backup).
  - **Feature-vs-feature comparison** (agreed in DECISIONS §6, but the
    nova compiler was not updated).
  - **Supertrend contract card + golden test** sample was not landed.

**Assets left** (inherited by Lyra):
- Validated semantics of the 4 core components (trade semantics, compiler
  grammar, metric definitions, data contracts).
- In-grammar validation results for the 17 hand-written strategies +
  146 campaign snapshots (held in temp/ pending triage).
- PAR download implementation in `extract_oci.py` (from moneta, portable).
- **A complete "what to drop" list** (DECISIONS §7).

## 3. Lyra (third generation, now)

**Window**: from 2026-11-05
**Repo**: `ttrrei/lyra`
**Goal**: port the 4 validated core components **as-is**, **drop** the
over-engineered periphery, and **add** the OCI bidirectional sync +
alpha boundary that nova lacked.

**Principles** (user's exact words on 2026-11-03):

> "This project is for me to keep trying and analyzing strategies in my
> spare time, on a small AI budget. It must stay stable and light. It
> must not become a 'perfectly engineered but useless' artifact."
> "The alpha (custom features, strategy definitions, run results) is the
> source of passive income and **must not** be open-sourced. The more
> people who see the alpha formula, the faster it gets arbitraged away."

**Build route**: the 0001→0009 table in [hld.md §8](hld.md) is the
**single source of truth** (each step = one decision doc written
**before** the code + one commit + one test set):

1. **0001 repo + OCI split** (alpha boundary rules, completed at the
   documentation level)
2. **0002 OCI pull + clean + aggregate** — the first **code** component;
   data sync is Lyra's primary function (R7), so it lands before
   features/compiler
3. **0003 Feature builder** → **0004 YAML compiler** → **0005 Trade
   engine** → **0006 Metrics & runner** — the four validated core
   components, ported semantics-intact from Nova; each component is
   proven on fixture data first, then wired to real OCI data
4. **0007 OCI push + backup** — the other half of the core feature
5. **0008 corpus migration + regression (12-direction formal library +
   temp/ gate)** → **0009 Polish** → **0010 temp/ AI triage**

**What we do not do** (see `requirements.md` §R9):
- Sizing / leverage / margin / equity / CAGR / HWM / Sharpe
- **autonomous / unbounded** AI strategy generation (unattended batch
  candidates). Note: **AI bounded iteration** (vNN inside a direction,
  human review per version) is in scope — see R12
- Live trading / broker integration
- Distributed / cloud-native
- Auto-scan of hundreds of indicators
- Portfolio optimization / asset-pool promotion
- OOS ledger / trial_log (Moneta's old mechanism, dropped)

## 4. Timeline

| Date | Event |
|---|---|
| 2026-10-19 | moneta repo created |
| 2026-10-26 → 30 | 5 rounds of repo review (`moneta/docs/repo_review_*.md`) |
| 2026-10-31 | 50-feature + 200-strategy campaign completed, 0 promotions |
| 2026-11-01 | nova repo created (moneta-next starter v0.1 → v0.2) |
| 2026-11-01 | luna6.1design / sol6.1design conversation archives (`nova/background/`) |
| 2026-11-03 | DECISIONS doc landed (`nova/docs/DECISIONS_2026-11-03.md`), fixed "what to drop / what to keep / what to add" |
| 2026-11-05 | **lyra repo created (this repo)**, documentation starts |

## 5. Inheritance matrix of key decisions

| Decision | moneta | nova | lyra |
|---|---|---|---|
| Data substrate | Parquet + DuckDB | Parquet + DuckDB | **same** |
| Strategy language | YAML | YAML | **same** (feature-vs-feature relaxed) |
| Feature storage | 305/270-col wide tables | Hybrid (core + domain) | **Hybrid** (core + domain) |
| Temporal conditions | SQL layer | SQL layer (past-only) | **same** |
| Cross-instrument | Universal | Universal | **same** |
| Leverage | up to 30x | 30x (only to explain 2% stop) | **30x** (only to explain 2% stop) |
| Drawdown rule | HWM + 1%/2% (**retired**) | only 2% stop | **only 2% stop** |
| 2% mandatory exit | none | yes (relative to actual entry) | **same** |
| One trade per instrument | yes | yes | **same** |
| Close-confirm / next-open fill | yes | yes | **same** |
| Monthly opportunity = actual entry | yes | yes | **same** |
| Annualized score = sum ÷ full calendar | yes | yes | **same** |
| OOS ledger / trial_log | yes | **no** | **no** (not inherited) |
| SHA256 snapshot directories | no | yes | **no** |
| FROZEN_CORE guard | no | yes | **no** |
| Artifact-hash manifests | no | yes | **no** |
| OCI bidirectional sync | pull only (`extract_oci.py`) | **no** | **yes** (core feature) |
| Alpha boundary | none (moneta is personal repo) | none | **yes** (OCI is source of truth) |

## 6. How to read the old moneta / nova docs

- **moneta**: `docs/BRD.md` (requirements), `docs/SAD.md` (architecture),
  `docs/indicators.md` (feature spec), `docs/data_profile.md` (data profile),
  `docs/repo_review_2026-10-26..31*.md` (5 review rounds with failure diagnosis).
- **nova**: `docs/DESIGN.md` (design contract),
  `docs/DECISIONS_2026-11-03.md` (**most important decision archive**),
  `docs/REAL_DATA_RESULTS.md` (real-data run results),
  `docs/VERIFICATION.md` + `docs/verification/` (verification evidence).
- **Conversation archives** (dense but high signal):
  - `nova/background/luna6.1design`: luna 6.1 full conversation (111 KB)
  - `nova/background/sol6.1design`: sol 6.1 full conversation (14 KB)
  - `nova/background/moneta-next/START_HERE.md`: starter v0.2 startup contract

## 7. Maintenance of this document

- Every time a Lyra feature is completed, tick off the matching step in
  the §3 build route and add a row to the §4 timeline.
- If a moneta / nova decision is **overridden** by Lyra, add a row to the
  §5 table (moneta column keeps the original, nova column keeps the
  original, lyra column has the new value + a link to the decision doc).
- This document is **append-only** (historical decisions are not deleted;
  they are only marked "retired" in the §5 table).

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft. |
| 2026-11-05 | 0.2 | §3 "three things" replaced by a "build route" that defers to the hld.md §8 0001→0009 table (single source of truth), resolving the ordering conflict with the README. |
