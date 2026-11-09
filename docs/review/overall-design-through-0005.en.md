# Lyra Overall Adversarial Review: Design Through 0005

> **中文：** [overall-design-through-0005.md](./overall-design-through-0005.md)

## Verdict

Lyra's component separation is generally clear: data ingestion, feature building, YAML compilation, past-only SQL, and the per-instrument trade state machine each have an implementation. However, the assembly contract between 0004 signal queries and 0005 bar inputs is incomplete. The current code and tests do **not** establish that the product is ready for reliable strategy search: data integrity, malformed-input handling, partial-bar semantics, and financing-day counting still have cross-stage gaps. The 0006 runner, R12 AI direction/branch/context workflow, 0007 OCI push/backup, 0008 migration of 332 strategies, and 0009 doctor/polish are still future stages. Their absence is incomplete work, not a defect in the build order.

This report records findings and recommendations only; runtime code was not changed.

## Scope and verification

Compared requirements R1–R12, `docs/hld.md`, decisions 0001–0005, the current `docs/ACTION_LOG.md` state, and the 0002–0005 implementation. Traced data, time, cost, and artifact boundaries along OCI → clean/aggregate → feature builder → compiler → trade engine.

- `.venv/bin/python -m pytest -q`: **187 passed**.
- `.venv/bin/python -m pyflakes lyra tests`: passed with no output.
- Targeted probes covered same-size objects without remote MD5, corrupt ZIPs, null/blank instrument/time keys, feature-output path traversal, multiple trades sharing one `trading_days` value, real bid/ask lookup, a legacy exit typo, numeric/Boolean column comparison, and mixed-instrument input.
- This review did not rerun a live OCI pull, the 21-instrument real-data E2E, or a 0006 runner E2E. Earlier logged successes are not claimed as fresh verification.

## Findings

### P1 — Defects that block reliable results

#### R1. File size is treated as proof of identical OCI content when MD5 is absent

**Evidence:** `lyra/oci_client.py:202–213`. When the remote object has an `md5`, the client compares MD5. When MD5 is absent but `size` exists, it compares only byte counts. A probe with different local and remote content of the same size and no remote MD5 still returned “up to date,” so the download was skipped.

**Impact:** New content under the same object name can continue to be treated as old data, breaking the content-integrity and reproducibility contract in R6/I20. File size is not a content check.

**Recommendation:** Do not treat size alone as a cache hit when the remote content digest is unavailable. Re-download and compute local SHA256, or verify another trusted remote checksum before reusing the file.

#### R2. Corrupt archives are silently skipped and can lead to an empty-data overwrite

**Evidence:** `lyra/pull.py:75–90` continues when `testzip()` finds a bad member. `lyra/pipeline.py:118–145` clears the target CSVs before cleaning; if no valid input remains, it writes zero-row bronze and zero-row 5m/1h Parquet without failing because expected data was not extracted.

**Reproduction:** A ZIP with a CRC error produced an empty extraction list without raising. Together with `clean_target=True` and the empty-bronze branch, corrupt input can look like a successful empty result and overwrite derived data.

**Impact:** Corruption cannot be distinguished from a legitimately empty dataset; a downstream run may treat an empty backtest as valid.

**Recommendation:** Fail closed for expected datasets: abort on archive validation failures or fewer valid extracts than expected. Do not replace the previous generation until the new artifacts have been fully validated.

#### R3. Required `instrument` / `time` columns do not guarantee valid key values

**Evidence:** `lyra/clean.py:106–115` checks required column names only. `lyra/clean.py:205–232` filters `is_complete` and deduplicates on `(instrument,time)`, but does not reject `instrument IS NULL`, `time IS NULL`, or empty strings. The current quality gates cover prices, spread, and volume.

**Reproduction:** A row with a NULL/blank `instrument` or `time` can survive clean into bronze. A NULL instrument can appear in the instrument list, after which the feature query using `instrument = NULL` returns no matching rows; a NULL time can produce a feature row that cannot be ordered/executed correctly.

