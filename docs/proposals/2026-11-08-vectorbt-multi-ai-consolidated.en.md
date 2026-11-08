# Consolidated VectorBT and Multi-AI Strategy Search Assessment (2026-11-08, Batch 1)

> **中文**: [2026-11-08-vectorbt-multi-ai-consolidated.md](./2026-11-08-vectorbt-multi-ai-consolidated.md)
>
> Status: **Ruled by the user (2026-11-08)**: (1) cap semantics = **B (8 active branches per track, tracks independent of each other)**; (2) tracks accepted, `track_id` mapped to an AI (research identity); (3) VectorBT **dropped entirely** (no runtime, no test-only control); (4) 0004 finalized per §5, no implementation this round; (5) lightweight multi-think (multiple AIs in parallel across the same or different directions; shared base; no scheduler/locks/concurrency coordination, R9 preserved). Rulings are recorded in **§9** and synced into R12 / O13 / oci-alpha-layout / 0004.
>
> Sources: [vectorbt-and-multi-ai-strategy-search.md](./vectorbt-and-multi-ai-strategy-search.md) and [2026-11-08-vectorbt-eval-and-multi-ai-v2.md](./2026-11-08-vectorbt-eval-and-multi-ai-v2.md). The user explicitly requested this synthesis, so both source documents are in scope. They remain unchanged for audit.
>
> This synthesis supersedes the previous document-handling choice to keep the two drafts separate. It does not mean the architecture recommendations are approved, and it does not amend R9, R12, the OCI contract, or the 0004 decision.

## 1. Conclusions

1. **Do not add VectorBT to Lyra's core dependencies or formal trade engine.** Its batch signal simulation API is useful, but Lyra requires a stop to become active after the entry fill, including within the entry bar. The isolated experiment observed VectorBT deferring that stop until the next bar. It also adds dependencies and a portfolio-oriented model. A future optional test control for simple PnL arithmetic remains a low-priority possibility; it cannot validate Lyra's R4 execution contract.
2. **Use logical, per-direction tracks for the proposed multi-AI design.** R12's branch tree is a foundation, but unique branch names alone do not prevent interference: the current single direction context and shared lessons expose each AI's process to the others. Each track should own its context, lessons, candidate YAMLs, and run identity. Direction hypotheses, market data, the feature catalog, and execution rules are shared through pinned read-only snapshots.
3. **Logical isolation does not mean Lyra supports concurrent multi-process execution.** R9 explicitly excludes multi-process and distributed infrastructure. This proposal adds no scheduler, lock service, or concurrency coordinator. It partitions research material by track so AIs can progress at user-controlled times. Lyra does not promise that multiple writers can modify or push the same workspace simultaneously. Supporting concurrent execution would require changing the R9 scope boundary first.
4. **All AIs use the same YAML, validate, compile, run, and per-instrument reporting rules.** Lower-capability models receive smaller tasks (for example, one candidate or one run diagnosis at a time); mechanical validation is not relaxed, and validate is not treated as proof of strategy quality.
5. **Cross-AI comparison happens only after the user pauses the direction and explicitly requests it.** A frozen, read-only synthesis context is produced; its report is stored separately and does not automatically rewrite track lessons, hypotheses, or candidates. The user explicitly controls resumption and promotion of any knowledge.
6. **Keep O13's active branch limit at eight per direction across all AI tracks.** Do not multiply it by the number of AIs. The user still needs to decide how to allocate the slots among tracks.
7. **Keep 0004 focused on deterministic YAML-to-past-only-SQL compilation and inexpensive validation.** Do not add track lifecycle, model identity, AI collaboration, or VectorBT to the compiler.

## 2. Merge and conflict decisions

