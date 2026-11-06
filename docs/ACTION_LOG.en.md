# Action Log (Central)

> **中文**: [ACTION_LOG.md](./ACTION_LOG.md)
>
> This file is Lyra's **central action log**: what was done, when, why,
> and where it landed (which doc / rule / section). Per-document
> "revision history" tables are the fine-grained audit trail; **this
> file is the timeline ledger**.
>
> **Maintenance rules**:
> 1. Any doc change, rule add/modify, user decision, or review outcome
>    **must be appended here in the same change** (same commit as the
>    change).
> 2. Append-only. Overturned entries are **not deleted**; add a new row
>    noting "overturns #N".
> 3. Every entry needs: date, category (decision / doc / review / fix),
>    content, landing spot (doc + section / rule number).
> 4. Readable by AI and humans alike; AI should scan the last 10 rows
>    before acting, to avoid re-deciding or overturning settled items.
> 5. **The `## Current state` block is the only section of this file that
>    may be updated in place over time** — and updating it is
>    **mandatory**: every change (doc / code / config / strategy / review)
>    must refresh it (done / next / awaiting-user / Updated stamp) in the
>    same change; see AGENTS.md Non-negotiables item 1. A change that
>    appends a log row but does NOT refresh the state block is incomplete —
>    do not finish the turn, do not commit. Log entries stay append-only.
>    **A new session reads that block as the answer to "where is the
>    project now"** (AGENTS.md only points here; it never states progress).

## Current state

