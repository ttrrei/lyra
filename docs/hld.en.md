# High-Level Design (HLD)

> **中文**: [hld.md](./hld.md)
>
> This is Lyra's "skeleton": component partition, data flow, boundaries,
> and core invariants. Implementation detail for each component lives in
> `docs/decisions/NNNN-*.md`.

## 1. Design principles (priority high → low)

1. **Correctness > simplicity > performance.**
   Correctness means causality, execution contract, and metric
   definitions; simplicity means code size, dependency count, config
   surface; performance means run wall-time and peak memory. When they
   conflict, **correctness is non-negotiable**, **simplicity beats
   performance**.
2. **Reviewability > automation.**
   One feature = one commit + one decision doc + one test set beats
   "AI generates 100 lines in one shot".
3. **Strict separation of alpha and core.**
   Core is open-source; alpha is closed-source; core interfaces must
   **not depend on** any specific alpha implementation (only on the
   generic "load Python modules from a directory" extension point).
4. **Data lives in OCI, code lives in git.**
   Local OCI mirrors (`data/` `strategies/` `runs/`) live **outside the
   repository by default** (`~/.lyra/<workspace>/…`, B13) and are
   rebuildable; `strategies/examples/` is the only strategies subtree in
   git (B14).
5. **Less is more.**
   No OOS ledger / trial_log from Moneta; no SHA256 snapshot directories /
   FROZEN_CORE / artifact manifests from Nova; no "for future use"
   abstractions.

## 2. Component partition

```
┌─────────────────────────────────────────────────────────────────┐
│                     lyra CLI (lyra / lyra-doctor)               │
├────────────┬────────────┬──────────────┬────────────────────────┤
│  data      │  features  │  strategy    │  run                   │
│  (pull)    │  (compute) │  (compile)   │  (backtest + report)   │
│            │            │              │                        │
│  - pull    │  - build   │  - validate  │  - execute             │
│  - clean   │  - load    │  - compile   │  - trade engine        │
│  - aggregate│ - extend  │              │  - metrics             │
│  - cache   │  (alpha)   │              │  - report              │
│            │            │              │                        │
├────────────┴────────────┴──────────────┴────────────────────────┤
│  oci client (pull / push / backup / list)  ── PAR URL + creds   │
├─────────────────────────────────────────────────────────────────┤
│  local cache (data/ strategies/ runs/)  ── rebuildable          │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 data component

**Responsibilities**:
- Pull raw CSV / raw Parquet from OCI (`lyra pull`).
- Clean: deduplication (unique `(instrument, time)`), mark missing
  minutes as gaps, UTC alignment, Bid/Ask field validation.
- Aggregate: 1m → 5m / 60m (`time_bucket` UTC boundary; aggregates the
  existing 1m bars in the window, **`n_bars` faithfully marks partial bars**
  — 0002 I21, partial gaps are legal, no synthetic fill).
- Local cache: `data/raw_csv/`, `data/raw_parquet/`,
  `data/ohlcv_5m/ohlcv_5m.parquet`, `data/ohlcv_1h/ohlcv_1h.parquet`
  (**single-file external tables** — 0002 D4 already deprecated the
  directory-level `<snapshot_id>` hierarchy; this hld §2.1 wording is
  historical draft, defer to 0002).

**Not doing**:
- No feature computation here (that is the features component).
- No OOS gate / holdout (retired).
- No "data version promotion" (snapshot id is a monotonically increasing
  integer; no "active / reserved / completed" state machine).

**Key invariants**:
- Files in `data/raw_csv/` and `data/raw_parquet/` are **immutable**
  (SHA256 recorded at import time; read-only thereafter).
- Aggregation starts from cleaned 1m; partial buckets are not
  synthetically filled.
- Calendar gaps remain gaps.

### 2.2 features component

**Responsibilities**:
- Compute registered standard features from OHLCV (the 0002 aggregated
  layers `ohlcv_5m`/`ohlcv_1h`) (SMA/EMA/RSI/ATR/PSAR/Supertrend/…).
- Load alpha features (`lyra.features.load_from(directory)` extension
  point).
- Publish feature wide tables to
  `data/features/<minutes>m/<instrument>.parquet` (**single file, NO
  `<snapshot_id>` directory level** — 0003 v0.7 aligned to 0002 D4's
  deprecated directory-level snapshot scheme; the version lives in
  Parquet metadata; see 0003 §3.1 + §2.3 D1 disposition).

**Not doing**:
- No parameter sweeps (parameters fixed at registration).
- No "feature combination / derived feature" (register a new feature
  instead).
- No feature-vs-feature runtime comparison (that is the compiler's job).

**Key invariants**:
- Each feature is available at `bar_close_time` (past-only).
- Warm-up NULLs retained, not arbitrarily removed (0003 v0.7 F2
  tightened: NULLs allowed only from the warm-up prefix ∪ a derived
  feature's defined zero denominator).
- Feature version identifier = a **derived string** over (timeframe,
  FEATURE_VERSION, full parameter-set sha256, numeric-stack version),
  written into **Parquet metadata** (**not a directory level** — 0003
  v0.7 aligned to 0002 D4's deprecated directory-level snapshot scheme;
  not a monotonic integer, no allocator).
- Changing a feature computation → FEATURE_VERSION + 1.

### 2.3 strategy component

**Responsibilities**:
- Read strategy YAML (from local `strategies/` or OCI `lyra/strategies/`).
- `lyra validate`: syntax check + feature registration check + parameter
  check.
- `lyra compile`: YAML → past-only SQL (DuckDB).

**Not doing**:
- No SQL execution (that is the run component).
- No "strategy combination / multi-strategy bundle" (one strategy = one
  file = one timeframe).

**Strategy evolution (user + AI are both writers; see R12 / oci-alpha-layout §2.3)**:
- `lyra context <dir>`: emits a single-file context bundle.
- `lyra new-version --branch`: derive candidate branches from a parent.
- `lyra compare --siblings`: side-by-side run summaries of sibling branches.
- `lyra merge --from <a> --from <b>`: AI-free crossover (granularity unrestricted).
- `lyra push-direction` / `lyra push-strategy`: persist to OCI.
- Crossover is fully decided by the AI; the framework ensures the AI has the capability (context includes full parameters).

**Key invariants**:
- Compiled SQL must be past-only (`lag` / current-row-ending windows, no
  `lead`, no forward joins).
- Right-hand side = constant or registered feature column only;
  **feature arithmetic is forbidden**.
- Temporal operators `held_for` / `within` require a full N-row non-NULL
  window to be true.

### 2.4 run component

**Responsibilities**:
- Execute the compiled SQL (DuckDB).
- Bar-by-bar trade state machine (2% stop / next-open / costs).
- Per-instrument, per-month accumulation (zero-entry months retained).
- Publish run reports to `runs/<name>/<date>/`.

**Not doing**:
- No sizing / leverage / margin / equity / CAGR / HWM.
- No portfolio optimization / asset-pool promotion.
- No live trading.

**Key invariants**:
- 2% stop is a **trigger**, not a cap on final net loss.
- Same-bar hit of stop and target → losing side wins.
- One trade per instrument; new entry signals ignored while a position
  is held.
- Entry scheduled on the last bar → expires.
- Position still open at end of data → exits at that last close.

### 2.5 oci client component

**Responsibilities**:
- `lyra pull`: fetch required datasets per `config.yml`.
- `lyra push`: upload `strategies/` / `runs/` to OCI.
- `lyra backup`: one-command **push-only** sync (local→OCI, with conflict detection; the early "pull + push" wording was corrected to push-only in 0.20 per batch-2/M2; `sync` is its alias).
- `lyra list`: list datasets / strategies / runs on OCI.
- Credential management: PAR URL preferred; optional OCI auth
  (`~/.lyra/credentials`).

**Not doing**:
- No OCI versioning (snapshot id is allocated locally; OCI only stores
  files).
- No OCI permission management (that is the OCI console's job).
- No multi-bucket routing (one bucket + one prefix in `config.yml` is
  enough).

**Key invariants**:
- Credentials never in git, never in run reports.
- Push must verify locally first (SHA256 + size + file manifest).
- Push is **idempotent** (same snapshot id + same content → no re-upload).

## 3. Data flow

```
OCI (raw CSV / Parquet)
        │
        ▼  lyra pull