| Topic | What can be merged | Conflict or trade-off | This proposal's conclusion |
|---|---|---|---|
| VectorBT's role | Both drafts advise against using it as Lyra's formal trade engine and leave room for a constrained future test control | One source emphasizes the observed entry-bar stop counterexample; v2 focuses more on its portfolio and parameter-scan orientation | Use the measured counterexample as the key compatibility evidence; portfolio reports, parameter scans, licensing, and dependencies are additional reasons |
| Installation size | Both drafts note meaningful runtime dependency cost | v2 recorded 68 installed distributions; this recheck of the same temporary venv reads 70. VectorBT 1.2.0's versioned pyproject declares 18 direct runtime dependencies; Lyra currently declares 8 direct dependencies | 18 is a direct-dependency count; 68/70 are installed-distribution counts from environment snapshots. The measures differ and the closure can change. Record the discrepancy; do not use 68 or 70 alone as the conclusion |
| Multi-AI isolation | Both drafts support one direction, user-controlled cadence, a common workflow, and user-triggered cross-AI learning | v2 considers R12's shared branch tree plus unique branch names sufficient; the other draft identifies cross-talk through shared context/lessons and proposes tracks | Reject “unique branches are sufficient.” Use logical tracks and make shared state read-only snapshots |
| Concurrency and R9 | Both drafts exclude distributed scheduling and unattended generation | v2 proposed atomic appends and file locks as a fallback for overlapping writes; R9 explicitly excludes multi-process operation | Do not implement file-lock or multi-process fallbacks. Lyra promises user-driven track isolation, not concurrent-writer support |
| Lower-capability AIs | Both support common commands and common mechanical quality gates | A single full-direction context can be too broad and can expose another AI's unreviewed work | Use the same track-scoped context, validator, and runner; vary task size by model capability; let a user-designated AI synthesize across tracks |
| 0004 | Both propose deterministic compilation, pre-run validation, and per-instrument results | v2 puts git_commit in the pure compiler function's inputs; a Git commit is provenance and should not determine SQL semantics. “Per-instrument reports” exceed the compiler's sole responsibility | Compile from normalized YAML, schema/compiler versions, and the feature catalog/snapshot. Record commit in run provenance. The compiler emits past-only signal SQL; runner/report preserves per-instrument output |
| Eight active branches | A direction-level limit exists and tracks must not bypass it | v2 did not specify the total across multiple tracks; the other draft proposed eight across the direction | Recommend a global total of eight across all tracks in a direction; leave allocation to the user |

## 3. VectorBT: evidence and recommendation

### 3.1 Isolated experiment

The experiment used Python 3.12.3, vectorbt==1.2.0, and the temporary virtual environment at /tmp/lyra-vectorbt-spike; no Lyra code or dependencies were changed.

- A synthetic OHLC scenario shifted a close signal to the next bar and entered at its open, with 1% slippage, FillPrice stop entry, StopMarket stop exit, a 2% stop, and a 6% take profit.
- Under this configuration, ordinary intrabar stops, gap stops, and a bar hitting both TP and SL could be mapped: SL won; gaps and slippage could make the realized loss exceed 2%.
- **Counterexample:** the entry bar opened at 101 and had a low of 98, already beyond the 2% stop. This run did not process the stop during the entry bar and exited at the next bar's open of 99. Lyra's stop activates immediately after the actual entry fill, so this delay violates R4.
- The experiment did not cover all fees/financing, missing data, all long/short conflicts, the 332 strategies, or full-scale performance. It does not prove complete equivalence between any engines.

### 3.2 Dependencies, capabilities, and maintenance

VectorBT 1.2.0's versioned project metadata lists 18 direct runtime dependencies. The v2 isolated install recorded 68 distributions; this recheck of /tmp/lyra-vectorbt-spike reads 70. The available evidence does not explain the change, so the synthesis treats them as environment snapshots at different points and does not treat one closure count as a stable metric. Lyra's current pyproject.toml declares 8 direct dependencies. R10's “≤15 core Python packages” does not specify whether to count direct dependencies or the full installed closure.

VectorBT's strengths are its mature, vectorized signal simulation API and batch research capabilities. Its portfolio, parameter-grid, and account-performance features overlap with areas Lyra explicitly excludes. Lyra still needs its own per-instrument state machine, cost/financing semantics, stop rules, and reports. Adding VectorBT at runtime would not remove those core rules. VectorBT 1.2.0's license contains Commons Clause restrictions; formal integration or distribution would need a separate review.

### 3.3 Recommendation

