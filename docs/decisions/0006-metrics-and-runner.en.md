# 0006 — Metrics + Run Pipeline (R5 + reproducible runs + O17 financing interface closure)

> **Chinese**: [0006-metrics-and-runner.md](./0006-metrics-and-runner.md)
>
> Scope of this decision doc: **R5 metrics** (formulas frozen) + **run pipeline**
> (`lyra run`, assembling 0004-compiled signals + 0005 per-bar trade engine into a
> reproducible per-instrument evaluation) + **report & run artifacts** +
> **reproducibility (I5)** + **O17 per-trade financing counter interface closure**
> (R4 trading-day compliance NOT closed, see D6 / Batch 1 H1). This feature does
> **not** do the R12 interactive workflow (track/context/compare/merge) — it builds
> on 0006's run artifacts and gets its own doc (see D1).

## Metadata

| Field | Value |
|---|---|
| ID | 0006 |
| Title | Metrics + Run Pipeline (`lyra run` + R5 metrics + report + reproducible runs) |
| Status | implemented |
| Owner | `ttrrei` |
| Created | 2026-11-08 |
| Related proposals | `docs/proposals/` (none — driven by R5 + O17) |
| Related requirements | `docs/requirements.md` §R5 (metrics), §R6/R7 (data + run artifacts) |
| Related HLD | `docs/hld.md` §1, §6, §8 |
| Related decisions | 0002 (data contract / snapshot), 0003 (features + snapshot identity / FEATURE_VERSION), 0004 (YAML compiler → signal SQL), 0005 (per-bar trade engine, `trade()`/`simulate()`) |
| Open items | O17 (financing day-basis): the **per-trade counter interface is closed here** (each trade countable individually); **R4/O15 trading-day compliance is NOT closed** — the natural-day default is a **documented known deviation** (H1 held, see D6 / Open item); O-0005-1 accordingly **partially closed** |

## 1. Problem

Strategy conditions are compiled to deterministic signal SQL by 0004 and filled
per-bar by 0005. But **nothing assembles them into a reproducible, metric-defined,
report-producing, artifact-identified run** (R5 + I5). Without it, no "direction"
can be judged, and the R12 workflow has no footing. 0006 fills this gap: **`lyra run`**.

## 2. Background

- **nova equivalent**: `nova/src/nova/runner.py` (per-instrument, signal → trade →
  `summarize`, per-instrument isolation) + `nova/src/nova/metrics.py::summarize`
  (`trade_count` / `net_trade_return_sum` / `annualized_trade_return_score` /
  `mean_net_trade_return` / `win_rate` / `yearly_net_trade_return_sum` /
  `monthly_entries` / `every_full_month_has_entry` / `passes_initial_screen`).
  nova computes **no Sharpe / profit factor / CAGR / HWM** (consistent with R5); nova
  is the **authoritative port source**: metric formulas copied, only swapping the
  signal source to 0004's compiled SQL output, and nova's built-in matcher for 0005's
  `simulate()`.
- **lyra data model** (ready):
  - `lyra build` produces feature wide-table Parquet (0003); `catalog.Catalog` registers
    `feature_tables` (view → path → kind).
  - 0004 `compile_sql(spec)` yields `SELECT instrument, time, entry_long,
    entry_short [exit_long, exit_short] FROM <spec.view> ORDER BY instrument, time`;
    `spec` carries `stop_loss_pct` / `direction` / `max_holding_bars` / costs
    (slippage/commission/financing bps) / `view`.
  - The feature wide table (0003) **includes OHLCV**, so the runner takes OHLC bars +
    signals from the same view.
  - 0005 `simulate(plan, bars, *, trading_days=None)` (``bars`` is a list of dicts
    with OHLC + the 4 boolean signal keys) already fills per-bar;
    `Trade.net_return` is the net field; supports `trading_days` override (O15/O17).
- **R5 metric definitions (frozen; see requirements §R5)**: see Appendix A, D4.
- **O17 financing day-basis**: 0003 D10 set "per session_day + calendar days", 0005
  engine already supports the `trading_days` override; 0006 lets the runner count days
  per trade's entry/exit bar time (natural-day default) — **closes the per-trade counter
  interface capability, but R4 trading-day compliance is NOT closed** (D6, Batch 1 H1
  correction).
