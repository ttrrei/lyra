# Lyra Overall Adversarial Review: Design Through 0008

> **中文：** [overall-design-through-0008.md](./overall-design-through-0008.md)

## Verdict

Lyra’s main path now runs from OCI data sync through feature building, constrained YAML compilation, per-instrument backtests, metric reports, OCI push, and migration regression for 12 formal research directions. Stages 0001–0008 are recorded as complete in `ACTION_LOG`; the real OCI bucket acceptance for 0007 passed, and the 12 formal 0008 directions passed validation and runs across 21 instruments. Core execution rules are clear and tested, including past-only windows, fills at the next observed open, the mandatory 2% adverse exit, and per-instrument reporting.

However, the current implementation **does not yet support the promised independent multi-AI strategy-search loop**. The most serious gaps are in 0007: default context combines every track in a direction, and the supposedly frozen hypothesis stores only an old hash while continuing to read the current file. Run artifacts are written to a different default directory than context scans; the official `v01` strategy `spec_id` also cannot be mapped back to its branch. Comparisons can include another direction. In addition, the `_1` branch names explicitly allowed by O12 are rejected. The project-wide acceptance baseline still contains the false “332 strategy YAMLs” compatibility requirement, and the financing-day requirement conflicts with the ruled implementation.

**Lyra can proceed to 0009 Polish, but the project should not be described as having passed overall R10 or having an accepted multi-AI search loop.** During 0009, prioritize the P1 findings in this report and synchronize superseded requirements and bilingual documents. This review does not change runtime code; this turn only refreshes the current-state block in the central action log and adds this bilingual report.

## Scope and verification

Compared requirements R0–R12, HLD §8, decision docs 0001–0008, the OCI alpha-layout proposal, the current `ACTION_LOG`, and the corresponding code. The review traced data contracts, time and financing semantics, strategy compilation, run identity, track isolation, OCI publication, and migration acceptance end to end.

- `.venv/bin/python -m pytest -q`: **305 passed**.
- `.venv/bin/python -m pyflakes lyra tests`: passed with no output.
- Isolated temporary-directory probes reproduced cross-track context exposure, hypothesis-baseline drift, cross-direction run matching, rejection of `_1` branch names, and feature-output path escape.
- A behavioral probe used two trading-day callbacks with the same fingerprint but different Fri-to-Mon results.
- Read-only inspection of default run locations found 24 `metrics.json` files under `~/.lyra/runs` and 0 under the workflow’s default scan root, `~/.lyra/default/runs`. An archived formal-direction run has `spec_id=directions_pullback_reentry`, while the corresponding branch file is `v01.yaml`.
- No OCI writes or fresh real-bucket acceptance were run in this turn; the real-bucket acceptance is based on the existing ACTION_LOG #105/#106 record.

## End-to-end stage review

| Stage | Design responsibility | Adversarial conclusion |
|---|---|---|
| 0001 repo / OCI split | Boundaries for core, alpha, and local mirrors | The main rules are clear; normal alpha paths are kept out of git. |
| 0002 pull / clean / aggregate | Download, validate, clean, and aggregate | The main data path has run; clean rejects blank/NULL keys, aggregation retains partial bars with `n_bars`, and O18 is closed with Lyra’s bar set as canonical. Feature output paths still lack equivalent path validation. |
| 0003 feature builder | Fixed-parameter registry and per-instrument wide tables | 146 core features are registered and fully recomputed; path traversal and non-atomic multi-file publication remain data-layer risks. |
| 0004 compiler | YAML validation and past-only SQL | Window and causality gates are clear; this review found no new look-ahead defect. |
| 0005 trade engine | Next-open execution, 2% stop, one trade per instrument | Core execution constraints have tests; the default financing basis conflicts with R4/O15’s requirement text. |
| 0006 metrics / runner | Run, metrics, reports, reproducible identity | Per-instrument reporting and artifact checks are solid; default output paths, run/branch association, callback fingerprinting, and feature-snapshot identity remain insufficient for trustworthy comparisons. |
| 0007 push / backup / R12 | OCI publication and multi-track research workflow | PAR-only behavior and real-bucket acceptance are closed; context isolation, run discovery, and O12 naming still break the multi-AI promise. |
| 0008 migration / regression | Formal-direction migration and regression | The 12 formal directions were verified; the old 332-YAML compatibility baseline remains in requirements, and the bilingual 0008 decision docs contain stale conclusions. |

## Findings

### P1 — Strategy-search loop and acceptance risks

#### R1. Default context combines all tracks and reads the current hypothesis, not a frozen track version

