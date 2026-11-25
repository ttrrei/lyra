# Decision 0019 — Run Reuse Hardening: Notice, Verification, Attribution, Numeric Golden

> **Chinese**: [0019-run-reuse-hardening.md](./0019-run-reuse-hardening.md)
>
> Scope: one read-only check (no code) plus one implementation commit. No change to `run_id` composition or artifact format.

## Metadata

| Field | Value |
|---|---|
| ID | `0019` |
| Title | Run reuse hardening: notice, verification, attribution, numeric golden |
| Status | Approved |
| Owner | `ttrrei` |
| Created | `2026-11-26` |
| Related requirements | `docs/requirements.md` §R5, §R6, §R12 |
| Related HLD | `docs/hld.md` §2.4, §2.5, §4 (I5, I17) |
| Related decisions | 0006, 0016, 0017, 0018 |

## 1. Problem

Local reuse (0016) and OCI preflight (0017) solved "compute once, write once", but an independent review identified a real usability gap: after a code change, the same branch still hits the old cache and silently returns old results, with no signal about which implementation produced them and no cheap way to check whether the numbers actually changed. In addition, identical strategy content (including its internal id) under a different branch yields the same `run_id`, and reuse currently performs no attribution check.

That review also suggested putting `code_digest` and `artifact_schema_version` into `run_id`. **The suggestion is rejected**: a comment or report-format edit would then change the run ID of every strategy and create a new path, forcing a full re-run and piling up duplicate runs — the opposite of "do not re-test when data and metrics are unchanged". The settled alternative: keep `run_id` composition unchanged; when numeric semantics really change, manually bump `_ENGINE_VERSION`, which is already in the payload, producing a new identity and path while retaining the old run.

## 2. Settled boundaries (not reopened)

- Do not change the `_compute_run_id` payload; add no `code_digest` / `artifact_schema_version` / `git_commit` identity field.
- Do not change existing manifest / metrics / report fields or formats; keep git commit in artifacts (R5).
- Add no `--recompute` / `--force` or any entry point that writes to an existing run path; no backfill of old runs (v02a/v02b).
- "No local run + OCI preflight unreachable + commit changed afterwards → push fails closed" is an accepted residual risk from 0016, not a defect; this decision does not try to remove it.

**`_ENGINE_VERSION` bump rule**: bump only when, for the same strategy and data, signals / trades or metric **values** would change (trade logic, metric formula or values). Adding artifact fields, rewording reports, pure refactors, and comment edits do **not** bump. A bump must update the numeric golden (§3.4) and this decision's revision history in the same commit.

## 3. Design

### 3.1 B1 — Notice the producing implementation on reuse

- Trigger: local hit or reuse after 0017 preflight restore (`RunResult.reused=True`).
- Action: read the git commit recorded in that run's `manifest.json` and compare it with the current worktree commit (including the dirty marker, using the existing recording convention). When different, append after `reused existing run <id>`:
  `note: this run was produced by commit <old>; current is <new>; not recomputed. Use --verify to check numbers; bump _ENGINE_VERSION only if numeric semantics changed (new run_id).`
- No notice when equal; `legacy` when the manifest lacks the field; skip the notice when git is unavailable (`no-git`).
- Notice only: never blocks, never changes the exit code, writes nothing.

### 3.2 B2 — `lyra run --verify` (verify only, never write)

- Precondition: the corresponding run already exists locally and is complete (reuse `_load_complete_run` validation); otherwise error out and tell the user to run or pull first. **No OCI preflight**.
- Action: recompute the same input with current code in a **system temp directory**, compare item by item against archived artifacts, remove staging afterwards, and write nothing under `runs/`. Staging must not be inside `runs/`; `--out` only locates the archived run (read-only) and no write-back switch is provided.
- Three outcomes:
  1. `IDENTICAL` — all artifacts byte-identical.
  2. `DESCRIPTIVE_ONLY` — signals/trades bytes and metric values identical; only manifest/report descriptive content differs; list differing field names.
  3. `NUMERIC_DIFFERENCE` — signals/trades bytes differ or metric values differ; print instruments and metric names and prompt evaluation of a `_ENGINE_VERSION` bump.