local data/raw_csv/ + data/raw_parquet/  (immutable, SHA256-verified)
        │
        ▼  lyra clean
local data/bronze/...  (cleaned 1m, single-file external tables)
        │
        ▼  lyra aggregate --minutes 5 60
local data/ohlcv_5m/ohlcv_5m.parquet + data/ohlcv_1h/ohlcv_1h.parquet
        │  (single-file external tables — 0002 D4 deprecated the
        │   directory-level <snapshot_id> hierarchy)
        ▼  lyra features --minutes 5 60
local data/features/ohlcv_5m/<instrument>.parquet + data/features/ohlcv_1h/<instrument>.parquet
        │  (one Parquet per instrument, version in metadata — 0003 v0.7)
        ▼
OCI (lyra/data/market/ + lyra/data/features/)  ← optional push, for
multi-machine reuse
        │
        ▼  lyra run --strategy <yaml>
local runs/<name>/<date>/
   ├── run_meta.json  (strategy, time window, instruments, feature
   │                  snapshot, git commit)
   ├── trades.csv     (per-trade)
   ├── monthly.csv    (per-instrument per-month)
   └── report.md      (human-readable)
        │
        ▼  lyra push
OCI (lyra/runs/)
```

## 4. Core invariants (cross-component)

| # | Invariant | Source |
|---|---|---|
| I1 | Each feature is available at `bar_close_time` | moneta / nova agree |
| I2 | Signals confirmed on a closed bar, filled at T+1 open | moneta / nova agree |
| I3 | 2% mandatory adverse exit (relative to actual entry) | nova 2026-11-03 confirmed |
| I4 | Same-bar stop+target hit → losing side wins | nova 2026-11-03 confirmed |
| I5 | One trade per instrument; new entries ignored while holding | moneta / nova agree |
| I6 | Zero-entry months retained | moneta / nova agree |
| I7 | Annualized score = sum ÷ full calendar years | moneta / nova agree |
| I8 | Parameters fixed, no sweeps | nova 2026-11-03 confirmed |
| I9 | Right-hand side = constant or registered feature column; feature arithmetic forbidden | nova 2026-11-03 confirmed |
| I10 | Compiled SQL past-only | moneta / nova agree |
| I11 | Local OCI mirrors (`data/` `strategies/` `runs/` **`alpha/`**) are rebuildable and **live outside the repository by default** (B13) | Lyra new |
| I12 | Credentials never in git / never in run reports | Lyra new |
| I13 | Feature computation change → FEATURE_VERSION + 1 | moneta / nova agree |
| I14 | Trade-semantics change → must update I1-I7 table + decision doc | Lyra new |
| I15 | git contains **no** alpha paths: all of `alpha/`, any direction-folder contents under `strategies/`, all of `runs/` | `0001` new |
| I16 | core never imports any specific alpha module (only the generic load point) | `0001` new |
| I17 | OCI files are **two-tier**: **(a) Immutable** (`data/**`, `runs/**`, `strategies/**/vNN.yaml`, `alpha/features/**`) — same path + same sha256 idempotent, different sha256 → error; **(b) Append-only** (`strategies/**/hypothesis.md`, `lessons.md`, `index/*.json`) — content may move forward (new ⊇ old), `push` validates superset, else error (B9 two-tier rule) | `0001` new |

## 5. Boundaries (vs moneta / nova)

| Boundary | moneta | nova | lyra |
|---|---|---|---|
| Strategy language | YAML | YAML | **YAML** (feature-vs-feature relaxed) |
| Parameters | swappable (`run_matrix.py` 3 cost tiers) | fixed | **fixed** |
| Feature count | 305/270 columns | ~20 registered | **~20 registered + alpha extension point** |
| OOS gate | yes (`oos_token.py`) | no | **no** |
| SHA256 directories | no | yes | **no** |
| FROZEN_CORE | no | yes | **no** |
| OCI pull | yes (`extract_oci.py`) | no | **yes** (core feature) |
| OCI push | no | no | **yes** (core feature) |
| Alpha boundary | none | none | **yes** (OCI is source of truth) |

## 6. Technology choices

| Dimension | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Consistent with moneta / nova; TA-Lib wheel available |
| Data engine | DuckDB | Native Parquet; past-only SQL expressive enough |
| Feature computation | NumPy / pandas + TA-Lib | Standard; TA-Lib's PSAR/Supertrend are reference implementations |
| Strategy expression | YAML (PyYAML) | Consistent with moneta / nova |
| OCI client | `requests` + PAR URL | PAR URLs carry their own signed token; zero client-side credentials; **OCI SDK not introduced (M3 rejected, 2026-11-11 user ruling)** |
| Tests | pytest | Consistent with moneta / nova |
| Packaging | `pyproject.toml` + `requirements.lock` | Consistent with nova; lock file pins all transitive deps |
| Lint | ruff | Consistent with nova |

## 7. Directory layout (target state)

```
lyra/
├── README.md
├── LICENSE
├── AGENTS.md
├── pyproject.toml
├── requirements.lock
├── .gitignore
├── .github/workflows/checks.yml
├── config/
│   ├── config_example.yml
│   └── config.yml              (gitignored)
├── docs/
│   ├── background.md           + background.en.md
│   ├── requirements.md         + requirements.en.md
│   ├── hld.md                  + hld.en.md        ← this doc
│   ├── open-questions.md       + open-questions.en.md
│   ├── decisions/
│   │   ├── TEMPLATE.md         + TEMPLATE.en.md
│   │   ├── 0001-repo-and-oci-split.md (+ .en.md)
│   │   ├── 0002-ohlcv-data-sync.md    (+ .en.md)  (complete)
│   │   ├── 0003-feature-builder.md    (+ .en.md)  (v1.4 implemented)
│   │   ├── 0004-yaml-compiler.md      (+ .en.md)  (implemented 2026-11-08: validate/compile + 28 tests)
│   │   ├── 0005-trade-engine.md       (+ .en.md)  (implemented v0.4, batch-3 disposition done #84, final basis → 0006/O17)
│   │   ├── 0006-metrics-and-runner.md (+ .en.md)  (implemented v2, #87 self-check/adversarial dispositioned)
│   │   ├── 0007-oci-push-and-backup.md(+ .en.md)  (implemented: OCI sync + R12 workflow, #94)
│   │   ├── 0008-migration-and-regression.md (+ .en.md) (pending)
│   │   └── 0009-polish.md               (+ .en.md)  (✅ implemented, 2026-11-11)
│   └── proposals/
│       ├── oci-alpha-layout.md  (+ .en.md)
│       ├── vectorbt-and-multi-ai-strategy-search.md (+ .en.md)
│       ├── 2026-11-08-vectorbt-eval-and-multi-ai-v2.md (+ .en.md) (source draft)
│       ├── 2026-11-08-vectorbt-multi-ai-consolidated.md (+ .en.md) (synthesis, awaiting ruling)
│       └── alpha-boundary.md    (+ .en.md)
├── src/lyra/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── common.py
│   ├── data.py                 ← R6
│   ├── features.py             ← R3
│   ├── catalog.py              ← R3.1
│   ├── indicators.py           ← standard feature impl (Supertrend recursion, etc.)
│   ├── compiler.py             ← R2
│   ├── config.py               ← R7 (config.yml parsing)
│   ├── trades.py               ← R4
│   ├── metrics.py              ← R5
│   ├── runner.py               ← R5
│   ├── oci.py                  ← R7 (pull/push/backup)
│   └── doctor.py               ← lyra-doctor
├── strategies/
│   └── examples/               ← open-source examples (alpha all in OCI)
│       ├── trend_hold.yaml
│       ├── ema_pullback.yaml
│       └── mean_reversion.yaml
├── tests/
│   ├── test_data.py
│   ├── test_features.py
│   ├── test_compiler.py
│   ├── test_trades.py
│   ├── test_metrics.py
│   ├── test_oci.py
│   └── fixtures/
└── scripts/
    ├── check_semantics.py
    └── research_round.py
```

## 8. Rollout order (feature-by-feature) — **single source of truth**

> Any description of build order in the README or background defers to
> this section; order changes are made **here only** and logged in the
> revision history.

One feature = one commit = one decision doc = one test set. **Before**
advancing, the decision doc (`docs/decisions/TEMPLATE.md`) must be
written. The decision doc must answer: what / why / boundaries /
invariants / tests / rollback.

**Why 0002 comes before 0003**: data sync is Lyra's primary function
(R7 / HLD §1); the data channel must exist before core components can
consume real data. 0003-0006 are proven on fixture data, so they are not
blocked by this ordering.

| # | Feature | Decision doc | Status |
|---|---|---|---|
| 1 | repo + OCI split | `0001-repo-and-oci-split.md` | ✅ written |
| 2 | OCI pull + clean + aggregate | `0002-ohlcv-data-sync.md` | ✅ complete (2026-11-07, real data end-to-end + Batch-01 (2026-11-07) adversarial review D1–D6 all fixed, v1.1) |
| 3 | Feature builder (standard + alpha extension point) | `0003-feature-builder.md` | ✅ core implemented (**146 features**: 0008 three-ruling 134→143 + prior12 window family 143→146, **FEATURE_VERSION=6**; pandas-ta-classic control + 107+ tests; alpha extension point `load_from` implemented) |
| 4 | YAML compiler (incl. feature-vs-feature) | `0004-yaml-compiler.md` | ✅ **Signed off (#76, 2026-11-08)**: after Batch 2 disposition, 50/50 focused and 157/157 repository tests pass; the new validation causes zero regressions across 169 existing strategy YAMLs. O16 corpus compatibility remains in 0008. |
| 5 | Trade engine (2% stop / next-open / costs) | `0005-trade-engine.md` | ✅ **Implemented + batch-3 review disposition complete (per #83 finding + #84 engine-side landing)**: `simulate()` in `lyra/trade_engine.py` is a Python API for the runner; a standalone CLI command is not required, and the user-facing `lyra run --strategy` belongs to 0006. #83 reproduced batch-3 H1/M1/M2 (calendar-day financing 7% vs 5% trading, `bars_held` not a day count across timeframes, silent zero on mixed tz); **#84 accepted and landed engine-side support**: added the `trading_days` param (caller supplies the R4/O15 trading-day count) + `_day_count` fail-closed (invalid time/override raises, not silent 0 financing) + 3 regression tests — **30/30 focused**, **187/187 repository** green; default keeps nova's natural days to preserve the cross-check (known divergence). **Final financing basis is finalized in 0006 (O17)**; O15 stays closed. (Note: the flat `trading_days` scalar was superseded in batch-4/C2/#88 by the per-trade counter `trading_days_for(entry, exit)`.) |
| 6 | Metrics + runner | `0006-metrics-and-runner.md` | ✅ **Implemented + self-check/adversarial self-check dispositioned (#87)**: `lyra/metrics.py` (R5 frozen set: annualized=Σnet/calendar-years(365.25), win_rate, expectancy, avg_bars_held, per-month rows; **forbids** Sharpe/Sortino/profit factor/CAGR/HWM/portfolio synthesis) + `lyra/runner.py` (`lyra run`/`lyra report`: 0004 SQL + per-instrument OHLC alignment + 0005 `simulate` + R5 metrics + report + artifacts + I5 reproducibility + I16 isolation) + `lyra/cli.py` run/report; **19 new**, full suite **206/206** green, pyflakes clean. **R12 interactive workflow (track/context/compare/merge) moved out of 0006 → 0007** (0006 D1). **O17 closed**: default per-trade calendar days; **batch-4 C2 (#88)**: the O15 trading-day compliance exit was refactored from the flat `--financing-days` (removed) to a per-trade counter `trading_days_for(entry, exit)`. 0006 decision doc v2, Current state refreshed (bilingual). |
| 7 | OCI push + backup (+ R12 workflow) | `0007-oci-push-and-backup.md` | ✅ **Implemented (2026-11-10, #94)**: `lyra/oci_push.py` (I17 classifier / plan / dry-run / `--force-push` exempts immutable sha conflicts only / append-only **line-subsequence** verbatim preservation (C2 tightened) / unclassified fail-closed / I19 redaction / D4 no-target error) + `lyra/workflow.py` (tracks baseline freeze / **per-track 8-active cap** (`MAX_ACTIVE_BRANCHES_PER_TRACK`, the only machine gate) / prune / new-version reusing 0004 `parent`+`parents`+`driven_by_lesson` / context track isolation + 0006 metrics summary / compare read-only / merge adds candidate only + parent sha256 provenance (C6) / synthesize writes `reviews/` only); 12 CLI commands (push/backup/sync/list/push-strategy/push-direction/**push-runs**/tracks/context/new-version/compare/merge/synthesize); **O2 canonical runs path `runs/<direction>/<track_id>/<run_id>` landed via `push-runs`**, O15 `backup`/`sync` alias; C1 (transport `.put` gate)/C2 (line-subsequence)/C6 (sha256 provenance) implementation gates landed. **#95 self-check + adversarial verification fixed 2 bugs** (I20 idempotent skip on real md5 listings + new-version/merge branch-name tightened to `vNN` self-consistency). 38+22 tests green, full suite 287/287, pyflakes clean. **Awaiting real-bucket end-to-end acceptance (R10) + code-level adversarial review.** |
| 8 | Corpus migration + regression (**scope revised 2026-11-10, #99**: "332 strategies" corrected to 17 hand-written + 146 campaign snapshots; **user's three final rulings 2026-11-11, #100**) | `0008-migration-and-regression.md` | ✅ **Regression complete (decision doc v0.3)**: (a) land the O16 20-gap ruling (**B-class 10 renamed** to the nova canonical names, no alias table + **C-class 9 new**; `rsi_14` not added — rerun with rsi_12 as a TODO; ATR basis 24→12; see the 0008 D table) → 0003 v1.5 (FEATURE_VERSION 4→5, registry 134→143); (b) migrate the 12-direction formal library into `strategies/directions/` + regression; (c) `strategies/temp/` (146 nova campaign + 132 moneta S-series read-only index) gate — **not** part of the 0008 regression set. |
| 9 | Polish (README / CI / config_example) | `0009-polish.md` | ✅ **Implemented (2026-11-12)**: `lyra doctor` (two-level severity) / README rewrite / pyproject pins Python 3.12 + `requirements.lock` / CI (py3.12) / D1–D6 parked findings landed / 11-12 batch-1 review disposition (H3 gate + H4 slot hard-fail + H5 install + M1–M4) / **327 tests all green** (#110 + review disposition). |
| 10 | temp/ AI triage | `0010-temp-triage.md` | ⬜ **Pending (new 2026-11-10, #99)**: AI scans `strategies/temp/` (146 nova campaign + 132 moneta S-series), assigns each a direction + `promote`/`drop`/`archive` verdict; `promote` entries enter `directions/<family>/vXX/` via the 0007 track flow. Depends on 0008's B/C feature-gap closure. |

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft. |
| 2026-11-05 | 0.2 | §8 declared the **single source of truth** for build order; added the rationale for "why 0002 comes before 0003"; README / background now reference this section. |
| 2026-11-05 | 0.3 | §2.3 removed the "No strategy generation (future campaign)" conflict row; added a "Strategy evolution" block (context / new-version / compare / merge / push-direction) aligned with R12 + version tree + AI-free crossover; §7 decision-tree now includes 0008 and 0009 in both languages (ZH was missing 0008, EN was missing 0009, and 0007 misused └──); **§4 invariant table completed with I15-I17** (previously only listed to I14, but AGENTS/0001 both cite I15-I17 — hld as the skeleton should be self-consistent). |
| 2026-11-06 | 0.4 | Batch-2 adversarial review fixes: I17 made **two-tier** (Immutable/Append-only, L1); I11 adds `alpha/` (L5). |
| 2026-11-07 | 0.5 | **0003 v0.7 alignment** (hld sync after accepting batch-02 red-team D1/D5/D6/D3): ① §2.1 market-layer cache path changed from the historical-draft `data/market/<m>/<snapshot_id>/` to 0002's actual single-file external tables `ohlcv_5m/ohlcv_5m.parquet` / `ohlcv_1h/ohlcv_1h.parquet` (0002 D4 deprecated directory-level snapshots; the hld early wording is a draft — marked "defer to 0002"); ② §2.2 features component: publish path → `data/features/<m>/<instrument>.parquet` single file, version into Parquet metadata, the "snapshot id monotonic integer" invariant → "derived string in metadata", Warm-up NULL tightened to 0003 F2; ③ §3 data-flow diagram synced (bronze → ohlcv_5m/1h single-file → features single-file). Note: §4 L148/155/179 **OCI push (0007) snapshot id** is 0007's still-undefined semantics — **not** changed here (0007 not yet written; avoids overstepping into 0007's scope), deferred to the 0007 decision |
| 2026-11-08 | 0.7 | **User rulings synced (#73)**: 0004 status changed to "finalized (2026-11-08 ruling), pending scheduling"; R12 AI tracks + 8-per-track cap + VectorBT dropped — see requirements v0.16 / oci-alpha-layout §2.3 / consolidated §9 (not expanded here). |
| 2026-11-08 | 0.6 | Synced current **0003 v1.4 / 107 tests**; changed 0004 status to "proposal drafted, awaiting user review, not implemented"; listed the VectorBT / multi-AI strategy-search evaluation in the §7 proposal tree (bilingual pair). |
| 2026-11-08 | 0.7 | Added the v2 source draft and this synthesis to the §7 proposal tree as bilingual pairs; source proposals are preserved and the synthesis awaits the user's ruling. |
| 2026-11-08 | 0.8 | **0004 implemented (2026-11-08)**: `lyra/strategy_schema.py` + `lyra/compiler.py` + `lyra/cli.py` (`validate`/`compile`) + `tests/test_compiler.py` (28 tests green, incl. live DuckDB temporal assertions N−1/N/N+1 / NULL gate / after_event exact-age / param invariant). Adversarial self-check fixed DuckDB 2.0 inline-window, temporal param-desync, and exit.stop_loss_pct widen (3 spots). §8 0004 status → "implemented"; the 332 corpus regression is in 0008 (see open-questions O16 — 20 missing features await user decision). |
| 2026-11-08 | 0.9 | Synced §8 stage status per ACTION_LOG #77: updated 0004 to the 50-focused / 157-repository-test verification after #76; marked 0005 in progress (decision, code, and test drafts visible in the worktree, not signed off) and recorded the calendar-day financing conflict with R4 and the outstanding golden-test gate. |
| 2026-11-08 | 0.10 | **0005 implemented (v0.2)**: `lyra/trade_engine.py` + `tests/test_trade_engine.py` (23 tests green); field-for-field cross-check vs nova `trades.simulate` diff=0 (§5 documents 3 deviation rows: exit_time_precision dropped / signal_time uses bar open / **financing natural days vs R4·O15 trading days**); self-check + adversarial 14/14 pass; §8 0005 status → "implemented"; registered **OPEN O-0005-1** (financing day count, awaiting user option 1/2/3, default option 2 keeps nova natural days). |
| 2026-11-08 | 0.11 | **0005 self-check + detailed adversarial self-check executed (v0.3)**: probes P1–P9 (boundaries / priority / direction-specific exit / re-entry) all pass; fuzz 300 cases / 381 trades vs nova — 0 real mismatches (119 cost/net-only diffs all explained by O-0005-1; second fuzz with financing=0 shows 0 mismatches); 4 new adversarial regression tests added (pending_exit vs inside-stop order ×3 + exit_long direction isolation), tests 23→27, repository 180→184 green; §8 0005 status synced (v0.3, 27 tests, self-check 9/9 + adversarial 10/10 executed). |
| 2026-11-08 | 0.12 | Per ACTION_LOG #82, assigned unimplemented commands to their existing stages: 0005 clarifies `simulate()` as a runner API (no standalone CLI required); 0006 owns `lyra run`/metrics/report and the R12 workflow; 0007 owns OCI commands; 0008 owns the O16-dependent 332 regression; 0009 owns doctor and the README command guide. O-0005-1 is promoted to open-questions O17. |
| 2026-11-08 | 0.13 | Synced the 0005 batch-3 adversarial review per ACTION_LOG #83: implementation/tests exist and 27/27 focused + 184/184 repository tests pass, but calendar-day financing violates R4/O15 (7% vs 5% across a weekend). §8 now marks 0005 as implemented with financing semantics to fix; implement the trading-day count and boundaries before 0006 locks cost semantics unless the user explicitly supersedes O15. |
| 2026-11-08 | 0.14 | Synced the 0005 batch-3 review disposition per ACTION_LOG #84 (#83 finding → #84 engine-side landing): accepted H1/M1/M2 — added the `trading_days` param (caller supplies the R4/O15 trading-day count), `_day_count` fail-closed (invalid time/override raises, not silent 0 financing), and `bars_held` explicitly documented as not a day count; 3 regression tests, focused 27→30, repository 184→187 green, pyflakes clean; default keeps nova's natural days to preserve the cross-check (known divergence). §8 0005 now "implemented + batch-3 disposition complete"; final financing basis finalized in 0006 (O17); O15 stays closed. |
| 2026-11-09 | 0.15 | Per ACTION_LOG #87, synced 0006 metrics + runner complete: `lyra/metrics.py` (R5 frozen set, forbids Sharpe/profit factor/CAGR/HWM/portfolio synthesis) + `lyra/runner.py` (`lyra run`/`lyra report`, 0004 SQL + per-instrument OHLC alignment + 0005 `simulate` + reproducible artifacts I5 + per-instrument isolation I16) + `lyra/cli.py` run/report; 19 new, full suite 206/206 green, pyflakes clean; R12 interactive workflow moved out of 0006 → 0007; O17 closed (default per-trade calendar days, `--financing-days` override). §8 0006 status "pending"→"implemented". |
| 2026-11-08 | 0.16 | Per ACTION_LOG #88, synced the 0006 batch-4 adversarial review disposition (8 findings: **accept×7 landed** C1/C2/M1/M2/M3/m1/m2 + **hold×1** m3 annotation-only + **reject×0**): **C1** OHLC projection + bars taken from signal rows; **C2** financing counting refactored from the flat `--financing-days` (removed) to a per-trade counter `trading_days_for(entry, exit)` (`TradingDaysCounter`, default `None` = natural days preserving the nova cross-check, manifest/run_id carry `trading_days_basis`); **M1** strategy expression value-domain gate (boolean/ordinal/numeric mismatch fail-closed, `_parse_value_rhs` 4-tuple); **M2** `_quote` strips the `mid_` prefix to use real `bid_o/ask_o`; **M3** `exit.feature` strictly allows only `when`; **m1** end_of_data exit timestamp taken at bar close; **m2** `simulate` rejects mixed instruments. 13 new regressions, full suite **219/219** green, pyflakes clean; nova cross-check `financing=0` → 0 diffs (400 cases/1434 trades), the 176 stop_loss 1-bar diffs with financing≠0 are the pre-existing O-0005-1-class data-model divergence (not a batch-4 regression). |
| 2026-11-10 | 0.17 | Per ACTION_LOG #92, synced **0007 decision draft v0.1 written** (user scope ruling: OCI sync layer + full R12 interactive workflow): §8 0007 row "pending"→"decision draft v0.1 written"; §7 dir tree 0007 status synced. **0007 scope**: Part A `lyra push`/`backup`(`sync` alias)/`list` + `push-strategy`/`push-direction` (I17 two-tier immutable/append-only + I19/I20 idempotency & redaction); Part B `tracks`/`context --track`/`new-version --branch`/`compare --siblings`/`merge`/`synthesize` (track = research identity, no machine-gate change; per-track 8 cap; read-only synthesis, no auto-write-back); invariants I18/I21/I22; O2 runs layout = `runs/<direction>/<track_id>/<run_id>`, O15 `backup`/`sync` alias. 332-compat still in 0008. **§4 L148/155/179 OCI push snapshot-id semantics still not changed this round** — 0007 has set the push canonical path to `runs/<direction>/<track_id>/<run_id>` (0007 D7); snapshot-id semantics to be refined in 0007's implementation. Awaiting implementation + adversarial review. |
| 2026-11-10 | 0.18 | Per ACTION_LOG #94, synced **0007 implemented**: added `lyra/oci_push.py` + `lyra/workflow.py`, 12 CLI commands (push/backup/sync/list/push-strategy/push-direction/push-runs/tracks/context/new-version/compare/merge/synthesize). I17 two-tier gate (immutable sha conflict needs `--force-push`; append-only tightened to **line-subsequence** verbatim preservation — C2 landed), unclassified fail-closed, I19 redaction, D4 no-target error; per-track 8-active cap (`MAX_ACTIVE_BRANCHES_PER_TRACK`, 0007's only machine gate), track baseline freeze, new-version reuses 0004 provenance fields, compare/synthesize read-only, merge adds candidate only + parent sha256 provenance (C6 landed). **O2 canonical runs path landed via `push-runs`**. Full suite 228→283 green, pyflakes clean. Awaiting real-bucket end-to-end acceptance (R10) + code-level adversarial review. |
| 2026-11-10 | 0.19 | Per ACTION_LOG #95, synced **0007 self-check + adversarial verification fixed 2 real bugs**: ① I20 idempotent skip broken on real PAR listings (md5-only, no sha256) — old code compared remote md5 to local sha256 (never equal), so unchanged files all misfired conflicts; fixed `_same_object()` (sha256 direct / md5↔md5 via `oci_client._md5_matches` / size fallback). ② `new-version`/`merge` output `b0.yaml` classified unclassified (self-produced file unpushable) — branch names tightened to `vNN`, merge defaults to next free vNN. +4 regression tests, full suite 283→287 green, pyflakes clean. |
| 2026-11-10 | 0.20 | Per ACTION_LOG #96, synced **0007 batch-2 adversarial review disposition** (`docs/reviews/对抗性review-2026-11-10-批次2.md` disposition record; 14 findings **13 accepted / 1 held (M3) / 0 rejected**): **H1** push-strategy/push-direction silent no-op → stage a direction slice into canonical `strategies/<direction>/...` (`push-direction` also folds in its runs slice), then push through the I17 classifier; **H2** no-digest size-equality now fails closed (#89 R1); **H3** `redact_par_url` keeps only `scheme://host` + new `redact_in_message` scrubs exception text; **H4** new `validate_ident` (direction/track/run_id single-component) + `plan_push` rejects symlinks / escape paths; **H5** sibling/cross naming unified to `^v\d+[a-z]*$` (`v02a/v04ab`) across workflow and the I17 classifier; **H6** `render_context` self-contained (full hypothesis+hash, feature listing, full YAML of each active branch, per-instrument run metrics) + per-track lessons at `tracks/<direction>/<track>.lessons.md`; **H7** strict branch-identity match + keep all per_instrument; **H8** push-runs validates `manifest.artifacts` presence + sha256, rejects files outside the manifest, writes `run_provenance.json`; **H9** `_push_all_roots` adds a second pass over the default `~/.lyra/runs` (conflict-safe); **H10** track index is now a JSONL event log (create/activate/prune, verbatim line-superset); **M1** frozen baseline uses the real `catalog.duckdb`; **M2** `backup`/`sync`/`push` defined push-only (L169 wording synced); **M4** within a run `manifest.json` is published last, docs no longer describe per-object PUT as a transaction. **M3 SDK auth fallback held** (pending R10 real bucket). Full suite 287→**302** green, pyflakes clean. R10 real-OCI-bucket end-to-end acceptance still not executed; this is not 0007 final sign-off. |
| 2026-11-10 | 0.21 | **0008 scope revision (#99, user ruling "proceed with the 5 points")**: verified that "332 strategies" was a wrong count — moneta has no strategy YAMLs (132 S-series are Python libs + 200 research batch is a 50×2 template Cartesian product with 0 promotions); "332" is actually the nova repo's total YAML *file* count (17 hand-written + 146 campaign snapshots + 169 other runs YAMLs). §8 0008 row rescoped to: land the O16 20-gap ruling (B-class aliases 10 + C-class new 10) → 0003 v1.5 + 12-direction formal library migration & regression + `strategies/temp/` gate (146 nova campaign + 132 moneta S-series read-only index, **not** part of the 0008 regression set); new **0010 temp/ AI triage** row (promote/drop/archive; promote goes through the 0007 track flow). `background.md` erratum added (zh+en). `strategies/temp/` skeleton landed (README zh+en + 2× `_index.json`). |
| 2026-11-11 | 0.22 | **0008 user's three final rulings landed (#100)**, superseding the v0.1 pre-filled recommendations: ① B-class 10 **renamed** to the nova canonical names (no alias table; moneta names unmapped — they decom with moneta); ② `rsi_14` **not added** — the 3 affected direction files (momentum_exhaustion/pullback_reentry/session_temporal) rewritten rsi_14→rsi_12 and rerun (TODO executed during migration, verbatim substitution; the root-level hand-written `ema_pullback.yaml` is outside the 12-direction set); ③ ATR normalization basis **24→12** (replacing the corpus' ATR(14); K6 basis change; C-class distance features on the same basis). C-class 10→9 (`psar/supertrend_direction` + 4 flips + `ema_alignment_6_24` + 2 distance features). Registry 134→**143**; FEATURE_VERSION 4→**5**. The 12-direction formal library is now at `strategies/directions/<family>/v01.yaml`; `lyra validate` passes 12/12. 0008 decision doc promoted to v0.2 final-rulings (ZH+EN). |
| 2026-11-11 | 0.23 | **0008 regression closeout (#100 part 2)**: 12 directions × 21 instruments × 1h `lyra run` all OK (feature tables rebuilt for all 21 instruments under v1.5); nova cross-check (trend_continuation USD_JPY, 902 common entries): direction/exit_reason **100% match**, entry_price 97% match; residual differences attributed to **data-layer bar-coverage disagreement** (overlapping OHLC identical, coverage sets differ) → new **O18** parked (pending data owner; does not block acceptance); rsi_12 drift quantified (momentum_exhaustion USD_JPY: lyra 177 trades −0.0271 vs nova rsi_14 168 trades −0.0602). 0008 decision doc v0.2→**v0.3**. |
| 2026-11-11 | 0.24 | **#101/#1.48 synced**: ① **M3 final = rejected** (user ruling 2026-11-11: SDK auth fallback not implemented; PAR scheme fully covers it; batch-2 final counts 13 accepted / 1 rejected / 0 held) — §2.5 dependency table drops the `oci` SDK row, §8 0007 row now "rejected"; ② **O18 closed** (deep-dive report archived to `docs/decisions/0008-bar-coverage-analysis.md`: raw byte-identical, difference 100% from nova's `source_bars<60` filter + display-timezone artifact; **user ruling: lyra's bar set is canonical, nova-side results entering lyra must be recomputed**); ③ OCI bucket list delivered (4 domains, 4 buckets + permissions; PAR without Delete; data stores `raw_zips/` only) — R10 acceptance runs once the user creates the buckets. |
