# VectorBT and Multi-AI Strategy Search Evaluation (2026-11-08, Batch 1)

> **中文**: [vectorbt-and-multi-ai-strategy-search.md](./vectorbt-and-multi-ai-strategy-search.md)
>
> Status: independent evaluation / proposal; no code change is approved. This document does not read or rely on evaluation documents written by another AI for this topic.
>
> Scope: assess VectorBT as a Lyra dependency/backtest engine; propose practical boundaries for different AI models to search strategies independently within the same direction and at their own pace; explain the implications for 0004 compiler.

## 1. Summary

1. **Do not make VectorBT a Lyra core dependency or the formal trade engine.** It offers reusable signal simulation, stops, and trade records, but its portfolio model, runtime dependency set, license terms, and the rule that stops cannot be processed on the entry bar do not fit Lyra. A one-off experiment confirmed that next-open execution, fill-price stops, gaps, and same-bar stop/target priority can be mapped in selected cases; it also confirmed the critical entry-bar stop mismatch.
2. **Use isolated search tracks under each direction instead of mixing different AIs' branches in one mutually writable tree.** Each track owns its candidate YAMLs, lessons, and context; tracks share only a read-only snapshot of the direction hypothesis, feature catalog, market data, and execution rules. Cross-AI comparison occurs only after the user pauses the direction and explicitly requests it. The comparison is stored separately and read-only; it does not write back or merge automatically.
3. **Reduce task size for lower-capability AIs without weakening machine gates.** One task may generate one candidate variant or diagnose one failure. `validate` / `compile` / `run` apply the same syntax, causality, trade semantics, and metric constraints to every model. Invalid candidates cannot proceed to a run; valid candidates are judged using the same reports and human/AI review, without relaxing rules based on model capability.
4. **Keep 0004 focused on path-independent YAML-to-past-only-SQL compilation.** Do not add multi-AI orchestration or VectorBT to the compiler. The compile API should not assume strategies live under a model-specific directory; track identity and run provenance belong to the strategy/runner/OCI design.

## 2. VectorBT assessment

### 2.1 Reusable capabilities

VectorBT 1.2.0's `Portfolio.from_signals` supports long/short signals, OHLC stops, stops based on acquisition/fill price, stop-loss and take-profit, order and trade records, and broadcasting across multiple columns. These capabilities can save substantial execution-engine work for large array research. The official documentation says `Portfolio` builds cash/position and equity curves and provides portfolio performance statistics, so its primary abstraction is still a portfolio backtest rather than Lyra's per-instrument trade ledger.

### 2.2 Fit with Lyra

| Dimension | VectorBT capability | Lyra constraint | Assessment |
|---|---|---|---|
| Signal confirmation and fill | A close-confirmed signal can be manually shifted and use the next row's open as the order price | Confirm at close, execute at the next observed open | Mappable, but Lyra must guarantee the shift/price pairing |
| 2% adverse stop | Supports `sl_stop` based on fill price, OHLC triggering, and stop-market slippage | 2% from the actual entry fill; gaps may enlarge losses | Mappable for ordinary cases |
| Stop on entry bar | Official API says a stop cannot be processed on the same asset/bar as the entry signal | The stop must become active immediately after the actual entry fill; later prices on the entry bar cannot be skipped | **Semantic mismatch**; the spike delayed it until the next bar |
| Same-bar target and stop | `from_signals` gives stop signals priority; the synthetic case chose stop-loss when both triggered | Losing side has priority | Matched with selected settings, but still requires version-pinned regression tests |
| One position per instrument, no reversal | Signal/accumulation/conflict settings can configure this | No adding, reversal, or same-bar re-entry | Configurable, but the state machine still needs scenario-by-scenario verification |
| Costs | Fees/slippage parameters exist | Spread, per-side slippage, round-trip commission, trading-day financing | Not fully equivalent; Lyra still needs its own financing calendar and spread model |
| Reporting | Provides portfolio/equity and combined statistics as well as per-column records | No portfolio return / equity / CAGR; report per instrument | Easy to misuse; Lyra would need to bypass its aggregators and create its own reports |
| Dependencies and license | Version 1.2.0 declares 18 direct runtime requirements (NumPy, pandas, SciPy, Matplotlib, Plotly, Numba, scikit-learn, among others); source uses Apache 2.0 + Commons Clause fair-code terms | R10 core dependency budget ≤15; Lyra repository is Apache-2.0 | R10 does not say whether it counts direct dependencies or the full installation closure; runtime integration would materially expand the environment, and there is no approved exception like the test-only `control` group. License compatibility also needs resolution before commercial distribution/integration |
| 0004 compiler | Does not implement Lyra YAML grammar or compile YAML into DuckDB past-only SQL | A core 0004 responsibility | Cannot replace 0004 |

