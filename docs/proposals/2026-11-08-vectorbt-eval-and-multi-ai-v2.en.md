# vectorbt adoption vs multi-AI parallel search (evaluation / proposal) — **v2**

> **中文**: [2026-11-08-vectorbt-eval-and-multi-ai-v2.md](./2026-11-08-vectorbt-eval-and-multi-ai-v2.md)
>
> This file answers the two independent questions the user raised before starting 0004:
> ① should we adopt vectorbt ("no need to reinvent the wheel"); ② how to support **multiple AIs
> (of different capability)** iterating on the **same direction**, each at its own pace, without
> interfering, with cross-AI compare/learn/consolidate only when the user explicitly requests it.
> This is an **evaluation + proposal** (not a numbered decision doc); its conclusions are for the
> user's ruling; the ruling is then folded into the relevant decision docs.
>
> **This file is standalone and self-contained**: it does not read, reference, or compare against
> any other AI's similar evaluation elsewhere (the user explicitly instructed to ignore that one).
>
> **Naming (v2)**: a separate evaluation on the same topic already exists in this repo
> (`vectorbt-and-multi-ai-strategy-search.md`, written by another AI; its content is ignored per
> user instruction). To **avoid overwriting by name collision**, this file is named **`-v2`** and
> coexists with it; the two are **not merged**, and the user will later read and choose the better
> parts. This file **does not modify** the other file, nor the shared `hld.md`.

## Meta

| Field | Value |
|---|---|
| Type | Evaluation / proposal (Q1 adopt-or-not + Q2 concurrency design) |
| Status | **Awaiting user ruling** |
| Owner | `ttrrei` |
| Created | `2026-11-08` |
| Requirements | R2 (strategy language) / R4 (execution contract) / R5 (metrics) / R9 (Out of Scope) / R12 (directions & iteration) |
| HLD | §2.3 (strategy component) / §4 (I8/I15/I16/I17) |
| Affects | 0004 (YAML compiler) / 0005 (trade engine) / 0006 (metrics+runner) |

---

## 0. Conclusion first (TL;DR)

**Q1 — vectorbt: do NOT adopt (neither core nor runtime).**
Its three "selling points" (parameter-grid scanning, portfolio equity / CAGR / Sharpe / HWM,
portfolio optimization) are **exactly the goals we exclude via R2/R9**; the differentiators we keep
(the R4 execution contract, the R5 report semantics) it **does not model**. The cost of using it:
a third signal representation (a YAML→pandas bridge on top of YAML→SQL), **68 packages** (vs our
8 core) + a numba/llvmlite JIT C runtime, and a constant pull toward the R9 anti-goals.
**This is not "reinventing the wheel"** — it's that we *deliberately* don't build the wheels it
owns (param scan / account equity / portfolio), while the wheels it doesn't build (our execution
contract and report semantics) we must write regardless.

**Q2 — multi-AI: no new concurrency infrastructure needed; the R12 version-tree is the isolation primitive.**
"Same direction, different AIs, each at its own pace, non-interfering" = **branches** in the
version-tree are naturally isolated (one unique file per branch + append-only log + read-only
compare); "compare/learn/consolidate across AIs when I ask" = the existing `lyra compare --siblings`
+ a judgment entry (human / designated-AI triggered, not background-automated — fitting R9's
"bounded" boundary). We only add **4 minimal rules** (unique branch name, atomic log append,
read-only compare, isolation boundary = direction). **No distributed / multi-process / lock-service
infrastructure** (R9 excludes distributed and multi-process); "no interference" comes primarily from
**G1 unique branch → unique file** (data partitioning); a file lock is only a backstop for rare
overlap. The only concrete asks on 0004 are three: **compile determinism**, a **cheap
`validate` gate** (so weak AIs don't burn runs), and **per-instrument output** (the compare table
needs per-instrument rows).

---

## Q1. vectorbt

### 1.1 Empirical (2026-11-08, isolated venv, py3.12)

> Reproducible: `python -m venv .vbt && .vbt/bin/pip install vectorbt && .vbt/bin/python probe.py`
> (the probe was run and then deleted, leaving no trace; below is the observed-output summary.)