**Evidence:** In `lyra/workflow.py:461–506`, `render_context()` reads the direction-level `strategies/<direction>/hypothesis.md` before filtering tracks by the optional `track` argument. If the caller omits `track`, every result from `list_tracks()` is rendered. `create_track()` stores only the creation-time hypothesis SHA256 in `tracks/<direction>/<track>.json`; it does not save the hypothesis content or check that the current file still matches that hash when rendering.

**Reproduction:** In a temporary workspace, create `weak_ai` and `strong_ai` tracks and call `render_context()` without `track`; the output contains both. Then change the shared hypothesis: the `weak_ai` baseline hash no longer matches the current hash shown by context, and context still contains the changed text.

**Impact:** The default command violates R12’s isolation semantics; different AIs see each other’s branch summaries and lessons. When the direction hypothesis changes, an old track works from the new text while still displaying its old baseline, so it is impossible to tell whether tracks evolved from the same frozen hypothesis.

**Recommendation:** Require an explicit track for single-AI context, or allow omission only when there is exactly one track. Cross-track aggregation should occur only through user-triggered synthesis. Save an immutable hypothesis snapshot (or a content-addressed object) at track creation, and validate it along with the feature and engine baseline when rendering.

#### R2. Runs cannot be reliably joined back to branches; comparison can miss or mix directions

**Evidence:** `runner._default_out()` (`lyra/runner.py:351`) writes to `~/.lyra/runs`; the CLI workflow workspace resolves to `~/.lyra/<workspace>` (`lyra/cli.py:854–858`). `_runs_for_branch()` scans only `<workspace>/runs/*/*/*/metrics.json` (`lyra/workflow.py:563–577`). It matches only `spec_id` to the branch slug and does not use the supplied `direction`. Formal 0008 strategy YAMLs use IDs such as `directions_<name>`, while their branch filenames are `v01.yaml`. Local run metrics/manifests also do not contain `track_id`.

**Reproduction:** The current default output contains 24 run metrics, while the workflow scan directory contains 0; lookup for `pullback_reentry/v01` returns no results. A temporary run with `direction=crypto, spec_id=v01` is returned by a query for `fx/v01`.

**Impact:** Under the normal R12 sequence—context → run → compare—the real result of the formal v01 is invisible. Even after fixing the root path, a run from another direction with the same slug can contaminate the comparison. Runs with different windows, timeframes, or feature snapshots are also not grouped or checked, so `compare --siblings` cannot guarantee like-for-like conditions. Without track ownership, a local run cannot show which AI/track produced it.

**Recommendation:** Unify the runner output root with the workspace. Record strategy-file identity, direction, branch, track, window, and feature snapshot when creating a run. Join runs by those exact fields and reject comparisons across incompatible cohorts.

#### R3. `_1` / `_2` branch names approved by O12 are rejected by workflow and OCI classification

**Evidence:** O12 in `docs/open-questions.md` is closed and explicitly allows names such as `v04ab_1` and `v04ab_2` for variants of the same strategy. But `workflow._BRANCH_NAME_RE = ^v\d+[a-z]*$` and `oci_push._VNN_RE = ^v\d+[a-z]*\.yaml$` do not accept underscores.

**Reproduction:** Both the workflow naming rule and OCI file classifier reject `v04ab_1`; `new_version()` fails closed.

**Impact:** Multiple parameter variants of a direction or parent branch cannot be created or pushed under the user’s settled naming rule. Replacing the numeric suffix with a letter cannot represent the O12 variant numbering.

**Recommendation:** Have creation, merge, push classification, schema, and tests share one version-name grammar that implements O12; cover `_1`, `_2`, and invalid suffixes.

#### R4. Requirements’ “332 strategies / unchanged 17 feature names” baseline was superseded by 0008

**Evidence:** Requirements R2, R10, and R11 (Chinese and English) still require all 332 strategy YAMLs to run unchanged and say 17 feature names remain unchanged. In #99, 0008 established that 332 was the total YAML-file count in the Nova repository: 17 hand-written strategies, 146 campaign snapshots, and 169 run/manifest files; Moneta did not contain 332 strategy YAMLs. In #100, the user ruled that 10 names are registered under renamed canonical names, `rsi_14` is not added and affected strategies use `rsi_12`, the ATR basis changes from 24 to 12, and new features are added. The actual formal migration scope is 12 direction strategies; 146 campaign files remain under temp/ for 0010 triage.