**Impact:** Invalid primary keys are not rejected at the data boundary. The failure appears later in aggregation, feature building, or strategy execution, where it is harder to diagnose.

**Recommendation:** Before writing bronze, require keys to be non-NULL, non-empty, and validly formatted. Also state and test that time is a valid, sortable UTC observation time.

#### R4. `trading_days` is one scalar per `simulate()` call, so it cannot represent each trade's holding interval

**Evidence:** `lyra/trade_engine.py:106–111` defines `trading_days` as an optional scalar. `_finish()` passes that same value to `_day_count()` for every trade (around lines 157–172). A single `simulate()` call can return multiple trades with different holding intervals.

**Reproduction:** Two trades in one call, held for 2 and 5 hours, were both charged as five financing days when `trading_days=5` was passed. A scalar cannot let the 0006 runner represent different weekend/holiday crossings for each trade.

**Default risk:** `trading_days=None` still derives natural days, while R4/O15 defines trading days excluding weekends and market holidays. A caller that forgets the override silently gets a cost basis that differs from the settled requirement.

**Recommendation:** Before 0006 integrates the engine, make day count depend on each actual entry/exit interval (for example, compute it per trade through a deterministic trading-calendar calculator). The Lyra contract path should fail closed when trading-day counts are missing. Nova parity can remain an explicit compatibility-test mode, but should not define default product semantics.

#### R5. Partial-bar policy conflicts across the design, and the feature builder consumes partial bars

**Evidence:** HLD §2.1 (`docs/hld.md:57`) says partial buckets are dropped and counted. 0002 I21 (`docs/decisions/0002-ohlcv-data-sync.md:296`) says to retain available bars in a window and flag partial bars with `n_bars`. `lyra/aggregate.py:92–106` aggregates available rows and outputs `n_bars`; tests explicitly assert partial 5m/1h buckets. Feature tables retain `n_bars`, and feature computation does not filter for completeness.

**Impact:** Boundaries or gaps in 1m data can create 5m/1h observations with fewer constituent bars, while indicators and strategies consume them as ordinary bars. If the actual contract is to drop partial bars, current output is wrong. If 0002's retention policy is the latest decision, HLD misleads downstream developers and AI.

**Recommendation:** If the more specific 0002 I21 is authoritative, update HLD and define the meaning of `n_bars` in the 0003/0004 consumption contract. If the product should drop partial bars, update the 0002 decision, aggregation, and tests together. Consumers should not have to guess.

#### R6. The compiler signal query omits OHLC, so it does not directly satisfy the trade-engine input contract

**Evidence:** The SELECT in `lyra/compiler.py:283–303` outputs only `instrument`, `time`, and the four entry/exit signals. `lyra/trade_engine.py:114–118` also requires `mid_o/mid_h/mid_l/mid_c` on every row. Compiling the example YAML in this review confirmed that OHLC columns are absent from the SQL result.

**Impact:** Passing compiled SQL rows directly to `simulate()` fails because fields such as `mid_o` are missing. HLD says 0006 executes SQL and drives the state machine, but there is no defined or implemented adapter joining signals back to price bars on `(instrument,time)`.

**Recommendation:** Specify one assembly path in the 0006 decision: preserve signal keys and align them with OHLC rows from the same timeframe. Fail closed on missing, duplicate, or NULL keys. Add an end-to-end test from YAML → SQL → aligned bars → `simulate()`.

#### R7. `_quote()` looks for bid/ask columns that do not match the data contract

**Evidence:** `lyra/trade_engine.py:83–103` turns `point="mid_o"` into `bid_mid_o` / `ask_mid_o`. The clean-input contract names those columns `bid_o` / `ask_o`, while aggregation currently outputs only mid OHLC. A probe with `mid_o=100, bid_o=99, ask_o=101` returned 100 for both long and short quotes, ignoring the actual bid/ask.