### 2.3 Isolated experiment

- Environment: Python 3.12.3; `vectorbt==1.2.0`; disposable virtual environment `/tmp/lyra-vectorbt-spike`; no Lyra source or dependency files changed.
- Built synthetic OHLC bars for one instrument. Manually shifted the close signal to the next row, used `open` for execution, `slippage=1%`, `stop_entry_price=FillPrice`, `stop_exit_price=StopMarket`, 2% stop, and 6% target.
- Result: entry at open 101 with buy slippage filled at 102.01; the 2% stop was 99.9698. An ordinary intrabar stop exited at the stop price with sell slippage, 98.970102, for a -2.98% trade return. A gap to next-bar open 99 filled at 98.01 after slippage, for a -3.92% return. When the same bar's high and low reached both the 6% target and 2% stop, the stop-loss won.
- **Counterexample**: the entry bar opened at 101 and its low of 98 breached the 2% stop, but VectorBT did not process a stop on that bar; it filled only at the next bar's open of 99, at 98.01. This violates Lyra's contract to monitor adverse price immediately after the actual entry fill and cannot be eliminated with a simple setting.
- These results cover only the tested version and synthetic paths. Financing, the complete cost model, missing data, complex long/short conflicts, the 332-strategy set, and full-scale performance were not tested. This is not acceptance of Lyra's trade engine.

### 2.4 Recommendation

- Keep Lyra's own per-bar trade state machine. Do not add VectorBT as a core/optional runtime dependency or as the authoritative result generator. If reconsidered, first clarify whether R10 counts direct requirements or the full installation closure and approve the dependency group explicitly.
- If a future, separate research need requires heavy vectorization, propose an optional benchmark/exploration adapter. First resolve entry-bar stop semantics, per-instrument reporting isolation, the dependency budget, and license review.
- A cross-check does not mean “let two engines vote”: results from an engine with different execution semantics cannot be an oracle for Lyra correctness.

## 3. Multi-AI search goal and current gap

R12 already provides multiple branches per direction, AI as a first-class writer, a single-file context, sibling summaries, continue/prune/cross, and an active-branch cap of 8 per direction. It does not define:

- File isolation, independent progress, and independent lessons for multiple AIs/models;
- How tracks freeze common hypotheses and inputs so experiments remain comparable;
- A read-only cross-track comparison, learning, and synthesis flow after the user pauses;
- Narrow tasks and common mechanical gates that let lower-capability models participate;
- How the existing cap of 8 active branches applies across multiple AI tracks.

## 4. Proposed isolation model

### 4.1 File and identity boundaries (proposal)

```text
strategies/<direction>/
  hypothesis.md                       # shared direction hypothesis; read-only to tracks
  tracks/<track_id>/
    manifest.yml                      # owner AI / model version / base snapshot / status
    lessons.md                        # owned by this track only
    v01.yaml, v02a.yaml, ...           # immutable candidates owned by this track
  reviews/<review_id>.md              # cross-track synthesis after pause; separate artifact
```

`track_id` is the isolated AI workflow identifier; the manifest/run provenance records the provider, model version, prompt/context version, and operator. When the model identity changes, a new track is recommended so distinct research histories are not mixed. All these paths remain alpha, outside Git in OCI/external workspaces.

### 4.2 Operating rules

