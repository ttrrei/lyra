# Decision 0016 — Immutable Run Artifacts and Local Reuse

> **中文**: [0016-run-immutability-and-local-reuse.md](./0016-run-immutability-and-local-reuse.md)
>
> Scope: ensure one `run_id` is written once and a completed run is not overwritten by a repeated backtest.

## Metadata

| Field | Value |
|---|---|
| ID | `0016` |
| Title | Immutable Run Artifacts and Local Reuse |
| Status | Approved |
| Owner | `ttrrei` |
| Created | `2026-11-25` |
| Related requirements | `docs/requirements.md` §R5, §R6, §R8 |
| Related HLD | `docs/hld.md` §2.4, §2.5, §4 |
| Supersedes | Revises artifact-writing details in I5/D5 of `docs/decisions/0006-metrics-and-runner.md` |

## 1. Problem

The runner currently calculates `run_id` only after executing signal SQL and the backtest, then writes artifacts directly into an existing directory using `mkdir(exist_ok=True)`. A repeated request reruns the strategy and rewrites a path that OCI treats as immutable; the same identity can also appear under multiple date directories.

## 2. Background

- Decision 0006/I5 defines run identity and deterministic artifacts; it explicitly excludes manifest `generated_at` from byte determinism.
- Decision 0013 added `market_data_snapshot_id` to new run artifacts while preserving the existing `run_id` inputs. Old runs are not rewritten and missing fields remain fail-closed as `missing_*`.
- OCI treats `runs/**` as immutable; different content at the same path must be rejected.
- R5 requires `report.md` to retain the git commit; 0006 D5 requires the manifest to record it. Both remain.

## 3. Design

### 3.1 In scope

1. Before executing strategy SQL or trade simulation, compute `market_data_snapshot_id`, `data_digest`, and the existing `run_id` using the instrument set in the catalog view. The identity inputs and formula do not change.
2. Search all local date directories under `runs/<name>/*/<run_id>/`. Completeness requires a matching run ID in the manifest and every listed artifact to exist and match its SHA256; CLI runs also require `run_meta.json`. For a complete run, load `metrics.json` and return without executing strategy SQL/simulation or writing any run file. If a run is incomplete, invalid, or multiple complete copies have different contents, fail and preserve every directory.
3. Write every new run file into a temporary directory beside the target date directory, including the CLI-supplied `run_meta.json`; write the manifest last. Publish the complete directory using an atomic rename on the same filesystem. If the target appears in the meantime, refuse to overwrite it.
4. New `run_meta.json` files store `strategy_path` relative to the workspace. Reused historical runs keep their existing sidecars unchanged.
5. Remove wall-clock `generated_at` from the manifest. Keep `git_commit` in the manifest and report (R5/D5). Remove the duplicate `git_commit` from metrics because it has no independent retention requirement; pass the same commit directly to the report renderer. Resolve git commit from the Lyra source repository, independent of the caller's working directory. All run files are byte-identical for the same source tree and inputs; byte equality across commits is not promised.
6. Each real execution appends a JSONL record to workspace `research-batches/run-executions.jsonl`, with run ID, run path, execution time, git commit, and command line. This audit log is outside `runs/` and the backup synchronization top-level scope. Logging failure only warns and does not change a completed run.
7. Add bilingual append-only revision pointers to 0006, 0007, and 0013 clarifying that old runs are neither backfilled nor overwritten.

### 3.2 Out of scope

- Do not change the `_compute_run_id` payload or add `git_commit`, `code_digest`, or artifact schema to the run ID.
- Do not change metric definitions/values, trade engine behavior, or R5 report fields.
- Do not backfill old runs or delete local/OCI runs.
- OCI lookup is not implemented here; cross-machine reuse is handled by 0017.

### 3.3 Boundaries

- A complete local run is a cache hit; validation failure must fail closed without repair or overwrite.
- `run_meta.json` is a CLI attribution sidecar, not included in the manifest artifact SHA map. New runs publish it with the rest of the directory; CLI reuse does not rewrite it.
- OCI remains read-only source of truth; this decision performs no uploads.
- Relative `strategy_path` applies only to new runs. Historical sidecars remain unchanged.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I5 | Deterministic artifacts are byte-identical for the same source tree and inputs; identity changes use the existing `run_id` rules | 0006 I5 / this decision tightens the `generated_at` exception |
| I17 | A completed OCI run path is immutable; different content at the same path is rejected | 0007 / OCI alpha layout |
| R5 | The report retains git commit and existing metric semantics | Requirements §R5 |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_local_run_reuse_skips_execution_and_writes` | A complete hit skips SQL/simulation and leaves all bytes/mtimes unchanged |
| `test_local_run_reuse_searches_all_dates` | Reuse the same run ID from any UTC date directory without creating a duplicate |
| `test_local_run_reuse_rejects_corrupt_or_ambiguous` | Missing files, SHA mismatch, or conflicting duplicate copies fail closed |
| `test_run_write_is_atomic` | Interrupted writing does not publish a partial target directory |
| `test_run_artifacts_deterministic_for_same_tree` | Same source tree/input with different time and cwd produces identical manifest/metrics/report/run_meta/Parquet bytes |
| `test_run_report_keeps_git_commit` | Report retains R5 git commit and metric values do not change |
| `test_run_execution_audit_is_outside_backup_scope` | Real execution log is written in workspace but excluded from backup planning |

## 6. Rollback

- Code: revert the implementation commit for this decision.
- Data: no run needs to be deleted or rewritten; existing directories remain readable.
- Existing local audit JSONL may remain; it does not affect run or OCI identity.

## 7. Approval

- [x] User review (execution plan v2)
- [x] AI review (second model; confirmed cache lookup must precede SQL/simulation and CLI must not rewrite the sidecar on reuse)
- [x] All tests pass (pytest 441 passed / 2 skipped, pyflakes, alpha-gate)
- [ ] OCI end-to-end write (not part of this decision; OCI read-only verification is recorded separately)

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-25 | 0.1 | Proposal: write a run ID once, reuse complete artifacts, refuse overwrite, and publish atomically. |
| 2026-11-25 | 0.2 | User approved execution plan v2; a second-model review found no blocker and clarified pre-SQL identity calculation and sidecar-safe reuse. |