| Item | Value |
|---|---|
| Updated | 2026-11-06 (#39) |
| Build order | `docs/hld.md` §8 (0001→0009, single source of truth) |
| Done | **0001** (repo + OCI split, settled in docs); first commit `c8f3851` (doc skeleton + LICENSE + pyproject + examples) |
| Next | **0002**: OCI pull + clean + aggregate — write `docs/decisions/0002-ohlcv-data-sync.md` (ZH+EN) first, then the code |
| Code status | No source code yet; the `lyra/` package is created with 0002 |
| Delivery order | 0002 pull → 0003 feature builder → 0004 compiler → 0005 trade engine → 0006 metrics/runner (on fixtures) → 0007 push/backup |
| Open questions | **None** (open-questions O1–O5, O11–O15 all closed) |
| Awaiting user | 0002's OCI access method (PAR URL vs signed requests — settles O5) + OCI connection parameters |

## Legend

- **decision**: user-confirmed decision
- **doc**: document added / rewritten
- **review**: review by the user or a second AI, and its conclusion
- **fix**: fix made in response to a review

## 2026-11-05

| # | Category | What | Where |
|---|---|---|---|
| 1 | doc | After scanning all moneta / nova docs, created the lyra doc skeleton (README, AGENTS, requirements, background, hld, proposals/oci-alpha-layout, decisions/TEMPLATE + 0001, open-questions, config_example) | whole repo |
| 2 | decision | User decided: lyra is a new repo (not a modification of nova); all modules will be rebuilt (to varying degrees); **a decision doc is written before each step**, proceeding feature-by-feature; the alpha layout may be proposed but must be documented for multi-party review; README in English, the rest in Chinese | `hld.md` §8, `AGENTS.md` |
| 3 | decision | User corrected: except README, every doc ships as a **bilingual pair** (`.md` Chinese keeping English terms + `.en.md` English) | 7 doc pairs + `AGENTS.md` References |
| 4 | decision | `strategies/` primary unit set to **direction + version chain (vNN) + hypothesis.md + lessons.md**; iteration (earlier runs drive later design) is the core workflow; the 12 nova directions inherited | `oci-alpha-layout.md` §2.3, `requirements.md` R12, new B11/B12 |
| 5 | decision | The direction set is **extendable**: the initial 12 are a seed, not a closed list; new directions go under `_new/` with full peer status | `oci-alpha-layout.md` §2.3, `requirements.md` R12 |
| 6 | decision | User confirmed **option A**: the new-direction admissions bar is a **soft standard** (recommendation: testable / non-duplicative); no direction-equivalence checker | `oci-alpha-layout.md` §2.3 (v0.4), `requirements.md` R12 |
| 7 | review | Second AI found: leftover old `active/` `archived/` model in the top-level tree, B1, B6, I15 (5+ places, both languages), conflicting with the direction model | — |
| 8 | fix | All leftovers cleared: tree now shows direction folders; B1 now judged by **content signatures** (hypothesis/lessons/vNN); B6 now "direction folders (incl. killed) are not deletable"; I15 aligned | `oci-alpha-layout.md` §1/§3 (v0.5), `0001` I15 |
| 9 | review | User found: `config_example.yml` `local.*` all point at the repo root → OCI mirrors (incl. alpha) would land inside the git working tree, accidental-commit risk | — |
| 10 | fix | Added **B13** (OCI mirrors default to outside the repo at `~/.lyra/<workspace>/…`; landing in the working tree requires explicit `--inside-repo`) + **B14** (`strategies/examples/` is the only git-tracked strategies subtree, never read/written as alpha at runtime); config switched to workspace mode; 0001 I11 aligned | `config_example.yml`, `oci-alpha-layout.md` §3 (v0.6), `requirements.md` R6, `0001` §3.3/§4/§5, `hld.md` §1.4/I11, `AGENTS.md` |
| 11 | review | Second AI found: README / background / hld gave three conflicting build-order stories (4 core components first vs three things vs 0001→0009) | — |
| 12 | fix | Unified: **`hld.md` §8 is the single source of truth** (0002 OCI pull before 0003-0006 core components; rationale: data sync is the primary function R7; core components proceed on fixtures, unblocked); README / background now reference it | `hld.md` §8 (v0.2), `README.md` Current status, `background.md` §3 |
| 13 | review | Second AI found: after B11/B12/B13/B14 were introduced, 7 old references still said "B1-B10" (layout §5, 0001 ×3, AGENTS) | — |
| 14 | fix | All B-rule references unified to **B1-B14** | `oci-alpha-layout.md` (v0.7), `0001` (v0.4), `AGENTS.md` |
| 15 | doc | Created this central action log | `ACTION_LOG.md` + `.en.md` |
| 16 | decision | User confirmed **AI is a first-class writer** (strategy iteration) and requires **efficient context** for AI writes: no bulk reading of repo files | — |
| 17 | doc | Landed the "AI efficiency requirement": `lyra context <direction>` single-file context bundle (hypothesis + last N lessons + latest vNN + last-run summary + feature list); AI write loop = read 1 / write 1 / run 1 / log 1; hypothesis/lessons/vNN formats stay LLM-friendly | `oci-alpha-layout.md` §2.3 (v0.8), `requirements.md` R12 (v0.5), `AGENTS.md` |
| 18 | review | Self-check for conflicts between the "AI first-class writer" change and other docs: found **R9 "no automatic strategy generation / AI candidate generation" literally conflicts with R12**; two other "user manual" mentions (alpha features / rebuild-index) checked and found non-conflicting | — |
| 19 | fix | R9 + background "do-not-do" list now exclude **autonomous / unbounded AI generation** and explicitly note that **AI bounded iteration (vNN inside a direction + per-version human review) is in scope (R12)** | `requirements.md` R9 (v0.6), `background.md` §3 |
| 20 | decision | User confirmed a **version tree** model: single-threaded deep search falls into local optima, so every version (success or failure) should support **multiple** evolution branches; the AI must compare branches and judge holistically (continue / prune / cross, GA-style mutation/crossover) | — |
| 21 | doc | Version tree landed: naming `v<generation><branch-suffix>` (v02a/v02b/v04ab); new commands `new-version --branch` / `compare --siblings` / `merge --from <a> --from <b>`; branch lifecycle active→pruned (retained, never deleted); kill criteria = ALL active branches failing N consecutive rounds; context bundle gains a sibling-branch run-summary comparison table; B12 reworded to `parent`/`parents` | `oci-alpha-layout.md` v0.9, `requirements.md` R12 v0.7, `AGENTS.md` |
| 22 | decision (supersedes its own first draft) | **Crossover/mutation is fully delegated to the strategy-finding AI**: what to take, how to combine (whole-part / per-parameter / modified params) is entirely up to the AI; the framework does **not** restrict granularity. The framework's job is to make sure this AI **has the capability** (`lyra context` includes the active branches' full YAML + parameters, so the AI can read and combine freely); audit relies on the AI declaring sources in `inherited`/`driven_by_lesson`. This supersedes the "restrained crossover (whole-part only)" first draft. | `oci-alpha-layout.md` §2.3, `requirements.md` R12 |
| 23 | review | Full cross-doc audit found **hld conflicting with R12 / version tree**: §2.3 said "No strategy generation (future campaign, not core)" — directly contradicting "AI is a first-class writer + version-tree iteration is the core workflow"; §7 decision-tree ZH was missing 0008, EN was missing 0009 | `hld.md` §2.3 / §7 |
| 24 | fix | hld §2.3 conflict row removed, a "Strategy evolution" block added (context / new-version / compare / merge / push-direction, aligned with R12 + AI-free crossover); §7 decision-tree in both languages now includes 0008/0009 and the 0007 └── glyph is fixed | `hld.md` v0.3, `hld.en.md` v0.3 |
| 25 | doc | Created `.gitignore`: configured per B1/B2/B13/B14 boundaries; `strategies/*` + `!strategies/examples/` achieves "ignore alpha direction folders, keep the examples subtree"; ignores data/runs/features/tmp + credentials + Python build; 19 boundary rules verified bidirectionally via `git check-ignore` | `.gitignore` (new) |
| 26 | review | Self-simulated adversarial review found **3 real conflicts/drifts**: ① AGENTS "no auto-strategy-generation" literally conflicts with R12 (AI first-class writer); ② AGENTS References said "R0-R11" but R12 exists; ③ hld §4 invariant table only listed to I14, yet AGENTS/0001 both cite I15-I17 (hld as skeleton not self-consistent) | AGENTS.md, `hld.md` §4 |
| 27 | fix | AGENTS "no auto-strategy-generation" → "no **autonomous/unbounded** strategy generation (bounded AI iteration in scope, see R12)"; AGENTS References "R0-R11" → "R0-R12"; hld §4 invariant table completed with I15/I16/I17 (source marked 0001), both languages | AGENTS.md, `hld.md` v0.3, `hld.en.md` v0.3 |