- Keep it out of Lyra core, the trade engine, and default optional dependencies. Implement and test Lyra's R4/R5 per-instrument execution and reporting semantics directly.
- If simple PnL arithmetic cross-checks become useful, propose a separate test-only, disabled-by-default [control] adapter. It must not be an execution oracle or introduce portfolio/equity metrics into Lyra reports.
- Before reassessing, define the R10 dependency-counting method and rerun entry-bar stop, cost, and reporting-boundary tests. Passing ordinary stop cases is not proof of compatibility.

## 4. Multi-AI: proposed logical-track design

### 4.1 Proposed layout

~~~
strategies/<direction>/
  hypothesis.md                         # direction hypothesis; each track pins a read-only version
  tracks/<track_id>/
    manifest.yml                        # track id, baseline hash, input snapshots, status
    lessons.md                          # append-only history for this track
    v01.yaml, v02a.yaml, ...            # candidates owned by this track
  reviews/<review_id>.md                # cross-track synthesis after a user pause
runs/<direction>/<track_id>/<run_id>/   # track-scoped run identity and artifacts
~~~

This is a proposal for R12 / the OCI layout, not an implemented path. All tracks, strategies, and runs remain alpha and must follow B9/I17's immutable / append-only rules in OCI, outside Git.

### 4.2 Execution and isolation rules

1. When a track is created, pin the content hash of the direction's hypothesis.md, the data snapshot, feature catalog/version, timeframe, and execution-rules version. Later edits to the direction hypothesis do not rewrite an existing track.
2. lyra context <direction> --track <id> produces one file containing only that snapshot, the track's lessons, its candidates and sibling run summaries, and the fixed feature list. Ordinary iteration context must not include drafts or lessons from other tracks.
3. Each run records direction + track_id + strategy SHA256 + data/feature snapshot + compiler/engine version. Identical YAML names may exist in different tracks; recreating an existing track, branch, or run ID must fail fast, without overwriting or automatic renaming.
4. Within a track, retain R12's parent / parents and driven_by_lesson. For a cross-track crossover, write the candidate into the destination track or a user-designated synthesis track and preserve both parent references and hashes; never modify the source track files.
5. Only after the user pauses the whole direction and explicitly requests synthesis, generate a frozen cross-track context for the AI designated by the user to compare branches, failure modes, complementary hypotheses, and run evidence. The report cites track/strategy/run/hash and is stored separately; it does not write back to tracks.
6. Only after the user explicitly asks to resume or promote findings may the system create candidates, update the direction-level hypothesis, or copy lesson summaries into a track. Comparison itself does not generate the next candidates automatically.
7. Track paths and unique IDs provide **logical content isolation**. Under R9, there is no lock service, background scheduler, or guarantee for simultaneous multi-process writes. Strategy changes and OCI pushes in one workspace remain user-controlled, single-writer operations.

### 4.3 How models with different capabilities can contribute

- A stronger model can propose multiple branches, analyze sibling comparisons, and synthesize across tracks after a pause.
- A lower-capability model can receive narrow tasks such as “make one constrained candidate,” “classify one run's failure,” or “check whether one candidate follows the hypothesis.”
- All models receive the same track-scoped context format and use the same validate → compile → run → per-instrument report path and strategy constraints. Model capability changes task scope, not the rules.
- Validate proves only that YAML / feature / temporal contracts are valid; it does not prove that a hypothesis is correct or a strategy is effective. Research conclusions still require run evidence and user/AI review.
- Do not provide automatic model routing, concurrent scheduling, unbounded batch generation, or model-specific permission channels. AIs and the user share the same workflow and mechanical gates.

### 4.4 Active-branch limit (**the single point in this plan that most needs a user ruling**)

Keep O13's limit of at most eight active branches per direction across every track in that direction. Do not grant eight per AI or per track. Preserve pruned history. The user must decide how to allocate the eight slots and whether to reallocate them manually.

