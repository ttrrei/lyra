# Decision 0018 — Archive apply-batch Input Before Parsing

> **Chinese**: [0018-archive-batch-before-parse.md](./0018-archive-batch-before-parse.md)
>
> Scope: on a real `apply-batch`, preserve the original user bundle in the workspace before parsing; dry-run remains write-free.

## Metadata

| Field | Value |
|---|---|
| ID | `0018` |
| Title | Archive apply-batch Input Before Parsing |
| Status | Approved |
| Created | `2026-11-25` |
| Related requirements | `docs/requirements.md` §R12 |
| Related HLD | `docs/hld.md` §2.5, §4 (I15, I17) |
| Related decisions | 0007, 0015, 0017 |

## 1. Problem

`apply-batch` currently reads and parses a bundle before creating its `batch-NNNN.yaml` archive. YAML syntax errors or schema parse failures exit before archival, losing the original rejected proposal and making it harder to review what the AI submitted and why it was rejected.

## 2. Design

1. For a non-dry-run command, immediately after reading the bundle's raw bytes and before decoding or calling `parse_batch`, write them using exclusive create/atomic publish to a workspace intake file. Intake files live under `research-batches/_intake/` with collision-resistant names. Preserve the original bytes even if UTF-8 decoding or YAML parsing fails. Intake write failures warn and do not change the existing command flow.
2. After `parse_batch` succeeds and all candidates share one safe direction/track, move the original into `research-batches/<direction>/<track>/batch-NNNN.yaml` using existing identifier validation and monotonically increasing numbering in that folder. A bundle mixing directions/tracks must not be attributed to its first item; route it to `_unparsed/unassigned/`. Write the complete preflight/adoption/run result beside the same numbered bundle as `batch-NNNN-result.md`; do not create a second bundle or allocate a second number.
3. If parsing fails, best-effort extract and validate a consistent direction/track from safe metadata. If YAML/UTF-8 cannot be parsed or the path identity is invalid, retain the original under `research-batches/_unparsed/unassigned/` and write the failure reason beside it. Any archive/move/result write failure only warns; it does not change the original `apply-batch` error or outcome. If moving fails, retain the intake original.
4. Dry-run creates no intake, result, or other archive files, preserving the existing zero-write contract. Existing archive API behavior remains compatible; new intake/finalize helpers are only for apply-batch.

## 3. Boundaries

- Archive only the original user bundle text; do not place strategy performance, real OCI content, or credentials in git.
- Preserve the raw bundle on disk before full parsing/validation. If moving it into its numbered folder fails, retain the `_intake/` copy.
- Do not change bundle parsing, validation, all-or-nothing adoption, or run semantics.

## 4. Tests

| Test | Scenario |
|---|---|
| `test_apply_batch_archives_raw_bundle_before_parse_failure` | Malformed YAML is archived with the failure reason before exit |
| `test_apply_batch_archives_parseable_preflight_rejection` | Schema/preflight rejection remains archived under direction/track |
| `test_apply_batch_dry_run_does_not_archive` | Dry-run creates no intake or archive files |
| `test_apply_batch_archive_failure_warns_and_continues` | Intake/archive write failure warns without changing the command result |

## 5. Approval

- [x] User review (execution plan v2)
- [x] AI review (second model; passed, see revision 0.2)
- [x] Tests all pass (pytest 451 passed / 2 skipped, pyflakes, alpha-gate)

## 6. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-25 | 0.1 | Proposal: preserve the raw bundle before apply-batch parsing and clarify rejection/dry-run boundaries. |
| 2026-11-25 | 0.2 | After second-model review, clarified byte-exact intake; only safe, consistent direction/track identities route to numbered folders; mixed/unidentified input stays under `_unparsed/unassigned`; do not allocate a second bundle number, and retain intake on failed moves. |
