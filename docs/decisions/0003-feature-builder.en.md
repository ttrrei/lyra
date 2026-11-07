# 0003 — Feature Builder (standard features + alpha extension point)

> **中文**: [0003-feature-builder.md](./0003-feature-builder.md)

## Meta

| Field | Value |
|---|---|
| ID | `0003` |
| Title | Feature Builder (standard features + alpha extension point) |
| Status | **Proposal** (awaiting user approval) |
| Owner | `ttrrei` |
| Created | `2026-11-07` |
| Related proposal | — |
| Related requirements | `docs/requirements.en.md` §R3 (R3.1 standard features / R3.2 alpha extension point / R3.3 causality) |
| Related HLD | `docs/hld.en.md` §2.2 (features component), §8 (build order, step 3) |
| Supersedes | — |

## 1. Problem

Strategy (0004 compiler) right-hand values can only be "constants or
registered feature columns" (I9), so before 0004 there must exist a
feature wide table with **deterministic column names, deterministic
semantics, and reproducibility**. This feature delivers: **from the
bronze / 5m / 1h Parquet produced by 0002, compute all standard
features defined in R3.1, produce "one Parquet per instrument"
feature wide tables, and leave a clean alpha feature extension point
(R3.2).**

It does NOT solve "which feature combinations make good strategies" —
that is 0004/0005+ and the in-direction strategy iteration (the user's
core ask: iteration depth, not feature breadth).

## 2. Background

- **moneta**: 305/270-column feature wide tables
  (`load_data.py` + feature scripts); features are strongly coupled
  with strategies, column names are the contract, but there is **no
  registration concept** — adding a feature means adding a column,
  visible to all strategies implicitly, with no versioning and no
  golden tests.
- **nova**: ~20 registered features (YAML references column names),
  introduces `FEATURE_VERSION` and "parameters fixed at registration"
  (I8), but feature computation is scattered across Python code with
  no contract card and no golden-test requirement. One of the lessons
  behind "strategy search had no substantive progress" was exactly a
  **too-wide feature surface without validation** (see §2.3).
- **lyra already has**: 0002's bronze/5m/1h Parquet (21 instruments,
  2020-01-02→2026-11-06 + 2019-11/12 backfill not yet folded in),
  `lyra/catalog.py` (DuckDB catalog + 3 views),
  `open_limited_duckdb` (memory/thread/temp-dir limits).
- **Related open questions**: O13 (Active Branch Cap = 8, used by
  0004; not relevant to this feature).

### 2.3 moneta / nova lessons and counter-examples (filled after read-only scan, 2026-11-07)

> Only **design decisions and lessons** are absorbed — never code
> structure. Sources: moneta `library/*.py` + `docs/indicators.md`
> §8 + `docs/indicator_research_20261031_report.md`; nova
> `src/nova/catalog.py` + `features.py` + `indicators.py`.

**Adopted (already in the plan)**:

1. **Supertrend path-dependence / keep NULL warm-up** (moneta
   `library/supertrend.py` implementation + comments / nova
   `indicators.py` same origin, now reproduced bar-for-bar by
   `talib.SUPERTREND` — see K1): the canonical construction = ATR
   basic bands + final band ratcheted against the **previous bar's
   close** + direction flip when close crosses the active band;
   **path-dependent**, warm-up does not guarantee convergence — so
   lyra computes from the **source head** and keeps NULL warm-up
   (K4), and does **not** adopt moneta's "WARMUP_DROP row deletion"
   (see counter-example 1). The moneta/nova self-implementation
   headers' "TA-Lib ships no Supertrend" is a **stale-version
   misconception** (the real TA-Lib 0.8.2 has `SUPERTREND`), so lyra
   uses the library implementation with the self-implementation as a
   golden cross-anchor, while still adopting the **path-dependence /
   keep-NULL-warm-up** discipline.
2. **Pure-NumPy boundary for `indicators`** (moneta
   `library/__init__.py`: "NumPy in, NumPy out; no parquet, no
   DuckDB, no network"): indicator functions have zero framework
   dependencies → pure functions, easy golden tests (feed arrays
   directly), independently versionable. Adopted as part of K1.
3. **nova's registry metadata** (`catalog.py`
   `definition(kind, unit, warmup_bars, family)`, kind ∈ {VALUE,
   STATE, EVENT}): warm-up row count is **registry data**, not
   implicit behavior → the 0004 compiler can reference it statically;
   the F2 "NULL after warm-up = bug" assertion can use it directly.
   Merged into §3.1 K3.