| Dimension | Observed | Meaning for us |
|---|---|---|
| Version / env | vectorbt **1.2.0**, deps numpy **2.5.4**, pandas **3.1.1** | Compatible with our numeric stack; installs cleanly |
| Dependency size | venv totals **68** packages (incl. **numba 0.68.1 + llvmlite 0.50.0 + scipy**) | vs our **8** core ([pyproject.toml](../../pyproject.toml)). numba is a **JIT C runtime** — the "no-wheel / C-build / ABI-break" risk class 0003-D2 already flagged |
| Data model | `Portfolio.from_signals(df, entry, exit_, price=df['Close'])`: a DataFrame is treated as **multi-asset**, signals broadcast across **all columns**; `total_return()` returns a **Series (one column per asset)**, not a scalar | vectorbt's default mental model is "one call = many assets × many params", not "one instrument, one at a time, never summed" — opposite to our R9 "never synthesize a portfolio". Using it means fighting its design to isolate per-instrument |
| Headline power | one call scans an N×M parameter grid (RSI window × threshold); `total_return` shape `(n_bars, n_params)` | This is **the core reason** people reach for vectorbt — **parameter scanning**. R2 **forbids parameter scanning** ("params fixed … no param scan (anti-overfit)"). Its most convenient feature is exactly what we deliberately removed |
| Metrics | natively computes CAGR (`annualized_return()`), Sharpe (`sharpe_ratio()`), max drawdown | These are the **account-level metrics R9 explicitly excludes**. Shipping them = a constant temptation to violate R9 (moneta fell into exactly this "peripheral over-engineering") |
| Execution contract | offers `sl_stop`/`tp_stop` (fractional stop/TP); does **not** model: one-position-per-instrument, no pyramiding, no-reentry, last-bar queued entry expires, TP+SL same-bar → loser-first, flat-at-end, conflicting L/S → both off | **None of R4's edge cases are modeled**. Using vectorbt for 0005 means re-implementing this contract outside its signal framework anyway |
| Return model | the `direction × (exit−entry)/entry − cost` PnL arithmetic **works**; but its cost/financing/trading-day semantics differ from R4 | the simple PnL arithmetic is reusable; the R4 details (trading-day financing excluding weekends/holidays, 2% trigger ≠ net-loss cap, gap can exceed 2%) are not its concern |

**Key judgment**: aligning "what it does" with "what we don't want", the overlapping part (PnL
arithmetic, monthly aggregation, win rate, avg holding bars) is on the order of **hundreds of lines
of numpy over trades**; the non-overlapping part (the R4 execution contract, the R5 report
semantics, causality, past-only compilation) is **our core differentiator, which it doesn't do**.
So using it = paying 68 packages + numba + a library that keeps pulling us toward R9, in order to
save a few hundred lines of "commodity" code, while still writing the hard part ourselves. **Net negative.**

### 1.2 Recommendation

1. **Do not put vectorbt in core / runtime** (not in the core deps of [pyproject.toml](../../pyproject.toml), not in the R10 ≤15-core budget).
2. **Do not use it in the trade engine (0005)**: R4's contract (2% trigger, gap can exceed, TP+SL loser-first, no-reentry, last-bar expiry, trading-day financing) is not modeled; using it means building a bridge + rewriting the contract, which is more complex and less "open-source-simple".
3. **(Optional, low priority) control group**: if cross-engine cross-validation is ever needed, use it at most as a **test-time control** (like pandas-ta-classic / tulipy under `[control]`), and **only to validate the simple PnL arithmetic**, explicitly noting "does not cover R4 edge cases" — because its sl_stop/tp_stop differ from our 2% trigger, using it as an execution-contract validator would be **misleading** (it passes the simple cases but fails exactly the edge cases we care about). **Default: do not do it**, to avoid opening another "control group" door.
4. **One-line answer to the user**: "no need to reinvent the wheel" — agreed. But we are not reinventing *its* wheel (param scan / portfolio / account equity); those are the ones we **deliberately** don't build (R2/R9). The wheel it doesn't build (our execution contract / report) is the one we must build, and can't skip.

### 1.3 If the user still wants to adopt it (risk list, for the ruling)

| Risk | Note | Mitigation |
|---|---|---|
| Dependency bloat | 68 packages + numba/llvmlite (JIT C runtime) | `[control]` optional only, never core; runtime import needs a whitelist |
| R9 temptation | ships CAGR/Sharpe/HWM/portfolio; easy to "happily" compute into reports | report layer explicitly disables its portfolio metrics; only per-instrument PnL allowed |
| Contract mismatch | sl_stop/tp_stop ≠ R4's 2% trigger + gap + loser-first | mark it "signal→PnL-arithmetic control only", never the execution contract |
| Maintenance surface | one more third-party engine = one more version lock + upgrade surface | pin the version, CI lock; no upgrade without a need |
| Mental-model drift | "many assets × many params at once" default model opposes R9 | doc states "per-instrument isolation, never summed"; using its API requires writing against its design |