**Impact:** The acceptance objects and compatibility semantics in requirements no longer correspond to the project’s actual scope. Overall R10 cannot be determined by validating 332 files as strategies. R10 also requires `lyra-doctor`, which is not currently a CLI command, and 0010 temp/ triage has not happened. Tests pass, the 12 formal directions ran, and the real OCI bucket gate passed, but **overall R10 still does not satisfy every clause in the current requirements**.

**Recommendation:** In 0009, rewrite R2/R10/R11 using the user-approved acceptance set. Distinguish the 12 formal directions, 146 temp campaign files, and non-strategy YAMLs; state that R10 is not fully signed off until doctor is addressed, and synchronize Chinese and English.

#### R5. Financing requirements still say trading days while the ruled implementation defaults to calendar days; the “no observable difference at 5m/1h” explanation is false

**Evidence:** Requirements R4 and open question O15 still require weekends and market holidays to be excluded from financing days. O17 / 0006 D6 instead set per-trade calendar days as the default, and the code uses natural days when `trading_days_for=None`. D6 explains that current 5m/1h granularity makes the difference unobservable, but financing is computed from entry/exit elapsed time, not the number of bars. 0005 already tests a Fri-to-Fri case with 7 natural days versus a 5-day trading-calendar override.

**Impact:** The behavior choice is recorded, but requirements still contain the opposite normative rule. Callers cannot identify the correct result from the requirements baseline. Natural versus trading days changes trade returns when financing is nonzero; timeframe does not erase the difference.

**Recommendation:** This review does not re-decide the user-approved default. Rewrite R4/O15 as an explicit exception or mark them superseded by O17, and correct the “no observable difference” rationale. Keep the CLI/API support boundary synchronized across both languages.

#### R6. An instrument value is concatenated into a feature filename and can write outside the configured data root

**Evidence:** `clean._clean_sql()` rejects NULL/blank instruments but does not restrict path separators. `features.feature_path()` (`lyra/features.py:887–897`) concatenates the instrument into `<instrument>.parquet`, and `run_features()` writes directly to that path (`lyra/features.py:964–970`).

**Reproduction:** `feature_path('/tmp/lyra-data', 60, '../../../../../../tmp/lyra-review-escape').resolve()` returns `/tmp/lyra-review-escape.parquet`, outside the data root.

**Impact:** Imported data with a malicious or corrupted instrument value can cause the feature builder to overwrite a file outside the data directory. An OCI source of truth does not make every imported CSV value trustworthy.

**Recommendation:** Restrict instrument names to permitted single path components at the clean boundary. Before writing, verify the resolved target remains inside the data root and reject symlink escapes.

### P2 — Reproducibility, publication atomicity, and documentation closeout

#### R7. Multi-instrument feature generation overwrites files one by one and can expose mixed versions

**Evidence:** `run_features()` overwrites each instrument’s final Parquet immediately after computing it. There is no staging generation, complete instrument-set manifest, or atomic publish step. `Catalog.upsert_feature_views()` registers `features/.../*.parquet` as a glob and does not check that each file has matching `feature_version` / `version_string`; the runner has no all-instrument consistency gate either.

**Impact:** An interrupted upgrade or disk failure leaves some new files and some old files. DuckDB’s wide-table view still reads that set. The user may get incomplete or cross-version instrument results, with no easy way to restore the last complete generation.

**Recommendation:** Write to a staging generation; validate the expected instrument set and uniform version metadata; publish only after validation. Catalog and runner should fail closed on a mixed generation.

#### R8. The fixed-sample `trading_days_for` fingerprint cannot identify callback behavior

**Evidence:** `runner._counter_fingerprint()` (`lyra/runner.py:124–152`) probes only 2024-01-01→2024-01-08 and a same-day interval. A custom callback can return the same values for those inputs but different values for actual holding intervals.

**Reproduction:** Two pure functions both return 5 / 0 for the canonical samples, so their fingerprints match; for Friday 2024-01-05→Monday 2024-01-08, one returns 0 and the other 1. The run ID payload receives the same fingerprint for both.

**Impact:** Two runs that charge different financing on actual trades can share the callback fingerprint; the claim that all output dependencies enter the run identity is not met. A finite sample cannot prove the behavior of an arbitrary callable.

**Recommendation:** Accept a named, versioned deterministic calendar/counter and require its content hash or explicit identity token. Do not treat a few probes as proof of arbitrary callback behavior.

#### R9. `feature_snapshot_id` is only a list of catalog view names, not a feature-data snapshot identity

