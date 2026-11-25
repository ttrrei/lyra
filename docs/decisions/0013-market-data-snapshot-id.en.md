# Decision 0013 — Market Data Snapshot ID & Cross-Feature Comparability Decoupling

> **中文**: [0013-market-data-snapshot-id.md](./0013-market-data-snapshot-id.md)
>
> Scope: Revise Decision 0009 §D13 comparability dimensions by introducing `market_data_snapshot_id` to decouple underlying market data consistency from strategy feature consumption differences.

## Meta

| Field | Value |
|---|---|
| ID | `0013` |
| Title | Market Data Snapshot ID & Cross-Feature Comparability Decoupling |
| Status | proposal |
| Owner | `ttrrei` |
| Created | `2026-11-22` |
| Related proposal | None |
| Related requirements | `docs/requirements.md` §R12 |
| Related HLD | `docs/hld.md` §4 (I5, I22), §8 |
| Supersedes | Revises 0009 §D13 rule using `data_digest` for `compare_siblings` comparability |

## 1. Problem

In 0009 D13, `compare_siblings` used `data_digest` as the first dimension to judge whether two runs are comparable. However, in `runner._data_digest`, the feature columns actually consumed by the strategy SQL are included in the SELECT query and hashed. Consequently, candidate strategies consuming different feature sets (which is the very definition of structurally distinct candidates) produce different `data_digest` values even when evaluated on identical market data, causing them to be flagged as `NOT COMPARABLE (incomparable — data_digest)`. This conflates **reproducibility identity (Run Identity)** with **horizontal comparability identity (Comparability Identity)**.

## 2. Background

- **0009 D13 Context**: To prevent runs evaluated over different data slices from being mistakenly compared side-by-side, 0009 introduced comparability checks based on `data_digest`. At the time, to ensure feature value changes altered run identity, `data_digest` incorporated referenced feature columns.
- **Pilot Empirical Evidence (2026-11-22)**: During the Round 1 pilot on `failed_breakout/pilot`, 3 structurally distinct candidates (`v02a` consuming `efficiency_24`, `v02b` consuming `rsi_12`, `v02c` consuming `bband_pctb_24`) ran on the identical 21-instrument 1h dataset. Running `lyra compare --siblings` produced:
  ```text
  comparable: NOT COMPARABLE (data_digests=3, ...)
    v02a: run <run_id_v02a> incomparable — data_digest
    v02b: run <run_id_v02b> incomparable — data_digest
    v02c: run <run_id_v02c> incomparable — data_digest
  ```
  This false incomparability blocked multi-candidate horizontal evaluations.

## 3. Plan

### 3.1 What we do

1. **Add `market_data_snapshot_id`**:
   - In `lyra/runner.py`, implement `market_data_snapshot_id(con, view, instruments)`.
   - Hash `(view name + sorted instrument list + base OHLC values time/mid_o/mid_h/mid_l/mid_c)`, **strictly omitting feature columns**.
   - Reuse `_data_digest(con, view, instruments, feature_cols=())` directly to prevent implementation drift across hash functions.
2. **Artifact Emission**:
   - Write `market_data_snapshot_id` to `metrics.json` identity section (alongside `feature_snapshot_id`, `feature_version`, and `data_digest`).
   - Write to `manifest.json` for reproducibility auditing.
3. **Preserve `data_digest` Role**:
   - Keep `_compute_run_id` payload unchanged; `data_digest` continues feeding `run_id` so that feature data perturbations still change `run_id` (I5 guarantee preserved).
4. **Revise `workflow._run_comparable_reason`**:
   - Replace the first check dimension from `data_digest` to `market_data_snapshot_id`.
   - If any run lacks `market_data_snapshot_id` (legacy runs), return `missing_market_data_snapshot_id`, degrading gracefully to `comparable=None` (unknown, never presumed comparable).
   - Retain existing `feature_version` and `feature_snapshot_id` checks.
5. **Revise `compare_siblings` & CLI**:
   - Track `distinct_market_data_snapshots` and display in compare output.

### 3.2 What we do NOT do

- Do not change `_compute_run_id` inputs or algorithms (preserves historical run_ids).
- Do not delete `data_digest` (retained in metrics and manifest for run reproducibility).
- Do not modify any metric calculations in `lyra/metrics.py`.

### 3.3 Boundaries

- **Compatibility**: Legacy runs lacking `market_data_snapshot_id` will be classified as missing identity and marked `comparable=None`.
- **Boundary with 0014**: 0013 establishes "whether runs are comparable"; 0014 solves "how to compare and rank" (cross-instrument summaries).

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I5 | Run reproducibility: identical inputs yield identical run_ids; feature perturbations change run_id | HLD §4 |
| I22 | Evidence comparability: sibling comparisons must be grounded on identical underlying market data | HLD §4 |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_market_data_snapshot_id_stable_across_features` | Strategies consuming different features share identical `market_data_snapshot_id` but distinct `data_digest` |
| `test_data_digest_and_run_id_change_on_feature_perturbation` | Perturbing feature values changes `data_digest` and `run_id` while leaving `market_data_snapshot_id` intact |
| `test_market_data_snapshot_id_changes_on_ohlc_perturbation` | Perturbing base OHLC changes both `market_data_snapshot_id` and `data_digest` |
| `test_compare_siblings_comparable_across_different_features` | Sibling candidates consuming different features are judged `comparable=True` |
| `test_compare_siblings_missing_market_data_snapshot_unknown` | Legacy runs missing `market_data_snapshot_id` yield `comparable=None` with reason `missing_market_data_snapshot_id` |

## 6. Rollback

- **Code**: Clean revert via git commit C3.
- **Data**: New runs with `market_data_snapshot_id` will simply have the extra JSON field ignored by older code without breaking.

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Tests all green
- [ ] Validated on real pilot data

## 8. Revision History

| Date | Version | Change |
|---|---|---|
| 2026-11-22 | 1.0 | Initial draft: introduce `market_data_snapshot_id`, revise 0009 D13 comparability criteria, decoupling feature differences from market data consistency. |
| 2026-11-25 | 1.1 | Decision 0016: the field is written only to newly created runs; completed historical runs are never backfilled or rewritten, and missing identity remains `missing_market_data_snapshot_id`. |