### 1.4 Advantages (recorded honestly, to avoid a "downsides-only" bias)

- **Installs & runs fast**: 1.2.0 installs cleanly on our stack; numba makes bulk PnL fast.
- **Mature multi-asset / multi-param API**: convenient for "portfolio-level" research (which we don't do).
- **Docs / ecosystem**: quick to learn, many examples.
- **These advantages all sit in "portfolio / param-scan / account-equity"** — the areas R2/R9 explicitly exclude — so for a per-instrument, param-fixed, no-portfolio, no-account-equity Lyra, they barely materialize.

---

## Q2. Multi-AI (different capability) parallel search

### 2.1 Requirements mapping (the user's words → R12)

| User's words | Mapping |
|---|---|
| "same direction, different AIs, each at its own pace" | within one **direction folder**, multiple AIs each iterate on **different branches** (`vNNa` / `vNNb`), each writing its own |
| "non-interfering" | writes are **isolated per branch** (unique branch file + unique run dir); logs are **append, never overwrite**; compare is **read-only** |
| "AIs of different intelligence can all participate" | the framework guarantees a **simple loop + self-contained context** (read 1 → write 1 → run 1 → log 1) so even a weak AI can reliably finish; `validate` catches bad YAML before any run |
| "unless I ask, let a certain AI compare/learn/consolidate across AIs on the direction" | **user-triggered** cross-AI review: `lyra compare --siblings` produces a side-by-side summary → a designated AI / user writes a **judgment entry** (continue / prune / cross); this is **bounded (within the direction) + human-initiated**, fitting R9's "bounded iteration" boundary, **not** background autonomy |

**Core insight**: the R12 version-tree (direction = isolation unit, branch = candidate, lessons =
append-only log, compare = read-only compare) **is itself the concurrency primitive**. "Multi-AI
parallelism" is not a new scheduler to build; it is making sure this existing structure doesn't
stomp on itself when multiple processes write to one direction folder.

### 2.2 Current-state inventory (what's already there / what's a gap)

| Operation | Current | Under multi-AI concurrency |
|---|---|---|
| write branch `vNNa.yaml` | one **unique file** per branch (R12 naming: depth + letter suffix + `_n`) | ✅ naturally isolated — as long as the branch name is unique (**G1**) |
| write run results `runs/<dir>/<branch>/…` | one unique run dir per branch | ✅ naturally isolated (lands in 0005/0006) |
| append `lessons.md` / `hypothesis.md` | I17 already sets **append-only + superset check** | ⚠️ needs **atomic append** (**G2**), else two concurrent appends can interleave / drop lines |
| `lyra compare --siblings` | reads sibling branch run summaries → read-only | ✅ read-only, no write conflict |
| cross-AI compare/learn/consolidate (user-triggered) | = compare + judgment + optional merge | ✅ already modeled; needs **explicit trigger** (**G4**), never automatic |
| cross-direction write | R12 undefined | needs **explicit prohibition** (isolation boundary = direction, **G4**) |

### 2.3 Four minimal rules (no distributed / multi-process / lock-service infrastructure)

> R9 explicitly excludes "distributed / multi-process / cloud-native". This design **does not
> violate** R9, because multi-AI collaboration is a **user-driven workflow** (the user advances it
> in separate sessions / at different times), **not** a persistent coordinated concurrent system.
> The framework **provides no multi-process / distributed / lock-service mechanism**; "no
> interference" is achieved entirely by **data-model partitioning** (G1 unique branch name →
> unique file), i.e. it is **single-writer-friendly by default**: even if two AIs touch the same
> direction folder at **different times**, they cannot corrupt each other. A file lock is kept
> **only** as a belt-and-braces backstop for the rare genuine overlap — **not** a concurrency
> engine, and **not** the multi-process R9 excludes.

- **G1 unique branch name (fail-fast)**: `lyra new-version --branch <id>` where `<id>` is already
  taken **errors immediately** (following the 0003 F5 precedent "name clash → error, no overwrite,
  no `_2` suffix"), telling the AI to pick another. **No auto-assignment, no retry queue** — keep the
  simple semantics a weak AI can use. **This is the primary "no-interference" mechanism** (unique
  branch → unique file, no write conflict by construction).
- **G2 atomic log append (best-effort backstop)**: one "entry" in `lessons.md` / `hypothesis.md`
  is an **atomic unit**; in the normal case it is **single-writer sequential append, no lock
  needed**; only when a **genuine overlap** (rare) occurs may the tool add a local advisory file
  lock (`fcntl`/`flock`) to prevent interleaving — **a backstop, not a concurrency mechanism**;
  I17's superset check at push is the final backstop (a dropped append is rejected at push, never
  silently lost).