1. The direction root provides a read-only snapshot of the shared `hypothesis.md`. Each track manifest records the starting hypothesis hash, data/feature snapshot, timeframe, and execution-rule version. Later edits to the shared hypothesis do not rewrite frozen track inputs.
2. `lyra context <direction> --track <id>` emits exactly one file: the shared hypothesis snapshot, that track's lessons, active YAMLs, sibling-run summaries, and the fixed feature list. It does not read another AI's candidates or lessons.
3. A run's unique identity/report includes `direction + track_id + strategy SHA256 + data/feature snapshot + engine version`. This prevents different AIs using the same YAML id from overwriting each other and makes comparability auditable.
4. Within-track `parent` / `driven_by_lesson` stays consistent with R12; same version names can coexist in separate track paths. Cross-track crossover cannot rewrite source tracks. To cross, first copy/reference the source artifacts into a new track or synthesis branch and retain both parent hashes.
5. When the user pauses a direction, writing is disabled for new branches, lessons, and runs; the CLI creates a frozen compare context. The user selects an AI to read all track snapshots and write a synthesis report with supporting/opposing evidence, shared failure patterns, complementary hypotheses, and possible next steps. **Synthesis itself changes no track and creates no candidate automatically.** A branch can be created or lesson copied only after the user explicitly resumes/approves.

### 4.3 Let AIs with different capabilities contribute

- Split work into tasks such as “make one constrained variant from one parent”, “classify one run's failure”, or “check whether one candidate follows the direction hypothesis”. A weaker model need not perform sibling comparison or cross-track synthesis.
- Input remains a single context file; output remains a YAML candidate plus a short rationale. Candidates containing SQL, Python, or feature arithmetic are rejected by the validator.
- Every model uses the same `validate → compile → run → per-instrument report` path. Passing validation proves syntax/contract compliance, not that a hypothesis is correct or profitable.
- No automatic model routing, distributed scheduler, or unbounded generation. The user controls when to call each model, which track to use, and how many candidates to create per round; R12 kill criteria and O13 cap remain in force.

### 4.4 Active-branch cap

O13 is already set by the user to at most 8 active branches per direction at a time. The recommendation is to keep it as a **global total of 8 across every track in that direction**, rather than 8 per AI; otherwise adding models bypasses the original anti-forking gate. Pruned history remains; do not auto-delete it before a separate OCI retention/archive policy exists. How to allocate the eight slots across tracks and whether the user can temporarily reallocate them remain operational rules for the user to decide.

## 5. Follow-up changes required (recorded only; not implemented)

| Location | Contract/function to add | Timing |
|---|---|---|
| `requirements.md` R12 | Define tracks, AI identity, read-only shared snapshots, cross-track isolation, and user-paused synthesis | After user approves the design, before implementing the search interface |
| `oci-alpha-layout.md` B9/I17 + §2.3 | Define track, track-lessons, manifest, and comparison-review paths plus immutable/append-only rules | Before final OCI layout/0007 |
| `hld.md` §2.3 | Define context/compare/pause CLI contract; keep compiler track-agnostic | After requirement and command boundaries are settled |
| Strategy/runner/report | Track metadata, unique run identity, snapshot references, pause gate, and global cap of eight | Split into strategy-version-tree/runner/OCI features; not 0004 SQL codegen |
| Tests | Cross-track read isolation, duplicate YAML IDs do not collide, no writes while paused, resume does not rewrite history, global cap, cross-AI comparison over the same snapshots | With the corresponding implementation feature |

## 6. Benefits and risks

| Topic | Benefit | Risk / control |
|---|---|---|
| Independent tracks | Models can work at different speeds without overwriting one another's files, lessons, or runs | A writable shared hypothesis would contaminate every track; keep it read-only and audit updates with hashes |
| Small tasks for weaker models | Simple candidate construction, labeling, or summarization can be delegated | Syntax can pass while the hypothesis is wrong; reports are evidence, not a model verdict |
| Synthesis after pause | Frozen inputs prevent compare-while-editing and immediate information leakage | A stronger AI may still be biased; cite each claim to branch/run/hash so a person can verify it |
| Global cap of 8 | Preserves bounded search as model count grows | Tracks may compete for slots; the user controls allocation, and the cap must not silently expand |
| OCI track paths | Separates filenames and keeps alpha outside Git | New paths need synchronized B9/I17, push validation, and backup rules |
| VectorBT reuse | Fast reuse of batch simulation and record APIs | Entry-bar stop mismatch, portfolio-stat misuse, dependency/license burden; do not adopt as formal engine |