- Exit codes: 0 for the first two, 2 for `NUMERIC_DIFFERENCE`.

### 3.3 B3 — Attribution check on reuse

- Before reuse, read `branch` / `track_id` from `run_meta.json` (legacy `track` key accepted too).
- Current `branch` is derived from the strategy file name; `track` is determined only when `--track` is supplied (which `apply-batch` does).
- Mismatch → fail closed: `this run_id already exists under branch <old> (track <old>); identical strategy content (including its id) cannot be reused under branch <new>. If this is a new candidate, change the YAML's substantive content (including id) or use a new slug.` No files written.
- Legacy sidecar missing `branch` / `track_id` → one WARN line, then continue to reuse.
- **Scope**: branch comparison covers every reuse path (local hit and OCI restore); track comparison only applies when `--track` is determinable, so a bare `lyra run <file>` skips it. The scope is also recorded in HANDOFF.

### 3.4 B4 — Numeric golden test

- Fix a synthetic sample run using the existing test data/strategy fixtures; pin SHA256 of `signals.parquet` and `trades.parquet` and all metric values in `metrics.json` (excluding descriptive fields such as git commit).
- Fixed failure message: "Numeric output changed. If this is an intentional numeric-semantics change: bump `_ENGINE_VERSION` and update this golden and the decision doc in the same commit. If not: explain why the engine changed unexpectedly."
- Pin numbers only; do not pin descriptive manifest/report bytes.

### 3.5 B5 — Documentation/test drift

- 0016 §5 lists `test_run_artifacts_deterministic_for_same_tree` and `test_run_report_keeps_git_commit`, neither of which exists in `tests/`. Equivalent behavior is covered by `test_run_reproducible_identical_manifest` (identical bytes for same inputs, no `generated_at`, report still contains git commit). Append one revision row to 0016 naming the actual test; never edit the old row.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I5 | Deterministic artifacts for same inputs; reuse never rewrites; numeric change must be expressed explicitly via `_ENGINE_VERSION` | 0006 I5 / 0016 / this decision |
| I17 | OCI `runs/**` immutable; notice and verification are read-only; no overwrite entry point | 0007 / 0016 / 0017 |
| R5 | Report keeps git commit; metric definitions and values frozen | Requirements §R5 |

## 5. Tests

| Test | Scenario |
|---|---|
| B1 notice | manifest commit differs → notice; equal → none; legacy → `legacy`; exit code and files unchanged |
| B2 verify | one each of `IDENTICAL` / `DESCRIPTIVE_ONLY` / `NUMERIC_DIFFERENCE`; missing run errors; real runs dir contents and mtime unchanged; no OCI call |
| B3 attribution | branch/track mismatch → fail closed, zero writes; match → normal reuse; legacy missing fields → WARN then reuse; local hit and preflight restore both covered |
| B4 golden | golden passes; forced engine numeric change fails with message containing "bump `_ENGINE_VERSION`" |
| B5 drift | 0016 revision row names the actual test |
| Regression | all 0016/0017/0018 tests still pass; R5 values unchanged; `_compute_run_id` payload key set fixed |

## 6. Rollback

- Code: revert the single implementation commit; B1/B2/B3 disappear and 0016/0017 behavior is restored.
- Data: no run needs deleting or rewriting; this decision never writes to `runs/`.
- Golden constants revert with the commit; historical runs are unaffected.

## 7. Approval

- [x] User review (task note new.md)
- [ ] AI review (second model; not separately executed this round)
- [x] All tests pass (pytest / pyflakes / alpha-gate)
- [ ] OCI end-to-end write (out of scope)

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-26 | 0.1 | Proposal: reuse notice, read-only three-way `--verify`, fail-closed attribution, numeric golden, and test-name drift fix; explicitly rejects code_digest / schema_version in run_id and defines the `_ENGINE_VERSION` bump rule. |
