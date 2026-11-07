# 0003 — Feature Builder (standard features + alpha extension point)

> **中文**: [0003-feature-builder.md](./0003-feature-builder.md)

## Meta

| Field | Value |
|---|---|
| ID | `0003` |
| Title | Feature Builder (standard features + alpha extension point) |
| Status | **Implemented** (0003 code shipped; 100 tests pass; real-data E2E passes; v1.1 adds Heikin Ashi; v1.2 adds the tulipy cross-library control group K1b) |
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
0002 aggregated layers `ohlcv_5m` / `ohlcv_1h` (NOT the bronze 1m
raw layer), compute all standard features defined in R3.1, produce
"one Parquet per instrument" feature wide tables, and leave a clean
alpha feature extension point (R3.2).**

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
- input: ohlcv_5m / ohlcv_1h (0002 aggregate views — the **5m / 1h
  aggregated layer**, NOT the bronze 1m raw layer; columns =
  `instrument, time, volume, mid_*, bid_*, ask_*`);
  **price basis = `mid_*` columns** (0002 bronze contract); the
  open/high/low/close in §3.4 are semantic shorthands for
  mid_o/mid_h/mid_l/mid_c;
- each standard feature = one registry record (K3); compute function =
  a pure-NumPy function in `indicators.py` or a vectorized
  composition in `features.py`;
- compute engine: see decision **K1** (standard indicators all from
  TA-Lib, incl. `talib.SUPERTREND`; window/structural via
  numpy/pandas vectorization);
- **data-flow control law (D5)**: the compute pipeline **must loop
  per instrument** (`for inst in instruments:`), each iteration
  requests only `SELECT ... FROM ohlcv_<m> WHERE instrument = ? ORDER
  BY time`, computes, writes, then frees that instrument's frame —
  **never** load all 21 instruments into one DataFrame at once (9.98M
  rows × 60 cols peaks >12 GB; a low-spec machine would be OOM-killed);
- output: `data/features/ohlcv_<layer>/<instrument>.parquet`
  (`<layer>` = `5m` / `1h`, aligned with the 0002 aggregate-layer name;
  **single file, NO `<snapshot_id>` directory level** — aligned with
  0002 D4's deprecated directory-level snapshot scheme; always
  recompute/overwrite, no stale directory accumulation, D1). Version
  info goes into **Parquet file metadata** (`feature_version`,
  param-set sha256, generation timestamp), not into path hierarchy.
  Columns = input OHLCV columns (K2 copy) + all registered feature
  columns, written via `pyarrow` (no pandas), row order = input
  row order (read `ORDER BY time`, same deterministic order as 0002
  I18);
- **Catalog integration (D1)**: register `features_5m` / `features_1h`
  views in 0002's `Catalog` (DuckDB external tables), the same
  consumer layer as `bronze`/`ohlcv_5m`/`ohlcv_1h`; 0004's compiler
  queries feature columns via the Catalog, not by scanning the
  filesystem for paths.

**Alpha extension point (R3.2)**:
- `lyra.features.load_from(directory)`: scans `*.py` in the
  directory; each module exposes a `register(registry)` function; an
  alpha feature = a contract card (module docstring, fixed schema:
  state variables / transition rules / seed / gap/flip / dependency
  columns) + a golden test in the same directory;
- **API contract (v0.7 added, D7)**: `registry.register(name,
  compute, *, kind, unit, warmup_bars, family, params)` is the only
  entry point; `compute` is a **pure-NumPy function** (`(mid_o, mid_h,
  mid_l, mid_c, volume, time, *extra) → 1-D float64 array or
  {col: array}`; the exact signature is finalized in the
  implementation spec, the `indicators.py` boundary unchanged);
  `load_from` **fail-fasts** on any alpha module's syntax error /
  missing dep / exception (raises and names the file, **never silently
  skips** — silent skip would only blow up at 0004 compile time); alpha
  `FEATURE_VERSION` attribution: an alpha feature's semantic change is
  carried by **its module docstring's version tag**, while core's
  `FEATURE_VERSION` covers only core registrations (the I16 boundary
  already isolates them, no conflict).
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
- the feature wide table's version identifier = a **derived string**
  over `(timeframe, FEATURE_VERSION, sha256 of the full registry
  parameter set, python/numpy/pandas version triple)`, written into
  the Parquet metadata (**NOT a directory level** — 0002 D4
  deprecated directory-level snapshot state machines, and 0002's
  market layer has no "market snapshot id" entity either, so we do not
  reference it; derived values are reproducible and need no
  allocator). **TA-Lib's version is deliberately NOT in the version
  identifier**: TA-Lib is the source of the indicator reference
  implementations; if its semantics change, the correct action is
  FEATURE_VERSION +1 (I13), not an implicit distinction via a version
  string — the version identifier expresses "registry semantics", not
  a "third-party implementation fingerprint".

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
- **TA-Lib dependency vs R8 portability (v0.7 clarified, D2)**: TA-Lib
  is the **official PyPI package** `TA-Lib` (`github.com/ta-lib/
  ta-lib-python`, author John Benediktsson; the **0.8.2** both
  generations lock **is the official wrapper, not a fork** — the
  reviewer's "0.8.2 is an unverified fork" claim does not hold). R8's
  "portable: POSIX + Windows; no system packages (**TA-Lib via
  wheel**)" already folds TA-Lib's C runtime into the portability
  boundary. **Measured on moneta's venv 0.8.2 wheel, it is a standard
  manylinux wheel**: the C runtime is bundled by auditwheel into
  `site-packages/ta_lib.libs/libta-lib-*.so.1.1.0` (3.4 MB), and
  `_ta_lib*.so` links that local library with **only `libc.so.6`
  external** — i.e. pip install is ready-to-use, **no
  `apt-get libta-lib` / MSVC hand-build needed**, opposite to the
  reviewer's "D2 will break pip with a compile crash" concern. So it
  **does not violate R8**. Residual risk (a future platform with no
  official wheel needing a source-build fallback) is recorded as an
  **implementation-phase environment check**, not a K1 decision
  change; and core keeps the "indicator algorithm layer decoupled from
  the library implementation" (`indicators.py` pure-NumPy boundary),
  so replacing/downgrading the engine later only touches
  `features.py`'s library calls, not the algorithms.