## 7. Self-check

- [x] VectorBT is not misrepresented as Lyra's compiler or indicator library.
- [x] Synthetic experiment results are distinguished from documented behavior, with untested scope stated.
- [x] Multi-AI design retains YAML-only, fixed feature parameters, past-only SQL, one trade per instrument, and per-instrument scoring.
- [x] The cap of 8 is global across a direction's tracks; it cannot be multiplied by AI count.
- [x] Shared market/feature data is read-only; direction and track artifacts remain within the OCI alpha boundary.
- [x] Requirements, OCI protocol, source code, and dependencies were not changed; this remains a proposal.

## 8. Adversarial self-check

| Attack/failure path | Consequence without control | Design disposition / open item |
|---|---|---|
| Every track gets a cap of 8 | N AIs turn the old cap into 8N | Global direction-wide cap = 8; allocation policy awaits user decision |
| AIs edit root `hypothesis.md` or shared lessons | Track isolation disappears and history is contaminated | Root hypothesis is read-only; lessons are per-track; root updates have hashes and affect only new snapshots |
| Two AIs write the same strategy id/run name | Results overwrite or get attributed to the wrong AI | Run identity includes track id, strategy hash, and snapshot; writes must be unique |
| Pause freezes only some files while runs remain mutable | Compare snapshots drift and cannot be reproduced | Direction-level write gate; compare context is built from frozen snapshots |
| “Learning synthesis” auto-writes lessons/branches | Unrequested cross-track contamination | Store a separate read-only compare report; promotion/crossover requires explicit user direction |
| A weak model emits valid YAML with bad trade logic | A wrong hypothesis advances anyway | Validation does not assert logical validity; measure with the shared run semantics, and prune/kill based on evidence and review |
| A track retains many pruned versions | OCI storage grows over time | Keep immutable history; define archive policy separately and do not silently garbage-collect |
| Default VectorBT `Portfolio` scores are used for Lyra | Portfolio return/equity violates R9 | Do not integrate as formal engine; any future spike may inspect per-instrument records only and must not publish a portfolio score |
| Only ordinary stops are tested in VectorBT | False conclusion that I3 is satisfied | Added an entry-bar counterexample; confirmed mismatch and rejected core reuse |
| One direct dependency is treated as “just one package” | VectorBT's 18 runtime requirements could bypass the R10 budget | Define whether R10 counts direct requirements or the complete installation closure; until then, do not make it a Lyra runtime dependency |

## 9. References

- [VectorBT 1.2.0 PyPI release and dependencies](https://pypi.org/project/vectorbt/1.2.0/) (accessed 2026-11-08)
- [Portfolio API: `from_signals`, signal-shifting hint, and Portfolio outputs](https://vectorbt.dev/api/portfolio/base/) (accessed 2026-11-08)
- [Portfolio enums: StopEntryPrice / StopExitPrice and same-bar entry/stop restriction](https://vectorbt.dev/api/portfolio/enums/) (accessed 2026-11-08)
- [VectorBT 1.2.0 `pyproject.toml`](https://github.com/polakowo/vectorbt/blob/v1.2.0/pyproject.toml) (18 direct runtime requirements; accessed 2026-11-08)
- [VectorBT 1.2.0 license](https://github.com/polakowo/vectorbt/blob/v1.2.0/LICENSE.md) (Apache 2.0 + Commons Clause; accessed 2026-11-08)
- Lyra internal baseline: `docs/requirements.md` R2/R4/R5/R9/R10/R12; `docs/hld.md` §2.3/§4/§8; `docs/proposals/oci-alpha-layout.md` §2.3, B9/B13/B14.

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.1 | Initial draft: VectorBT assessment + isolated multi-AI track proposal + compatibility spike and adversarial self-check. |