> **Why this is called out on its own (v2 contributor's addition)**: the **counting scope** of the cap is not a detail — it is the switch that encodes "multi-AI" as **collaboration** or **competition**. O13's original intent (ruled by the user, 2026-11-06) is to **stop an AI from evading kill criteria via unbounded forking**; its target is **unbounded branching within a single research flow**. Once tracks are introduced, two mutually-exclusive semantics exist, and the user must choose one:
> - **A. Global 8 (collaboration)**: all tracks in a direction **share** the 8 slots. This matches O13's original intent (direction-level branch total stays bounded), but the cost is that **tracks compete for slots** — one track's branch occupancy squeezes the others, which **directly conflicts** with the user's goal that different AIs **"not interfere with each other."**
> - **B. Per-track 8 (competition)**: each track gets its own 8 slots, N tracks → 8N total. This is "each researcher's fork budget is independent," best fits "not interfering," but it **breaks O13's direction-level bound** (it stacks N researchers' fork budgets, so the direction-level branch total is no longer capped).
>
> The current wording leans toward **A (global 8)** — consistent with O13's original intent, but at the cost of "not interfering." **This is not an "allocation rules" question; it is a question about the _definition_ of the direction-level branch cap** — so it should be promoted to the **top-priority ruling** (see §8 item 2; the weight is emphasized here). Before the user rules, the branch-counting logic in tracks must not be locked in by the 0005/0006 implementation.

## 5. Consolidated requirements for the 0004 compiler

| Recommendation | What 0004 should own | Boundary |
|---|---|---|
| Determinism | The same normalized strategy YAML, schema/compiler versions, and feature catalog/snapshot must yield the same SQL, without time, randomness, or process-state dependencies | Git commit and AI/track identity go in the run manifest as provenance; they do not change SQL semantics |
| Early validation | Before a run, cheaply validate fields, features, parameters, comparison types, temporal operators, and value types; locate errors by field/line where possible | Valid YAML does not mean the hypothesis is correct; the compiler does not replace strategy review |
| Causality and type boundary | Generate past-only SQL; windows end on the current row; reject lead, arbitrary SQL, duplicate YAML keys, and feature arithmetic | Strategy files remain YAML only; the compiler does not accept callbacks or AI-generated SQL |
| Per-instrument semantics | SQL produces one strategy's signals; runner/report retains independent output for each instrument without portfolio aggregation | The SQL compiler does not own the trade engine, portfolio metrics, or track lifecycle |
| Multi-AI metadata | No need to put track or AI fields in the SQL AST | Track provenance belongs to the version-tree / run layer; identical strategy rules should compile to identical SQL |

These recommendations are review input for the existing docs/decisions/0004-yaml-compiler.md; they do not automatically revise that decision draft. Schema aliases and after_event semantics remain subject to the 0004 review.

## 6. Trade-offs, benefits, and risks

| Choice | Benefit | Main risk / control |
|---|---|---|
| No VectorBT runtime | Avoids stop-semantic mismatch, dependency weight, and a portfolio-first default model | A custom engine costs engineering and maintenance; test it independently against R4/R5 |
| One logical track per AI | Separates context, lessons, candidates, and run evidence so work can progress at different paces | OCI B9/I17 and push/run naming need extension; freeze the path and hash contract before implementation |
| Read-only synthesis after pause | The user controls when knowledge is compared and promoted; evidence is traceable | Pause state, frozen snapshots, and resume behavior need definition; later hypothesis edits must not overwrite old snapshots |
| Same gates, variable task size | Lower-capability models can do small tasks without weakening strategy constraints | Syntactic compliance can still be logically wrong; do not treat model output or metrics as automatic promotion signals |
| Global cap of eight | Search stays bounded as the number of AIs grows | Tracks may compete for slots; allocation requires a user decision and is not automated here |
| No concurrent processes | Respects R9 and avoids coordination infrastructure | Does not provide a strong guarantee for multiple simultaneous writers in one workspace; if that is required, change the scope boundary first |

## 7. Self-check and adversarial self-check