- **User stance** (consistent): lightweight, no over-engineering (B6); 0005 established
  "one reusable engine + parallel direction research", 0006 continues that shape.

## 3. Design

### 3.1 What we do

**New files**:
- `lyra/metrics.py` — R5 pure metric functions (`annualized_return` / `win_rate` /
  `expectancy` / `avg_bars_held` / `_monthly_rows` / `compute_metrics`), definitions
  in D4; **does not compute Sharpe / profit factor / CAGR / HWM / Sortino** (R5
  forbids them); safe on empty / single / all-loss / all-win / zero-span (returns
  `None`/`0.0`, no exception).
- `lyra/runner.py` — run pipeline:
  1. Parse strategy YAML → `StrategySpec` (reuse 0004 `strategy_schema` + `compiler`).
  2. `sql = compile_sql(spec)`; DuckDB-query `spec.view` for per-bar
     `instrument/time/OHLC/entry_long/entry_short`.
  3. **Per-instrument processing** (D3, Batch 1 M1: not true streaming, only I16
     isolation): each instrument in an isolated DuckDB scope, fetch bars (OHLC dicts) +
     attach the 4 boolean signal keys, then
     `simulate(plan, bars, trading_days_for=<None per-trade natural-days | a user-injected
     trading-day counter>)` → `Trade[]` (flat `--financing-days` removed, 0004 C2).
  4. Per-instrument `compute_metrics` (D4); **never aggregate across instruments** (I7).
  5. Write run artifacts (D8) + report (D7) + reproducibility manifest (D5).
- `lyra/cli.py` — add `lyra run` (+ `lyra report` to re-render artifacts) subcommands.

**Modified files**:
- `lyra/trade_engine.py` — **no semantic change**, only confirm `simulate(..., trading_days=...)`
  is 0006's financing entry (0005 batch 3 already implemented).
- `pyproject.toml` — no new core deps (duckdb / numpy / pyarrow already in 0003/0004).

**Run artifact layout** (D8, local mirror, `~/.lyra/<workspace>/runs/` or repo `runs/`,
both gitignored per repo policy):
```
runs/<name>/<YYYYMMDD>/<run_id>/      # Batch 1 H3: scoped by run_id, never shared
  manifest.json      # D5 reproducibility manifest + all four artifacts' SHA256
  signals.parquet    # per-bar signals (instrument,time,side,...); written even if zero rows
  trades.parquet     # Trade[] (0005 output); written even if zero rows
  metrics.json       # per-instrument + summary (D4); hashed in manifest (Batch 1 M2)
  report.md          # D7 human-readable report
```

### 3.2 What we do NOT do (Out of Scope)

- **R12 interactive workflow** (track / context / compare / merge / new-version /
  lessons / hypothesis) — **not in this feature**, own doc (0007). Rationale: it builds
  on 0006's run artifacts (comparing "two runs' metrics.json"), is large, needs its own
  adversarial pass; user is explicit "lightweight, one foundation, parallel directions";
  the workflow should stand on validated runs.
- **Position sizing/leverage/margin/account equity/account CAGR** — R9 / I9
  (trade-level research, no sizing).
- **OCI push of runs** (R7 push) — this feature writes local mirror only; OCI push is
  R7's own feature (0006 artifacts can be consumed by it).
- **Live/non-backtest execution**, **multi-strategy orchestration**, **portfolio synthesis**
  (forbidden by I7).

### 3.3 Boundaries

