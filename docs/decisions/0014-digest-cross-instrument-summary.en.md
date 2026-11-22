# Decision 0014 — Candidate Pool Digest Cross-Instrument Summary & Median Re-sort

> **中文**: [0014-digest-cross-instrument-summary.md](./0014-digest-cross-instrument-summary.md)
>
> Scope: Enhance `lyra digest` with macro cross-instrument robustness summaries, and restructure `lyra compare --siblings` ranking to sort by cross-instrument median annualized return, preventing single-instrument selection bias.

## Meta

| Field | Value |
|---|---|
| ID | `0014` |
| Title | Candidate Pool Digest Cross-Instrument Summary & Median Re-sort |
| Status | proposal |
| Owner | `ttrrei` |
| Created | `2026-11-22` |
| Related proposal | None |
| Related requirements | `docs/requirements.md` §R5, §R12 |
| Related HLD | `docs/hld.md` §4 (I7, I22), §8 |
| Supersedes | None (enhances workflow and CLI presentation logic) |

## 1. Problem

In the existing `lyra digest`, each active branch only displays raw one-liners for up to 8 instruments, with remaining instruments truncated (`(+13 more instruments omitted; see report)`), leaving researchers without macro cross-instrument statistics (such as median annualized return, median net return, profitable instrument ratio, or worst instrument). Concurrently, `compare_siblings` used the single highest per-instrument annualized return (`best`) for ranking, directly contradicting the tool's own warning against choice bias and misleading researchers and AI into single-point hill climbing and overfitting.

## 2. Background

- **R5 and I7 Contract**: The system enforces strict per-instrument isolation (I7: Per-instrument reporting), strictly forbidding portfolio equity aggregation. However, when evaluating the generalization power of candidate strategies across markets, cross-instrument statistical distributions (such as median and profitable ratio) are essential indicators of robustness.
- **Pilot Empirical Evidence (2026-11-22)**: During the Round 1 pilot on `failed_breakout/pilot`, 21-instrument evaluation lines were truncated, preventing immediate assessment of whether positive returns were widespread across instruments or merely an outlier on a single instrument; simultaneously, `compare` cherry-picked `best`, masking severe losses across the remaining instruments.

## 3. Plan

### 3.1 What we do

All computations are pure in-memory projections performed over data already loaded by `_runs_for_branch`, introducing no new external dependencies or database tables.

1. **`render_digest()` per-branch enhancements**:
   - Compute cross-instrument medians: `median_annualized`, `median_net_return`, `median_expectancy`;
   - Compute profitable instrument ratio: `profitable_instrument_ratio = count(ann > 0) / len(universe)`, where universe = `per_instrument keys ∪ instrument_failures`, strictly including zero-trade and failed instruments;
   - Sample size and execution completeness: report total trade count, count of instruments with <20 trades, and failure count. Flag `[Incomplete]` if failures exist or actual evaluated instruments < expected universe;
   - Surface worst instrument: report the worst instrument by annualized return to expose single-instrument vulnerability;
   - Compress instrument one-liners to maintain an 8-branch active pool digest size of ≤ ~5KB.
2. **`compare_siblings()` ranking and highlighting**:
   - Re-rank sibling branches by `median_annualized` descending;
   - Retain the single highest instrument as `best_single_instrument` explicitly labeled "single best, not aggregate" (`最好的一次，非综合分`);
   - Output top-level set summary: `median_annualized`, `min_annualized`, `median_profitable_ratio`, `incomplete_count`;
   - Incomparable runs (`comparable is False` or `comparable is None`) are listed with specific reasons and excluded from the ranking.
3. **No pool_score**:
   - Avoid artificial composite score formulas (no pool_score or arbitrary weightings), preserving transparent multi-dimensional metrics.

### 3.2 What we do NOT do

- Do not alter metric formulas or definitions in `lyra/metrics.py` (R5 freeze maintained);
- Do not construct cross-instrument portfolio equity curves or calculate portfolio Sharpe/CAGR;
- Do not add database or disk persistence tables for intermediate statistics;
- Optional exit-month diagnosis is either completed or explicitly deferred to Plan 3 §2.0.

### 3.3 Boundaries

- **Read-only**: `render_digest` and `compare_siblings` remain strictly read-only.
- **Null and error handling**: Instruments with 0 trades count in the universe denominator with 0.0 annualized return; failed instruments count in the denominator and trigger an Incomplete flag.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I7 | Per-instrument isolation: no portfolio curve constructed; medians serve solely as distribution reference | HLD §4 |
| I22 | Evidence chain comparability: only comparable candidates evaluated on identical market data are ranked | HLD §4 |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_0014_run_stats_math` | Validate mathematical accuracy of median/min/ratio calculations |
| `test_0014_run_stats_empty_runs` | Safe handling for empty runs / zero trades |
| `test_0014_run_stats_single_instrument` | Single-instrument dataset boundary case |
| `test_0014_run_stats_zero_trade_instruments` | Zero-trade instruments counted in denominator, not in profitable numerator |
| `test_0014_run_stats_instrument_failures` | Failed instruments counted in denominator and trigger Incomplete flag |
| `test_0014_compare_siblings_median_sort` | Sibling comparison properly sorts by median_annualized descending and excludes incomparable runs |
| `test_0014_digest_size_budget` | Digest text length for 8 active branches stays ≤ 5KB |

## 6. Rollback

Clean revert via git commit C4. All changes are pure Python presentation and aggregation logic, without impacting saved data schemas.

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Tests all green
- [ ] Validated on real pilot data

## 8. Revision History

| Date | Version | Change |
|---|---|---|
| 2026-11-22 | 0.1 | Initial proposal: digest cross-instrument summary and compare median re-sorting. |
