# Decision: YAML Compiler (including feature-vs-feature)

> **中文**: [0004-yaml-compiler.md](./0004-yaml-compiler.md)

## Metadata

| Field | Value |
|---|---|
| ID | `0004` |
| Title | YAML compiler (strategy validation + past-only SQL codegen) |
| Status | **Implemented (2026-11-08)** — after the user's finalizing ruling, this round landed: `lyra/strategy_schema.py` (YAML safe-load + schema validation + AST + StrategySpec), `lyra/compiler.py` (deterministic past-only SQL codegen + CompiledPlan), the `validate`/`compile` commands in `lyra/cli.py`, and `tests/test_compiler.py` (28 tests green, incl. live DuckDB temporal assertions). Boundary decisions unchanged (deterministic inputs / cheap validate / past-only SQL / per-instrument in the runner). **Note**: the 332 legacy strategies' feature gap is `open-questions.md` O16 (blocks 0008, does not block this compiler) |
| Owner | `ttrrei` |
| Created | `2026-11-08` |
| Related proposal | `docs/proposals/vectorbt-and-multi-ai-strategy-search.en.md` |
| Related requirements | `docs/requirements.en.md` R2 / R3 / R12 |
| Related HLD | `docs/hld.en.md` §2.3 / §4 / §8 |
| Supersedes | None |

## 1. Problem

Lyra needs to translate constrained YAML rules into safe, deterministic, past-only signal SQL for DuckDB, while rejecting unknown features, illegal expressions, and unsupported timeframes early. Directly turning YAML into SQL would compromise R2, I9, I10, and auditability through arbitrary SQL, future data, or feature arithmetic.

## 2. Background

- 0003 now publishes 5m and 1h Catalog feature views (`features_5m` / `features_1h`) containing raw `mid_o/mid_h/mid_l/mid_c` and standard/alpha features. 0004 should consume them without reading or executing user-written SQL.
- HLD §2.3 assigns `validate` and YAML-to-DuckDB-SQL code generation to the strategy/compiler component; query execution, trade state machine, and reporting belong to later components.
- `requirements.md` R2 permits `eq/ne/gt/gte/lt/lte`, `all/any/not`, `held_for`, `within`, and `after_event`; the RHS is a constant or another registered feature. Feature arithmetic, cross-instrument comparison, and arbitrary SQL are forbidden.
- The documents/examples need a grammar reconciliation in 0004: README shows `exit.feature.when` / `time_bars` and no direction field; the tracked Lyra example uses `stop_loss_pct` / `take_profit_pct` / `max_holding_bars` / `direction`; read-only Nova YAML examples use `family` and `exit.long/short`. This decision proposes normalized compatibility aliases and requires mapping the available 332-YAML inventory before implementation; do not claim compatibility for untested files.
- `docs/proposals/vectorbt-and-multi-ai-strategy-search.en.md` recommends keeping AI tracks at the strategy/runner layer. The compiler remains independent of input path and does not depend on AI provider or VectorBT.

## 3. Plan

### 3.1 Scope

**Input and API**

- Add `lyra/compiler.py` and wire `lyra validate <strategy.yaml>` and `lyra compile <strategy.yaml>` into the existing CLI. `validate` performs safe YAML parsing, schema/feature/timeframe checks, and SQL code generation; `compile` prints normalized SQL and its parameters/summary for inspection. Neither executes trade SQL.
- `compile_strategy(strategy_path, catalog, feature_registry) -> CompiledPlan`. At minimum, `CompiledPlan` contains SQL, bound parameters, timeframe view, resolved feature list, strategy summary/hash, and execution metadata (stop/target/holding horizon/costs); only a later runner executes signal SQL in DuckDB.
- Each query is ordered by `time` and retains `instrument` and time columns; run/runner invokes it per instrument. The compiler does not create cross-instrument windows or comparisons. `timeframe_minutes` resolves only to an existing 5m/1h Catalog view; any other timeframe fails fast.
- Column identifiers are accepted only when known to the Catalog/Registry or a whitelisted OHLC alias, then quoted for DuckDB. Constants use query bind parameters; they are never interpolated into SQL text.

**Normalized YAML model (proposal)**