- **Reads**: `catalog.duckdb` + feature wide-table Parquet (`data/`, R6; `lyra build` produces).
- **Writes**: `runs/<name>/<date>/` (local mirror, R6/R7/B13; **does not write git**, R8 no side effects).
- **Alpha boundary**: 0006 **only reads** registered feature views (0003's alpha output);
  adds/changes no alpha features; `FEATURE_VERSION` (0003 D7) feeds the manifest's reproducibility.
- **moneta/nova compat**: metric formulas line-for-line with nova `metrics.py`
  (cross-verifiable); but signal source (0004 compiled SQL) and engine (0005 `simulate`)
  are lyra's own, no runtime sharing with nova.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I1 | Causality: signal determined by past-only windows (0004 guarantees, 0006 does not break) | I1 (HLD §4) / 0004 |
| I5 | **Reproducible**: same manifest (strategy+data+versions+params+financing counter identity) → same `run_id`, **deterministic data artifacts** byte-identical (`signals/trades/report/metrics`); any input change → different `run_id` (see D5). **Scope**: `manifest.json`'s `generated_at` (wall clock) is the **only excluded field** — the contract is "deterministic artifacts identical, generation timestamp may vary", not every artifact including manifest byte-identical (Batch 1 M4 explicit) | I5 (HLD §4) / reinforced here |
| I7 | **Per-instrument**: each instrument reported separately; **never** synthesize cross-instrument returns/equity/portfolio score | I7 (HLD §4) |
| I8 | Monthly opportunities = actual open count (zero-open months included as 0, not dropped) | I8 (HLD §4) |
| I9 | Trade-level research: no sizing/leverage/margin/account equity/account CAGR | I9 (HLD §4) |
| I10 | Signal confirms at close, fills at next visible open (via 0005 `simulate`) | I10 (HLD §4) / 0005 |
| **I15** (new) | **Metric definitions (R5 frozen)**: annualized = Σnet / calendar-years (365.25d); win_rate = wins/total; expectancy = mean(net); avg_bars_held = mean bars in position; per-month rows = (actual openings / net sum / win rate / avg bars held), zero-open months kept as 0. `score` = `annualized`. **Forbids** Sharpe / Sortino / profit factor / CAGR / HWM / portfolio synthesis | new here / R5 |
| **I16** (new) | **Per-instrument isolation**: within a run each instrument is processed in an isolated DuckDB scope + isolated engine instance; one instrument's failure is recorded in the manifest and raised, but does **not** silently block other instruments' completed aggregation (unless `--strict`) | new here / I7 / B6 (lightweight) |

## 5. Tests

**Metrics (`lyra/metrics.py`)**:

| Test | Scenario |
|---|---|
| `test_metrics_annualized_calendar_years` | net-sum / calendar-years; span 0 → `None` (no error) |
| `test_metrics_win_rate_zero_trades` | no trades → `0.0` (not NaN/raise) |
| `test_metrics_expectancy_matches_mean` | expectancy == mean(net) |
| `test_metrics_avg_bars_held` | mean bars in position; no trades → `0.0` |
| `test_metrics_single_trade` | single: win_rate=1 or 0; expectancy=that trade |
| `test_metrics_all_loss` | all loss: win_rate=0; annualized negative |
| `test_metrics_deterministic_and_score_equals_annualized` | same input twice → field-for-field equal; `score == annualized` |
| `test_metrics_monthly_rows_zero_open_months_kept` | every calendar month in the window appears; zero-open months kept as 0 (I8) |
| `test_metrics_forbidden_fields_absent` | result has **no** sharpe / profit_factor / sortino / CAGR / HWM (R5 forbids) |

**Run pipeline (`lyra/runner.py`)**:

| Test | Scenario |
|---|---|
| `test_run_single_instrument_matches_engine` | single-instrument run trades == direct `simulate` (field-for-field, diff=0) |
| `test_run_multi_instrument_isolated` | 3 instruments, no cross-talk; one `metrics.json` entry each; no portfolio score |
| `test_run_reproducible_identical_manifest` | same input run twice → `manifest.json` + `metrics.json` + `trades.parquet` byte/field identical |
| `test_run_reproducible_perturbation_fails` | change strategy param/data/version → `run_id` changes (I5 fail-fast) |
| `test_run_id_covers_consumed_feature_values` | consumed feature value (`mid_c`) changes → `run_id` changes; only unconsumed column (`volume`) changes → `run_id` unchanged (Batch 1 H2) |
| `test_run_id_covers_trading_counter_behavior` | two financing counters with different behavior → different `run_id` (Batch 1 H2) |
| `test_run_dir_scoped_by_run_id_no_stale_trades` | zero-trade rerun → its own `run_id` dir, zero-row `trades.parquet`, manifest does not hash another dir's stale trades (Batch 1 H3/M2) |
| `test_run_manifest_hashes_metrics_json` | `metrics.json` is hashed in `manifest` and matches (Batch 1 M2) |
| `test_metrics_zero_open_month_in_middle` | trade at start/end, zero-open month in middle → that month's all-zero row is kept, end rows normal (Batch 1 M5) |
| `test_run_monthly_zero_openings_counted` | data with zero-open month → monthly series includes 0, not dropped (I8) |
| `test_run_empty_produces_zero_trades` | no signals → empty trades, safe metrics, run still emits manifest (no crash) |
| `test_run_manifest_sha256s` | `manifest.json` SHA256 per artifact matches actual file hash |
| `test_run_financing_wired` | long held across days → financing by per-trade entry/exit (`simulate` default `trading_days=None` → **natural days**, H1 known deviation); short hold → 0; the interface accepts a `trading_days_for` counter (flat `--financing-days` removed, 0004 C2) |
| `test_run_report_fields` | `report.md`/`metrics.json` include all R5 metric fields + run metadata (no sizing/$ PnL) |
| `test_run_instrument_failure_isolated` | one instrument data error → recorded in manifest, visible; others' aggregation unaffected (I16) |

**Cross-implementation**: metric functions vs nova `lyra/metrics.py` on identical input (definitions match).

## 6. Rollback

- **Code**: revert 0006's implementation commit (`lyra/metrics.py`, `lyra/runner.py`,
  `lyra/cli.py` `run`/`report`, related tests) to return to 0005; 0005 `simulate`'s
  `trading_days` param existed independently in 0005, unaffected by reverting 0006.