- **G3 self-contained context (weak-AI parity)**: `lyra context <dir>` emits a single-file context
  bundle (defined in R12); any-capability AI reads the same one and runs the same loop
  (read 1 → write 1 → run 1 → log 1); the I8 guard (strategy layer only) + a pre-run `validate` gate
  = a weak AI doesn't burn runs or corrupt features. **The framework's job is to "guarantee the loop
  is simple enough for a weak AI to finish reliably"** — that is how "AIs of different intelligence
  can all participate" is realized, rather than building different flows for different AIs.
- **G4 isolation boundary = direction**: writes stay **within this direction folder**; cross-direction
  is **read-only reference** (a branch `driven_by_lesson` may cite another direction's lessons, but
  **no auto-import**); cross-AI "compare/learn/consolidate" is a **user-explicitly-triggered**
  compare + judgment, **never background-automated**. "Non-interference" is thus guaranteed by
  **data-model partitioning**, not runtime coordination.

### 2.4 Concrete asks on the 0004 compiler (only three, all 0004's job)

| # | Requirement | Rationale | Landing |
|---|---|---|---|
| C1 | **Compile determinism**: `compile(yaml, feature_snapshot, git_commit)` is a **pure function** — same input → same SQL, no wall-clock / random / in-process state | multiple AIs running the same branch in parallel must get reproducible, comparable results (the precondition for compare); otherwise "compare/learn" is meaningless | 0004 invariant + test (two compiles byte-identical) |
| C2 | **Cheap `validate`**: `lyra validate` catches feature-name / param / time-operator / right-value errors **before any run**, precise to the line with LLM-friendly messages | a weak AI's biggest time sink is "writing a bad YAML, only discovering it after a full run"; moving the gate to validate slashes a weak AI's iteration cost | 0004 CLI (HLD §2.3 already lists `lyra validate`) |
| C3 | **Per-instrument output contract**: the compiled artifact is **per-instrument** past-only SQL (against a single feature wide-table view, e.g. `features_5m` / `features_1h`), **not** a synthesized portfolio | the compare table needs **per-instrument rows** (R5); R9 never synthesizes. Per-instrument is also the basis for per-branch compare across AIs | 0004 plan §3.1 + invariant |

### 2.5 Risks & advantages

**Advantages**:
- **Zero new infrastructure**: concurrency isolation comes from the R12 version-tree's **data partitioning**; no scheduler / lock service / message queue.
- **Weak-AI parity**: the same simple loop + self-contained context + I8/validate guard lets a lower-capability AI reliably produce work.
- **The human keeps control**: cross-AI compare/learn/consolidate is a **user-triggered** bounded operation, fitting R9's "bounded iteration" boundary and not sliding into "unattended batch generation".
- **Auditable**: each branch's `driven_by_lesson` + `parent`/`parents` + author (AI-declared) → any evolution is traceable to who, and why.

**Risks (and mitigations)**:
| Risk | Mitigation |
|---|---|
| two AIs appending `lessons.md` interleave / drop lines | normal case is single-writer sequential append (no lock); G2 file lock is only a best-effort backstop for the rare genuine overlap + I17 superset check at push |
| branch-name collision | G1 fail-fast error (F5 precedent), no auto-assignment |
| a weak AI burns many runs on a bad strategy | G3 simple loop + C2 cheap validate gate + I8 guard |
| "multi-AI" misread as a "distributed / multi-process system" | state clearly: **user-driven workflow + data-model partitioning** (G1 unique branch → unique file); **not** a persistent concurrent system, not distributed (R9 not violated); the file lock is only a backstop for rare overlap; write it in the docs |
| cross-AI "learning" overreach into "autonomous generation" | compare/learn/consolidate is **user-triggered** + within one direction (**G4**), holding the R9 boundary |

### 2.6 Recommendation

1. **Do not build a new concurrency subsystem.** Write the **4 minimal rules (G1–G4)** into the
   invariants of the 0004/0006 decision docs, and the **3 compiler requirements (C1–C3)** into
   0004's invariants.
2. **Multi-AI concurrency is the natural result of the existing version-tree + a few local-file
   disciplines**; it needs no new architectural layer.
3. If "multiple AIs competing on one direction" ever truly needs coordination, evaluate stronger
   mechanisms then; **do not build it now** (YAGNI, and R9 excludes distributed).

---

## Appendix: boundary vs "another AI's evaluation"