- `version: 1` means the **YAML schema version**, not v01/v02 in the direction's version tree. `id` must be a safe slug; `timeframe_minutes` must match an available feature view; `entry.long` and/or `entry.short` contain expression trees.
- `direction` is canonical. For old YAML, `family` may be accepted as an alias; if both appear and differ, reject. `parent(s)`, `driven_by_lesson`, and `inherited` are audit metadata, retained but excluded from SQL. The single-file compiler does not create or rewrite tracks/version trees.
- Comparison leaves retain `{feature: <left column>, op: <enum>, value: <constant or known column name>}`. Numeric/boolean scalars are constants; strings resolve only to a whitelisted raw column (`open/high/low/close` map to `mid_o/mid_h/mid_l/mid_c`) or Registry feature. Free string literals are unsupported; an unknown string is an unknown-column error.
- `all` / `any` take non-empty lists; `not` takes one child expression. Numeric columns permit all comparison operators; boolean columns permit only `eq/ne`; type mismatches report the YAML path.
- `held_for: {bars: N, condition: expr}`: TRUE only when the current row and previous N−1 observed rows are all TRUE; an incomplete window or NULL produces NULL; a full window containing FALSE produces FALSE.
- `within: {bars: N, condition: expr}`: TRUE only if at least one of the latest N observed rows (including current) is TRUE and all N can be evaluated; an incomplete/NULL window produces NULL; a full window with no TRUE produces FALSE.
- Proposed `after_event: {bars: N, event: expr, condition: expr}` inherits Nova DESIGN's meaning: `event` is TRUE exactly N observed rows ago, and `condition` is TRUE on each of the following N rows, including current, before the current close confirms. SQL uses past `lag(event, N)` plus an N-row window ending at current; NULL event/condition cannot become TRUE. 0004 fixtures must cover this meaning before implementation.
- `exit.long` / `exit.short` represent the directional feature exit. For README compatibility, `exit.feature.when` may normalize to the same exit expression for both directions; `time_bars` aliases `max_holding_bars`. The tracked example's canonical fields take priority. If `stop_loss_pct` is absent, the trade engine must apply the mandatory 2%; when explicitly present, only `0.02` is allowed, so strategy YAML cannot disable or widen the mandatory stop. `take_profit_pct` is optional; cost fields are range/type checked, while cost calculation remains in 0005.
- Strict schema: reject duplicate YAML keys, unknown keys, recursive aliases, NaN/Infinity, non-integer/non-positive `bars`, empty groups, unknown features, and mismatched timeframes. Errors must include file path and YAML field.

**SQL code generation**

- Emit fixed columns: `instrument`, `time`, `entry_long`, `entry_short`, `exit_long`, `exit_short`. A missing directional entry/exit expression always emits FALSE. The run engine treats only SQL TRUE as a signal; FALSE and NULL never open a trade.
- Comparators map only from enums to fixed SQL tokens; columns are resolved through Catalog/Registry before quoting. There is no SQL-fragment field and no callback, UDF, Python, or Jinja.
- Temporal windows use `PARTITION BY instrument ORDER BY time ROWS BETWEEN <N-1> PRECEDING AND CURRENT ROW`; `after_event` uses only `lag` and a past-only window. No `lead`, future-bounded windows, future joins, or future-data backfill.
- Preserve warm-up NULLs; `not(NULL)` remains NULL. Comparisons do not `COALESCE` to TRUE; complete-N-row gates prevent immature `held_for` / `within` windows from firing accidentally.
- Generate nested `all/any/not` recursively from an AST. Never splice user input into SQL. Constant ordering is stable so SQL/parameters are reproducible.

**Files involved (at implementation time)**

`lyra/compiler.py`, `lyra/cli.py`, `tests/test_compiler.py`, strategy schema/fixtures (split `lyra/strategy_schema.py` if needed), and the bilingual decision doc; no change to 0003 feature semantics and no VectorBT dependency.

### 3.2 Non-goals

- No execution of generated SQL, trade state machine, stops/slippage/financing, indicators, or monthly/yearly reports (0005/0006).
- No `lyra run`, version-tree orchestration, cross-AI tracks, pause/resume, or cross-track synthesis; these belong to R12/OCI/runner design.
- No user SQL/Python/eval/callback, feature arithmetic, cross-instrument/cross-timeframe joins, or feature-parameter search.
- No VectorBT implementation, runtime dependency, result oracle, or compiler backend.
- No automatic reads from arbitrary external paths; the CLI explicitly names the YAML and the configured alpha feature loader. Run-output path safety belongs to the runner/OCI feature.

### 3.3 Boundaries and closure items