**Impact:** If the runner supplies real quote columns, the engine still falls back to mid plus configured spread and ignores the actual spread; fills and costs can be wrong. Since 0002 currently aggregates only mid data, the runner's intended quote source must be made explicit.

**Recommendation:** Align trade-engine field lookup with the input schema (for example, map `mid_o` to `bid_o` / `ask_o`) and test actual-quote priority, missing-field fallback, and spread double-counting.

#### R8. A typo inside the legacy `exit.feature` block silently drops the exit condition

**Evidence:** `lyra/strategy_schema.py:703–727` accepts top-level `feature` as a compatibility key. It parses the block only when the nested `when` key exists, and does not allow-list other nested keys. A probe with `exit: {feature: {whne: ...}}` was accepted with both `exit_long` and `exit_short` as `None`; the compiler emitted `FALSE` exit conditions.

**Impact:** A user may believe an indicator exit is enabled while only stop/time/end-of-data exits remain. The strategy still validates and compiles, silently changing its behavior.

**Recommendation:** Require exactly the `when` key in the legacy mapping and reject unknown nested keys, or retire the legacy shape. Add a typo-rejection test.

### P2 — Known cross-stage risks that remain open

#### R9. Feature-vs-feature comparisons do not validate the value-domain types on both sides

**Evidence:** In `lyra/strategy_schema.py:387–403,427–464`, parsing a known right-hand column resolves but discards its `FeatureKind`; the AST retains only the left-hand kind. `lyra/compiler.py:213–219` emits a direct column comparison. For example, a numeric feature compared with a Boolean state can pass validate/compile and fail at DuckDB execution with `BinderException` (reproduced in this review with `DOUBLE > BOOLEAN`).

**Impact:** Valid YAML is not necessarily executable; the error appears only at run time. Comparisons between numeric features with different units can also pass and produce meaningless signals.

**Recommendation:** Validate kind/unit compatibility before compilation and fail at the YAML path for incompatible columns. Add a matrix of Boolean/state, event, ordinal, and continuous combinations.

#### R10. An instrument value can escape the data root when constructing feature output paths (0003 Batch-1 parked item)

**Evidence:** `lyra/features.py:776–786` inserts the instrument directly into the filename. `run_features()` writes the resulting path without validating the filename or resolved path boundary (lines 855–860). A probe using `../../../../tmp/...` resolved outside the data root.

**Impact:** If source or alpha data contains an abnormal instrument value, feature output may overwrite a matching path in the repository or a user directory. 0003 Batch 1 parked this for 0004/0007; it remains open.

**Recommendation:** Validate instrument slugs at the clean-input boundary and verify the resolved path remains under the configured data root before writing. Do not rely only on OCI data being “usually controlled.”

#### R11. Multi-instrument feature writes are not atomic; failure can leave mixed versions (0003 Batch-1 parked item)

**Evidence:** `lyra/features.py:758–773` overwrites the final Parquet directly. `run_features()` writes one instrument at a time (855–862), without a staging directory, manifest, or one-step publication.

**Impact:** If instrument N fails, the first N−1 files are new while the rest remain old. Catalog or later runs can read a mixed generation. The earlier 0003 review assigned this to 0004/0007, but it is still present.

**Recommendation:** Write the whole generation to staging, validate completeness/version/instrument set, then atomically switch the visible pointer. Keep the previous complete generation on failure.

#### R12. Alpha feature semantics are not bound to the feature version identity (0003 Batch-1 parked item)

**Evidence:** `lyra/features.py:584–599` hashes registered names, parameters, and warm-up, and includes Python/NumPy versions; it does not include alpha module source hashes or alpha version labels. The current decision assigns the full provenance boundary to 0007.

**Impact:** Alpha code can change while its feature identity stays the same, so values may differ under the same identity. This weakens reproducibility and the audit chain for immutable OCI objects.

**Recommendation:** Before finalizing 0007, define how alpha source/contract hashes enter Parquet/run provenance, and verify that a code change changes the identity.

#### R13. The documented original-row-order tie-break is not implemented in clean SQL