| Adversarial point | Failure mode | Assessment / disposition |
|---|---|---|
| Prove VectorBT equivalence with ordinary stop cases | Miss the entry-bar low that already crossed the stop | Use the measured counterexample to reject formal runtime reuse; other execution details remain untested |
| Treat 18, 68, and 70 as the same dependency count | Confuse direct requirements with installed closure, or present one environment count as a stable promise | Separate the figures: 18 direct requirements; 68 recorded by v2; 70 in the current venv recheck. Do not make exact closure size the main argument |
| Isolate only candidate files by track | Each AI's context still reads shared lessons / active branches and leaks process state | Partition context, lessons, candidates, and runs by track; share only a pinned read-only baseline |
| Collide on a track / branch / run ID | A later writer overwrites an earlier file, or a run is attributed to the wrong track | Reject duplicate IDs immediately; do not overwrite or add an automatic suffix |
| Claim tracks imply concurrent execution | Concurrent appends/pushes may still conflict, and R9 excludes multiprocessing | Make no concurrent-write promise; user serializes mutations in one workspace. If concurrency is required, change the scope constraint |
| Give each AI eight active branches | N models turn O13 into 8N | Share a total of eight across every track in a direction; allocation is left to the user |
| Auto-write synthesis into lessons / new branches | Cross-track contamination or search expansion without user direction | Keep the comparison report separate and read-only; require an explicit user action to promote or resume |
| A weaker model emits valid but meaningless YAML | A candidate may be treated as a valid research conclusion after validation | Validate checks contracts only; keep run evidence and human/AI review separate |
| Put track implementation into 0004 | The compiler becomes coupled to strategy-search state and AI metadata | Keep 0004 as pure YAML-to-past-only-SQL compilation; put tracks in R12 / OCI / run layers |
| Make Git commit a determinism input | Identical strategies produce different SQL solely due to commit hashes | Treat commit as provenance, not an SQL-generation input |

**Self-check conclusion:** This document separates observed experiment results, version metadata, and recommendations; marks tracks as a proposal; does not claim R9 permits supported multi-process concurrency; preserves the source documents; and changes no requirements, OCI rules, code, dependencies, or 0004 decision.

## 8. Questions for the user