- A YAML path may belong to any AI track; schema compilation does not infer the AI/provider from parent directories or inspect other tracks. Direction/track/parent metadata stays structured.
- The compiler reads only the Catalog view for the selected timeframe and the Registry manifest. Alpha features must register through the generic `lyra.features.load_from(directory)` extension point; no module name is hard-coded.
- The mandatory 2% stop, costs, and exit config are validated and carried in `CompiledPlan`; fill timing, OHLC ambiguity, and P&L calculation are decided by 0005.
- Before 0004 implementation, freeze aliases between README and tracked YAMLs; add normalization tests for every accepted alias and obtain/build a 332-YAML regression fixture. If that fixture is unavailable, 0004 may implement the verified grammar, but only 0008 may claim full 332-file compatibility.
- 0003 batch-1 review parked H1 (path traversal) and H4 (atomic Catalog visibility) across the 0004/0007 boundary per #66: strictly resolve instrument/column identifiers in compiler-facing inputs; atomic Catalog publication is not owned by this SQL compiler alone and must be decided jointly with 0007 push.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I8 | Feature parameters are fixed after registration; no sweeps | HLD §4 / R2 |
| I9 | RHS is a constant or registered feature; no feature arithmetic | HLD §4 / R2 |
| I10 | Emitted SQL is past-only | HLD §4 / R3.3 |
| I15 | Alpha/direction YAML never enters Git | HLD §4 / 0001 |
| I16 | Core never imports a specific alpha module | HLD §4 / 0001 |
| I17 | OCI immutable / append-only semantics do not change | HLD §4 / B9 |
| C1 | `held_for` / `within` can be TRUE only with N complete, non-NULL observed values | HLD §2.3 / R3.3 |
| C2 | Only SQL TRUE is a candidate signal; NULL cannot become an entry through `not` | Past-only / warm-up contract |
| C3 | A strategy reads one timeframe only; no cross-instrument windows/comparisons | R2 / HLD §2.3 |

## 5. Tests (**Implemented** — `tests/test_compiler.py`, 28 tests green, incl. live DuckDB temporal assertions)

The table below is the 0004 §5 plan; the **implemented** ones are in `tests/test_compiler.py`
(same name or equivalent assertions). The ones not listed separately (`timeframe_and_instrument_partition`,
`duckdb_fixture_truth_table`, `all_available_legacy_yaml`) are folded into existing tests (partition is
covered by the DuckDB assertions, truth-table is the three `*_executed_against_duckdb` tests, legacy-332
regression is in 0008 — see O16).

| Test | Scenario | Status |
|---|---|---|
| `test_compiler_compiles_registered_feature_vs_constant` | Scalar values and comparison operators map correctly; bound parameters and SQL tokens are safe | ✅ (all_six_ops + constant_binds_parameter) |
| `test_compiler_compiles_feature_vs_feature` | Resolve RHS Registry column; reject unknown columns and type mismatch | ✅ |
| `test_compiler_rejects_sql_injection_and_duplicate_yaml_keys` | SQL-like values, unknown keys, and duplicate keys cannot bypass the AST | ✅ |
| `test_compiler_nested_boolean_operators` | Nested all/any/not and SQL NULL three-valued logic | ✅ |
| `test_compiler_held_for_full_window_and_null` | N-row boundary, warm-up, NULL, and N−1/N/N+1 assertions | ✅ (+ `held_for_executed_against_duckdb`) |
| `test_compiler_within_requires_full_non_null_window` | One TRUE, all FALSE, incomplete/NULL paths | ✅ (+ `within_executed_against_duckdb`) |
| `test_compiler_after_event_exact_age_and_past_only` | Event exactly N rows earlier, N following conditions, off-by-one, NULL, future perturbation | ✅ (+ `after_event_executed_against_duckdb`) |
| `test_compiler_timeframe_and_instrument_partition` | 5m/1h view selection; no cross-instrument window leakage | ✅ (folded: view assertion + DuckDB `PARTITION BY instrument`) |
| `test_compiler_yaml_alias_normalization` | Normalize direction/family, close/mid_c, README exit aliases; reject conflicts | ✅ (3 alias tests + direction_family_conflict) |
| `test_compiler_duckdb_fixture_truth_table` | Execute generated SQL and match independent row-wise expectations; signals confirm at close | ✅ (three `*_executed_against_duckdb`) |
| `test_compiler_all_available_legacy_yaml` | Compile all available migration corpus; formal 332-file regression is in 0008 | ⏳ (332 is in 0008 — blocked by O16 gap) |

**Additional safety tests** (found in adversarial self-check):
- `test_compiler_state_event_only_eq_ne` — STATE/EVENT only allow eq/ne.
- `test_compiler_rejects_mandatory_stop_widen` + `test_compiler_rejects_exit_level_stop_widen` — 2% stop cannot be widened (execution and exit paths both).
- `test_compiler_rejects_nested_temporal` — temporal operators cannot be nested.
- `test_compiler_rejects_unknown_feature` / `test_compiler_rejects_bad_timeframe`.
- `test_compiler_deterministic_*` — same input, same output (SQL + params + plan_hash).
- `test_compiler_param_count_matches_question_marks_all_fixtures` — SQL `?` count == bound param count (guards the param-desync regression).

