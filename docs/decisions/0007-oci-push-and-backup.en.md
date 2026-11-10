# 0007 — OCI bidirectional sync + R12 interactive workflow (push / backup / list + tracks / context / new-version / compare / merge)

> **Chinese**: [0007-oci-push-and-backup.md](./0007-oci-push-and-backup.md)
>
> This decision doc covers two blocks in 0007's scope (**user-ruled 2026-11-10: both
> belong to 0007**):
>
> **Part A — OCI sync layer**: `lyra push` / `lyra backup` (alias `sync`) / `lyra list`
> and the `push-strategy` / `push-direction` OCI persistence commands (R7 core feature +
> I17 two-tier file rules + I19/I20 idempotency and URL redaction).
>
> **Part B — R12 interactive workflow**: the `tracks` / `context` / `new-version
> --branch` / `compare --siblings` / `merge` direction-organization and evolution loop
> (built on 0006's run artifacts; moved out of 0006 per 0006 D1).
>
> This feature does **NOT** do: the 332-corpus migration + O16 completion (→ 0008);
> doctor/README/CI polish (→ 0009); schedulers/file-locks/multiprocess concurrency (R9
> excluded).

## Meta

| Field | Value |
|---|---|
| ID | 0007 |
| Title | OCI bidirectional sync (push/backup/list) + R12 interactive workflow (tracks/context/new-version/compare/merge) |
| Status | proposal |
| Owner | `ttrrei` |
| Created | 2026-11-10 |
| Related proposals | `docs/proposals/2026-11-08-vectorbt-multi-ai-consolidated.md` (tracks landing path §9), `docs/proposals/oci-alpha-layout.md` (OCI layout + B9/I17) |
| Related requirements | `docs/requirements.md` §R6/R7 (OCI bidirectional sync), §R12 (direction & iteration / tracks / per-track 8 cap), §R9 (non-functional: no side effects, no concurrency) |
| Related HLD | `docs/hld.md` §2.5 (oci client), §3 (data flow OCI push), §4 (I11/I15/I16/I17/I19/I20), §8 (0007 row) |
| Related decisions | 0002 (OCI pull/clean/aggregate + oci_client), 0003 (feature snapshot identity), 0004 (YAML→SQL, direction from strategy folder), 0005 (trade engine), 0006 (`lyra run` + I5 reproducible artifacts + I16 per-instrument isolation) |
| Open items | **O2** (runs/ layout): take `runs/<direction>/<track_id>/<run_id>` (aligned to R12 tracks, **user-ruled 2026-11-10**); **O15** (R7 command naming): keep `lyra backup` as primary, `sync` as alias (#89 lean); **R10/R11/R12** (#89 held items): 0007 takes the OCI/workflow implementation portions; 332-compat stays in 0008 |

## 1. Problem

Strategies can be compiled by 0004, filled by 0005, and run into reproducible artifacts
by 0006, but **the local artifacts cannot leave a single machine**: without push/backup,
research output just sits in `~/.lyra/<workspace>/runs/`; without the R12 workflow
(direction/branch/track/context/compare), **strategy evolution is done by hand-copying
files and recalling lessons from memory** — with multiple AIs researching in parallel they
interfere with each other, cannot compare sibling branches, and cannot turn a diagnosis of
one version into the next batch of candidates. 0007 fills these two gaps:

1. **OCI sync** (R7 core feature): persist runs / strategies / alpha features to OCI,
   rebuildable and multi-machine reusable, while obeying the I17 two-tier file rules
   (immutable / append-only).
2. **R12 workflow**: turn the "direction → branch → track → candidate → run → lessons →
   synthesis" evolution loop into commands, so AI and user share the same mechanical gate
   (read 1 file / write 1~N branches / run each once / record 1 paragraph), without
   introducing concurrency coordination (R9 maintained).

## 2. Background

- **moneta**: has `extract_oci.py` (pull), **no push / no backup / no R12 workflow**
  (moneta is a one-way pull pipeline with no "strategy evolution" concept).
- **nova**: runner artifacts land locally, no OCI sync layer; no direction/branch
  organization.
- **0002** already delivered `lyra/oci_client.py` (PAR list + download + I19 redaction +
  I20 idempotent **pull side**), and `lyra/config.py` already reserved
  `strategies_par_url` / `features_par_url` push slots (comment-marked "reserved for 0007").
- **0006 D1 / out-of-scope**: explicitly moves the R12 interactive workflow out of 0006 into
  0007; rationale: the workflow builds on 0006's run artifacts, is large, needs its own
  adversarial self-check, and the user wants "lightweight, one base, parallel directions".
- **Consolidated §9 / requirements R12 / O13 (closed)**: tracks are a **research identity,
  not an execution identity** — `track_id` is only for isolation/ownership/synthesis and
  does **not** change any machine gate of validate/compile/run/report; **per-track 8 active
  branches** each, tracks do not crowd each other; no scheduler/lock/concurrency (R9).
- **I17 (HLD §4, B9 two-tier rules)**: OCI files are two-tier — (a) **Immutable**
  (`data/**`, `runs/**`, `strategies/**/vNN.yaml`, `alpha/features/**`): same path + same
  sha256 idempotent, different sha256 errors; (b) **Append-only** (`strategies/**/
  hypothesis.md`, `lessons.md`, `index/*.json`): content may advance forward (new ⊇ old),
  push validates the superset, else errors.
- **Existing CLI**: `pull / clean / aggregate / catalog / oanda / features / validate /
  compile / run / report / version`. **push / backup / list / push-strategy /
  push-direction / context / new-version / compare / merge are all absent** — exactly what
  0007 adds.

## 3. Design

### 3.1 What we do

**Part A — OCI sync layer** (new `lyra/oci_push.py` + `cli.py` commands):
- `lyra push [--strategies-root DIR] [--runs-root DIR] [--alpha-root DIR]
  [--force-push] [--dry-run]`: push the local mirror to OCI under the I17 two-tier rules;
  `--force-push` overrides the "I17 immutable conflict" gate (R7 default: OCI is source of
  truth).
- `lyra backup` (alias `lyra sync`, O15): one-shot = **push changed strategies + runs** +
  conflict detection + summary (R7's "one-shot command").
- `lyra list [--prefix <data|strategies|runs|alpha>]`: list OCI objects (reuses 0002
  `list_objects`), read-only.
- `push-strategy <direction>/<branch>` / `push-direction <direction>`: fine-grained push
  (single version vs whole direction).
- Transport: PAR URL preferred (config already has `strategies_par_url`/`features_par_url`);
  optional OCI SDK auth (`config.auth_file`, `~/.lyra/credentials`, **never in git**).

**Part B — R12 interactive workflow** (new `lyra/workflow.py` + `cli.py` commands):
- `lyra tracks <direction> [--create <track_id>] [--list]`: manage tracks within a
  direction (research identity); a track freezes a read-only baseline snapshot
  (hypothesis hash + data snapshot + feature catalog/version + execution-rule version).
- `lyra context <direction> [--track <id>] [--n-lessons N]`: emit a **single-file context
  package** (that track's hypothesis snapshot reference + last N lessons paragraphs +
  active branches vNN + sibling-branch run summary comparison table + feature list); a
  normal iteration does **not** read other tracks' drafts/lessons.
- `lyra new-version <direction> --branch <name> [--track <id>] [--from <parent_branch>]`:
  derive 1~N branch templates from a parent (vNN.yaml skeleton + `parent`/`parents` +
  `driven_by_lesson` placeholder); **enforce the per-track 8 active-branch cap** (O13) —
  over the cap fails fast.
- `lyra compare <direction> --siblings [--track <id>] [--branch <a> <b> ...]`: read-only
  comparison of sibling branches' 0006 `metrics.json` summaries (per-instrument R5
  metrics), emitting a **evidence table** for continue/prune/cross (no auto-write-back).
- `lyra merge <direction> --parents <a> <b> [--track <id>]`: cross/synthesize a candidate
  (whole-block / per-param / rework — AI has full authority; `inherited` +
  `driven_by_lesson` record the source); **does not modify** source branch files.
- Cross-track synthesis: `lyra synthesize <direction> --by <ai> --out reviews/<ts>.md` —
  only after the user pauses the direction and explicitly requests it, producing a
  **read-only report** (`reviews/`), **not auto-writing** back to lessons/candidates;
  promotion and restoration are user-explicit.

### 3.2 What we do NOT do (Out of Scope)

- **332-corpus migration + O16 feature-gap completion + full-corpus regression gate** — 0008.
  Rationale: 0008 first completes 0003 features per the rulings, then migrates/verifies; it
  is the compatibility gate, independent of sync/workflow.
- **doctor / README / CI / config_example polish** — 0009.
- **Scheduler / file locks / multiprocess concurrency coordination** — R9 excluded. tracks
  are **logical isolation** (user-driven sequential work), not concurrent execution; Lyra
  does not promise multiple writers pushing the same workspace at once.
- **OCI multi-bucket routing / permission management / data version promotion** — HLD §2.5
  "do not do". One bucket one prefix is enough; permissions belong to the OCI console;
  snapshot id is locally assigned, OCI only stores files.
- **Changing 0004 compiler / 0005 engine / 0006 runner machine behavior** — 0007 only
  **consumes** 0006 artifacts and only **reads** 0004/0005/0006 output; track is a research
  identity and does not change any validate/compile/run/report gate (R12 / consolidated).

### 3.3 Boundaries

- **OCI boundary**: Part A reads OCI (`list`) + writes OCI (`push`/`backup`); credentials
  from `config.yml` (PAR URL preferred / optional `~/.lyra/credentials`), **credentials
  never in git** (R7). Part B does **not** touch OCI directly — it only reads local
  runs/strategies and produces context/candidates/comparisons; persistence is handled by
  `push-direction` / `push-strategy` / `backup`.
- **Alpha boundary**: on push, `alpha/features/**` goes to OCI under the I17(a) immutable
  rule (alpha is OCI's source of truth); **core imports no concrete alpha module** (I16
  maintained); 0007 treats alpha only by file/hash, not understanding alpha semantics.
- **0006 boundary**: `compare` reads 0006's `metrics.json` / `trades.parquet` (I5
  reproducible, I16 per-instrument); 0007 **does not change** 0006's run semantics, only
  compares/synthesizes on top.
- **runs layout (O2 ruling)**: **canonical OCI layout** = `runs/<direction>/<track_id>/
  <run_id>/` (aligned to R12 tracks). 0006 `lyra run`'s local workspace layout
  (`runs/<name>/<YYYYMMDD>/<run_id>/`) is a **staging/workspace** area; on `push`, the
  canonical OCI path is resolved from the strategy's **direction**
  (`strategies/<direction>/vNN.yaml` path) + the active **track**. 0006's local layout is
  **unchanged** (keep a completed feature stable); the canonical OCI path is defined by 0007
  (D7).

## Design decisions (D1–D10)

**D1 (scope — user-ruled 2026-11-10)**: 0007 = **OCI sync layer + R12 interactive
workflow**, both in this feature (the user explicitly chose "OCI sync layer + full R12
workflow" in the scope ruling). Rationale: both build on 0006's artifacts and both center
on "research output that can be persisted + evolved"; splitting them would leave push and
workflow each dangling; combining into one commit lets the adversarial self-check cover the
whole thing.

**D2 (I17 two-tier rules are push's core gate)**: `push` first classifies each local file as
I17(a) Immutable or I17(b) Append-only:
- **Immutable**: remote **absent** → upload; remote **present with same sha256** → skip
  (idempotent, I20); remote **present with different sha256** → **error fail-closed**
  (unless `--force-push`, R7 default OCI is source of truth).
- **Append-only**: remote **absent** → upload; remote **present** → validate **new content
  ⊇ old content** (superset: every line/paragraph of the old file is in the new one); if
  superset → upload; **not a superset** → **error fail-closed** (prevent regressing/
  tampering with lessons).
> Classification: `runs/**`, `strategies/**/vNN.yaml`, `alpha/features/**`, `data/**` =
> Immutable; `strategies/**/hypothesis.md`, `lessons.md`, `index/*.json` = Append-only.
> A path that cannot be classified → **error** (fail-closed, do not guess).

**D3 (idempotency & redaction inherited from 0002)**: `push` reuses 0002 `oci_client`'s
I19 (PAR URL redaction; the signed token never leaks into logs/exceptions) + I20 (same
content not re-uploaded). Push-side idempotency uses **sha256** (I17 two-tier compares
sha256, stronger than md5); if PAR only provides md5, fall back to md5 (consistent with
0002's pull side).

**D4 (credentials)**: `config.yml`'s `strategies_par_url` / `features_par_url` are the push
targets (reserved by 0002); `auth_file` (`~/.lyra/credentials`) optional. **Credentials
never in git** (R7 / config_example comment); `push` with no push target configured →
**error** (not silently skipped, no local placeholder written).

**D5 (track is a research identity, does not change machine gates — R12/consolidated)**:
`track_id` is only for **isolation** (each track owns context/lessons/candidates/run
ownership), **ownership** (run manifest records direction+track_id+strategy sha+
data/feature snapshot+compiler/engine version), **synthesis** (user-triggered read-only
report). `tracks` / `context` / `new-version` / `compare` / `merge` **do not change** any
validate/compile/run/report behavior or gate — 0007 only organizes research material on top
of 0006's artifacts.

**D6 (per-track 8 active-branch cap — O13 final)**: `new-version --branch` creating a new
active branch counts **that track's** (not the direction-global) active branches; reaching
8 → **fail-fast error**, must explicitly prune one before forking again. Tracks do **not**
crowd each other for quota ("mutual non-interference" first). This is the **only** machine
gate 0007 introduces (all other commands are read-only/derivation/organization, adding no
gates).

**D7 (canonical OCI runs path — O2 ruling)**: OCI runs are always
`runs/<direction>/<track_id>/<run_id>/`. `push` resolution: **direction** from the strategy
folder (`strategies/<direction>/vNN.yaml`; 0006's manifest already carries a `direction`
field that can be reused directly); **track_id** is the research identity introduced by
0007, supplied by `push --track` (or that track's track manifest) and recorded into the
archive path — 0006's manifest does **not** contain `track_id` (0006 has no track concept,
which is correct). 0006's **local workspace** layout `runs/<name>/<YYYYMMDD>/<run_id>/` is
unchanged (staging area); `push` maps it to the canonical OCI path (injecting `--track` into
the archive path). **Local and OCI layouts need not match** (local is the workspace, OCI is
the canonical archive).

**D8 (compare / synthesize are read-only, no auto-write-back — R12)**: `compare --siblings`
and `synthesize` only **read** 0006 artifacts and emit a **read-only evidence table/report**;
they **never** auto-write back to lessons, candidates, or cross-track promotion. `merge`
only **adds** a candidate branch (`vNN.yaml`, writing `inherited`/`driven_by_lesson`) and
**does not modify** the source branch. Cross-track synthesis reports land in `reviews/`,
stored independently.
> **Reuse point**: 0004's `strategy_schema.py` already implements the three provenance
> fields `parents`/`driven_by_lesson`/`inherited` (retained, never compiled into SQL);
> `new-version --branch` derivation and `merge` provenance **reuse** these directly — 0007
> needs no schema extension.

**D9 (fail-closed first)**: the following all **error rather than silently** proceed — push
target not configured (D4); I17 classification fails (D2); immutable conflict without
`--force-push` (D2); append-only non-superset (D2); duplicate track/branch/run ID creation
(fail-fast, no overwrite, no auto-rename, consolidated); branch cap exceeded (D6). **No side
effects** (R9): dry-run only reports, does not upload; no command writes git or the network
(except OCI).

**D10 (command surface & aliases — O15)**: the one-shot command is `lyra backup`, with
`lyra sync` as its **alias** (#89 lean; R7's original text uses `sync`; take `backup` as the
primary name, `sync` as the alias, the two equivalent). `list` is read-only. `push`
supports `--dry-run` (first validate under D2 two-tier rules and report "will upload / will
skip / will conflict", without actually uploading).

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I17 | OCI files two-tier: (a) Immutable same path + same sha256 idempotent, different sha256 errors; (b) Append-only new ⊇ old, else errors | I17 (HLD §4) / B9 |
| I19 | PAR URL (with signed token) never leaks into logs/exceptions | I19 (HLD §4) / 0002 |
| I20 | Idempotent: same content not re-uploaded | I20 (HLD §4) / 0002 |
| I11 | Local OCI mirror (data/strategies/runs/alpha) rebuildable, default out of repo (B13) | I11 (HLD §4) |
| I15 | git contains no alpha paths / strategies direction content / runs all | I15 (HLD §4) / 0001 |
| I16 | core imports no concrete alpha module (0007 treats alpha only by file/hash) | I16 (HLD §4) / 0001 |
| I18 | **track is a research identity, not an execution identity**: `track_id` does not change any validate/compile/run/report machine behavior or gate; duplicate track/branch/run ID creation fails fast, no overwrite | this feature new (R12 / consolidated §9) |
| I21 | **per-track 8 active branches each**, tracks do not crowd each other; `new-version` over-cap fails fast | this feature new (O13 final) |
| I22 | **compare/synthesize are read-only**: no auto-write-back to lessons/candidates/cross-track promotion; `merge` only adds a candidate, does not modify source branches | this feature new (R12) |

## 5. Tests

Scenarios that must be covered (pytest case name + one sentence):

**Part A — OCI sync**:

| Test | Scenario |
|---|---|
| `test_push_immutable_new_uploads` | remote-absent immutable file → upload (D2) |
| `test_push_immutable_same_sha_skips` | remote same sha256 → skip, no upload (I20 idempotent) |
| `test_push_immutable_conflict_fails` | remote different sha256, no `--force-push` → error fail-closed (D2/D9) |
| `test_push_immutable_force_push_overrides` | `--force-push` → allow override (R7) |
| `test_push_append_only_superset_ok` | lessons.md new content ⊇ old → upload (D2) |
| `test_push_append_only_regression_fails` | lessons.md deletes/rewrites an old line (not a superset) → error fail-closed (D2/D9) |
| `test_push_unclassified_path_fails` | path not classifiable to I17(a)/(b) → error, no upload (D2/D9) |
| `test_push_no_target_fails` | no push PAR target configured → error, not silent (D4/D9) |
| `test_push_url_redacted_in_error` | push failure exception message contains no PAR signed token (I19) |
| `test_push_dry_run_reports_no_upload` | `--dry-run` → prints will-upload/skip/conflict list, no actual upload (D10) |
| `test_backup_is_push_of_changed` | `lyra backup` = push changed strategies+runs + summary (R7 one-shot) |
| `test_sync_alias_equals_backup` | `lyra sync` and `lyra backup` behave equivalently (D10/O15) |
| `test_list_is_readonly` | `lyra list` lists OCI objects, does not write (R7) |

**Part B — R12 workflow**:

| Test | Scenario |
|---|---|
| `test_tracks_create_freezes_baseline` | creating a track freezes hypothesis hash + data/feature snapshot + execution-rule version (consolidated §9.1) |
| `test_tracks_duplicate_id_fails` | duplicate track/branch/run ID → fail-fast, no overwrite, no auto-rename (I18/consolidated) |
| `test_context_track_scoped_isolated` | `context --track A` does **not** read track B's drafts/lessons (R12 isolation) |
| `test_context_contains_siblings_runs` | context contains that track's active branches + sibling-branch run summaries + feature list (R12) |
| `test_new_version_writes_parent_and_lesson` | derived branch template contains `parent`/`driven_by_lesson` placeholder (R12 vNN≥2 required) |
| `test_new_version_enforces_cap_8` | 9th active branch (same track) → fail-fast (I21/D6/O13) |
| `test_cap_is_per_track_not_global` | track A at 8 does not block track B from forking (I21 "no crowding") |
| `test_compare_siblings_readonly` | `compare --siblings` reads 0006 metrics, emits evidence table, writes no file (I22/D8) |
| `test_merge_adds_candidate_no_source_change` | `merge --parents a b` adds a candidate, source branches a/b files byte-unchanged (I22/D8) |
| `test_synthesize_requires_explicit_and_writes_reviews_only` | `synthesize` produces a `reviews/` read-only report, no write-back to lessons/candidates (I22/D8) |
| `test_push_direction_uploads_full_direction` | `push-direction` pushes hypothesis+lessons+all active vNN+index (D2 two-tier) |
| `test_push_strategy_immutable_only` | `push-strategy <direction>/<branch>` pushes only the single vNN.yaml (I17(a)) |

**Cross-invariant / rollback**:

| Test | Scenario |
|---|---|
| `test_run_id_provenance_in_manifest` | run manifest contains direction+track_id+strategy sha+snapshot+versions (D5) |
| `test_no_git_side_effect` | all 0007 commands do not write the git workspace (R9 no side effects) |

**Cross-implementation**: I19/I20 consistent with 0002 `oci_client` semantics (same
injected fake transport); `compare`'s metric definitions match 0006 `metrics.json`
field-for-field (R5 frozen set).

## 6. Rollback

- **Code**: revert the 0007 commit (`lyra/oci_push.py`, `lyra/workflow.py`, `cli.py` new
  commands, `tests/test_oci_push.py`, `tests/test_workflow.py`). 0002-0006 unaffected
  (0007 only **adds** modules and commands; does not modify 0006 runner/0005 engine/0004
  compiler).
- **Data**: push is **idempotent + fail-closed** (D2/D9), so a failed upload leaves no
  half-state; already-uploaded OCI files, under the I17 immutable rule, are **not deleted
  by a local rollback** (OCI is the source of truth). Immutable files overridden by
  `--force-push`, if a rollback is needed, are re-pushed by the user with the correct
  version (or via the OCI console); **0007 provides no destructive delete command**.
- **Compatibility**: after rollback, moneta/nova and 0001-0006 are all unchanged (0007 is
  an incremental feature).

## 7. Approval

- [ ] User review (scope/layout ruling confirmed: OCI sync + full R12 workflow, runs take
  the tracks layout)
- [ ] AI review (another model)
- [ ] Self-check + adversarial self-check (this doc Appendices B/C)
- [ ] Tests green (new `test_oci_push.py` + `test_workflow.py`)
- [ ] OCI end-to-end passes (R10 acceptance: pull/push passes once on a real bucket)
- [ ] 332-strategy regression passes (**N/A** — the 332-corpus gate belongs to 0008)

## 8. Revision log

| Date | Version | Change |
|---|---|---|
| 2026-11-10 | 0.1 | Draft: scope ruling (OCI sync + full R12 workflow, user 2026-11-10); D1–D10; invariants I18/I21/I22; test matrix; O2 runs layout takes `runs/<direction>/<track_id>/<run_id>`, O15 `backup`/`sync` alias; R10/R11/R12 held items — the OCI/workflow portions are taken here, 332 stays in 0008. |
| 2026-11-10 | 0.2 | Self-check + adversarial verification (#93) fixed 3 items: ① D7 corrected — `track_id` is a 0007 construct, injected into the OCI archive path by `push --track`; 0006 manifest carries `direction` (reusable) but **not** `track_id`; ② B5/C1 PAR-PUT wording refined — depends on **mount mode** (read-only: no PUT; read/write: PUT via `shutil.copy2`), not "PAR is necessarily read-only"; ③ D8 added the reuse point that 0004's `strategy_schema.py` already implements `parents`/`driven_by_lesson`/`inherited`. No blocking design issue; 27-row test matrix verified; ready for implementation. |
| 2026-11-10 | 0.3 | **Implemented** (#94): added `lyra/oci_push.py` (I17 classifier / plan / dry-run / force-push promotes immutable conflicts / append-only **line-subsequence** preservation / unclassified fail-closed / I19 redaction / D4 no-target error / out-of-scope top-level skip / top-level filter) + `lyra/workflow.py` (tracks baseline freeze / per-track 8-active cap `MAX_ACTIVE_BRANCHES_PER_TRACK` — the only machine gate / prune / new-version reusing 0004 `parent`+`parents`+`driven_by_lesson` / context track isolation + 0006 metrics summary / compare read-only / merge adds candidate only with parent sha256 provenance (C6) / synthesize writes `reviews/` only); CLI added 12 commands (push/backup/sync/list/push-strategy/push-direction/push-runs/tracks/context/new-version/compare/merge/synthesize); `tests/test_oci_push.py` (36) + `tests/test_workflow.py` (20) green, full suite 228→283, pyflakes clean. Implementation confirmations: C1 landed (`push` requires transport `.put`; CLI exposes get+put via requests.Session); C2 landed (append-only = ordered line-subsequence, reorder rejected, `test_superset_reorder_rejected`); C6 landed (merge records `# parent_sha256` per parent); D7 landed (`push-runs <direction> <run> --track` maps local `runs/<name>/<date>/<run_id>/` to canonical `runs/<direction>/<track_id>/<run_id>/`, direction cross-checked against the 0006 manifest, `test_push_runs_maps_to_direction_track_runid`). Backup scope = strategies+runs+alpha (raw `data/` not re-pushed, one-shot R7). |

---

## Appendix B: Self-check

**B1 scope check**: Part A (push/backup/list + push-strategy/direction + I17/I19/I20) +
Part B (tracks/context/new-version/compare/merge/synthesize + cap + read-only synthesis)
covers HLD §8 0007 row ("OCI push+backup") and 0006 D1's moved-out item (R12 workflow) ✓;
consistent with the user's scope ruling ✓.

**B2 contract check**:
- R7 (OCI bidirectional sync: push/backup/list/conflict policy/credentials) → D2/D3/D4/D10 ✓
- R12 (direction/branch/track/cap/context/compare/merge/read-only synthesis) → D5/D6/D7/D8 +
  I18/I21/I22 ✓
- R9 (no side effects/no concurrency) → D9/D10 + I22 + §3.2 excludes scheduler/lock ✓
- I17 (two-tier) → D2 ✓; I19/I20 (redaction/idempotency) → D3 ✓; I15/I16 (alpha boundary) →
  §3.3 ✓
- O13 (per-track 8 cap) → D6 + I21 ✓; O2 (runs layout) → D7 ✓; O15 (command naming) → D10 ✓
- Consolidated §9 (track frozen baseline / duplicate-ID fail-fast / read-only synthesis /
  per-track 8) → D5/D6/D8 + I18/I21/I22 ✓

**B3 boundary check**: 0007 only **consumes** 0006 artifacts, only **reads** 0004/0005/0006
output, and does not change any machine gate (§3.3 / D5) ✓; Part B does not touch OCI
directly, persistence goes through Part A (§3.3) ✓; 332 migration / doctor explicitly moved
out (§3.2) ✓.

**B4 potential gaps (self-check found, already handled in the body)**:
- **G1 local vs OCI runs layout mismatch**: 0006 local `runs/<name>/<date>/<run_id>` vs OCI
  canonical `runs/<direction>/<track_id>/<run_id>` — D7 clarifies "local is the workspace,
  OCI is the canonical archive, push maps it"; 0006's local layout is unchanged (keep a
  completed feature stable). ✓
- **G2 where does direction come from**: D7 resolves it from the strategy folder
  `strategies/<direction>/vNN.yaml`; the run manifest must contain direction (does 0006's
  manifest already have it? see B5).
- **G3 `--force-push` vs I17 immutable tension**: D9 makes `--force-push` the **only**
  exemption to I17(a) immutable conflict (R7 explicit), and it only overrides sha conflict,
  does **not** exempt append-only non-superset (append-only always fails closed, preventing
  lessons regression). ✓
- **G4 cap counting boundary**: D6 makes it "active" counting (pruned not counted toward
  the 8 quota; O13's original intent "prevent infinite fork" is still met, pruned history
  retained). ✓

**B5 to confirm at implementation time (not design defects; listed as implementation
check-items)**:
- The 0006 run manifest already records `direction` (runner.py L631); **`track_id` is not
  in the 0006 manifest** (0006 has no track concept — correct). At implementation, `push`
  resolves `--track` from the CLI arg or track manifest and injects it into the OCI archive
  path (D7 leaves this exit), **not requiring** a change to 0006.
- The concrete granularity of the `append-only superset` check (line-level vs paragraph-level
  vs content-hash prefix) is decided at implementation time (D2 only fixes the "new ⊇ old"
  semantics).
- PAR PUT availability depends on **mount mode**: read-only PAR does not support PUT;
  read/write PAR does (via `shutil.copy2`, no new dependency). The first implementation
  step is to verify the target bucket can be mounted read/write; if only read-only is
  available, the push side uses the OCI SDK (`config.auth_file`). D3/D4 already leave the
  SDK exit. **This is the largest uncertainty for 0007's implementation** (the pull side in
  0002 using PAR read-only holds; push needs write permission).

**Self-check conclusion**: scope/contract/boundary/invariants all checked and passed; 4
self-check findings (G1–G4) are handled in the D decisions in the body; 3 implementation-time
check-items (B5) are not design defects. No blocking design issue.

---

## Appendix C: Adversarial self-check

> The following is the design-level adversarial self-check (a code-level adversarial review
> is done again at implementation time). Each item gives the "contrary interpretation /
> failure mode" + ruling + disposition.

**C1 (high) Does PAR support PUT? If PAR is read-only, the whole push side does not hold**
- Failure mode: 0002's pull uses PAR (read-only) and holds; but OCI PAR is traditionally a
  **pre-authenticated read-only** link, so push (write) may simply not be usable with a PAR
  URL and must go through OCI SDK signing.
- Ruling: **partially holds** — this is the largest uncertainty for 0007's implementation
  (already listed in B5).
- Disposition: D3/D4 already abstract the transport as "PAR preferred / OCI SDK auth
  fallback", the `config.auth_file` exit is left in place; the first step at implementation
  is to **verify push transport on a real bucket** (R10 acceptance "OCI pull/push
  end-to-end on a real bucket passes"). The design layer does **not assume** PAR supports
  PUT; both transports stay switchable.

**C2 (high) the append-only "superset" determination is semantically weak and could pass a
"one word changed" edit as a legal advance**
- Failure mode: `lessons.md`'s old line "use SMA" changed to "use EMA" — the line set
  changed; judging a superset by "line ⊇" would error (good), but if it is an **in-line word
  change** ("SMA"→"EMA") while that line still exists, the superset check would **pass**
  this tampering.
- Ruling: **holds** — pure superset (set inclusion) cannot guarantee the **old content is
  preserved verbatim**.
- Disposition: D2's append-only semantics should be understood as **every byte/line of the
  old file remains a verbatim subsequence/prefix of the new file and is not rewritten**
  (stricter: new = old + append, or old lines preserved verbatim). At implementation time,
  tighten "superset" to **"old content preserved verbatim + only append/paragraph-level
  extension allowed"** (B5 G4 granularity item). **This downgrades C2 from "acceptable" to
  "must be tightened at implementation time"** — the design layer already writes the
  semantics as "new ⊇ old"; implementation lands the stricter "verbatim preservation",
  erring toward fail-closed.

**C3 (med) `--force-push` overrides the immutable conflict, opening a hole to bypass I17**
- Failure mode: `--force-push` lets anyone overwrite OCI's immutable runs/vNN.yaml, breaking
  the "source of truth" and idempotency promise.
- Ruling: **partially holds** — but R7 **explicitly requires** "a local change needs an
  explicit `--force-push`"; this is a user-authorized escape hatch.
- Disposition: D9 limits `--force-push` as the **only** exemption to the immutable sha
  conflict, **not** an exemption to append-only non-superset (preventing lessons regression
  is always fail-closed); and `--force-push` is an **explicit command-line** flag, not on
  the default path. Acceptable — this is R7's stipulated semantics, not a 0007 hole.

**C4 (med) the "per-track 8 cap" can be over-issued on cross-machine push (two machines each
fork to 8)**
- Failure mode: R9 excludes concurrency, but the **user** might first fork to 8 on machine
A, then keep forking on machine B — local counting can't see A's branches, so the cap is
bypassed.
- Ruling: **partially holds** — the cap is a **local track-state** gate; cross-machine state
is not shared.
- Disposition: D6/I21's cap is **single-machine local** semantics (R9 already excludes
cross-machine concurrency); cross-machine consistency is backstopped by the **I17 immutable
rule at push time** — if two different tracks' vNN.yaml collide on path, I17(a) errors. The
cap is not a security boundary but a **local guard** (O13's original intent "prevent
infinite fork"); it does not promise cross-machine strong consistency. The design layer
positions the cap as a "local guard", not a distributed constraint.

**C5 (med) `context` reading "sibling-branch run summaries" may mix up run ownership**
- Failure mode: R12 requires context to contain a "sibling-branch run summary comparison
table", but 0006's run is keyed by `<name>` (D7); if two siblings run a same-named
strategy, run ownership is confused.
- Ruling: **partially holds** — depends on whether 0006's run manifest provenance is
sufficient to disambiguate.
- Disposition: D5 requires the run manifest to record direction+track_id+strategy sha+
snapshot+versions; `compare` locates a run by the (direction, branch, run_id) triple, not by
`<name>`. If the 0006 manifest lacks track_id (B5 G2), `compare` falls back to strategy sha
+ run_id. Acceptable; already listed as an implementation check-item in B5.

**C6 (med) the `inherited` source traceability of a `merge` candidate may point to a branch
that no longer exists**
- Failure mode: `merge --parents a b` writes `inherited: [a, b]`, but a/b were later
pruned — the audit chain breaks.
- Ruling: **holds** — prune is "the file is retained, not deleted" (R12 branch
lifecycle), but a cross-track merge's source may be in **another track**.
- Disposition: D8 requires merge to record the **source's sha256** (not just the branch
name); source files are **not modified**; on a cross-track merge the source hash is still
on OCI (I17 immutable), so the audit chain does not depend on the branch name surviving.
Implementable; already handled in D8 (record sha, not a bare name).

**C7 (low) `lyra list` is valid under read-only PAR, but "listing OCI objects" may expose
the object inventory**
- Failure mode: `list` lists OCI object names/sizes; if they contain sensitive paths, that
is information leakage.
- Ruling: **does not hold (low)** — the object paths themselves are not sensitive data
(alpha is "into OCI, not into git"; visibility is controlled by OCI permissions); `list`
only lists name/size (0002 `_LIST_FIELDS`), not content. The credential (PAR URL) is still
redacted (I19). Acceptable.

**C8 (low) the backup vs push relationship — could `backup` re-upload what push already
sent**
- Failure mode: `backup` = "push changed strategies+runs"; if push already uploaded, backup
uploads it again.
- Ruling: **does not hold** — D3/I20 idempotency guarantees same content is skipped
(sha256 comparison); `backup` is push's "one-shot + summary" wrapper over the same
idempotent path. Acceptable.

**Adversarial self-check conclusion**: C1/C2 are **high** (C1 = the largest
implementation-time uncertainty, already leaving the SDK exit + R10 real-bucket acceptance;
C2 = append-only semantics must be tightened to "verbatim preservation" at implementation
time), C3/C4/C5/C6 are **med** (all handled by D decisions or already listed as B5
implementation check-items), C7/C8 are **low** (do not hold / acceptable). No blocking design
defect; C1/C2 are **implementation-time gates** (R10 real-bucket pass + append-only
verbatim-preservation validation) that must be verified first in 0007's implementation.