1. Do you approve separate AI tracks within a direction, with logical isolation and user-serialized writes?
2. **[Top priority] Cap semantics — binary choice (see §4.4)**: is it **A. Global 8 (collaboration: matches O13's original intent, but tracks compete for slots and may starve a weaker AI, sacrificing "not interfering")**, or **B. Per-track 8 (competition: best fits "not interfering," but breaks O13's direction-level bound)**? This is the **definition** of the direction-level branch cap, not an allocation rule; the branch-counting logic in 0005/0006 must not be locked in until this is ruled.
3. Do you agree not to use VectorBT at runtime, with any PnL-only test control left off by default?
4. Should the 0004 compiler adopt the determinism inputs, validation scope, and per-instrument boundary in §5?
5. If multiple processes must write or run simultaneously, are you willing to revise R9 first? This proposal does not assume that capability is authorized.
6. **(v2 contributor's addition) Do you approve "tracks are a research identity, not an execution identity"?** i.e. `track_id` is used **only** for content isolation / attribution / synthesis, and **never** changes the mechanical behavior or gates of validate / compile / run / report. This prevents a hidden backdoor of "switching track = switching the standard."

## 7a. v2 contributor's review of this consolidated draft (2026-11-08, batch 1)

> Note: this is the v2 author's **review** of this consolidated draft, not a rewrite. Each item gives
> "endorse / needs-clarification / strengthen" for the user's and final ruling's reference.
> **Verified factual anchors**: O13 (cap=8, ruled by the user 2026-11-06, original intent "stop an AI
> from evading kill criteria via unbounded forking," targeting a single research flow); R12 has
> **direction + branches + single hypothesis + shared lessons + 8-per-direction cap** but **no "track"
> concept** yet; the vectorbt 1.2.0 dependency numbers (18 direct deps / 68 and 70 distributed
> packages) are correctly scope-separated in this draft.

**Overall**: this consolidated draft is better than both source drafts; I **endorse its overall
direction** and **voluntarily accept two of its corrections to my v2** (below). My main opinions
concentrate on §4.4 (cap semantics) and an implementation-cost / ordering problem the draft has not
yet surfaced.

| # | Topic | My opinion | Recommended disposition |
|---|---|---|---|
| P1 | **Cap semantics (§4.4 / §8.2)** | This is the **only** choice in the plan that genuinely changes the user's goal: A (global 8) fits O13's intent but makes tracks compete for slots, possibly **starving a weaker AI** and sacrificing "not interfering"; B (per-track 8) fits "not interfering" but breaks O13's direction-level bound. **Choose one, and rule it before 0005/0006 lock the branch-counting implementation.** | §8.2 already promoted to top priority and §4.4 expanded into the two A/B semantics (**added**). |
| P2 | **Tracks are a research identity, not an execution identity** | `track_id` should be used **only** for content isolation / attribution / synthesis, and **never** change the mechanical behavior or gates of validate / compile / run / report; otherwise "switching track = switching the standard" becomes a hidden backdoor, breaking R2's "fixed params / same rule set." The draft's §4.2 implies this but doesn't state it. | Added a new explicit ruling item in §8.6 (**added**). |
| P3 | **Tracks' implementation cost & ordering (the draft's weakest point)** | The draft treats tracks as settled, but tracks are a **new concept across R12 + OCI + CLI** (new file layout + new CLI commands + new run naming); **the implementation cost is non-trivial**, and it depends on the runner / run identity that 0005/0006 have not landed yet. **Before 0004→0005→0006 land, tracks are only a proposal and must not be locked in by any implementation.** Also give a **minimal-usable** landing path (below), to avoid building out the full §4.1 layout up front. | **Suggest a new minimal path** (this item is a supplementary opinion): ① first do only **§4.2-3's fail-fast unique ID + §4.2-1's snapshot freeze** (low cost, high value, and a precondition for 0005/0006); ② the tracks directory layout and `lyra context --track` come after the 0006 runner lands; ③ cross-track synthesis (§4.2-5/6) is user-triggered and comes last. **Do not** reserve any structure for tracks inside the 0004 compiler (the draft's §5 already correctly "keeps tracks out of the compiler" — **endored**). |
| P4 | **Corrections to my v2 (accepted)** | ① My v2 kept a "file lock as backstop"; the draft **correctly removes** it (more R9-consistent: don't promise concurrent writes, so don't implement a lock at all). ② My v2's C1 listed the git commit as a **compile input**; the draft **correctly changes** it to commit being **provenance** (not in SQL generation). I agree with the draft on both. | Already reflected in the draft's §2 conflict table / §5 determinism row; no further change. |
| P5 | **VectorBT conclusion** | I **fully endorse** the draft (not in core / runtime). The draft's entry-bar stop **measured counterexample** is **harder** than my "param-scan / portfolio metrics = R2/R9 forbidden" argument — it is an **empirical execution-semantics incompatibility**, not a "positioning mismatch" inference. I accept it as the primary evidence. | No change needed (the draft's §3.1 is already the primary evidence). |
| P6 | **Weak-AI parity (§4.3)** | Endorse "same gates + variable task granularity + validate does not prove the strategy works." One addition: state explicitly that a weak AI's failure does **not** auto-trigger cross-track write-back (consistent with §4.2-6; the draft already covers this — **endored**). | No change needed. |

> **Summary**: this consolidated draft can go to the user for ruling. My one **strong** suggestion is to
> treat **§8.2 (cap semantics A/B)** and **§8.6 (tracks = research identity)** as the **two pre-
> implementation rulings**, and to add **P3's minimal landing path** to §6 / the implementation plan
> (first fail-fast + snapshot freeze → then tracks directory / CLI → then cross-track synthesis), so
> tracks are not locked in or over-built by 0005/0006. I endorse the draft's conclusions on all other
> items.

## 9. User rulings (2026-11-08; supersedes the open state of §8)

| §8 item | Ruling | Where it lands |
|---|---|---|
| §8.1 tracks | **Accepted.** `track_id` maps to one AI (research identity: isolated context / lessons / candidates / run attribution); different AIs may work on the **same or different directions** in parallel without affecting each other; the base (data / features / catalog / compiler / CLI) is shared; lightweight — define candidate directions → evaluate → conclude → hypothesize the next step; **no scheduler / file locks / concurrency coordinator** (R9 preserved) | `requirements.md` R12, `oci-alpha-layout.md` §2.3 |
| §8.2 cap semantics | **B: 8 active branches per track**, slots do not compete across tracks ("mutual non-interference" takes precedence over O13's original direction-level global bound; O13's intent — preventing infinite forking of a single research flow — still holds because the cap is per-track) | `requirements.md` O13 reference, `oci-alpha-layout.md`, `open-questions.md` O13 amendment |
| §8.3 VectorBT | **Accepted, strengthened**: dropped entirely — no core / runtime use, **and no** PnL-only test-only control (no future re-evaluation planned) | This doc §3 conclusions stand; R8/R10 unchanged |
| §8.4 0004 | **§5 scope accepted**: deterministic inputs (normalized YAML + schema/compiler version + feature catalog/snapshot; git commit = provenance only), cheap pre-run validate, past-only SQL, per-instrument boundary in runner/report. **Docs finalized this round; no implementation.** | `0004-yaml-compiler.md` status → "finalized, pending scheduling" |
| §8.5 concurrency | **Lightweight multi-think**: parallel AI research is the goal, but only logical isolation + user-sequenced writes; no multi-process concurrent writing; if concurrent writers are ever needed, a separate R9 amendment must come first | R9 unchanged; tracks design stays logical (§4) |
| §8.6 tracks = research identity | **Accepted.** `track_id` is only for isolation / attribution / synthesis; it must not change any machine behavior or gate of validate / compile / run / report | R12 + 0004 invariants |

**Implementation order (P3 minimal path, refined)**:
1. Documentation (done this round): R12 tracks clause + O13 cap-semantics amendment + oci-alpha-layout layout + 0004 finalization + open-questions status.
2. 0004 implementation: YAML → past-only SQL compiler (`lyra validate` / `lyra compile`); does not touch tracks.
3. When 0005 trade engine + 0006 metrics/runner land, introduce the tracks layout (`tracks/<track_id>/`) and `lyra context --track`; fail-fast unique IDs + snapshot freezing are prerequisites.
4. Cross-track synthesis (`reviews/` read-only reports) comes last, user-triggered only.

> Note: the O13 semantics amendment (2026-11-08 user ruling) supersedes the 2026-11-06 "8 global per direction" decision; the old wording is kept in `open-questions.md` O13 as history — the amendment line is authoritative.

## References

- VectorBT 1.2.0 [version metadata](https://github.com/polakowo/vectorbt/blob/v1.2.0/pyproject.toml), [Portfolio API](https://vectorbt.dev/api/portfolio/base/), [stop enums](https://vectorbt.dev/api/portfolio/enums/), and [license](https://github.com/polakowo/vectorbt/blob/v1.2.0/LICENSE.md), accessed 2026-11-08.
- Lyra baseline: docs/requirements.en.md R2/R4/R5/R9/R10/R12; docs/hld.en.md §2.3/§4/§8; docs/proposals/oci-alpha-layout.en.md B9/B13/B14; docs/decisions/0004-yaml-compiler.en.md.

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.3 | **User rulings merged (§9)**: cap = 8 per track (option B, tracks independent); tracks accepted (`track_id`↔AI, research identity); VectorBT dropped entirely; 0004 finalized per §5 (no implementation this round); lightweight multi-think (no concurrency coordination, R9 preserved). Synced R12 / O13 / oci-alpha-layout / 0004 / open-questions / ACTION_LOG. |
| 2026-11-08 | 0.1 | Per the user's latest request, reviewed and consolidated the two existing assessments; preserved the source files; documented merge points, conflict decisions, the R9 concurrency boundary, VectorBT evidence, and 0004 interface recommendations; completed self-check and adversarial self-check. |
| 2026-11-08 | 0.2 | **Merged in the v2 contributor's review (P1–P6)**: ① §4.4 + §8.2 promoted the **cap semantics** to the **top-priority ruling**, expanding **A global 8 (collaboration / slot competition / may starve a weaker AI) vs B per-track 8 (non-interference / breaks O13's bound)** as two mutually-exclusive definitions; ② §8.6 added the **"tracks = research identity, not execution identity"** ruling item (prevents the "switch track = switch standard" backdoor); ③ §7a records the v2 author's review of the consolidated draft (P1–P6, including **accepting two corrections the draft made to my v2**: removing the file lock, and git commit = provenance not a compile input; plus **P3's minimal landing path** suggestion: first fail-fast + snapshot freeze → then tracks directory / CLI → then cross-track synthesis, so 0005/0006 don't lock in or over-build tracks). Bilingual pair. |
