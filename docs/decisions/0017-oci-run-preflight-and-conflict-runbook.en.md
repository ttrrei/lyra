# Decision 0017 — OCI Run Preflight and Immutable Conflict Recovery

> **Chinese**: [0017-oci-run-preflight-and-conflict-runbook.md](./0017-oci-run-preflight-and-conflict-runbook.md)
>
> Scope: when a run is absent locally, read-only check the existing OCI backup layout before execution; restore and reuse a complete hit, or warn and continue on lookup failure.

## Metadata

| Field | Value |
|---|---|
| ID | `0017` |
| Title | OCI Run Preflight and Immutable Conflict Recovery |
| Status | Approved |
| Created | `2026-11-25` |
| Related requirements | `docs/requirements.md` §R6, §R7 |
| Related HLD | `docs/hld.md` §2.5, §4 (I17); I19/I20 (redaction and idempotency) are defined in `docs/decisions/0007-oci-push-and-backup.md` |
| Related decisions | 0006, 0007, 0016 |

## 1. Problem

Local reuse (0016) cannot prevent a second machine without the old run from recomputing the same `run_id` and attempting to upload different bytes to an immutable OCI path. The current `backup` run-object layout is `runs/<name>/<date>/<run_id>/<file>`; existing PAR list/download helpers can list from the bucket root and fetch individual objects.

## 2. Design

1. After a local miss and before strategy SQL/simulation, `run_strategy` invokes an optional OCI loader. The CLI supplies it only when `strategies_par_url` or its `data_par_url` fallback is configured; without a remote URL, normal execution proceeds.
2. The loader read-only lists the OCI root and filters for run objects under the exact `runs/<name>/*/<run_id>/` path. If multiple date copies exist, it downloads and validates all of them; any incomplete or byte-different copy fails closed, while identical copies allow one to be selected. It first downloads and validates in a system temporary directory, then copies to a staging directory beside the target, validates again, and atomically renames on the same filesystem into local runs. The 0016 metrics loader returns `reused=True`; strategy SQL/simulation do not run.
3. No matching object means local execution continues. Listing/network/authorization errors print a WARN without exposing the PAR URL and continue. A matching run with missing files, SHA mismatch, invalid manifest, or a conflicting local target fails closed; it is not repaired or overwritten.
4. `oci_push` immutable-conflict errors explain that the path exists with different content and give executable recovery steps: move every local date copy of the run ID into `superseded-runs/`, then, when OCI is reachable, rerun `lyra run` with the same strategy, data, name/track, and config so this preflight read-only restores and validates the OCI original, then rerun dry-run. `pull-runs` does not apply to the legacy backup path. If preflight is unavailable, stop and preserve the copies; overwriting is prohibited.
5. Add cross-machine run and conflict-recovery instructions to 0007 and `lyra/ai_readme.md`. The preflight only queries the existing backup layout under `strategies_par_url` / `data_par_url`; it does not change `runs_par_url`, the canonical push-runs layout, or OCI contents.

## 3. Boundaries and residual risk

- Preflight is best-effort. If no local run exists and OCI is unreachable, execution continues. A later push of different bytes must fail closed and be recovered using the runbook; OCI is never overwritten and data is not silently lost.
- Reuse existing PAR list/download helpers; add no abstraction layer and change no OCI layout.
- Install only a fully validated OCI hit. An interrupted download is confined to a temporary directory and leaves no target run behind.

## 4. Tests

| Test | Scenario |
|---|---|
| `test_oci_preflight_restores_complete_run_and_skips_execution` | Fake OCI hit is restored and reused without strategy SQL/simulation |
| `test_oci_preflight_miss_or_unreachable_warns_and_runs` | A miss runs normally; lookup failure warns and continues |
| `test_oci_preflight_rejects_corrupt_remote_run` | Invalid remote manifest/artifact is not installed and execution does not proceed |
| `test_oci_immutable_conflict_actionable_message` | Conflict explains no-overwrite and recovery steps |

## 5. Approval

- [x] User review (execution plan v2)
- [x] AI review (second model; passed, see revision 0.2)
- [x] Tests all pass (pytest 447 passed / 2 skipped, pyflakes, alpha-gate)
- [x] Read-only OCI path verified; no OCI writes

## 6. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-25 | 0.1 | Proposal: reuse OCI list/download helpers for read-only preflight and document immutable-conflict recovery. |
| 2026-11-25 | 0.2 | After second-model review, clarified that all remote date copies for one run must be validated and ambiguity rejected; downloads are copied from system temp into target-parent staging before atomic rename; the runbook quarantines all local copies then reruns the same command to trigger preflight restoration. |
