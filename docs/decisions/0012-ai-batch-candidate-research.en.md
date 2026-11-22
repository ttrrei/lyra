# Decision 0012 — AI Batch Candidate Research Contract

> **中文**: [0012-ai-batch-candidate-research.md](./0012-ai-batch-candidate-research.md)
>
> Scope: Establish a multi-candidate pooled research contract to prevent AI single-thread iterations from falling into local optima via parameter micro-tuning.

## Meta

| Field | Value |
|---|---|
| ID | `0012` |
| Title | AI Batch Candidate Research Contract |
| Status | proposal |
| Owner | `ttrrei` |
| Created | `2026-11-22` |
| Related proposal | None |
| Related requirements | `docs/requirements.md` §R12 |
| Related HLD | `docs/hld.md` §8 |
| Supersedes | Narrows and standardizes existing single-branch iteration guidelines in `lyra/ai_readme.md` |

## 1. Problem

Under the single-line iteration workflow, AI models tend to repeatedly tweak numeric parameters around a single performance metric on a single branch (e.g. perpetually tweaking RSI thresholds from 35/65 to 40/60), quickly getting trapped in overfitting and local optima. A batch candidate research contract is needed to transform the 8-seat track capacity into a candidate pool mechanism ("retained elite/watch + diverse structural candidates"), mandating explainable structural differences so that research progresses on diverse empirical evidence and prune memory rather than single-metric hill climbing.

## 2. Background

- **Existing Foundation**: Lyra already possesses basic pool governance capabilities (`MAX_ACTIVE_BRANCHES_PER_TRACK = 8`, `lyra digest`, `lyra compare --siblings`, `lyra prune`, `lyra apply-batch` preflights). However, previous AI interaction guidelines (`lyra/ai_readme.md`) modeled single-branch micro-adjustments ("One branch per iteration", RSI 40/60 tuning examples), providing adverse behavioral guidance to LLMs.
- **User Ruling (2026-11-22)**:
  1. Methodological narrowing of requirement R12 (strategy evolution): **strictly prohibit pure parameter/threshold/window micro-tuning**; this must be codified in contract 0012 rather than implemented as a silent rejection black-box gate;
  2. Standardize batch submissions to 3–4 candidates per bundle, comparing candidates only within the same direction/track;
  3. Parameter variants are audited/tagged during analysis, not silently hard-rejected.
- **Related Initiatives**: Decision 0010 (temp/ triage) supplies the initial stock of candidates for the pool; subsequent decisions 0013 (comparability enhancement), 0014 (cross-instrument digest), and 0015 (anti-tuning guardrails) form the technical implementation roadmap for this contract.

## 3. Plan

### 3.1 What we do

1. **Batch Submission Specification (3–4 candidates)**:
   - Each AI iteration must submit 3–4 candidate branches packaged in a single `apply-batch` bundle.
   - Recommended composition (as a heuristic guide, not a rigid algorithm): **2 new hypotheses + 1 logical combination + 1 mechanism replacement**.
   - Every candidate must declare: research hypothesis, **structural differences** relative to active pool candidates (novel indicator introduction, entry/exit regime shift, state filter changes), parent lineage (`parent`) with driving lesson (`driven_by_lesson`), and anticipated failure regimes.
2. **Prohibition of Pure Parameter Micro-tuning**:
   - Strictly ban tweaking numeric thresholds alone (e.g. RSI 30→35), altering lookback windows alone (e.g. SMA 20→25), or masquerading parameter variants as structural novelty.
   - Structural differences must be clearly auditable and justifiable in plain language.
3. **Cost and Baseline Consistency**:
   - All 4 execution cost fields (`commission_round_trip`, `financing_per_day`, `stop_loss`, `slippage`) must match the track baseline exactly, preventing artificial metric inflation via fee/slippage deflation.
4. **Intra-Track Comparison and Reading Protocol**:
   - A batch is only compared against candidates within the same `direction` and `track`.
   - AI reading protocol prioritizes `lyra digest` (low-token compact history).
   - Full YAMLs, failure retrospectives, and relevant lessons are inspected on-demand for at most 3–4 relevant candidates, preventing context bloat.
5. **Candidate State Deduction**:
   - Candidate states (Experimental / Promising / Proven / Rejected / Incomplete) are dynamically derived from existing Branch, Run, and Prune artifacts; no external persistent state database is introduced.
6. **Workspace Batch Archiving**:
   - Original proposal bundles and evaluation reports are archived in local workspace at `research-batches/<direction>/<track>/batch-NNNN/`.
   - Batch archives never enter git.
7. **Holdout Boundary Reservation**:
   - Reserve the concept of Sealed Holdout boundaries for out-of-sample validation; models only access the Research window and authorized summary feedback in this stage.

### 3.2 What we do NOT do

- Do not implement Genetic Algorithms (GA), Candidate DB, PoolManager, or autonomous background loops.
- Do not introduce silent hard-rejections of parameter variants at the engine level.
- Do not impose arbitrary hard cutoffs (e.g. 30 trades / 60% win rate / 35% Jaccard similarity hard gates).
- Do not implement physical Sealed Holdout isolation in this phase.

### 3.3 Boundaries

- **Alpha Boundary**: Real strategy YAMLs, performance figures, and batch run artifacts remain strictly in workspace `research-batches/` and OCI; git tracks only contracts, engines, and examples.
- **R5 Freeze**: Zero modifications to `lyra/metrics.py` indicator definitions or existing field semantics; no introduction of portfolio-level metrics (Sharpe, CAGR, PF).
- **Implementation Boundary**: 0012 defines behavioral contracts; comparability fixes belong to 0013, cross-instrument digests to 0014, and guardrail detection tooling to 0015.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I18 | Track isolation & identity binding: batches and candidates are strictly bound to one direction and track | HLD §4 |
| I21 | Active branch limit gate: at most 8 active branches per track (prune before apply) | HLD §4 |
| R4 | Mandatory 2% adverse-price stop: all candidates strictly inherit execution meta specs | HLD §4 |
| R5 | Frozen metric definitions: evaluations rely solely on R5 standardized per-instrument metrics | HLD §4 |
| R12 | Bounded strategy evolution: research proceeds strictly within established directions without unconstrained generation or micro-tuning | HLD §4 |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_batch_bundle_structural_tagging` | Verify apply-batch bundles support structural difference tagging and hypothesis declarations |
| `test_batch_execution_meta_consistency` | Verify cost fields across batch candidates match track baseline |
| `test_batch_candidate_cap_enforcement` | Verify batch preflight enforces 8-seat active capacity before adoption |
| `test_batch_workspace_archive_layout` | Verify batch artifacts and summary markdown archive properly in workspace |

## 6. Rollback

- **Code**: Decision contract docs can be cleanly reverted via git commit.
- **Data**: Remove corresponding `research-batches/<direction>/<track>/` files from workspace.
- **Compatibility**: Does not alter underlying engine schema; fully backward-compatible with existing CLI commands.

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Tests all green
- [ ] Pilot validated

## 8. Revision History

| Date | Version | Change |
|---|---|---|
| 2026-11-22 | 1.0 | Initial draft: establish 3–4 candidate batch structure, anti-micro-tuning contract, and 8-seat pool rotation rules. |