**Evidence:** 0002 specifies selecting a duplicate by “non-null payload count → source filename → original row order” (`docs/decisions/0002-ohlcv-data-sync.md:85,145`). The actual `lyra/clean.py:221–226` sorts only by `_payload_score DESC, _source_file ASC, time ASC`; candidates with the same key, score, and source file have no unique sort field.

**Impact:** I18's deterministic survivor rule is incomplete. DuckDB does not promise to choose the same row when all `ORDER BY` expressions tie. The existing repeat-run test does not cover this conflicting input.

**Recommendation:** Preserve a stable source row number during CSV reading and use it in the ordering. Add a same-file, same-score duplicate with different payload values to the tests.

#### R14. `simulate()` accepts mixed-instrument input without failing fast

**Evidence:** `simulate()` documents a one-instrument input (`lyra/trade_engine.py:112–118`), but does not verify that the input has only one instrument. A probe signaled entry on instrument A and then supplied a bar for B; the engine raised no error and attributed the trade to B.

**Impact:** If the runner accidentally sends multiple instruments into one state machine, entry signals, fill prices, and report instrument can be mismatched. Even if the runner is designed to call the engine per instrument, the API does not guard against misuse.

**Recommendation:** At the start of `simulate()`, verify all bars contain exactly one instrument and are strictly time-ordered; raise a clear error otherwise.

### P3 — Documentation and delivery consistency

#### R15. The one-command OCI sync name conflicts

**Evidence:** Requirements R7 says `lyra sync`; HLD §2/§8 and 0001 say `lyra backup`. 0007 is not implemented yet, so no code currently resolves the ambiguity.

**Recommendation:** Choose one user-facing command before the 0007 decision and state whether a compatibility alias is supported.

#### R16. 0001 / 0002 decision metadata still says Proposed

HLD and ACTION_LOG record 0001 and 0002 as complete, while the decision metadata still says “proposal / awaiting user approval.” This is an audit-state inconsistency, not a runtime defect. Update the status at the next documentation maintenance point without rewriting historical decisions.

#### R17. HLD/doctor expect a lock file, but the repository has none

HLD describes `requirements.lock` as pinning transitive dependencies, and `pyproject.toml` comments on it, but the repository currently has no `requirements.lock`, `uv.lock`, or equivalent lock file. R8's same-version reproducibility and the doctor dependency check therefore lack the lock input described in the docs.

**Recommendation:** Choose and land one locking mechanism in 0009, or correct the docs so they do not describe a file that is not delivered.

## Verified design surfaces and stage gates

- The 0004 compiler emits controlled, parameterized past-only SQL; temporal operations require a complete N-row window and preserve NULL semantics. No new look-ahead defect was found. The 0004 Batch-2 fixes continue to pass the full suite.
- 0005 has tests for next-observed-open execution, the 2% adverse stop, gap fills at the actual open, stop priority on the same bar, and the one-trade-per-instrument state machine. This review did not overturn those semantics.
- There is still no `lyra run`, monthly metrics/report, per-trade calendar integration, or R12 multi-AI tracks/context/branch lifecycle. The 0005 Python API is not an end-to-end strategy-search entry point; O16 still blocks migration of the 332 strategies in 0008.
- Recommended order: resolve R1–R8 (data integrity, execution semantics, and the 0004→0005 interface) before 0006; close R10–R12 at the 0004/0007 consumption and publication boundary; close R15–R17 through later decisions/doctor work.

## Carry-forward from earlier reviews

R10, R11, and R12 correspond to 0003 Batch-1 findings H1, H4, and H3. They were parked for 0004/0007 at the time; this review does not present them as new discoveries, but confirms they remain unresolved. The 0005 Batch-3 review added `trading_days` support and fail-closed timestamp validation, but this review found that one scalar still cannot represent multiple trade intervals within a call.

---

## Disposition (2026-11-10, ruled after item-by-item verification against current code)

