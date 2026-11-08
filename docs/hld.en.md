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
- Aggregate: 1m → 5m / 60m (complete-bucket policy; partial buckets
  dropped and counted).
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
- `lyra backup`: one-command sync (pull + push + conflict detection).
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
| OCI client | `requests` + PAR URL (default); `oci` SDK (optional) | PAR URL is simplest; SDK for push to avoid signing |
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
│   │   ├── 0004-yaml-compiler.md      (+ .en.md)  (finalized 2026-11-08; pending scheduling)
│   │   ├── 0005-trade-engine.md       (+ .en.md)  (pending)
│   │   ├── 0006-metrics-and-runner.md (+ .en.md)  (pending)
│   │   ├── 0007-oci-push-and-backup.md(+ .en.md)  (pending)
│   │   ├── 0008-migration-and-regression.md (+ .en.md) (pending)
│   │   └── 0009-polish.md               (+ .en.md)  (pending)
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
| 3 | Feature builder (standard + alpha extension point) | `0003-feature-builder.md` | ✅ core implemented (v1.4: 134 features/6 indicator families + pandas-ta-classic control + 107 tests; alpha extension point `load_from` implemented) |
| 4 | YAML compiler (incl. feature-vs-feature) | `0004-yaml-compiler.md` | 🟡 **Finalized (user ruling 2026-11-08, incl. consolidated §5 scope)**; pending scheduling |
| 5 | Trade engine (2% stop / next-open / costs) | `0005-trade-engine.md` | ⬜ pending |
| 6 | Metrics + runner | `0006-metrics-and-runner.md` | ⬜ pending |
| 7 | OCI push + backup | `0007-oci-push-and-backup.md` | ⬜ pending |
| 8 | 332-strategy migration + regression | `0008-migration-and-regression.md` | ⬜ pending |
| 9 | Polish (README / CI / config_example) | `0009-polish.md` | ⬜ pending |

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