**K1b Cross-library control group (v1.2, user approved 2026-11-07: "install tulipy as a control, keep it for later")**:
K1 uses TA-Lib as the **sole compute backend**; to guard against a silent
semantic change if TA-Lib is ever re-versioned, we adopt an **independent
second implementation** for cross-validation. Empirical selection (isolated
venv, py3.12 + numpy 2.5.4, our deliberate pandas-free runtime stack):
- **Adopt tulipy** — C-backed, **pandas-free** (the only third-party indicator
  lib with no pandas dependency), 100+ indicators, broader coverage than the
  hand-rolled pure-NumPy references in `test_indicators.py`, and reusable as
  the control group whenever we add P1/P2 indicators later. It is an
  **optional dependency** `lyra[control]`
  (`pyproject.toml` `[project.optional-dependencies] control = ["tulipy"]`),
  **not a core dependency** (R10 keeps the core at ≤15 packages); only
  `tests/` imports it. `tests/test_crosscheck_tulipy.py` auto-skips via
  `pytest.importorskip` when tulipy is absent, so the core suite is untouched
  (100 tests incl. its 2; 98 without the lib).
- **Reject Finta** — its PyPI name `fintech` is squat-registered by an
  unrelated "LicenseManager" package, so the real lib cannot be installed, and
  it is archived; **reject bukosabino/ta and pandas-ta-classic** — both hard-
  require pandas, contradicting the "deliberately pandas-free runtime stack",
  and are themselves TA-Lib re-implementations whose cross-check value tulipy
  already covers; **reject vectorbt** — it is a full strategy-research
  framework (with its own backtest/portfolio), not an indicator lib; adopting
  it would install "a second strategy-finding engine", exactly the peripheral
  over-engineering trap moneta hit.

**Two empirically-verified difference classes (K1b core finding, frozen into
control tags, NOT bugs)**:
- **Machine-precision match (tag `exact`, asserted < 1e-6)**: SMA / HMA / KAMA /
  RSI / MOM / CCI / WILLR / MFI / STDDEV — these use **no decaying recursive
  smoother**, so the two C libraries differ only by floating-point noise.