## 6. Rollback

- Code: revert the 0004 compiler commit (module, CLI wiring, schema, tests); do not roll back the feature builder or Catalog files.
- Data: compilation writes no OCI data and changes no Parquet/strategy/run files; nothing needs deletion.
- Compatibility: keep source YAML unchanged so the prior-generation tool can still read it. If public SQL output changes incompatibly, version the compile plan and retain old YAML.

## 7. Approval

- [ ] User review (proposed grammar aliases, exact `after_event` semantics, 2% stop schema behavior)
- [ ] AI review (second model)
- [x] Implementation tests all pass (`tests/test_compiler.py` 28 tests + 135 repo-wide; pyflakes clean)
- [ ] 332-strategy regression passes (0008) — **blocked by O16** (20 missing features await user decision)
- [ ] OCI end-to-end (not applicable to compiler-only feature; list separately if OCI reader integration is included)

## 8. Self-check and adversarial self-check

### Self-check

- [x] Compiler boundary matches HLD: YAML → SQL, no SQL/trade execution.
- [x] Comparison operators use only enums; feature-vs-feature resolves through Registry; no arithmetic.
- [x] Past-only uses lag / windows ending at current; warm-up NULL and SQL three-valued logic are explicit.
- [x] Multi-AI and VectorBT are not included in 0004 core scope.
- [x] Legacy 332 compatibility is not presented as a verified fact; 0008 is the full regression gate.

### Adversarial self-check (document-level)

| Attack | Finding | Disposition |
|---|---|---|
| YAML `value: "x) OR TRUE --"` | Direct interpolation could alter every instrument's signal | Accept only finite scalars or registered column names; bind constants and resolve identifiers through Registry |
| Duplicate YAML `feature:` / `op:` keys | Last-key-wins parsing can make runtime meaning differ from reviewed text | Parser must reject duplicate keys |
| `not` over warm-up NULL | `COALESCE(..., FALSE)` followed by NOT could make immature data TRUE | Preserve SQL NULL semantics; only TRUE triggers |
| Window off-by-one | `bars=N` compiled as N PRECEDING counts N+1 rows | Define current + N−1 preceding and assert N−1/N/N+1 boundaries |
| Future lookup in after_event | `lead` or future confirmation would introduce lookahead | Use `lag(event,N)` plus an N-row window ending at current; future perturbation must not alter past signals |
| Eight branches per AI track | If compiler reads AI metadata, it may accidentally expand the cap | Compiler owns no cap; cap is enforced in the version-tree layer (**2026-11-08 user ruling: 8 per track, tracks do not compete for slots**) |
| README and strategy YAML schemas differ | Supporting only one may break examples/legacy files; accepting every alias may hide semantic differences | List aliases and semantics explicitly; confirm 332 corpus and test accepted aliases before implementation |
| Treat `stop_loss_pct` as user-relaxable | Could bypass the mandatory 2% stop | Omission defaults to engine-mandated 2%; explicit value must be 0.02; state machine is 0005 |

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.3 | **Implemented (2026-11-08)**: landed `lyra/strategy_schema.py` + `lyra/compiler.py` + `lyra/cli.py` (`validate`/`compile`) + `tests/test_compiler.py` (28 tests green, incl. live DuckDB temporal assertions N−1/N/N+1, NULL gate, after_event exact-age, param/`?`-count invariant). Adversarial self-check fixed 3 issues: DuckDB 2.0 named-window-with-frame can't be referenced by >1 function → inlined the window spec; a temporal condition inlined into two SQL positions desynced params → emit per occurrence; `exit.stop_loss_pct` widen was not rejected → added the 2% enforcement on both the execution and exit paths. Legacy-332 regression is in 0008 (O16 gap blocks). |
| 2026-11-08 | 0.2 | **Finalized by user ruling (2026-11-08)**: current boundary decisions accepted (including consolidated §5: deterministic inputs, cheap validate, past-only SQL, per-instrument in the runner; git commit = provenance only; track does not enter the SQL AST). Status changed to "finalized, pending scheduling for implementation"; the cap row in the adversarial self-check synced to the 2026-11-08 per-track-8 semantics. No code implemented this round. |
| 2026-11-08 | 0.1 | Initial draft: compiler boundary, proposed grammar/SQL generation, test matrix, and document-level adversarial self-check; implementation awaits user review. |