**Evidence:** `runner.py:257` serializes `Catalog.views()` as `feature_catalog_snapshot`; `Catalog.views()` returns only schema/view names (`lyra/catalog.py:126–140`). That value is later written to reports/metrics as `feature_snapshot_id`. It contains no SHA256 for the Parquet files, no feature `version_string`, and no alpha feature source digest. `data_digest` is included in the run ID but is not written to the manifest as reviewable evidence.

**Impact:** Feature files or values can change while the report’s `feature_snapshot_id` remains the same. An AI cannot verify from context/run reports alone that two runs used the same data and alpha code. The content digest in the run ID reduces identity collision risk but does not provide explainable provenance.

**Recommendation:** Define snapshot identity over each consumed input file’s relative path and SHA256, feature registry/version, and alpha module/contract hashes. Store the digest manifest with the run and reference it from each track baseline.

#### R10. The 0008 bilingual decision docs retain stale O18 and R10 states

**Evidence:** Section 3.1 of `0008-migration-and-regression.en.md` still says the bar-set delta is “100% aggregation-rule-driven,” while the actual attribution is 179,550 (97.6% aggregation difference) + 4,359 (2.4% window tail). Its revision history still says O18 parked. Section 5 in both Chinese and English still says R10 real-bucket acceptance is held at #98, although ACTION_LOG #105/#106 record the bucket acceptance and 0007 sign-off. The English 0008 revision 0.3 also still calls O18 parked. This does not match the bilingual synchronization recorded in #103.

**Impact:** The English decision doc gives a wrong attribution and stale acceptance status, conflicting with the authoritative action log and Chinese body. This weakens the audit trail for migration.

**Recommendation:** Update the active conclusions and R10 status in both 0008 decision docs. Historical revision rows may remain as records, but label them as contemporaneous snapshots; do not leave their claims in active conclusions.

#### R11. OCI layout and authentication docs still describe superseded behavior

**Evidence:** Requirements R6 still describes `raw_csv/raw_parquet/market/<minutes>m/features/<minutes>m` and `runs/<name>/<date>`; `docs/proposals/oci-alpha-layout.md` remains marked “Proposal, pending review” and uses the old layout. Current 0002 uses `raw_zips` and `ohlcv_5m/ohlcv_1h`; 0007 D7 defines OCI runs as `runs/<direction>/<track_id>/<run_id>`. In addition, `requirements.en.md` R7 still says OCI auth is optional, and the English 0007 D4 paragraph still has `auth_file optional` before the final M3 rejection note.

**Impact:** Different languages and documents teach different object layouts and authentication capabilities. A user or AI following the old layout may upload to the wrong bucket prefix or expect an unavailable SDK/auth_file.

**Recommendation:** Promote the settled 0002 / 0007 layout and PAR-only rule to the active specification. Mark the old proposal as superseded/historical, and align requirements plus the current English 0007 paragraph with the Chinese ruling.

#### R12. Developer entry points for 0009 still point to artifacts that do not exist

**Evidence:** README’s repository layout still lists `src/`, unstarted tests, and placeholder decision docs. Getting started installs `requirements.lock` and recommends `lyra-doctor`, but the repo has no lock file, no files under `.github/workflows`, and no `lyra-doctor` command. README still describes optional OCI credentials when PAR is not used, contrary to the M3 rejection. The current CLI help has commands from `pull` through `synthesize`, but README has no complete command reference. `config_example.yml` was already updated early in #104 and should not be listed as unfinished in 0009.

**Impact:** New developers cannot follow the installation/acceptance instructions. Reproducible dependency setup and CI gates also lack the referenced lock/workflow files. The missing doctor means requirements R10 remains incomplete.

**Recommendation:** In 0009, rewrite README for the actual CLI and B13 paths; select one lockfile tool and Python-version policy; add CI; define and implement doctor or revise R10; remove the rejected auth_file path.

## Review metadata corrected this turn

At the start of this review, the `ACTION_LOG` current-state block still said 0007 awaited R10, listed the 11-11 review as pending, and carried an old financing question. Those statements conflicted with #105/#106, #103, and #107. This turn updated the Chinese and English state blocks to show 0001–0008 complete, 0007 R10 passed, 0009 next, and no pending user input. Historical log entries remain append-only. This is not an unresolved code finding.

## Priorities before 0009 closeout

1. Address R1–R3 first: restore track isolation, make run-to-branch discovery/comparison work, and implement the approved branch names.
2. Fix R6 and add generation consistency / atomic publication protection for R7.
3. Synchronize the settled user rulings and acceptance facts in R4, R5, and R10–R11; do not reopen settled decisions while editing docs.
4. Complete README, lock, CI, and doctor entry points in 0009 before claiming overall R10 passed.
5. Close R8–R9 as run-provenance work. Until those identity fields exist, comparisons should be marked incomparable rather than silently interpreted.