4. **Research-feature boundaries exclude the current bar** (nova
   `features.py:_research_features` header: "Boundaries and activity
   baselines exclude the current bar"): prior-24 high/low/range,
   relative volume, path efficiency windows all `shift(1)` before
   opening, preventing the current bar from polluting its own
   structural features. Merged into §3.4.
5. **Three hardest of moneta's six quality gates**
   (`docs/indicators.md` §8): Gate 1 causal truncation (truncated
   recompute, zero redraw, <1e-12), Gate 3 numeric bounds
   (RSI ∈ [0,100], ATR ≥ 0), Gate 4 singular-value tolerance (zero
   amplitude does not crash) — merged into the §5 test list.
   Gate 5 (dual-library parity) needs a second library; lyra does not
   introduce a second implementation, **not adopted** (over-engineering).
6. **utc_hour = UTC hour of the bar's opening** (nova `features.py`:
   "Session hour is the UTC hour of the bar opening, observable at
   the confirmation close") — the open time is **known** at close
   confirmation, causally safe. Merged into the §3.4 structural family.

**Counter-examples (lyra explicitly does NOT learn)**:

1. **moneta's "WARMUP_DROP deletes prefix rows"**
   (`library/supertrend.py` header admits: "dropping WARMUP_DROP rows
   reduces but does *not* eliminate the start-point dependence"):
   row deletion masks path dependence and breaks bar-time alignment.
   lyra = keep NULLs (K4/F2), aligned with nova.
2. **moneta P1 feature research: 2160 combinations, 0 promoted**
   (`docs/indicator_research_20261031_report.md`: "No tested output
   qualifies for promotion"): feature breadth alone does not produce
   strategy depth. lyra's boundary echoes this: **0003 only
   guarantees the R3.1 list is correct, reproducible, and
   compilable**; "which features carry information" is driven by 0005
   backtests + direction lessons — 0003 does no effectiveness
   screening (already in §3.2).
3. **moneta's 575-column Gold wide table**
   (`indicator_research_20261031_report.md` data table): 305/270-column
   wide tables are the product of "no registration, column name is
   the contract, all strategies see everything implicitly" — features
   added with no versioning and no golden tests. lyra's ~20
   registered features + FEATURE_VERSION + contract cards is a
   targeted convergence; we do not restore the wide table.
4. **nova's `close_ema60_distance_atr` uses `atr_14` (Wilder) while
   `close_sma24_distance_atr` uses `atr_sma_14`** (`features.py:
   compute`): mixing two ATR normalization bases within the same
   semantic family is **undefined behavior** (a reader cannot infer
   which basis applies to which feature). lyra decision: **all
   ATR-normalized features use `atr_wilder_14`** (Wilder is the
   industry-convention basis); `atr_sma_14` stays registered but
   only for explicit reference. (**v0.5 update**: with K8's grid
   discipline, the whole 14-window family retires → the
   normalization denominator uniformly becomes `atr_24`; the
   mixed-basis counter-example still stands.)

**Not applicable**: moneta's OOS token / frozen buckets / paired
week-block uncertainty (deprecated; hld §1 less-is-more); nova's
SHA256 snapshot directories (decided out in I11); moneta
`library/catalogue.py`'s median-stretch / log-OLS residual family
(moneta P1 research outputs, never promoted, not in lyra's R3.1).

## 3. Plan

### 3.1 What we build

**CLI**: `lyra features [--minutes 5 60] [--instrument <inst>]`
(**always recomputes, always overwrites** — aligned with 0002 A1's
"derived layers always recompute"; no "skip if present" derived cache,
otherwise a deleted/corrupted bronze would silently reuse stale
features; no `--force`).

**Compute core** (`lyra/features.py` + `lyra/indicators.py` + `lyra/registry.py`):
- input: ohlcv_5m / ohlcv_1h (0002-contract bronze / aggregate
  views; columns = `instrument, time, volume, mid_*, bid_*, ask_*`);
  **price basis = `mid_*` columns** (0002 bronze contract); the
  open/high/low/close in §3.4 are semantic shorthands for
  mid_o/mid_h/mid_l/mid_c;
- each standard feature = one registry record (K3); compute function =
  a pure-NumPy function in `indicators.py` or a vectorized
  composition in `features.py`;
- compute engine: see decision **K1** (standard indicators all from
  TA-Lib, incl. `talib.SUPERTREND`; window/structural via
  numpy/pandas vectorization);
- output: `data/features/<minutes>m/<snapshot_id>/
  <instrument>.parquet` (one file per instrument; columns = input
  OHLCV columns (K2 copy) + all registered feature columns), pandas →
  `pyarrow` writes the Parquet, row order = input row order (read
  `ORDER BY time`, same deterministic order as 0002 I18).

**Alpha extension point (R3.2)**:
- `lyra.features.load_from(directory)`: scans `*.py` in the
  directory; each module exposes a `register(registry)` function; an
  alpha feature = a contract card (module docstring, fixed schema:
  state variables / transition rules / seed / gap/flip / dependency
  columns) + a golden test in the same directory;
- core imports no specific alpha module (I16), only `lyra.features`;
  the alpha directory comes from `config.yml` `local.alpha`
  (gitignored, B13/I15);
- name conflict: an alpha name colliding with a core name →
  **error** (no override, no `_2` suffix — feature column names are
  the SQL right-value contract; silently renaming them would blow up
  only at strategy compile time).

**FEATURE_VERSION**:
- one integer, a module constant in `lyra/features.py`;
- any change to a registered feature's **compute semantics or
  parameters** → +1 (I13);
- the feature wide table's snapshot id = a **derived string** over
  `(market snapshot id, timeframe, FEATURE_VERSION, sha256 of the
  full registry parameter set, python/numpy/pandas version triple)`
  (not a monotonic integer — 0002 deprecated directory-level snapshot
  state machines; we align: derived values are reproducible and need
  no allocator). **TA-Lib's version is deliberately NOT in the
  snapshot id**: TA-Lib is the source of the indicator reference
  implementations; if its semantics change, the correct action is
  FEATURE_VERSION +1 (I13), not an implicit distinction via a version
  string — the snapshot id expresses "registry semantics", not a
  "third-party implementation fingerprint".

### 3.2 What we do NOT build

| Not doing | Why / owner |
|---|---|
| Parameter scanning | I8 fixed parameters; scanning belongs to in-direction iteration (0004+ strategy layer) |
| Feature composition / derived features (feature arithmetic) | Banned by I9; a new feature = a new registration |
| Feature effectiveness screening (which feature "carries information") | Not a 0003 acceptance criterion; driven by 0005 backtests + direction lessons |
| Pushing features to OCI | 0007 push (yml position already reserved by 0002) |
| Cross-timeframe features (e.g. a 5m feature using 1h columns) | Not in v1; R3.1 has none; avoid premature abstraction (a later need = a new direction) |

### 3.3 Key decisions

**K1 Compute engine (decided; second revision 2026-11-07:
Supertrend back to the library)**:
**Compute on the Python side only; standard indicators all come from
TA-Lib; DuckDB never computes features** —
- standard indicators (SMA / EMA / ATR / RSI / PSAR / **Supertrend**)
  use **TA-Lib** (validated across two generations by moneta
  `library/psar.py` and nova `features.py`: `talib.SAR/EMA/SMA/ATR/RSI`
  are both generations' reference implementations; py3.12 wheels
  exist; already chosen in hld §6);
- **Supertrend uses `talib.SUPERTREND` (built into TA-Lib 0.8.2), no
  longer self-implemented**: the moneta `library/supertrend.py` and
  nova `indicators.py` headers' "TA-Lib ships no Supertrend" is a
  **stale-version misconception** — the real TA-Lib 0.8.2 both
  generations lock does ship `SUPERTREND` (`timeperiod` +
  `multiplier`, output line + trend). **Verified with real data via a
  dual-library parity test** (SPX500_USD 1h, 5000 bars,
  `PER=24, multiplier=3`): the self-implementation and
  `talib.SUPERTREND` **match bar-for-bar 100%** (line
  max_abs_diff=0, direction 100% agreement), proving the same
  semantics; we therefore adopt the library implementation and use
  the self-implementation (moneta/nova reference) as a golden-test
  cross-anchor (see §2.3 adoption 1 + K7 rule 3);
- window/structural features (prior-24 / breakout / path
  efficiency / range position / ATR normalization) use
  **numpy/pandas vectorization** (`shift(1)` + `rolling`, same as
  nova `_research_features`; §2.3 adoption 4);
- `indicators.py` keeps the **pure-NumPy boundary** (§2.3 adoption
  2): NumPy in, NumPy out; no duckdb/pandas/framework imports;
- **no numba** (the v0.1 draft's "numba hard dependency" is
  voided): TA-Lib's C core covers recursive performance; hld §1
  less-is-more;
- **DuckDB's role**: in 0003 it only **reads input / COPY output**
  (the external-table pattern validated by 0002); it does not
  compute features — all compute semantics live on the Python side
  for golden tests and determinism (F4).

**K2 Wide-table granularity (decided)**: one feature wide table per
**timeframe × instrument** (same layout as the market layer); each
file copies the raw OHLCV columns (copy, not reference) → the 0004
compiler reads **a single file** and is self-sufficient, no join to
the market layer. Cost: OHLCV column duplication (~1.2× size) —
aligned with moneta's proven "self-sufficient wide table" practice,
bought for 0004's SQL simplicity.

**K3 Registry shape (decided)**: a pure Python dict
(`lyra/registry.py`), not a DB (the registry is **code**, shipped
with the commit; git is the version history — stronger than moneta's
"scattered column names", simpler than nova's "YAML feature
declarations"). Each registry record carries **nova-style
metadata** (§2.3 adoption 3):
`(name, kind ∈ {VALUE, STATE, EVENT}, unit, warmup_bars, family,
params)` — `warmup_bars` is the data source for the F2 assertion
(NULL after warm-up = bug); `kind/unit` serve the 0004 compiler's
static right-value checks.

**K4 warm-up (decided)**: features emit **NULL** during warm-up
(no zero-fill, no row truncation); the `held_for`/`within`
N-non-NULL truth rule is implemented in the 0004 compiler; 0003 only
guarantees consistent NULL semantics (R3.3).

**K5 21-instrument universality (decided)**: the same feature with
the same parameters runs **point-for-point identically** across the
21 instruments (universal; HLD §1 spirit); a shorter dataset giving
a longer warm-up is allowed (different NULL counts); a different
algorithm is not.

**K6 ATR normalization basis (decided; §2.3 counter-example 4; v0.5
re-grid per K8)**: all "distance/displacement normalization"
features (`shift6_atr`, `bar_range_atr`, the ATR variants of
`prior24_width`, etc.) **uniformly divide by `atr_24`** (Wilder
smoothing, 24-bar window, grid default point); **no mixing** of
different ATRs within one semantic family (nova's mixing of
`atr_14`/`atr_sma_14` is undefined behavior; we do not learn that).

**K7 Self-implemented feature management (decided; v0.5 new,
v0.6 revised to a conditional guard; user request)**:
**0003's standard-feature set contains NO self-implemented
implementation** — Supertrend is now back to `talib.SUPERTREND`
(K1, verified by a real-data dual-library parity test), so this
rule is **not triggered** under 0003's current list. It is kept as
a **conditional guard**: any future feature NOT implemented by a
third-party library (alpha self-implementation or core
self-implementation) must carry `self_implemented: true` in the
registry and enforce four management rules (**stricter** than
library-backed features):
1. **Parameters must be explicit in the registry** (no hard-coding
   in the function body; window parameters take grid points (K8);
   other numeric parameters explicitly registered and pinned by a
   golden test);
2. **contract card mandatory** (the R3.2 alpha requirement applies
   equally to core self-implemented features): state variables /
   transition rules / seed convention / flip boundaries, written in
   the `indicators.py` function docstring;
3. **golden test against an independent reference**: not
   "verify ourselves with ourselves" — hand-derived first-N-bar
   values + point-for-point cross-check against an independent
   implementation (a moneta/nova reference can serve as a
   cross-anchor), failing on any deviation > 1e-12;
4. **version discipline**: any semantic change to a
   self-implemented feature → FEATURE_VERSION +1 (I13) and the
   reason must be recorded in the decision doc's revision log
   (a library-backed change usually just bumps the dependency
   version; a self-implemented change has no external anchor and
   must self-justify).

> The **equivalent discipline for library-backed** features
> (Supertrend now belongs to this class; applies directly):
> parameters explicit in the registry (ATR window = a grid point,
> multiplier explicit) + a pinned golden test (Supertrend uses the
> moneta/nova self-implementation reference as a bar-for-bar
> cross-check — see K1's dual-library parity).

**K8 Parameter grid discipline (decided; v0.5 new, v0.6 added 120;
user request)**: all **window parameters only take the CFD grid
{6, 12, 24, 60, 120}** (≈ 30m/1h/2h/5h/10h scale; consistent
semantics across timeframes; **120 aligns with moneta
`library/catalogue.py`'s authoritative grid `(6, 12, 24, 60, 120)`**,
which directly `raise ValueError("window outside CFD grid")` for
windows outside it); **the Wilder-era "14 trading days ≈ 2 weeks"
legacy parameter is not used** (nova's research features in practice
all use 6/12/24/60 — `return_6`, `prior24`, `efficiency_24`).
Motivation (user): keep the parameter surface small and the grid
coarse so strategies have low sensitivity to parameters — preventing
overfitting into a very narrow parameter environment. **Impact**:
- ATR registers `atr_6 / atr_12 / atr_24 / atr_60 / atr_120` (single
  Wilder smoothing, grid windows; the `atr_sma_14` dual-smoothing
  variant is **deleted** — under grid discipline the benefit of "two
  smoothings × one window" does not pay for its complexity);
- RSI registers `rsi_6 / rsi_12 / rsi_24 / rsi_60 / rsi_120` (same,
  grid);
- SMA/EMA register `sma_/ema_ 6 / 12 / 24 / 60 / 120` (full grid);
- **exception (explicitly recorded)**: PSAR `(0.02, 0.2)` is
  Wilder's standard acceleration/extreme factor — **not a bar
  window**, no "week" legacy; kept. Supertrend multiplier `3` is a
  multiplier, not a window; kept with **explicit registry parameters
  + a pinned golden test** (K7's library-backed equivalent
  discipline);
- default normalization denominator = `atr_24` (K6 updated).

### 3.4 Standard feature list (R3.1 decomposition)

| Family | Feature columns | Params | Compute class |
|---|---|---|---|
| Market | `open/high/low/close/volume` | — | copy (K2) |
| SMA | `sma_6 / sma_12 / sma_24 / sma_60 / sma_120` | grid (K8) | TA-Lib (K1) |
| EMA | `ema_6 / ema_12 / ema_24 / ema_60 / ema_120` | grid (K8) | TA-Lib (K1) |
| ATR | `atr_6 / atr_12 / atr_24 / atr_60 / atr_120` | grid (K8) | `talib.ATR` (Wilder smoothing); **`atr_24` = default normalization denominator** (K6) |
| RSI | `rsi_6 / rsi_12 / rsi_24 / rsi_60 / rsi_120` | grid (K8) | `talib.RSI` |
| PSAR | `psar / psar_bullish / psar_bearish` | (0.02, 0.2) (K8 exception: not a window param) | `talib.SAR` + direction flags |
| Supertrend | `supertrend / supertrend_bullish / supertrend_bearish` | (ATR window 24, multiplier 3) | `talib.SUPERTREND` (K1, library) + moneta/nova self-implementation reference as golden cross-anchor |
| Semantic | `sma_cross_up_6_24 / sma_cross_down_6_24 / sma_alignment_6_24 / rsi_divergence_up / rsi_divergence_down` | reference registered columns (6/24) | derived deterministic predicates over registered columns |
| Structural | `prior24_high / prior24_low / prior24_range / prior24_range_pos / prior24_width / breakout_up / breakout_down / failed_breakout_up / failed_breakout_down / shift6_atr / bar_range_atr / rel_quote_activity / utc_hour / path_eff_24` | 6 / 24 (both in-grid) | numpy/pandas vectorized (K1) |

**Structural-family semantics (§2.3 adoptions 4/6, K6)**:
- the 24-bar windows of `prior24_*` **exclude the current bar**
  (`shift(1)` then open the window; same as nova
  `_research_features`);
- `failed_breakout_up` = the current bar's `high` sweeps past
  prior24_high but `close` returns inside it (a wick-sweep fake
  breakout; same definition as nova);
- `utc_hour` = the UTC hour of the bar's **opening** (known at close
  confirmation; causally safe);
- all ATR-normalization denominators = `atr_24` (K6 updated);
- **v0.5/v0.6 gridding (K8, user decision)**: the original `atr_14 /
  rsi_14` (Wilder "14 trading days ≈ 2 weeks" legacy) and the
  `atr_sma_14` dual-smoothing variant are **deleted**; SMA/EMA
  gain 12; **v0.6 adds 120**; all window parameters ∈
  {6,12,24,60,120}. Prior-generation evidence: moneta `catalogue.py`
  directly `raise ValueError("window outside CFD grid")` for off-grid
  windows (authoritative grid = 6/12/24/60/120); nova's research
  features in practice all use 6/12/24/60.

> The list is authoritative per R3.1; this table is 0003's
> **implementation decomposition**. Adding/removing a feature =
> change R3.1 + this doc + FEATURE_VERSION.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I1 | every feature is available at `bar_close_time` (past-only, no future reference) — **column alignment**: in 0002's bronze/aggregate layers this time column is actually named `time` (bar open, UTC); I1/R3.3's `bar_close_time` is its semantic name; 0003 implements against `time` and does **not** add a `bar_close_time` column (that would create a dual-time-column ambiguity for 0004) | HLD §4 / R3.3 (this feature clarifies the column-name alignment) |
| I13 | changing a feature's computation/parameters → FEATURE_VERSION +1 | HLD §4 / R3.1 |
| I15 | alpha feature directories never enter git (`local.alpha` gitignored) | 0001 / B13 |
| I16 | core imports no specific alpha module, only the `lyra.features` extension point | 0001 |
| I17 | alpha feature files are Immutable (OCI side, same-sha idempotent) | HLD §4 |
| F1 | feature wide table **column set is deterministic**: same FEATURE_VERSION + same registry → same column-name set (the 0004 compiler can statically check) | new in this feature |
| F2 | warm-up NULL semantics: NULLs appear only in the **warm-up prefix** or in **legitimate upstream-missingness propagation** (a market-gap bar with no data → dependent window features are legitimately NULL for that bar and its following window period — not a bug); **out-of-bounds NULL = bug**, judged by: a feature's NULL position set ⊆ (its dependency chain's latest warm-up prefix ∪ upstream-missingness propagation closure) (K3's `warmup_bars` is the lower-bound datum; gap-propagation direction is guaranteed by I1 causality) | new in this feature |
| F3 | each instrument's feature wide table is a self-sufficient single file (K2): 0004 can compile by reading one file, no join to the market layer | new in this feature |
| F4 | compute determinism: same input + same FEATURE_VERSION + same numeric-stack version → feature values bitwise identical (bitwise, not "row-identical" — the feature layer is numeric computation; I18's "values + row order" is tightened here to bitwise) | new in this feature |
| F5 | registry name conflict (core vs alpha) → error, no override | new in this feature |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_registry_core_names_unique` | registry has no duplicate names |
| `test_registry_alpha_conflict_raises` | alpha collides with a core name → error (F5) |
| `test_load_from_alpha_dir` | `load_from(directory)` loads an example alpha module successfully |
| `test_load_from_core_only_unchanged` | with no alpha directory the core registry is unchanged (I16) |
| `test_sma_values_known` | SMA hand-computed golden test |
| `test_ema_recursion_known` | EMA first-5 values hand-computed golden (recursion seed = first value) |
| `test_rsi_grid_known` | RSI (window 24) hand-computed golden (`talib.RSI` Wilder smoothing) |
| `test_atr_grid_values_known` | `atr_6/12/24/60/120` per-window hand-computed goldens; different windows give different values (the grid takes effect) |
| `test_grid_only_windows` | every window parameter in the registry ∈ {6,12,24,60,120}, no 14 (K8 regression guard) |
| `test_psar_bull_bear_flags` | PSAR direction flags align with the flip bar |
| `test_supertrend_line_and_flags` | `talib.SUPERTREND` line + bull/bear flags are mutually consistent |
| `test_supertrend_parity_vs_reference` | `talib.SUPERTREND` vs the moneta/nova self-implementation reference, bar-for-bar (line/direction), deviation < 1e-12 (K1's dual-library parity hardened into a regression, guarding against a TA-Lib version change silently altering semantics) |
| `test_warmup_null_semantics` | gap-free input: NULLs only in the warm-up prefix (F2); injected gap: NULL set = prefix ∪ gap-propagation closure (F2 revised) |
| `test_no_future_reference` | truncating the last N rows of data → the prefix feature values are unchanged (I1 causality — the hardest one) |
| `test_deterministic_rerun` | re-running with the same input → feature values bitwise identical (F4) |
| `test_wide_table_self_sufficient` | the wide table contains all OHLCV columns and is independently queryable as a single file (F3/K2) |
| `test_snapshot_id_derived` | changing FEATURE_VERSION/params/numeric-stack version → snapshot id changes |
| `test_universal_21_instruments` | 21 instruments, same feature, same parameters, point-for-point identical algorithm (K5) |
| `test_feature_count_matches_r31` | wide-table column set == R3.1 list (F1 drift guard) |
| `test_gate1_truncation_zero_redraw` | truncated recompute vs full prefix: `max\|V_trunc − V_full[:k]\| < 1e-12` (moneta Gate 1; the hardest form of I1) |
| `test_gate3_bounds_rsi_atr` | RSI ∈ [0,100], ATR ≥ 0, PSAR/Supertrend line within the [low, high] domain (moneta Gate 3) |
| `test_gate4_zero_amplitude_no_crash` | flat bar / zero amplitude / zero volume injection → no Inf / NaN leakage / crash (moneta Gate 4) |
| `test_atr_normalization_basis_atr24` | every ATR-normalized feature's denominator == `atr_24` (K6; prevents the nova-mixing counter-example) |
| `test_supertrend_path_dependent_from_head` | computed from the data head; a mid-start may differ (path dependence explicitly accepted; warm-up NULLs kept; K4) |
| `test_supertrend_k7_management` | all four K7 management rules pass: parameters explicit in the registry (not hard-coded) + contract-card fields complete + golden values point-for-point cross-checked against the same-origin moneta/nova reference implementation, deviation < 1e-12 (K7) |

## 6. Rollback

- code: revert the 0003 commit (`lyra/features.py`,
  `lyra/indicators.py`, `lyra/registry.py` + tests + this doc); 0002
  is unaffected (the feature layer is purely additive; it does not
  touch clean/aggregate/pull).
- data: delete the entire `data/features/` directory (derived layer,
  always recomputable — the 0002 A1 convention); bronze/5m/1h
  untouched.
- compatibility: zero behavior change for 0002 and earlier; 0004 is
  not yet developed, so there are no downstream dependents.

## 7. Approval

- [ ] user review
- [ ] AI review (a different model)
- [ ] all tests green
- [ ] add `TA-Lib` to `pyproject.toml` (introduced by K1; lock synchronized at implementation)
- [ ] real data (bronze 48M rows) end-to-end 5m/1h feature wide tables
- [ ] after the 2019-11/12 backfill is folded in (timing is a user decision): cross-month warm-up behavior of features

## 8. Revision log

| Date | Version | Change |
|---|---|---|
| 2026-11-07 | 0.1 | First draft (skeleton): problem / background / plan K1–K5 decisions + R3.1 feature-list decomposition + invariants F1–F5 + 17 tests + rollback. |
| 2026-11-07 | 0.2 | **Filled from the moneta/nova read-only scan**: §2.3 six adoptions + four counter-examples + three not-applicable classes (Supertrend self-implementation / pure-NumPy `indicators` boundary / nova registry warm-up metadata / structural windows exclude the current bar / Gate 1-3-4 / utc_hour semantics; counter-examples = WARMUP_DROP row deletion, P1 2160 combinations with 0 promoted, 575-column wide table, mixed ATR bases); **K1 revised**: the numba draft is voided, now TA-Lib + self-implemented Supertrend + numpy vectorization, DuckDB reads/writes but never computes; K3 gains nova metadata; **K6 added** (ATR normalization uniformly on the Wilder basis); §3.4 structural semantics pinned; tests 17→**22** (+Gate1/3/4 + K6 + Supertrend path dependence) |
| 2026-11-07 | 0.3 | **Self-check fixes (3 self-contradictions + 1 implementation ambiguity)**: ① §3.1 CLI's "skip if present with the same snapshot id" contradicted 0002 A1's derived-layers-always-recompute → now always recompute/overwrite; §3.1's leftover numba/DuckDB-compute draft contradicted the K1 decision → rewritten to point at K1; the §3.2 "no TA-Lib" row contradicted K1's TA-Lib adoption → row removed. ② §3.4's column names `open/high/low/close` did not match the bronze contract's `mid_o/...` → price basis = mid columns, shorthands clarified. ③ the `bar_close_time` vs bronze's actual column name `time` dual-column ambiguity → I1 row clarifies the alignment (no new column). ④ `atr_sma_14`'s "hybrid" implementation semantics were undefined → defined as the 14-bar SMA of TR (must be a different algorithm from Wilder recursion). Also: TA-Lib's version is deliberately excluded from the snapshot id (semantic changes go through I13); the approval checklist gains the TA-Lib dependency item |
| 2026-11-07 | 0.4 | **Adversarial self-check fix (1 over-strong invariant)**: F2's original "any NULL after warm-up = bug" false-positives on **market gaps** (0002 I22 declares gaps legal; 730k real occurrences) — a gap bar's missingness propagating into dependent window features is a **legitimate** NULL, not a bug. Revised to "NULL positions ⊆ warm-up prefix ∪ upstream-missingness propagation closure" (direction guaranteed by I1 causality); `test_warmup_null_prefix_only` renamed `test_warmup_null_semantics` with a gap-propagation assertion. Other candidates (F1/F4/F5, K2 copy size, K5 interaction with gaps, snapshot-id derived-string length) verified as false positives or already covered — unchanged |
| 2026-11-07 | 0.5 | **User decided two points, landed as K7/K8**: ① **self-implemented feature management (K7)** — the user asked "why is Supertrend self-implemented?": TA-Lib **indeed has no** Supertrend (moneta/nova headers both confirm); self-implemented features are managed **stricter** than library-backed ones: parameters explicit in the registry (no hard-coding) + mandatory contract card + golden test cross-checked point-for-point against the same-origin moneta/nova reference implementation (<1e-12, no self-verification) + any semantic change must be I13+1 with a recorded reason. ② **parameter grid discipline (K8, user decision)** — the user pointed out 14 is the Wilder "14 trading days ≈ 2 weeks" legacy and asked for 6/12/24/60 with few parameters to prevent overfitting into a narrow parameter environment; prior-generation evidence: moneta `catalogue.py` directly `raise ValueError("window outside CFD grid")` for off-grid windows, nova's research features in practice all use 6/12/24/60 → **ATR/RSI re-registered as the 6/12/24/60 grid**, the `atr_sma_14` dual-smoothing variant deleted, SMA/EMA gain 12, Supertrend's ATR window 14→24, normalization denominator `atr_wilder_14`→`atr_24` (K6 updated); exception: PSAR (0.02,0.2) kept (not a window parameter). Synced R3.1 (the requirements ZH+EN authoritative list) + §3.4 table + tests (+`test_grid_only_windows`/`test_supertrend_k7_management`, the two 14-related cases re-gridded). Tests 22→**24** |
| 2026-11-07 | 0.6 | **Two user directives landed**: ① **Supertrend switched to the library** — the user asked "re-review whether any lib provides Supertrend". Measured evidence overturns the prior generations' assumption: the moneta/nova headers' "TA-Lib ships no Supertrend" is a **stale-version misconception** — the **TA-Lib 0.8.2** both generations lock does ship `SUPERTREND` (a real import probe confirms it, and `pandas-ta-classic` in moneta's deps also has one). A real-data dual-library parity test (SPX500_USD 1h, 5000 bars, PER=24/mult=3) shows the self-implementation and `talib.SUPERTREND` **match bar-for-bar 100%** (line diff=0, direction 100%). → **K1 revised** to "standard indicators all from TA-Lib (incl. Supertrend)"; **K7 demoted to a conditional guard** (0003 now has no self-implemented implementation; the rule is kept for the future); §2.3 adoption 1 changed from "must self-implement" to "path-dependence / keep NULL warm-up" (Supertrend's semantics unchanged, only its implementation source moved); §3.4's Supertrend row's compute class → `talib.SUPERTREND`; **new test** `test_supertrend_parity_vs_reference` (dual-library parity hardened into a regression). ② **K8 grid adds 120** (user directive "add 120") → grid = {6,12,24,60,120}, **aligned with moneta `catalogue.py`'s authoritative grid**; ATR/RSI/SMA/EMA each gain a `*_120` variant (§3.4 table + K8 impact block + `test_atr_grid_values_known` + `test_grid_only_windows` synced). Synced R3.1 (requirements ZH+EN authoritative list). Tests 24→**25** |