- **Definitional difference (tag `definitional`, only finiteness asserted, no
  magnitude bound)**: EMA / DEMA / TEMA / ATR / ADX / NATR / ROC / CMO / OBV —
  these use a **decaying recursive smoother** (EMA or Wilder); TA-Lib and tulipy
  differ in recursion **seed / alpha / ×100 scaling / OBV seed**, so the tail
  does **not** converge to machine precision at reasonable series lengths
  (measured: EMA/DEMA ~1e-2, TEMA ~1e-3, ATR/ADX ~3e-3, length-dependent).
  This is a legitimate inter-library convention difference, same family as the
  CMO/MFI findings in #61. **Key engineering point**: tulipy **truncates the
  warm-up prefix and returns a shorter array** (the opposite of TA-Lib, which
  keeps the full length and NaN-fills the prefix — exactly the moneta §2.3
  anti-pattern #1 "delete the prefix rows" trap), so the cross-check **must
  align on the tail** (`a[-k:]`) and never assume equal lengths.

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
| NATR | `natr_6 / natr_12 / natr_24 / natr_60 / natr_120` | grid (K8) | `talib.NATR` (`atr/close` volatility scale) |
| MACD | `macd_6_12_6 / macd_6_24_6 / macd_12_60_12` (each with `line / signal / hist`) | **curated triplets** (K8 exception, see below) | `talib.MACD` (fast/slow/signal) |
| ROC | `roc_6 / roc_12 / roc_24 / roc_60 / roc_120` | grid (K8) | `talib.ROC` (momentum) |
| STOCH | `stoch_k_6 / stoch_d_6` etc., (fastk, slowd) ∈ {(6,6),(24,12),(60,24)} | in-grid pairs (K8) | `talib.STOCH` (%K/%D) |
| BBANDS | `bband_pctb_24 / 60 / 120` + `bband_bw_24 / 60 / 120` | grid (K8), std=2 | `talib.BBANDS` (%B + bandwidth, **no raw upper/lower bands**) |
| ADX family | `adx_24 / adx_60`, `plus_di_24 / plus_di_60`, `minus_di_24 / minus_di_60` | 24/60 (K8, 2 points only) | `talib.ADX / PLUS_DI / MINUS_DI` (trend strength) |
| CCI | `cci_24 / cci_60` | 24/60 (K8, 2 points only) | `talib.CCI` (mean-reversion momentum) |
| WILLR | `willr_24 / willr_60` | 24/60 (K8, 2 points only) | `talib.WILLR` (mean reversion) |
| MFI | `mfi_24 / mfi_60` | 24/60 (K8, 2 points only) | `talib.MFI` (needs volume, money flow) |
| CMO | `cmo_24 / cmo_60` | 24/60 (K8, 2 points only) | `talib.CMO` (momentum) |
| OBV | `obv`, `obv_slope_24` (24-bar `LINEARREG_SLOPE` of `obv`) | slope window 24 (K8) | `talib.OBV` + slope derivation (**not the absolute value**, use slope/rate) |
| Reg. slope | `lrslope_24 / lrslope_60` (`LINEARREG_SLOPE / close` normalized) | 24/60 (K8, 2 points only) | `talib.LINEARREG_SLOPE` (trend direction) |
| KAMA | `kama_24` | 24 (K8) | `talib.KAMA` (adaptive MA, ER factor internal) |
| DEMA | `dema_6 / dema_24 / dema_60` | 6/24/60 (K8) | `talib.DEMA` double exponential (`2·EMA − EMA(EMA)`), faster than EMA |
| TEMA | `tema_6 / tema_24 / tema_60` | 6/24/60 (K8) | `talib.TEMA` triple exponential, even lower lag |
| HMA | `hma_24 / hma_60` | 24/60 (K8) | `talib.HMA` (Wilder, √n / n/2 internal weights) low-lag smoothed MA |
| MOM | `mom_6 / mom_24 / mom_60` | 6/24/60 (K8) | `talib.MOM` = close−close[n] absolute momentum (ROC is the relative % form) |
| StdDev | `stddev_24 / stddev_60` | 24/60 (K8) | `talib.STDDEV` absolute price dispersion (ATR is TR-based; this is close-based) |
| Z-Score | `zscore_24 / zscore_60` | 24/60 (K8) | derived: (close − SMA(close,n)) / STDDEV(close,n) — dimensionless position, defined zero-denominator |
| PSAR | `psar / psar_bullish / psar_bearish` | (0.02, 0.2) (K8 exception: not a window param) | `talib.SAR` + direction flags |
| Supertrend | `supertrend / supertrend_bullish / supertrend_bearish` | (ATR window 24, multiplier 3) | `talib.SUPERTREND` (K1, library) + moneta/nova self-implementation reference as golden cross-anchor |
| Heikin Ashi | `ha_o / ha_h / ha_l / ha_c` | no window param (recursive transform, converges in ~16 bars) | **K7 self-implementation** (TA-Lib has no HA); recursive `ha_c=(o+h+l+c)/4`, `ha_o=(ha_o[i-1]+ha_c[i-1])/2`, `ha_h=max(h,ha_o,ha_c)`, `ha_l=min(l,ha_o,ha_c)`; warmup_bars=16 |
| Semantic | `sma_cross_up_6_24 / sma_cross_down_6_24 / sma_alignment_6_24 / rsi_divergence_up / rsi_divergence_down` | reference registered columns (6/24) | derived deterministic predicates over registered columns |
| Structural | `prior24_high / prior24_low / prior24_range / prior24_range_pos / prior24_width / breakout_up / breakout_down / failed_breakout_up / failed_breakout_down / shift6_atr / bar_range_atr / rel_quote_activity / utc_hour / path_eff_24 / prior60_high / prior60_low / prior60_range / path_eff_60` | 6 / 24 / 60 (all in-grid) | numpy/pandas vectorized (K1); v0.9 adds prior60_* (Donchian @60) + path_eff_60 (Efficiency Ratio @60) |

**v0.8 new standard-indicator families (K8 grid + parameter-surface discipline)**: the NATR / MACD / ROC / STOCH / BBANDS / ADX family / CCI / WILLR / MFI / CMO / OBV / regression-slope / KAMA — **13 families** — are adopted in this release (2026-11-07 user approved the "recommended scope"; the external suggestion list's **parameters are all ignored** and re-mapped onto the K8 grid). Parameter-surface discipline (echoes K8's anti-overfitting motive):
- **MACD uses curated triplets, not full grid expansion** — fast/slow/signal are mutually constrained; a full `5×5×5` grid would generate many meaningless combos (fast>slow, signal>slow, etc.); only 3 semantically-sound in-grid triplets kept;
- **Trend-strength / momentum / oscillator families (ADX/CCI/WILLR/MFI/CMO) take only 24 and 60**, not all 5 points — these are "scale choices", not "key signal points"; opening more only inflates the parameter surface;
- **BBANDS uses %B + bandwidth, not raw upper/lower bands** (raw bands carry a price dimension, not comparable across instruments; %B and bandwidth are dimensionless and cross-instrument comparable, consistent with "universal rules");
- **OBV uses slope/rate, not the absolute cumulative value** (the absolute value's scale drifts with each instrument's volume, not comparable).

**Parked families (with rationale, not forgotten)**: PPO (normalized MACD variant, redundant), TRIX / ULTOSC / AROON (niche variants, low marginal value), ~~STDDEV~~ (**v0.9 un-parked** — see below), CORREL / BETA (no natural reference series in a single-instrument universe), Keltner (= EMA ± 2×ATR, BBANDS already covers "mean ± n·vol band"), Choppiness (= 100·LOG(SUM(TR)/range), an ATR+Donchian composite transform, not an independent dimension), Relative Volume / VWMA (`rel_quote_activity` already covers the volume dimension), P1 families (AROON / TRIX / CMF / EFI / PVT / SMI / TSI / VHF / QQE / RSX / Ichimoku / HeikinAshi / InsideBar / Williams Fractal / Squeeze Momentum / Schaff — parameter surface too large or require self-implementation, deferred to batch 2 after the 0003 base works), HT_* (Hilbert transforms, poor interpretability / overfitting risk), CDL* (61 candlestick patterns, sparse binary, weak standalone significance — needs a statistical pre-screen first).

> **v0.9 new standard-indicator families (P0 gap fill, 8 items)**: DEMA (6/24/60), TEMA (6/24/60), HMA (24/60), MOM (6/24/60), StdDev (24/60), Z-Score (24/60, `(close − SMA) / STDDEV` — dimensionless position, defined zero-denominator), **Donchian @60** (`prior60_high / prior60_low / prior60_range`, same `shift(1)`-exclude-current-bar convention as prior24), and **Efficiency Ratio @60** (`path_eff_60`).
> **STDDEV un-parked** (per user decision): the "price dispersion / position around the mean" dimension is not fully covered by ATR (TR-based) or BBANDS (%B relative position), and P0 requires coverage.
> **Triggers I13**: feature-set change again → **FEATURE_VERSION +1** (v0.8 already +1, cumulative +2, applied at implementation). D4 gate extended with `zscore_*` (all-flat bars → rolling stddev 0 → 0/0); `test_grid_only_windows` scope expanded. **Synced R3.1** (requirements v0.12 ZH+EN).

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

> **D4 process gate (this table ≠ implementation spec)**: the table
> above is a **feature list**, not a mathematical spec. **Before**
> 0003 implementation begins, the implementation spec (each function's
> docstring in `indicators.py` + `tests/` goldens) must give **an exact,
> variable-and-operator-level deterministic mathematical definition**
> for **every** self-implemented semantic/structural feature, and every
> division feature (`path_eff_24` / `prior24_range_pos` / `shift6_atr` /
> `bar_range_atr` / `rel_quote_activity` / v0.8 new: `natr_*` /
> `bband_pctb_*` / `bband_bw_*` / `lrslope_*` / `mfi_*` / v0.9 new: `zscore_*`) must define an
> explicit zero/near-zero denominator fallback rule (`denom == 0 → NULL`
> or `0.0`, and it must NOT be caught by Gate 4 as a NaN leak) —
> `mfi_*`'s money-flow ratio and `bband_pctb_*`/`bband_bw_*`'s bandwidth
> can hit a zero denominator on 24 all-flat bars (a legitimate defined
> NULL, not a crash); **v0.9 adds `zscore_*`** (N all-flat bars → rolling stddev 0 → 0/0, same gate). The decision doc
> locks only "which to compute, which parameter family to use"; "how to
> compute" is governed by the spec + golden test (to prevent different
> implementers writing different code and the golden test becoming
> self-referential).

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
| F2 | warm-up NULL semantics (**v0.7 tightened**, D3): 0002 already guarantees the input `mid_*` is NULL-free and has **no gap placeholder rows** (measured 9.98M rows, 0 NULLs), so a feature's NULLs are **allowed to come only** from (a) the **warm-up prefix** (K3 `warmup_bars`), or (b) a **defined zero-denominator of a derived feature** (e.g. `prior24_range_pos` hitting 24 all-equal bars → `range==0`, producing NULL/0 per the D4-gate fallback rule — a legitimate semantic, not gap propagation); **outside these two classes, any NULL/NaN after warm-up = a compute crash or divide-by-zero bug** (Gate 4 catches it) | new in this feature (v0.7 tightened per D3, removing the "gap-propagation closure" phantom concept) |
| F3 | each instrument's feature wide table is a self-sufficient single file (K2): 0004 can compile by reading one file, no join to the market layer | new in this feature |
| F4 | compute determinism (**v0.7 tightened**, D6): same input + same FEATURE_VERSION + same numeric-stack version + **same platform / same math library** → feature values **bitwise identical**; **cross-platform** (Linux↔Windows↔macOS, AVX2/AVX-512/NEON, OpenBLAS/MKL etc. math-library differences) only commits to `np.allclose(atol=1e-12, rtol=1e-12)` high-precision equality, **not bitwise** — floating-point sum/product order and 1-ULP rounding vary with hardware and compiler optimization (D6); golden tests therefore assert on two tiers: "same-platform bitwise, cross-platform allclose" (aligned with moneta Gate 1) | new in this feature (v0.7 added the cross-platform tolerance tier per D6) |
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
| `test_grid_only_windows` | **v0.9 expanded scope**: **every** window parameter in the registry (SMA/EMA/ATR/NATR/RSI/ROC/STOCH/BBANDS/ADX family/CCI/WILLR/MFI/CMO/LRSLOPE/KAMA/obv_slope/MACD triplet params + **v0.9 DEMA/TEMA/HMA/MOM/STDDEV/Z-Score/prior60/path_eff_60**) ∈ {6,12,24,60,120}, no off-grid 14/15/20/50/100 (K8 regression guard) |
| `test_macd_triplets_known` | MACD's 3 curated triplets (6,12,6)/(6,24,6)/(12,60,12): `line/signal/hist` hand-computed goldens; and `line − signal == hist` (`talib.MACD`) |
| `test_roc_stoch_known` | ROC(24) and STOCH(%K/%D, fastk=6/slowd=6) hand-computed goldens; STOCH %K ∈ [0,100] (`talib.ROC` / `talib.STOCH`) |
| `test_bbands_pctb_bw_known` | BBANDS(window 24, std=2): %B hand-computed golden + bandwidth `(upper−lower)/middle ≥ 0`; **raw bands not registered** (dimensionless discipline) (`talib.BBANDS`) |
| `test_trend_momentum_family_known` | ADX/PLUS_DI/MINUS_DI(24/60) ∈ [0,100]; CCI(24/60) finite; WILLR(24/60) ∈ [−100,0]; CMO(24/60) ∈ [−100,100] (`talib.ADX/PLUS_DI/MINUS_DI/CCI/WILLR/CMO`) |
| `test_volume_flow_known` | MFI(24/60) ∈ [0,100]; OBV cumulative, `obv_slope_24` = its 24-bar `LINEARREG_SLOPE`; KAMA(24) ∈ [low, high]; LRSLOPE(24/60) finite (`talib.MFI/OBV/LINEARREG_SLOPE/KAMA`) |
| `test_natr_consistency` | `natr_W` == `atr_W / close` (pointwise < 1e-12), i.e. NATR is ATR normalized by close, not an independent indicator |
| `test_dema_tema_hma_known` | DEMA/TEMA/HMA window-24 hand-computed golden values (pointwise < 1e-12); DEMA/TEMA ∈ [low, high] (a MA combination); HMA lags less than SMA at the same window |
| `test_mom_stddev_zscore_known` | MOM(24) == close − close.shift(24) (pointwise < 1e-12); STDDEV ≥ 0; Z-Score = (close−SMA)/STDDEV formula match; **all-flat bars → `zscore_*` = NULL (not NaN/0), per D4** |
| `test_prior60_path_eff60_known` | prior60_high/low/range = shift(1) 60-bar window (excludes the current bar, same convention as prior24); `path_eff_60` = |close−open60| / Σ|Δclose| formula match, denominator 0 → NULL |
| `test_psar_bull_bear_flags` | PSAR direction flags align with the flip bar |
| `test_supertrend_line_and_flags` | `talib.SUPERTREND` line + bull/bear flags are mutually consistent |
| `test_supertrend_parity_vs_reference` | `talib.SUPERTREND` vs the moneta/nova self-implementation reference, bar-for-bar (line/direction), deviation < 1e-12 (K1's dual-library parity hardened into a regression, guarding against a TA-Lib version change silently altering semantics) |
| `test_warmup_null_semantics` | contiguous gap-free input: NULLs **only** in the warm-up prefix; any NULL/NaN after warm-up = assertion failure (F2 v0.7, D3); **exception**: a derived feature's zero denominator (e.g. `prior24_range_pos` on 24 all-equal bars) yields NULL/0 per the D4 fallback rule, legitimate (asserted separately, not mixed into the prefix rule) |
| `test_no_future_reference` | truncating the last N rows of data → the prefix feature values are unchanged (I1 causality — the hardest one) |
| `test_deterministic_rerun` | re-running with the same input, **same environment** → feature values bitwise identical (F4 strict tier) |
| `test_wide_table_self_sufficient` | the wide table contains all OHLCV columns and is independently queryable as a single file (F3/K2) |
| `test_feature_version_in_metadata` | changing FEATURE_VERSION/param-set sha256/numeric-stack version → the version string in the Parquet metadata changes (**not a directory level**, D1) |
| `test_output_single_file_no_snapshot_dir` | output is a single `features_<m>/<instrument>.parquet` file, **no** `<snapshot_id>` sub-directory; re-runs overwrite without accumulating (D1) |
| `test_per_instrument_streaming` | the data flow loops per instrument: the single-instrument working set stays bounded (<~300MB asserted), never all 21 instruments resident at once (D5) |
| `test_f4_same_env_bitwise_cross_env_allclose` | same-environment re-run is bitwise identical (F4 strict tier); document "cross-platform allclose(1e-12)" as the maintainable upper bound (F4/D6) |
| `test_universal_21_instruments` | 21 instruments, same feature, same parameters, point-for-point identical algorithm (K5) |
| `test_feature_count_matches_r31` | wide-table column set == R3.1 list (F1 drift guard) |
| `test_gate1_truncation_zero_redraw` | truncated recompute vs full prefix: `max\|V_trunc − V_full[:k]\| < 1e-12` (moneta Gate 1; the hardest form of I1) |
| `test_gate3_bounds_rsi_atr` | RSI ∈ [0,100], ATR ≥ 0, PSAR/Supertrend line within the [low, high] domain (moneta Gate 3) |
| `test_gate4_zero_amplitude_no_crash` | flat bar / zero amplitude / zero volume injection → no Inf / NaN leakage / crash (moneta Gate 4) |
| `test_atr_normalization_basis_atr24` | every ATR-normalized feature's denominator == `atr_24` (K6; prevents the nova-mixing counter-example) |
| `test_supertrend_path_dependent_from_head` | computed from the data head; a mid-start may differ (path dependence explicitly accepted; warm-up NULLs kept; K4) |
| `test_supertrend_registry_params` | Supertrend (library-backed) management discipline: ATR window on a grid point, multiplier explicit in the registry (not hard-coded in the function body) + golden values point-for-point cross-checked against the moneta/nova reference implementation, deviation < 1e-12 (K7's library-backed equivalent discipline, NOT the "four self-implemented rules" — that is the untriggered conditional guard) |
| `test_heikin_asi_known_values` | **v1.1**: Heikin Ashi recursive-transform golden test — independent pure-Python textbook reference vs shipped, point-for-point < 1e-9 from bar 32 (seed dependence converges after ~16 bars); the invariant `ha_h ≥ ha_c ≥ ha_l` holds at every bar (K7) |
| `test_heikin_asi_k7_management` | **v1.1**: K7 management discipline — `self_implemented=True` marker + `window_params=()` (recursion, not a window; K8 N/A) + `warmup_bars ≥ 16`, three assertions |
| `test_crosscheck_all_mapped` | **v1.2**: K1b cross-library control — tulipy (C-backed, independent implementation) vs our TA-Lib backend, cross-checking every feature in MAP. The `exact` group (SMA/HMA/KAMA/RSI/MOM/CCI/WILLR/MFI/STDDEV) asserts tail-reldiff < 1e-6 (two C libs differ only by float noise); the `definitional` group (EMA/DEMA/TEMA/ATR/ADX/NATR/ROC/CMO/OBV — recursion seed/alpha/×100/OBV-seed differences) asserts only finiteness; the `no_lib` group (plus_di/minus_di/lrslope/supertrend/ha_o) is a documented skip. **Tail alignment** (tulipy truncates the warm-up prefix and returns a shorter array, the opposite of TA-Lib which keeps NaN prefix at full length). Auto-skips via `importorskip` when tulipy is absent, so the core suite is untouched (K1b) |
| `test_crosscheck_skips_unknown_features` | **v1.2**: K1b control-group robustness — a mapped feature renamed out of the registry (0004) is skipped cleanly (not KeyError); unmapped features are silently ignored |

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
| 2026-11-07 | 0.7 | **Batch-02 external red-team D1–D8 disposition (per user's accept/park/reject 3-level: 接受 5 = D1/D3/D5/D6/D8, 挂起 2 = D4/D7, 拒绝 1 = D2)**: ① **D1 (accepted)** — §3.1 abolished the `<snapshot_id>` directory level and the phantom "market snapshot id" derived term (0002 D4 already deprecated directory-level snapshots; the market layer has no such entity), now a single `features_<m>/<instrument>.parquet` file with the version written into Parquet metadata; added **Catalog integration** (register `features_5m/1h` views; 0004 queries feature columns via the Catalog, not by scanning the filesystem); test renamed `test_feature_version_in_metadata` + new `test_output_single_file_no_snapshot_dir`. ② **D5 (accepted)** — §3.1 added the **data-flow control law**: force per-instrument looping, bound the single-instrument working set, never load all 21 instruments resident at once; new `test_per_instrument_streaming`. ③ **D6 (tightened)** — F4 tightened from "bitwise" to a **two-tier: same-environment bitwise + cross-platform allclose(1e-12)**; new `test_f4_same_env_bitwise_cross_env_allclose`. ④ **D3 (tightened)** — F2 removed the "gap-propagation closure" phantom concept (0002 DQ1 guarantees `mid_*` NULL-free with no gap placeholder rows; measured 9.98M rows, 0 NULLs); now NULLs allowed only from warm-up prefix ∪ a defined derived-feature zero denominator; `test_warmup_null_semantics` synced. ⑤ **D4 (parked + process gate)** — decision doc ≠ implementation spec; §3.4 added a **D4 process gate**: before implementation, every self-implemented semantic/structural feature must get an exact variable/operator-level mathematical definition + every division feature a zero-denominator fallback (`denom==0 → NULL/0`, not caught by Gate 4 as a NaN leak). ⑥ **D2 (rejected on the merits, clarified with evidence)** — K1 clarified: TA-Lib 0.8.2 is the **official PyPI package** (`ta-lib/ta-lib-python`, not a fork); **the measured wheel bundles the C runtime via auditwheel** (`ta_lib.libs/libta-lib-*.so`, only `libc.so.6` external), so pip install is ready-to-use with no system C build → **does not violate R8**; the residual "a platform with no wheel" risk is recorded as an implementation-phase environment check. ⑦ **D7 (parked + process gate)** — the alpha extension point gained an API contract (`registry.register(...)` entry + pure-NumPy `compute` signature + fail-fast load with no silent skip + alpha version attribution); details land in the implementation spec. ⑧ **D8 (accepted)** — §1 input scope changed from "bronze/5m/1h" to "5m/1h aggregated layer" (0003 consumes only 0002's aggregated layer, not bronze 1m). Also fixed a **v0.5 leftover inconsistency**: `test_supertrend_k7_management`'s semantics ("four self-implemented rules") contradicted v0.6's K7 demotion → renamed `test_supertrend_registry_params` (library-backed management discipline). Tests 25→**28** (+3: single-file output / per-instrument / F4 two-tier; renamed 2: warmup_null, supertrend management; renamed 1: snapshot→metadata) |
| 2026-11-07 | 0.8 | **Expanded the standard-indicator set (user approved the "recommended scope"; the external suggestion list's 5/10/14/20 parameters are all ignored and re-mapped onto the K8 grid {6,12,24,60,120})**: §3.4 adds **13 families** of standard indicators — NATR (`atr/close`), MACD (**curated triplets** 6_12_6/6_24_6/12_60_12, NOT full grid expansion), ROC, STOCH (%K/%D), BBANDS (**%B + bandwidth**, no raw upper/lower bands), ADX/PLUS_DI/MINUS_DI (trend-strength family, 24/60 only), CCI, WILLR, MFI, CMO (all 24/60 only), OBV (**slope**, not absolute value), LINEARREG_SLOPE (normalized slope), KAMA (adaptive MA). Parameter-surface discipline: MACD curated triplets, trend-strength/momentum/oscillator families take 2 points, BBANDS/OBV use dimensionless forms (echoes K8's anti-overfitting motive). **Parked families** (with rationale): PPO/TRIX/ULTOSC/AROON/STDDEV (redundant or niche), CORREL/BETA (no reference series in a single-instrument universe), HT_*/CDL* (overfitting / need a pre-screen first). D4 gate extended to 5 new division features (`natr_*`/`bband_pctb_*`/`bband_bw_*`/`lrslope_*`/`mfi_*`); `test_grid_only_windows` scope expanded to cover all new families; **+6 tests** (MACD / ROC+STOCH / BBANDS / trend-momentum family / volume-flow family / NATR consistency). **Triggers I13**: feature-set change → **FEATURE_VERSION +1**. Synced R3.1 (the requirements ZH+EN authoritative list). Tests 28→**34** (ZH=EN) |
| 2026-11-07 | 0.9 | **Filled the P0 base-indicator gap (user confirmed; the 8 P0-gap items from the external P0/P1/P2 list landed, all params on the K8 grid)**: §3.4 adds 6 standard families — DEMA (6/24/60), TEMA (6/24/60), HMA (24/60), MOM (6/24/60), StdDev (24/60), Z-Score (24/60, `(close−SMA)/STDDEV` dimensionless); the structural family adds **Donchian @60** (`prior60_high/low/range`, same `shift(1)`-exclude-current-bar convention as prior24) + **Efficiency Ratio @60** (`path_eff_60`). **STDDEV un-parked** (user decision: its price-dispersion/position dimension is not fully covered by ATR/BBANDS, and P0 requires coverage); parked list extended (Keltner / Choppiness / Relative Volume-VWMA / all P1 families — parameter surface too large or self-implementation needed, deferred to batch 2 after the 0003 base works). D4 gate adds `zscore_*` (6th new division feature, N all-flat bars → 0/0); `test_grid_only_windows` scope expanded; **+3 tests** (dema_tema_hma / mom_stddev_zscore / prior60_path_eff60). **Triggers I13**: feature-set change again → **FEATURE_VERSION +1** (v0.8 already +1, cumulative +2). Synced R3.1 (requirements v0.12 ZH+EN). Tests 34→**37** (ZH=EN) |
| 2026-11-07 | 1.0 | **0003 implementation shipped (user approved "you may implement 0003 now")**: `lyra/registry.py` (K3 Registry/FeatureSpec; `window_params` kept separate from `params` so the K8 guard doesn't false-positive on nbdev/multiplier) + `lyra/indicators.py` (pure-NumPy TA-Lib boundary + the moneta/nova Supertrend golden reference + zscore) + `lyra/features.py` (`build_registry()` 116 features, `compute_features`, `load_from` alpha loader (D7 fail-fast + I16 core-untouched), `run_features` D5 per-instrument pipeline, Parquet metadata versioning) all landed. **Implementation-time corrections (none change the feature list/params → no I13 trigger)**: ① NATR implemented as `atr/close` (**not** `talib.NATR` — that ×100, violating the §3.4 / `test_natr_consistency` dimensionless contract); ② `rel_quote_activity` implemented as `volume/SMA(volume,24)` (dimensionless, matches nova's proven formula; supersedes an earlier draft's `×1e9` variant); ③ **warm-up prefixes made exact from measurement** (MACD = slow+fast−2, STOCH = fastk+slowd−2, DEMA/TEMA kept safe upper bounds, HMA = n+5, `shift6_atr` = ATR_NORM=24, `rsi_divergence` = 48) — `warmup_bars` is the safe lower bound the F2 assertion relies on, set to the measured max prefix; ④ output path `data/features/ohlcv_5m|1h/<instrument>.parquet` (aligned with the 0002 aggregate-layer name, dir named by layer not minute count). **New engineering pieces**: `lyra features` CLI (always recompute+overwrite; `--minutes 5|60` / `--instrument` / `--alpha-dir`), Catalog `features_5m/1h` views (D1, glob `features/ohlcv_*/\*.parquet`), `pyproject.toml` adds the `TA-Lib>=0.8.2` dependency. **All 37 documented tests implemented and passing** (`tests/test_registry.py` / `test_indicators.py` / `test_features.py`, plus 1 real-data E2E), and the 0002 suite's 58 tests stay green (**96 total**). **Status: Proposal → Implemented**; `test_real_data_one_instrument` (SPX500_USD 1h, 40,435 rows, 124 columns) passes. |
| 2026-11-07 | 1.1 | **Added the Heikin Ashi family (user: "if it can be added, add it"; TA-Lib has no HA → triggers the K7 self-implementation path)**: §3.4 table gains `ha_o / ha_h / ha_l / ha_c` (4 columns; recursive transform, no window parameter → K8 grid N/A; warmup_bars=16 is the safe lower bound for the recursive convergence, seed dependence < 1e-9 after ~16 bars). **All K7 management discipline applies**: parameters explicit in the registry (the `self_implemented: True` marker is now an explicit `FeatureSpec`/`Registry.register` field — first real trigger after 0003 v0.6 demoted K7 to a conditional guardrail) + contract card (recursive definition + seed rule + convergence bound) + golden test `test_heikin_asi_known_values` (independent pure-Python textbook reference vs shipped, per-point < 1e-9 from bar 32) + `test_heikin_asi_k7_management` (self_implemented=True / window_params=() / warmup_bars>=16). **Triggers I13**: feature-set change (+4 columns) → **FEATURE_VERSION +1 (2→3)**. Tests 38→**40** (ZH=EN), the 0002 suite's 58 stay green (**98 total**). The P1 parked-list entry "HeikinAshi" is removed (shipped, not forgotten) |
| 2026-11-07 | 1.2 | **Introduced the tulipy cross-library control group (K1b; user: "install it as a control and keep it for later")**: empirical selection (isolated venv, py3.12 + numpy 2.5.4 + pandas-free stack) → adopted **tulipy** (C-backed, **pandas-free**, 100+ indicators, broader than the hand-rolled references, reusable for future P1/P2) as an **optional dependency** `lyra[control]` (`pyproject.toml` gains `[project.optional-dependencies] control = ["tulipy"]`, **not a core dependency**, R10 keeps the core at ≤15 packages); **rejected** Finta (its PyPI name `fintech` is squat-registered by an unrelated LicenseManager package — the real lib can't be installed — and it is archived), bukosabino/ta + pandas-ta-classic (both hard-require pandas, contradicting the pandas-free runtime principle), and vectorbt (a full strategy-research framework, not an indicator lib; adopting it installs a second strategy-finding engine = the peripheral over-engineering trap moneta hit). **Added** `tests/crosscheck_tulipy.py` (MAP + `run_crosscheck` tail-alignment) + `tests/test_crosscheck_tulipy.py` (2 tests; auto-skips via `importorskip` when tulipy is absent). **Two empirically-verified difference classes frozen into tags**: `exact` (SMA/HMA/KAMA/RSI/MOM/CCI/WILLR/MFI/STDDEV — no recursive smoother, asserted < 1e-6) vs `definitional` (EMA/DEMA/TEMA/ATR/ADX/NATR/ROC/CMO/OBV — recursion seed/alpha/×100/OBV-seed differences, only finiteness asserted) vs `no_lib` (plus_di/minus_di/lrslope/supertrend/ha_o — documented skip). **Key engineering point**: tulipy truncates the warm-up prefix and returns a shorter array (the opposite of TA-Lib, which keeps the NaN prefix at full length — moneta §2.3 anti-pattern #1's "delete the prefix rows" trap) → the cross-check **must align on the tail**. §3.3 gains the K1b section + §5 test table +2 rows. **Feature set unchanged** (FEATURE_VERSION stays 3). Tests 98→**100** (ZH=EN), pyflakes clean |