---

## Disposition record (2026-11-12, lyra development AI)

> Per-finding accept / park / reject dispositions with landing evidence. No rejections.

| ID | Level | Disposition | Landing evidence |
|---|---|---|---|
| R1 | P1 | **Parked (0009)** | Verified: `workflow.render_context` merges all tracks; `create_track` stores only the hypothesis SHA256, rendering the current file text. The fix needs a two-part design (track-isolated context + hypothesis content snapshot), part of the 0009 track-system closeout. Until then, `render_context` output is human-readable only and never feeds a persisted conclusion. |
| R2 | P1 | **Parked (0009)** | Verified: `runner._default_out()` = `~/.lyra/runs` (runner.py:351) while `workflow._runs_for_branch` scans `~/.lyra/<workspace>/runs/...`; official v01's `spec_id=directions_<name>` matches no branch. Fix = runs-dir unification + run→branch/direction/track identity fields + incomparable-marking in compare; all 0009 scope. |
| R3 | P1 | **Accepted (fixed)** | `_BRANCH_NAME_RE` and `_VNN_RE` now allow `(_\d+)?` (workflow.py / oci_push.py); regression tests `test_o12_variant_ordinal_branch_names_accepted` and `test_o12_variant_ordinal_suffixes_classify_immutable` added. `lyra validate` now accepts `v04ab_1`. |
| R4 | P1 | **Accepted (fixed)** | `docs/requirements.md` + `.en.md`: R2/R10/R11 332/17 baselines replaced with the current ruling state (12 directions delivered, 146 temp campaigns pending 0010 triage, feature naming per the three rulings, 134→146+prior12); old baselines explicitly marked superseded. |
| R5 | P1 | **Accepted (fixed; no re-ruling)** | Requirements R4 cost line (both languages): "per trading day" marked superseded by O17/0006 (default per-trade natural days + `trading_days_for` compliance outlet). The user's established default was **not** re-opened. |
| R6 | P1 | **Accepted (fixed)** | `features.feature_path` now validates the instrument (rejects `.`/`..`/`/`/`\`/NUL) and asserts `root in resolved.parents` (fail-closed); regression test `test_feature_path_rejects_instrument_traversal` added. |
| R7 | P2 | **Parked (0009)** | Verified: `run_features` overwrites per instrument directly; the catalog does not check version consistency. Fix = staging + atomic publish + generation-consistency gate, part of the 0009 publish-semantics closeout; current data is produced by a single `lyra features` process with no concurrent-write window. |
| R8 | P2 | **Parked (0009)** | Verified: `_counter_fingerprint` probes only 2 fixed points; distinct counters can share a fingerprint. Fix = named/versioned counter identity token, bundled with R9 as the run-provenance closeout in 0009. |
| R9 | P2 | **Parked (0009)** | Verified: `feature_snapshot_id` is only the list of table names, not a data identity. Fix = per-file SHA256 + registry/alpha hashes in the snapshot digest, 0009 run-provenance closeout. Until it lands, any cross-run comparison is treated as "incomparable" (report point 5). |
| R10 | P2 | **Accepted (fixed)** | 0008 both languages: §3.1 unified as "183,909 = 179,550 (97.6%) + 4,359 (2.4%) window tail"; revlog 0.3 "O18 parked" annotated as a pre-closure snapshot; §5 R10 status synced to the #105/#106 sign-off facts. |
| R11 | P2 | **Accepted (fixed)** | Requirements R6 layout (both languages) now states the 0002/0007 actual paths (raw_zips / ohlcv_5m-1h / lyra-features / canonical lyra-runs path); requirements.en R7 "OCI auth optional" replaced with the M3-rejected wording; `docs/proposals/oci-alpha-layout.md` header marks the layout section as superseded (design principles remain valid). |
| R12 | P2 | **Accepted (0009 scope)** | By definition the 0009 deliverables: README rewrite against the real CLI, single lockfile + Python version policy, CI, `lyra-doctor` scope decision and implementation. `config_example.yml` already done in #104 — not re-scoped. |

**Conclusion**: the 3 code-level P1 items (R3/R6 + R4 docs) and all doc P2 items (R4/R5/R10/R11) landed this round; R1/R2/R7/R8/R9 parked in 0009 and registered on its task list; R12 is the 0009 work item itself. 308 tests pass, pyflakes clean.
