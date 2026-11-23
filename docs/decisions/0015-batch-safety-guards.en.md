# Decision 0015 — Batch Candidate Safety Guards and Records

> **中文**: [0015-batch-safety-guards.md](./0015-batch-safety-guards.md)
>
> Scope: lock track costs before `apply-batch` adoption, label structural similarity and complexity, and archive real batches in the workspace.

## Metadata

| Field | Value |
|---|---|
| ID | `0015` |
| Title | Batch candidate safety guards and records |
| Status | Proposal |
| Owner | `ttrrei` |
| Created | `2026-11-23` |
| Related proposal | None |
| Requirements | `docs/requirements.en.md` §R4, §R5, §R9, §R12 |
| HLD | `docs/hld.en.md` §2.3, §4, §8 |
| Supersedes | None |

## 1. Problem

Batches can currently adopt candidates that change execution costs without an explicit guard, and they do not flag branches that only change a window or threshold. Real batches also lack a traceable workspace record for proposals, rejections, run outcomes, and branch decisions.

## 2. Context

- Decision 0012 requires 3–4 structurally distinct candidates per batch, within one direction/track, with costs matching the baseline.
- `ExecutionMeta` stores the four cost fields as `float | None`: omitted values remain `None`, while explicit zero remains `0.0`. The trade engine treats both as zero for cost calculation, but the adoption guard preserves the distinction so an omitted value is not mistaken for an explicit declaration.
- `stop_loss_pct` is not an optional cost: the schema normalizes it to the mandatory `0.02`. It is excluded from the four-field cost comparison, while both candidate and baseline remain subject to the mandatory stop contract.

## 3. Decision

### 3.1 What changes

1. Require each `apply-batch` bundle to contain 3–4 candidates sharing one direction/track. During complete preflight, load that direction's shared read-only `v01.yaml` baseline. Compare all four cost fields individually, preserving the distinction between `None` and explicit zero; candidates within a batch must also agree. Any mismatch rejects the entire batch before writes and explains how to fix it. If all four fields are zero or omitted, print a prominent warning, but allow adoption when they match the baseline.
2. Add pure functions `ast_complexity(spec)` and `structural_signature(spec, registry)` to `strategy_schema`. Complexity reports feature references, AST nodes, leaves, maximum depth, and entry/exit condition counts. The signature describes long/short entry and exit trees independently; it captures node structure, operators, and normalized features while retaining constants, windows, and temporal operator bar counts as parameters. Build the normalization map from the complete registered-name set passed by the registry: replace only trailing, underscore-delimited segments in `{6, 12, 24, 60, 120}`. Embedded digits remain unchanged. Alpha/unknown names are not mapped and remain as written. Classify candidates as `structural_change`, `parameter_only`, or `identical`; report exit-tree differences separately as `exit_structure_changed`. Complexity and signature are informative only and never reject a candidate.
3. Archive each real submission (excluding dry-runs), including zero-write preflight rejections, by writing the original bundle and `result.md` to workspace `research-batches/<direction>/<track>/batch-NNNN.*`. Number batches monotonically within that directory; validate path segments with the existing identifier rules and keep paths inside the workspace. Record proposal, preflight rejection and reasons, adoption, OK/PARTIAL/failure counts, each actual run ID (or why none was produced), and branch decision slots. Archive failures emit a warning only and do not alter adoption/run results. Archives and real strategy content never enter git.
4. Add a compact signature classification hint for the latest candidate to the digest; show complexity and similarity to active same-track branches in apply-batch stdout and the workspace result.

### 3.2 Out of scope

- Do not hard-reject structural similarity, complexity, or sample size; do not add a BatchItem override field.
- The 3–4 candidate count and shared direction/track are P3 batch-shape checks, not performance thresholds.
- Do not change `metrics.py`, the trade engine, or R5 metric semantics. Do not add a GA, database, model API, pool score, or Holdout.
- Do not write batch archives, real hypotheses, strategies, or performance into git.

### 3.3 Boundaries

- Bundle-shape and cost checks run before any workspace write, and dry-run and real apply use the same preflight logic. Real submissions attempt an archive even when preflight rejects them.
- Build an explicit normalization mapping for every registered feature and enforce coverage in tests. Unknown/alpha feature names remain unchanged; do not guess by stripping digits.
- Workspace archives are local research records, not OCI synchronization objects.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| R4 | Mandatory 2% adverse-price stop is immutable | Requirements §R4 |
| R5 | Metric output semantics are frozen | Requirements §R5 |
| R12 | At most 8 active branches per track; prune before apply | Requirements §R12 / 0012 |
| B13/B14 | Real strategies and batch archives stay outside the repo; examples are the only tracked strategy subtree | AGENTS.md |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_apply_batch_cost_mismatch_is_zero_write` | Baseline or within-batch cost mismatch rejects the whole batch with no writes |
| `test_apply_batch_cost_match_and_zero_warning` | Matching costs pass and all-zero costs emit a warning |
| `test_structural_signature_registered_feature_coverage` | Every registered feature follows the explicit window mapping rules |
| `test_ast_complexity_and_signature_classification` | Identical, parameter-only, structural, and exit changes are classified correctly |
| `test_apply_batch_archive_numbering_and_contents` | Workspace archive numbering, containment, counts, and run IDs are correct |
| `test_apply_batch_archive_failure_warns` | Archive failures warn without changing the run result |

## 6. Rollback

- Code: revert C5.
- Data: keep existing workspace archives; do not delete or move them. Older code ignores them.
- No OCI, alpha, market-data, or run artifacts are modified.

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Full test suite, pyflakes, and alpha-gate pass
- [ ] Real pilot calibration (separate from the implementation commit)

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-23 | 0.1 | Initial proposal: cost lock, structural signature/complexity hints, and workspace batch records. |
| 2026-11-23 | 0.2 | C5 implemented and adversarially reviewed by a second model: cost and batch-shape preflight, structure/parameter signatures and complexity hints, workspace attempt archives, and digest hints are in place; archive numbering races and rejection wording were corrected. Full suite: 434 passed / 2 skipped; `pyflakes` and `alpha-gate` pass. |