> This is a cross-AI independent review. The dispositions below are based on verifying each item against the current code (not copying the report's conclusions), and distinguish "already landed in batch-4" from "landed now".

| Finding | Ruling | Rationale and action |
|---|---|---|
| R1 OCI size-fallback | **Accept (fixed)** | Size is not a content proof. `oci_client._is_local_up_to_date` drops the size-only skip: without a verifiable remote digest (md5) it always re-downloads (fail-closed). Added `test_oci_size_match_is_not_a_content_proof`. |
| R2 corrupt ZIP silently skipped | **Accept (fixed)** | `pull.extract_zips_to_csv` adds a `strict` mode: validates each member via `testzip` **before** clearing the target; failure raises `CorruptArchiveError` (no more overwriting prior data with an empty result). Pipeline enables `strict=True`. Added `test_pull_strict_fails_on_corrupt_archive_before_clear`. |
| R3 blank/NULL keys not rejected | **Accept (fixed)** | `clean._clean_sql` WHERE adds `instrument IS NOT NULL AND TRIM(instrument)<>'' AND time IS NOT NULL`. Added `test_clean_rejects_blank_instrument_and_null_time`. |
| R4 `trading_days` scalar | **Accept (already landed in batch-4, C2)** | Superseded by the per-trade counter `trading_days_for(entry, exit)`; default `None` = natural days preserving the nova cross-check. Stale finding in this report. |
| R5 partial-bar contract conflict | **Accept (doc fixed)** | 0002 I21 is authoritative (keep + `n_bars` marking). Two stale HLD "partial dropped" statements fixed (zh+en). Code already conforms to 0002. |
| R6 signal query lacks OHLC | **Accept (already landed in batch-4, C1)** | compiler OHLC projection + runner bars alignment implemented. Stale finding in this report. |
| R7 `_quote` column names | **Accept (already landed in batch-4, M2)** | `_quote` now strips the `mid_` prefix to use real `bid_o/ask_o`. Stale finding in this report. |
| R8 `exit.feature` typo | **Accept (already landed in batch-4, M3)** | `exit.feature` now strictly allows only `when`; unknown keys fail-closed. Stale finding in this report. |
| R9 feature-vs-feature value domain | **Accept (already landed in batch-4, M1)** | Value-domain gate (boolean/ordinal/numeric mismatch fail-closed) implemented, 5 `test_b4_m1_*` regressions. Stale finding in this report. |
| R10 path traversal | **Hold (0007)** | Parked in 0003 batch-1; belongs to the 0004/0007 publication boundary. To be closed at 0007 decision. |
| R11 non-atomic write | **Hold (0007)** | Parked in 0003 batch-1; belongs to the 0004/0007 publication boundary. To be closed at 0007 decision. |
| R12 alpha version binding | **Hold (0007)** | Parked in 0003 batch-1; full provenance boundary is 0007's. To be closed at 0007 decision. |
| R13 dedup tie-break | **Accept (fixed)** | Added a content-hash final tie-breaker (same file/key/score/different content still deterministically survives, I18). Added `test_clean_dedup_deterministic_on_conflicting_content`. |
| R14 `simulate` mixed instruments | **Accept (already landed in batch-4, m2)** | `simulate` now rejects mixed instruments. Stale finding in this report. |
| R15 command name sync/backup | **Hold (0007)** | 0007 not implemented; command name to be unified at the 0007 decision (lean to keep `lyra backup`, `sync` as alias). |
| R16 0001/0002 metadata | **Accept (fixed)** | 0001/0002 decision docs "proposal" → "implemented" (zh+en), aligned with HLD/ACTION_LOG. |
| R17 lock file missing | **Hold (0009)** | Locking mechanism to be finalized at 0009 doctor; not introduced now. |

**Tally**: 11 accepted (R1/R2/R3/R5/R13/R16 landed now + R4/R6/R7/R8/R9/R14 already landed in batch-4), 6 held (R10/R11/R12→0007, R15→0007, R17→0009), 0 rejected.
**Verification**: 223/223 tests green (+4: R1/R2/R3/R13), pyflakes clean.