The user explicitly instructed to **ignore the other AI's evaluation doc**. This file **does not
read, reference, or compare** against that document; its conclusions rest entirely on this repo's
R2/R4/R5/R9/R12 + HLD + the §1.1 measurements above. If the two conflict, the **user's ruling**
governs (see §0).

## Self-check and adversarial self-check (2026-11-08, v2)

> Method: every claim this file makes about R2/R4/R5/R9/R12 / HLD was **checked back against the
> original text** of requirements.md + hld.md, and we actively looked for counterexamples that
> would refute a conclusion. Dispositions: **Fixed / Accepted (with reason) / Parked**.

| # | Finding | Level | Disposition |
|---|---|---|---|
| F1 | **Wrong feature view name**: C3 said `features_ohlcv_<m>`; `lyra/catalog.py` actually defines `features_5m` / `features_1h` (reading `features/ohlcv_5m` / `features/ohlcv_1h`) | High (factual) | **Fixed** (C3 now `features_5m`/`features_1h`; ZH+EN) |
| F2 | **Self-contradiction with R9**: §2.3 justified multi-AI as "local multi-process + file lock", but R9 explicitly excludes "**multi-process**" | High (conflicts with a requirement) | **Fixed** (reframed as "user-driven workflow + data-model partitioning"; G1 is the primary mechanism; file lock demoted to a rare-overlap backstop, **not** a concurrency engine; ZH+EN) |
| F3 | **Inconsistent terminology**: TL;DR / §2.4 mixed "per-scalar output" while R5 uses "per-instrument rows" | Medium | **Fixed** (unified to "per-instrument output / 每合约输出") |
| F4 | **C1 typo**: "no wall-clock / random / process-in" | Low | **Fixed** ("in-process state / 进程内状态") |
| F5 | Same-name collision: another AI's same-topic proposal already exists in the repo, and `0004-yaml-compiler.md` is also taken by the other AI | High (process / ownership) | **Accepted (user ruling)**: this file renamed to `-v2` to coexist, not overwrite, not merge; 0004 to be picked by the user later |
| F6 | Is the Q1 "do NOT adopt vectorbt" over-stated? Is its `[control]` PnL-validation value under-weighted? | Medium | **Accepted (kept optional)**: "not in core / runtime" holds; `[control]` for simple-PnL only stays **optional / low-priority / default-off**, to avoid opening another "control group" door |
| F7 | Is the G2 file lock over-engineered into a "concurrency mechanism"? | Medium | **Accepted (framing demoted)**: explicitly **single-writer by default, no lock needed**; the lock is only a best-effort backstop (same root as F2) |
| F8 | Does "weak-AI parity (G3)" imply "building a different flow for weak AIs"? | Medium | **Accepted (clarified)**: parity = one simple loop, no per-capability branch; the framework does **not** ship two different flows |
| F9 | Is the boundary between multi-AI concurrency and R9 "bounded iteration / human per-version review" covered? | Medium | **Accepted**: G4 already states cross-AI compare/learn/consolidate = **user-triggered + within one direction**, holding R9's bounded boundary (not background autonomous generation) |
| F10 | Are the vectorbt numbers (68 packages / numba / multi-asset default model) genuinely measured that day? | High (reproducibility) | **Accepted (source annotated)**: §1.1 marks it "2026-11-08 isolated-venv measurement, reproducible command"; if the environment drifts, re-run before re-citing |

> **Conclusion**: F1/F2/F3/F4 are **factual / consistency errors, fixed**; F5 is the user's
> process ruling; F6–F9 are **accepted boundary clarifications** (conclusions unchanged, wording
> tightened); F10 is an **empirical-reproducibility** annotation. No "unfixed and misleading"
> open item remains.

## Revision log

| Date | Version | Change |
|---|---|---|
| 2026-11-08 | 0.2 | **v2 naming + self-check / adversarial self-check.** ① A same-topic proposal by another AI already exists in this repo (`vectorbt-and-multi-ai-strategy-search.md`; its content ignored per user instruction) — this file was **renamed `-v2`** to coexist without overwriting; no merge; ② fixed the **feature view name** (`features_ohlcv_<m>` → actual `features_5m`/`features_1h`); ③ **fixed the R9 contradiction**: the earlier "local multi-process + file lock" framing conflicted with R9's exclusion of "multi-process"; reframed as a **user-driven workflow + data-model partitioning** (G1 unique branch → unique file is the primary no-interference mechanism; the file lock demoted to a best-effort backstop for rare overlap, **not** a concurrency engine); ④ terminology unified "per-scalar output" → "per-instrument output". |
