# Decision 0010 — temp/ Strategy Migration Triage

> **中文**: [0010-temp-triage.md](./0010-temp-triage.md)
>
> Scope: Promote / drop / archive triage for 146 Nova campaigns + 132 Moneta S-series under `strategies/temp/` (HLD §8 row 10, added in #99).

## Meta

| Field | Value |
|---|---|
| ID | `0010` |
| Title | temp/ Strategy Migration Triage |
| Status | proposal |
| Owner | `ttrrei` |
| Created | `2026-11-14` |
| Related proposal | None |
| Related requirements | `docs/requirements.md` §R8, §R12 |
| Related HLD | `docs/hld.md` §8 |
| Supersedes | None |

## 1. Problem

Systematically triage, sanitize, validate, and manage the corpus of 278 candidate strategies inherited from legacy repositories (Nova, Moneta) into Lyra. These historical artifacts cannot be used directly as valid strategies (some reference outdated feature definitions, lack verification on Lyra data, and lack Track governance), nor should they be discarded arbitrarily. A reproducible triage mechanism adhering to the Alpha boundary and machine gates is required.

## 2. Background

- **Corpus Status**:
  - **Nova campaign**: 146 YAMLs + 146 `meta.json` files located at `strategies/corpus/nova_campaign/<family>/<hex>/` (or local `temp/`). All are 60m single-timeframe strategies. All 146 IDs are unique. 122 pass `lyra validate`, 24 fail due to referencing `rsi_14` (Lyra feature layer registers `rsi_12` only); 1 special case `directions_volatility_expansion` is byte-for-byte identical to the official repository baseline.
  - **Moneta S series**: 132 records originally in Python code (inside the Moneta repo, not copied into Lyra), indexed in temp/corpus solely by `_index.json` with initial verdict=null.
- **Historical Decisions**:
  - **O18 ruling (2026-11-11)**: Legacy performance from Nova/Moneta cannot be used directly; any strategy entering Lyra must be recomputed on Lyra's actual bar dataset.
  - **User ruling (2026-11-14)**: Nova migrated strategies use a dedicated track ID `nova`; Moneta S series has no direction attribution and remains in temp/ for registration; the work requires both procedural correctness and content correctness.
  - **F2 ruling**: Triage verdicts are appended to OCI corpus `_index.json` (append-only) and do not enter git.

## 3. Plan

### 3.1 What we do

1. **Target and Inventory**:
   - The authoritative inventory is OCI corpus (`strategies/corpus/…` + `_index.json`). Local temp/ originals are read-only if present, or pulled from OCI if absent. If Moneta 132 source files are missing on both sides, the gap is recorded and triage uses available materials.
   - The initial triage round does not process all 278 items at once. Instead, a subset of 1 direction family (20–40 items) is triaged as an experimental testbed, with item-by-item verdicts confirmed by the user.
2. **Three-State Verdict Criteria**:
   - **promote**: Passes `lyra validate` (valid syntax, existing features, compilable SQL) and possesses research value. Copied to `directions/<family>/nova/v<NN>.yaml` with a provenance comment header appended (source ID, source path, content sha256, hypothesis, Nova historical pass count, triage date and verdict). The rest of the file remains byte-for-byte unchanged.
   - **drop / archive**: Fails validation (e.g. 24 rsi_14 cases) or shows invalid historical performance (pass=0). Kept in temp/ corpus without migration; marked with `verdict: archive` in index with specific reason (e.g. pending rewrite to rsi_12).
   - **duplicate**: Byte-for-byte identical to baseline (e.g. `directions_volatility_expansion`). Not migrated; index marked with `verdict: duplicate_of_baseline`.
   - **keep-in-temp**: All 132 Moneta S-series items remain registered in temp/ without migration to any direction (`verdict: keep_in_temp`).
3. **Ingestion and Re-run Workflow (O18 Mandate)**:
   - Promoted strategies enter `strategies/<family>/nova/` with track ID `nova`.
   - Standard `lyra run` must be executed across Lyra live feature data (21 instruments 1h) to produce official run artifacts. Relying on Nova historical metrics is strictly prohibited.
4. **I21 Active Cap (8 active/track) Compliance**:
   - Ingestion does not mean activating all candidates simultaneously. Track `nova`'s `active_branches` activates at most 8 candidates based on validation pass and initial performance ranking. Remaining items reside on disk and index as inactive, managed via `lyra prune` and explicit rotation.

### 3.2 What we do NOT do

- Do not migrate all 278 strategies at once without oversight.
- Do not commit real strategy YAMLs, real performance figures, or batch archives to git (strictly adhere to Alpha boundary).
- Do not increase the I21 limit of 8 active branches per track.
- Do not rewrite feature definitions to re-register ghost indicators like `rsi_14`.

### 3.3 Boundaries

- **OCI Boundary**: Corpus inventory and appended verdicts live in OCI `strategies/corpus/**/_index.json`, adhering to append-only semantics (F2 ruling).
- **Git Boundary**: Only triage tooling (e.g. `scripts/triage_0010.py`) and decision/report documentation enter git. Strategy YAMLs and run artifacts remain strictly in workspace / OCI.
- **Boundary with 0012**: 0010 governs legacy corpus triage and baseline ingestion; 0012 governs how ingested candidates participate in multi-candidate batch evolution.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I17 | OCI two-tier immutability & append rules: strategy files immutable, indices append-only | HLD §4 |
| I18 | Track isolation & identity binding: all Nova migrated strategies belong to track `nova` | HLD §4 |
| I21 | Active branch limit gate: at most 8 active branches per track | HLD §4 |
| O18 | Metrics must be recomputed: strategies entering Lyra must re-run on Lyra bars | Ruling O18 |
| B13/B14 | Alpha boundary: strategies and run artifacts remain in workspace, never in git | Proposal |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_triage_0010_dry_run` | Verify triage script dry-run idempotency without side effects |
| `test_triage_promoted_validate` | Verify 100% of promoted candidates pass `lyra validate` |
| `test_triage_duplicate_skipped` | Verify baseline duplicate items are skipped |
| `test_triage_provenance_comments` | Verify strategy plan_hash matches original after provenance comment addition |
| `test_triage_i21_active_cap` | Verify track `nova` activates strictly ≤ 8 candidates |

## 6. Rollback

- **Code**: Directly revert git commits containing the triage script and docs.
- **Data**: Remove corresponding `strategies/<family>/nova/` and run artifacts from workspace; update OCI append-only index to mark retired status if needed.
- **Compatibility**: No engine modifications; zero breaking impact on baseline strategies.

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Tests all green
- [ ] OCI end-to-end verified

## 8. Revision History

| Date | Version | Change |
|---|---|---|
| 2026-11-14 | 0.1 | Initial draft: input inventory, naming conventions, and three-state triage definitions. |
| 2026-11-22 | 1.0 | Complete standard decision document structure (Problem, Boundaries, Invariants, Tests, Rollback) aligned with HLD §8 and P1. |
| 2026-11-23 | 1.1 | Restored the vp1_r06 naming convention: branch names derive from the last two number runs of the Nova id (`campaign_failed_breakout_p1_r06` → `vp1_r06`); must match `_VNN_RE`/`_BRANCH_RE` (digit directly after `v`, else UNCLASSIFIED and I17-illegal); the original id stays traceable via `provenance.source_id` and the temp index; per-direction rNN collisions verified absent. Four-layer validation matrix (user ruling #3: program correctness and content correctness): L1 `lyra validate` passes for all (program compliance), L2 byte-identical to the direction baseline `v01.yaml` (content dedup → duplicate), L3 provenance comment block appended with plan_hash unchanged (content traceability), L4 track `nova` activation ≤ 8 (I21 active-branch cap). Deliverables list: OCI corpus `_index.json` three-state verdicts (promote/archive/duplicate/keep_in_temp, append-only per F2), promote results `directions/<family>/nova/vNN.yaml` (worktree, to be pushed, never committed), and the action-log entry. |