## 2026-11-06

| # | Kind | Content | Location |
|---|---|---|---|
| 28 | doc | Established dedicated `docs/reviews/` subfolder; archived Batch 01 adversarial review report with implementation status badges (.gitignore / legacy active scrub / roadmap alignment resolved; LICENSE / pyproject / Commit 0 pending) | `docs/reviews/对抗性review-2026-11-05-批次1.md` + `.en.md` |
| 29 | review | Round 2 adversarial red-team review (Batch 02): uncovered 7 deep vulnerabilities (B9/I17 global immutability crashing lessons.md update push deadlock, "parameter modification" wording clashing with I8 fixed params, version tree cross-gen crossover undefined / unbounded branches evading kill criteria, sparse SQL signals vs trade engine 2% bar-by-bar stop extreme gap, B13 omitting alpha/ sandbox, 21-instrument pool & weekend financing calendar days undefined, engineering scaffold pending) | `docs/reviews/对抗性review-2026-11-06-批次2.md` + `.en.md` |
| 30 | review | Verified all 10 (batch1) + 7 (batch2) items' factual claims, then **classified**: ✅ real bugs to fix now = L1 (B9/I17 deadlock), L2 (I8 conflict), L5 (alpha isolation gap), O4 (dangling), batch1 already-fixed items; ⏳ legitimate-defer = L4 (SQL/trade-engine interface → 0004/0005), L6-financing definition → 0004, LICENSE/pyproject/Commit0 → T1/T3, CI → 0009; 🟡 new decisions needing user = L3 (cross-gen numbering / naming collision / branch cap), L6-21-instrument list → became O11-O15 | — |
| 31 | fix | Landed 4 real bugs: **L1** B9/I17 made two-tier (Immutable: data/runs/vNN/alpha + Append-only: hypothesis/lessons/index, new ⊇ old), removing the lessons-iteration push deadlock; **L2** R12/layout gained an I8 boundary (AI modification limited to strategy layer, feature underlying params off-limits); **L5** B13/I11 add `alpha/` + config gains `local.alpha` + `.gitignore` gains `alpha/` + AGENTS synced; **O4** closed | B9/I17 (layout+0001+hld ZH+EN), R12 (layout+requirements ZH+EN), B13/I11, config_example.yml, `.gitignore`, AGENTS.md, open-questions |
| 32 | decision (deferred to user) | 3 batch-2 items are **new decisions** (not bugs), moved to open-questions: **O11** cross-generation generation formula (suggest max+1), **O12** naming collision (suggest `_2` suffix / hash), **O13** Active Branch Cap (suggest 3-4); **O14** 21-instrument code list, **O15** financing day definition (suggest calendar days) | `open-questions.md` O11-O15 (ZH+EN) |
| 33 | decision (user) | User decided O11–O15: **O11** generation = `max(parent gens)+1`; **O12** version names may take `_1/_2` suffixes for same-strategy param variants; **O13** Active Branch Cap **pending the user's number** (meaning explained: cap on simultaneously-active branches per direction); **O14** instruments inherit moneta's `BASE_QUOTE` code system (list enumeration in 0002); **O15** financing counted by **trading days** (weekends + market holidays excluded) | `open-questions` O11/O12/O14/O15 closed (O13 pending), `oci-alpha-layout` §2.3 naming, `requirements` R4 costs, `config_example` comment |
| 34 | decision (user) + fix | **O13 set to 8** (per direction, max simultaneously-active branches; prevents AI infinite forking; excess must be explicitly pruned) → `open-questions` + layout §2.3 (ZH+EN); **batch-1 review annotation corrected**: item 7 (O4) was marked "Pending" by the prior reviewer but O4 was closed in #31, so item 7 ZH+EN + summary table row 10 all updated to "Done" | `open-questions` (O13 closed), `oci-alpha-layout` §2.3, `docs/reviews/batch-1` (item 7 + table row 10) |
| 35 | fix | **T3 done**: ① `LICENSE` (Apache-2.0 full text); ② `pyproject.toml` skeleton (lyra 0.1.0, py≥3.11, core deps ≤ 8 packages, `lyra` CLI entry, pytest/ruff/mypy config); ③ `strategies/examples/momentum_breakout/` (hypothesis.md + lessons.md + v01.yaml, YAML schema per nova's proven structure) + `strategies/examples/README.md` inventory — closing the "dangling examples promise" found in self-audit; .gitignore boundary verified (examples trackable; custom directions / alpha / data / config.yml all ignored) | `LICENSE`, `pyproject.toml`, `strategies/examples/*` (4 files) |
| 36 | commit | User decided to skip a further adversarial round and make **lyra's first commit** directly (doc skeleton + engineering init: .gitignore / LICENSE / pyproject.toml / strategies/examples). T1 closed; next is T2 (0002 OCI pull decision doc + code) | first commit (see git log) |
| 37 | doc | User asked whether AGENTS.md is enough for a fresh session to grasp background + progress — audit found the contract was sufficient but **three things missing**: ① current progress (0001 done / 0002 next / no code yet) ② **bilingual-pair rule + ACTION_LOG ZH/EN must be updated together** (the convention a new session is most likely to miss) ③ one-line core loop + explicit pointer to hld §8 as single source of truth. Added `## Where we are (read first)` + `## Documentation conventions (load-bearing)` | `AGENTS.md` |
| 38 | doc (user feedback) | User pushed back: #37 hard-codes "where we are" into AGENTS.md, which **goes stale and needs manual edits before every new session** — wrong. Settled: **the `## Current state` block in ACTION_LOG is the single source of truth for progress** (the only in-place-updatable section of the file, refreshed with every appended entry; the log body stays append-only). AGENTS.md `## Where we are` now **only points** (to the state block + hld §8 + core loop) and states no stale progress facts; working style "scan before acting" changed to "state block first, then last 10 rows" | `docs/ACTION_LOG.md`/`.en.md` (new state block + maintenance rule #5), `AGENTS.md` |
| 39 | decision (user) | After the user's foolproofing adversarial check, settled: **"refreshing the state block" is upgraded from convention to a mandatory rule** — every working turn (doc / code / config / strategy / review) must, in the same change: ① append an ACTION_LOG row AND ② refresh the `## Current state` block at the top; missing either = incomplete change, do not finish the turn, do not commit. Landed in: AGENTS.md **Non-negotiables item 1** (one-liner, first thing a new window reads) + Working style (full version with the completeness check) + maintenance rule #5 in both ACTION_LOGs (mandatory wording). Rationale: a fresh session must read many docs and risks losing the thread; the state block is the one entry point that locates "where the project is" without reading everything | `AGENTS.md`, `docs/ACTION_LOG.md`/`.en.md` maintenance rule #5 |

## Open (as of 2026-11-05 close)

| # | Item | Depends on |
|---|---|---|
| T1 | ✅ User decided to commit directly (2026-11-06, skipping a further review) → **first commit in progress** | — |
| T2 | Write the `0002-ohlcv-data-sync.md` decision doc (OCI pull + clean + aggregate), incl. settling O1 snapshot_id | T1 |
| T3 | ✅ Done (2026-11-06, #35): `.gitignore` (#25) + `LICENSE` + `pyproject.toml` + `strategies/examples/` example direction | — |
| T4 | ✅ Resolved (2026-11-05): user decided #22 = "AI-free crossover", superseding the restrained first draft; layout/requirements synced | — |

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft, back-filling all 15 actions of the day. |
| 2026-11-05 | 0.2 | Added #20/#21 (version-tree decision + landing); added **#22 restrained crossover (marked TBC)**; open items gains **T4** (user to confirm #22). |
| 2026-11-05 | 0.3 | **#22 flipped to "AI-free crossover"** (user decision: crossover/mutation is entirely up to the strategy-finding AI, granularity unrestricted; the framework ensures the AI has the capability; audit via AI-declared provenance); T4 marked ✅ resolved. |
| 2026-11-06 | 0.4 | Added #28/#29: created `docs/reviews/` subfolder, archived Batch 01 review with status tracking, executed Batch 02 adversarial red-team review. |