- **Data**: delete the corresponding `runs/` artifacts (re-runnable to rebuild); `data/`, catalog untouched.
- **Compat**: after rollback 0004/0005 still run independently; moneta/nova unaffected (lyra self-contained).

## 7. Approval

- [x] User review (user directive "make decisions per your recommendation and record them" — see Appendix A)
- [x] AI review (same-session self-check + adversarial self-check; see Appendix B/C)
- [x] Tests all green
- [x] 332-strategy regression: N/A (no moneta 332 dependency; synthetic data + nova cross-check)
- [x] OCI end-to-end: N/A (0006 writes local runs mirror only; OCI push is R7's own feature)

## 8. Revision log

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.1 | Draft: R5 metrics + `lyra run` pipeline + report + run artifacts + reproducibility manifest + O17 financing closure; R12 workflow explicitly moved out (→0007). |
| 2026-11-10 | 0.2 | **Batch 1 adversarial review disposition** (H2/H3/M1/M2/M3/M4/M5 accepted and landed, H1 held): `run_id` data identity now covers all feature columns consumed by the strategy SQL + counter behavior fingerprint (H2); run dir scoped by `run_id`, zero-trade results still write a zero-row Parquet, manifest hashes all four D8 artifacts (H3/M2); D3 clarified as not true streaming (M1); D6/H1 wording corrected to "interface capability closed, R4 trading-day compliance NOT closed, natural-day default is a documented known deviation"; I5 states `generated_at` is the sole excluded field (M4); test matrix gains 5 Batch 1 regressions. |
| 2026-11-08 | 0.2 | **Align to R5**: code-phase adversarial self-check found the first-draft D4/I15/B3/H5/§5 test table introduced Sharpe / profit factor (R5 forbids, nova lacks them). Rewrote D4/I15/B3/H5/§5 to the R5 frozen set (`avg_bars_held` + per-month rows + report metadata), added `test_metrics_forbidden_fields_absent`; code was already R5-correct, doc-only correction. |

---

## Appendix A: Design decisions (incl. user-ruling landings)

**D1 (scope — user-recommended execution)**: 0006 = **execution core** (`lyra run` +
R5 metrics + report + run artifacts + reproducibility + O17 closure). **R12 interactive
workflow moved out** (→ 0007, own adversarial pass). Rationale: the workflow builds on
0006's run artifacts; large; user "lightweight, one foundation, parallel directions";
avoid turning 0006 into "transition engineering" (user #73's critique of codex).

**D2 (data path)**: runner reads `catalog.duckdb`'s registered `spec.view` (0004
compiled SQL target). OHLC bars and signals share the same view (0003 wide table has OHLCV).
**No new data pipeline**.

**D3 (per-instrument processing)**: each instrument in an isolated DuckDB scope, JOIN
`plan.sql` (`SELECT instrument,time,entry_long,entry_short,exit_long,exit_short FROM <view>`)
with the same view's OHLC (`mid_o/mid_h/mid_l/mid_c`) on `(instrument,time)` to produce
per-bar **dicts** (`instrument/time/mid_* /entry_*/exit_*`, boolean signals), fed directly
to 0005 `simulate(plan, bars, trading_days=...)` (**bars are a dict sequence, not
separate o/h/l/c + signals arrays**). **Never synthesize cross-instrument** (I7).
> **Batch 1 M1 (clarified)**: "streaming" here is a **misnomer** — per-instrument only means
> I16 isolation (one instrument's failure/isolation does not affect others); the runner reads
> the full OHLC for that instrument via `fetchall()` in one pass, which is **not true
> streaming** (no incremental per-bar processing). True streaming is a **follow-up
> enhancement**, out of 0006 scope.

**D4 (metric definitions, I15, R5 frozen)**:
- `annualized = Σnet / (span_days/365.25)`; span 0 → `None`. `score` (annualized score)
  = same formula as `annualized` (R5 "annualized score = net arithmetic sum ÷ full
  calendar years (365.25d)").
- `win_rate = wins / total` (no trades → `0.0`).
- `expectancy = mean(net)` (no trades → `0.0`).
- `avg_bars_held = mean bars in position` (no trades → `0.0`).
- **Per-month rows** (every calendar month in the window): `actual_entries` (actual
  openings, zero-open months kept as 0 — I8) / `net_return_sum` (that month's net sum) /
  `win_rate` / `avg_bars_held`.
- **Forbids** Sharpe / Sortino / profit factor / CAGR / HWM / cross-instrument synthesis
  (R5/I7/I9).
- **Report metadata** (R5 must list): strategy name, timeframe, instrument list,
  time window, feature snapshot id, git commit, date (date = data window,
  deterministic; generation time only in manifest).

**D5 (reproducibility manifest, I5)**: `manifest.json` records
`{run_id, strategy_yaml_sha256, FEATURE_VERSION, engine_version, compiler_version,
duckdb_version, data_snapshot_ids, params{stop_loss_pct,direction,max_holding_bars,
slippage/commission/financing_bps}, git_commit, generated_at}`;
`run_id = sha256(all above except generated_at)`. Same manifest → same `run_id`; any change → changes.
(Extends 0003 snapshot identity; aligns with nova `runner.py`'s `run_id` mechanism.)
> **Batch 1 H2 (landed)**: `run_id`'s data identity now covers **every input the strategy SQL
> actually consumes** — `_data_digest` hashes the OHLC columns **plus all columns in
> `plan.features_used`** (perturbing a consumed feature value → `run_id` must change); the
> financing counter's **behavior fingerprint** `counter_fingerprint` (evaluated on a fixed
> probe interval) is part of `run_id` (two counters that bill differently → `run_id` must
> differ).

**D6 (O17 interface closure)**: 0005 engine's `simulate(..., trading_days=None)` **already
computes per-trade** days from each trade's entry/exit **bar time** (`_day_count`:
`trading_days=None` → per-trade from timestamps; a `trading_days_for` counter → per-trade
counter). 0006's runner **defaults to passing `None`** → per-trade **natural-day** financing;
a `trading_days_for` counter can be injected for per-trade trading-day counting (the flat
`--financing-days` override was **removed**, 0004 C2).
> **Batch 1 H1 (wording corrected, IMPORTANT)**: the earlier phrasing "O17 closed here / R4
> compliant" was **inaccurate** — O17 closes the **per-trade counter interface capability**,
> but **R4/O15 require financing counted on trading days** (weekends and market holidays
> excluded), which the natural-day default does **not** satisfy (holding across a weekend
> over-counts financing). Correct statement: **the interface capability is closed** (each trade
> counted individually, `trading_days_for` in place), but **trading-day compliance is not
> closed**; the natural-day default is a **documented known deviation** pending a real trading
> calendar or a user decision (H1 held).

**D7 (report)**: `report.md` + `metrics.json`: per-instrument metric table + cross-instrument
summary (min/median/max of each metric, **not synthesis**) + run metadata (manifest
summary). **Excludes** sizing / $ PnL / account CAGR (I9/R9).

**D8 (run artifacts)**: see §3.1 layout. **All four D8 artifacts** (`signals.parquet`,
`trades.parquet`, `metrics.json`, `report.md`) are written unconditionally and **all** enter
`manifest.json` SHA256 (Batch 1 M2: a zero-row result still emits a zero-row Parquet with the
fixed schema; `metrics.json` was previously omitted from the checksums, is now included, and
a missing artifact fails closed).
Local mirror in `~/.lyra/<workspace>/runs/` (B13: out of repo) or repo `runs/` (gitignored).
> **Batch 1 H3 (landed)**: each run directory is **scoped by `run_id`**
> (`runs/<name>/<YYYYMMDD>/<run_id>/`); different `run_id`s never share a directory — a
> zero-trade rerun can no longer inherit or re-hash a previous run's `trades.parquet`. The
> checksum only proves a file is uncorrupted; directory isolation proves the file **belongs**
> to that `run_id`'s manifest.

**Open item (H1)**: the financing day-basis is currently **natural days** (0005
`_day_count`, with `trading_days_for=None` counting per-trade entry/exit timestamps) —
**the interface capability is closed, but R4 trading-day compliance is not** (see D6 Batch 1
H1 correction). Wiring a **versioned real trading calendar** (count actual trading days,
exclude weekends/holidays) requires fail-closed behavior when financing rate is non-zero, or
an explicit user ruling to adopt natural days and revise R4/O15 accordingly — this is a
**follow-up enhancement / user decision item**, not a defect; 0006 uses per-trade **natural
days** as the current default definition (documented known deviation, see D6 H1). The
`simulate(trading_days_for=...)` counter entry is already in place in 0005, allowing a
non-invasive switch to a real trading calendar.

## Appendix B: Self-check

**B1 contract reference check**: R5 (metric table) field-by-field against D4 ✓;
R6/R7 (data read / artifact write) against §3.3/D8 ✓; R9/I9 (no sizing) against §3.2/D7 ✓;
I5/I7/I8/I10 against §4 ✓; O17/O-0005-1 closure against D6 ✓.
**B2 data model check**: `compile_sql` output columns (instrument/time/entry_long/entry_short)
match runner consumption ✓; OHLC same-source from view ✓; `simulate(signals)` contract
(per-bar 1/-1/0) matches D3 ✓.
**B3 definition check**: D4 each formula cross-checked against nova
`metrics.py::summarize` (`annualized_trade_return_score` / `win_rate` /
`mean_net_trade_return` / `monthly_entries` / `every_full_month_has_entry`)
line-for-line ✓; nova also has **no Sharpe / profit factor**, consistent with R5 ✓.
**B4 invariant closure**: I1/I5/I7/I8/I9/I10 (referenced) + I15/I16 (new) cover all §5 tests ✓.
**B5 scope check**: R12 explicitly moved out (D1) ✓; out-of-scope (§3.2) consistent with
user "lightweight" ✓.
**B6 rollback check**: revert 0006 back to 0005, 0005 `trading_days` independently unaffected ✓.
**Self-check conclusion**: 2 spots found and fixed in body/appendix (explicit D4 declaration
that `score` == `annualized`; explicit D6 "open item" for calendar vs trading days). No blockers.

## Appendix C: Adversarial self-check

**H1 (high) per-instrument failure silently swallowed → aggregation skewed**
- Rebuttal/disposition: **accept**, add I16: one instrument's failure recorded in
  manifest and visible, `--strict` blocks; default does not block other completed
  aggregations (B6 lightweight). Test `test_run_instrument_failure_isolated`.
- Residual risk: low.

**H2 (high) `annualized` span 0 / single bar → divide by zero**
- Disposition: **accept**, D4 explicit "span 0 → `None`"; test
  `test_metrics_annualized_calendar_years`.
- Residual risk: low.

**H3 (high) cross-instrument synthesis (I7 violation) — runner lazily computes a portfolio**
- Disposition: **reject that approach**; D3/D7 explicit "never synthesize", summary only
  min/median/max; test `test_run_multi_instrument_isolated` asserts no portfolio field.
- Residual risk: low.

**H4 (med) "same manifest → same output" reproducibility broken by float/dict-order/timestamp**
- Disposition: **accept**, D5 `run_id` excludes `generated_at`; parquet written in fixed
  row order (instrument, time); tests `test_run_reproducible_identical_manifest` +
  `test_run_reproducible_perturbation_fails`.
- Residual risk: low.

**H5 (high) Metric set inconsistent with R5 / nova: the first-draft D4/I15 introduced
Sharpe / profit factor, but R5 explicitly says "no CAGR / HWM / Sharpe / Sortino" and
nova's `summarize` has neither**
- Disposition: **accept and correct**. The code-phase adversarial self-check found that
  `lyra/metrics.py` was already implemented to the R5 frozen set (no Sharpe / profit
  factor), but the **decision doc first draft** (D4 / I15 / B3 / H5 / §5 test table) still
  listed Sharpe / profit factor / median — doc inconsistent with code, and the doc itself
  violated R5. D4 / I15 / B3 / H5 / §5 test table were rewritten to the R5 frozen set
  (`trade_count` / `net_return` / `annualized` / `win_rate` / `expectancy` /
  `avg_bars_held` / per-month rows), and `test_metrics_forbidden_fields_absent` was added
  to lock in "no sharpe / profit_factor / sortino / CAGR / HWM".
- Residual risk: low (the code was already correct; the doc is now aligned with code + R5
  and locked by tests).

**H6 (med) O17 "closure" not real: runner uses calendar days, if O17 wants trading days then
not truly closed**
- Disposition: **partially accept** — 0006 implements with calendar days and **explicitly
  declares** the closed definition, keeping the `trading_days` override entry; "trading
  calendar" listed as a **follow-up enhancement** (open item), not a defect. Consistent with
  0003 D10 / 0005's progressive strategy (non-blocking).
- Residual risk: low (definition explicit, not misleading).

**H7 (med) bar-dict signal keys may mismatch 0005 `simulate`'s `bar.get("entry_long")`
consumption contract (column names / boolean-ness)**
- Disposition: **accept**, D3 explicit: each runner-produced bar dict must carry the 4 signal
keys (`entry_long/entry_short/exit_long/exit_short`, boolean) + 4 OHLC keys
(`mid_o/mid_h/mid_l/mid_c`) + `instrument`/`time`; 0004 already guarantees
`entry_long`/`entry_short` mutually exclusive (test "not both true").
  Test `test_run_single_instrument_matches_engine` pins it (field-for-field diff=0).
- Residual risk: low.

**M1 (med) report lacks "zero-open month" info → I8 only in metrics, not visible in report**
- Disposition: **accept**, D7 report includes "monthly opportunities (incl 0)" series;
  test `test_run_monthly_zero_openings_counted`.
- Residual risk: low.

**M2 (low) `lyra report` (re-render from artifacts) boundary unclear**
- Disposition: **accept**, §3.1 explicit `report` = read existing `runs/` artifacts and
  re-render, no data change; decoupled from `run`.
- Residual risk: low.

**M3 (low) `runs/` in gitignored repo `runs/` vs `~/.lyra/` — which not decided**
- Disposition: **accept**, D8: default `~/.lyra/<workspace>/runs/` (B13 out of repo),
  `--out` points to repo `runs/` (gitignored); mutually exclusive, neither in git.
- Residual risk: low.

**M4 (low) `run_id` excludes `generated_at` but includes `git_commit` — unstable on dirty tree**
- Disposition: **accept**, on dirty tree `git_commit` takes `HEAD^{short}+dirty` marker,
  still deterministic (same dirty state → same marker); cross-machine not comparable, local
  `run_id` authoritative (same as 0003 snapshot identity).
- Residual risk: low.

**P1 (low) `compute_metrics` empty input returns dict not exception, could be misused as "has trades"**
- Disposition: **accept**, empty input returns `{"trade_count": 0, ...}`, fields explicit;
  test coverage.
- Residual risk: low.

**Adversarial self-check conclusion**: 7 high/med + 4 med/low all dispositioned; 2
**accepted as explicit conventions** (H5 doc/code-R5 alignment correction, H6
calendar-day definition), rest **accepted with tests/invariants** (H1→I16, H2/H4/H7/M1)
or **rejected as approach** (H3 cross-instrument synthesis). No blocking defects;
implementation follows Appendix A.
