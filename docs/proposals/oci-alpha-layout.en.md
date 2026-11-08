# OCI Alpha Layout (Proposal)

> **中文**: [oci-alpha-layout.md](./oci-alpha-layout.md)
>
> **Status**: Proposal, pending review.
> **Version**: v0.9 | **Date**: 2026-11-05
> **Owner**: ttrrei
> **Related**: `docs/decisions/0001-repo-and-oci-split.md`

## 0. Why this proposal exists

Lyra's core is open-source (git); alpha is closed-source (OCI). The two
must be **physically separated** with a **clear boundary**, otherwise:
- Alpha accidentally committed to git → arbitraged away.
- Core accidentally pushed to OCI → open-sourcing loses meaning.
- AI touching alpha while modifying core → semantic drift.

This proposal defines the **full OCI directory layout** as the physical
boundary between core and alpha.

## 1. Top-level layout

```
oci://<bucket>/lyra/
├── data/                 base data (shareable, rebuildable)
│   ├── raw_csv/          raw CSVs (OANDA / other sources)
│   ├── raw_parquet/      raw Parquet
│   ├── market/           cleaned OHLCV
│   │   ├── 1m/
│   │   ├── 5m/
│   │   └── 60m/
│   └── features/         feature wide tables
│       ├── 5m/
│       └── 60m/
├── alpha/                custom features (closed-source)
│   ├── features/
│   │   ├── *.py          feature implementations
│   │   ├── contracts/    contract cards
│   │   │   └── *.md
│   │   └── tests/        golden tests
│   │       └── *.py
│   └── README.md         alpha feature inventory (human-readable)
├── strategies/           strategies (closed-source), organized by direction (see §2.3)
│   ├── <direction>/      one folder per direction: hypothesis.md + lessons.md + vNN.yaml (see §2.3)
│   ├── _new/             user-created directions
│   └── README.md         strategy inventory (human-readable)
├── runs/                 run results (closed-source)
│   ├── <strategy_id>/
│   │   ├── <YYYY-MM-DD>/
│   │   │   ├── run_meta.json
│   │   │   ├── trades.csv
│   │   │   ├── monthly.csv
│   │   │   └── report.md
│   │   └── ...
│   └── README.md         run inventory (human-readable)
└── index/                index / manifest (closed-source, optional)
    ├── strategies.json   full strategy index (id → path → summary)
    ├── features.json     full alpha feature index
    └── runs.json         full run index
```

## 2. Per-directory rules

### 2.1 `data/` (base data)

**Nature**: shareable, rebuildable, **non-alpha**.
**Writer**: `lyra pull` from OCI; `lyra push-data` optionally pushes
back (multi-machine reuse).
**Reader**: `lyra run` reads `data/features/`; `lyra clean` reads
`data/raw_csv/` `data/raw_parquet/`.
**Versioning**: `<snapshot_id>` is a monotonic integer (`000001`,
`000002`, …) allocated locally by `data.py`. Files on OCI with the same
snapshot_id are **immutable** (SHA256 recorded at upload; never
overwritten).

```
oci://<bucket>/lyra/data/raw_csv/
  EUR_USD/2019-01.csv
  EUR_USD/2019-02.csv
  ...
  XAU_USD/2019-01.csv
  ...
  _manifest/
    2026-11-05/
      manifest.json   {files: [{name, sha256, size, instrument}]}

oci://<bucket>/lyra/data/market/60m/000042/
  EUR_USD.parquet
  XAU_USD.parquet
  ...
  manifest.json       {snapshot_id, source_snapshot_ids, instruments,
                       sha256_per_file, created_at}

oci://<bucket>/lyra/data/features/60m/000042/
  EUR_USD_core.parquet
  EUR_USD_trend.parquet
  EUR_USD_momentum.parquet
  XAU_USD_core.parquet
  ...
  manifest.json       {snapshot_id, market_snapshot_id, FEATURE_VERSION,
                       feature_list, sha256_per_file, created_at}
```

### 2.2 `alpha/` (custom features)

**Nature**: **closed-source**, the core of alpha.
**Writer**: user via `lyra push-alpha`; **not** written by `lyra run`.
**Reader**: `lyra features --extend-from <oci_path>` loads them.
**Naming**: one file per feature; filename = registered name.
**Contract card**: each feature must carry `contracts/<name>.md`
containing:
  - state variables
  - transition rule (pseudocode + boundary conditions)
  - seed rule
  - gap / flip boundary
  - dependent input columns
  - parameters (fixed values)
**Golden test**: each feature must carry `tests/test_<name>.py`
covering at minimum:
  - a fixed input → fixed output segment
  - warm-up NULL behavior
  - gap behavior
  - boundary flip behavior

```
oci://<bucket>/lyra/alpha/features/
  my_trend_filter.py
  my_momentum_pulse.py
  contracts/
    my_trend_filter.md
    my_momentum_pulse.md
  tests/
    test_my_trend_filter.py
    test_my_momentum_pulse.py
  README.md
```

### 2.3 `strategies/` (directions + version tree)

**Core idea**: the **primary unit of organization is a direction
(research family)**, not an individual strategy file. One direction = one
testable market hypothesis ("why this opportunity may exist + how long it
is expected to last + why costs won't eat it + what result makes us
abandon the hypothesis"). Within a direction, strategies evolve as a
**version tree**: **v01's run results + failure diagnosis can spawn
several candidate branches**; the AI compares the actual performance of
multiple branches, then judges **which branch to continue, which to
prune, or synthesize a new branch from parts of two** (a
genetic-algorithm-style mutation / crossover). Iteration is the **primary
production process** of alpha, not "run it and glance at the result";
**single-threaded deep search falls into local optima, so branching is a
first-class capability, not an exception**.

**Nature**: **closed-source**, the core of alpha.
**Writer**: **the user and AI are both first-class writers**, using the
same commands: `lyra push-direction <dir>` / `lyra push-strategy <yaml>`;
`lyra new-version <direction>` derives a template from a chosen parent
(call it multiple times to create multiple branches); `lyra merge <new>
--from <a> --from <b>` synthesizes a new branch from two (crossover).
**Reader**: `lyra run --strategy <path_or_oci_ref>`;
`lyra show-direction <direction>` presents hypothesis + lessons + version
tree in one view; `lyra compare <direction> [--siblings]` lays out the
run summaries of each branch under the same parent side by side (the
input for the AI's judgment).

**AI efficiency requirement (first-class)**: when AI participates in
iteration, the context it needs must be **self-contained inside the
direction folder** — it must not have to read the whole repo or dig
through historical run files:

- `lyra context <direction>` emits a single **context bundle** file
  (AI reads exactly one file and can start writing):
  1. the full `hypothesis.md`
  2. the **last N sections** of `lessons.md` (default 5; `--all` for
     everything)
  3. the full latest vNN.yaml of the **active branch(es)** + its
     `parent` / `driven_by_lesson` fields
  4. a **comparison table of sibling-branch run summaries** (each
     branch's annualized score / zero-entry months / failure-scenario
     classes — the input for the AI's "which branch to continue" call, no
     need to browse the runs/ directory)
  5. a full summary of the most recent run (annualized score /
     zero-entry months / failure-scenario classes, from report.md — AI
     does not read trades.csv in full)
  6. the list of features this direction uses, with parameters (from
     the catalog — no need to open `features.py`)
- The complete AI write loop = **read 1 file (context bundle) → write 1
  or more files (vNN+1 branches) → run each once → write 1 section
  (lessons.md) + 1 judgment (continue / prune / cross)**, never touching
  the rest of the repo.
- Consequently the formats of `hypothesis.md` / `lessons.md` / `vNN.yaml`
  must stay **LLM-friendly**: fixed sections, short sentences, each
  section self-contained, key numbers written directly in the text
  (no "see table elsewhere" indirection).

**Directory layout** (one folder per direction; 12 initial directions
inherited from nova; **the direction set is open (extendable)** — the
initial 12 are a seed, not a ceiling):

```
oci://<bucket>/lyra/strategies/
  trend_continuation/
    hypothesis.md          direction hypothesis (testable claim + kill criteria)
    lessons.md             evolution log (each version's result / lesson / branch judgment)
    v01.yaml               first hypothesis strategy
    v02a.yaml              branch A: candidate 1 derived from v01's lesson
    v02b.yaml              branch B: candidate 2 derived from v01's lesson
    v03a.yaml              branch A continued (AI judged A stronger after comparison)
    v04ab.yaml             crossover: v03a's entry + v02b's exit
    ...
  failed_breakout/
    hypothesis.md
    lessons.md
    v01.yaml
    ...
  mean_reversion/
    ...
  momentum_exhaustion/
  pullback_reentry/
  range_trading/
  regime_transition/
  relative_strength/
  session_temporal/
  volatility_expansion/
  volume_activity/
  market_structure/
  _new/                    user-created directions (beyond the initial 12)
    <new_direction>/
      hypothesis.md
      lessons.md
      v01.yaml
  README.md                full direction inventory (human-readable: direction /
                           hypothesis / active branch / latest run date +
                           annualized score / status)
```

**Naming convention**: `v<generation><branch-suffix>.yaml`. Generation =
tree depth (v01, v02, v03…); suffix = branch id (a/b/c/…; crossover
branches concatenate their sources, e.g. `ab`). The branch id is a
**letter**, not a digit, to avoid clashing with the generation.
**Cross-generation generation** = `max(parent generations) + 1` (v02a×v04b → gen 5) — the next generation after the latest parent.
**Same strategy, different params / repeated variants of the same parent pair**:
any version name may carry a `_1` `_2` … suffix (e.g. `v04ab_1`, `v04ab_2`)
to distinguish the same strategy's different parameter sets or fusion schemes.

**Fixed structure of `hypothesis.md`**:

```markdown
# <direction> — hypothesis
- Claim: …… (testable, 1-2 sentences)
- Why this opportunity may exist: ……
- Expected duration / environments where it fails: ……
- Why costs won't eat it: ……
- Kill criteria: **all active branches** for N consecutive evolution
  rounds (each round = one new version per branch) with annualized
  score < X and the same failure class → stop this direction (a single
  branch failing is NOT a kill — branch first, then judge)
- Current status: active / paused / killed
- Active branches: v03a (others pruned: v02b → pruned @ 2026-11-20, see
  lessons for reason)
- History: (append a row each time the hypothesis changes; never delete)
```

**Fixed structure of `lessons.md`** (append-only, the main driver of
evolution; one section per version + one per branching judgment):

```markdown
## v02a (2026-11-20)
- Parent: v01
- What changed: exit from fixed 12 bars → conditional (range_position_24 reversion)
- Lesson that drove it: v01's failures concentrated in the "breakout then
  immediate retrace" scenario
- Result: annualized score +0.0012; zero-entry months 3; failure
  scenario distribution ……

## v02b (2026-11-20)
- Parent: v01
- What changed: entry + session filter (within UTC opening hour)
- Lesson that drove it: 60% of v01's losing trades occurred in Asian hours
- Result: annualized score -0.0004; zero-entry months 5

## judgment (2026-11-21)
- Comparison: v02a +0.0012 vs v02b -0.0004
- Call: **continue v02a / prune v02b**
- Reason: v02b's filter is too strong (5 zero-entry months); the loss of
  scenario coverage outweighs the session gain
- v03 candidates: A (tighten v02a's conditional exit) / B (weaker version
  of v02b's session filter, only excluding losing hours)
```

**Strategy YAML metadata** (header of vNN files):

```yaml
version: 1
id: trend_continuation_v03a
direction: trend_continuation
parent: trend_continuation_v02a           # v01 has none
driven_by_lesson: "v02a failures concentrated in scenario X"  # one line, points to lessons.md
hypothesis: A PSAR flip confirmed for three observed bars ...
timeframe_minutes: 60
# ... entry / exit / execution compatible with nova ...
```

Crossover branches additionally declare (AI-declared, for audit
traceability — **not** a constraint on the AI's behavior):

```yaml
id: trend_continuation_v04ab
parents: [trend_continuation_v03a, trend_continuation_v02b]   # crossover sources
inherited: {entry: from_v03a, exit: from_v02b}                # per-part provenance (AI-declared)
```

**Crossover is fully decided by the strategy-finding AI (user
decision)**: what to take from two (or more) branches and how to
combine it is **entirely up to the AI** — whole-part inheritance,
per-parameter mixing, or even modifying parameters. The framework does
**not** restrict crossover granularity. The framework's job is to make
sure this AI **has the capability**: the `lyra context` bundle already
includes the **full YAML + parameters** of the active branches, so the
AI can read and combine freely. Audit relies on the AI **declaring the
sources** in `inherited` / `driven_by_lesson` (traceable, but not
forced into "whole-parts only").

> **Boundary (I8 unchanged)**: the AI's "modification" capability is
> **strictly limited to the strategy layer** — threshold constants,
> comparison operators, temporal operators (`held_for.bars` /
> `within.bars`), entry/exit structure. **Changing a feature's
> registered name or the underlying parameters of a registered feature
> is forbidden** (`sma_6_24` → `sma_7_25` is an I8 violation; `lyra
> validate` rejects it). A changing feature = a newly registered
> feature (alpha side: contract card + golden test), not a number
> change inside the strategy YAML.

**Branch lifecycle**: `active` (evolving) → `pruned` (kept, no longer
selected by default `lyra run`) → or inherited as a parent in a
crossover. Pruning **never deletes files** (extension of B6/B12);
multiple active branches may evolve in parallel at the same generation.
**Active Branch Cap (O13, amended 2026-11-08 by the user: 8 per
track)**: per **track**, at most **8 simultaneously-active branches**;
slots do not compete across tracks (multiple AIs are mutually
non-interfering; the original intent of preventing infinite forking
within one research flow still holds); excess must be pruned explicitly.
(The 2026-11-06 global-per-direction-8 rule is superseded by the
2026-11-08 ruling.)

**AI tracks (user ruling 2026-11-08)**: a direction may hold multiple
tracks, layout:

```
strategies/<direction>/
  hypothesis.md            direction hypothesis (each track pins one read-only snapshot)
  tracks/<track_id>/
    lessons.md             this track's append-only evolution log
    v01.yaml, v02a.yaml, … this track's candidates (≤ 8 active per track)
  reviews/<review_id>.md   read-only cross-track synthesis reports, user-triggered
runs/<direction>/<track_id>/<run_id>/   runs attributed per track
```

- `track_id` ↔ one AI researcher (research identity); it **does not
  change** any machine behavior or gate of validate / compile / run /
  report.
- Multiple AIs may work on the same or different directions in parallel;
  the base (data / features / catalog / compiler / CLI) is shared; no
  scheduler / file locks / concurrency coordination (R9 preserved).
- This layout and `lyra context --track` land with 0005/0006; the 0004
  compiler stays track-agnostic (it only consumes the given YAML +
  catalog).

**Iteration loop (Lyra's core workflow, branching-capable)**:

```
   ┌──────────────────────────────────────────────────┐
   │  1. lyra context <dir>                           │
   │     read hypothesis + lessons + active branches  │
   │     + sibling-branch run-summary comparison      │
   ├──────────────────────────────────────────────────┤
   │  2. lyra new-version <dir> --branch <suffix>     │
   │     derive 1..N candidate branch templates from  │
   │     the same parent (v0(N+1)a / v0(N+1)b / ...)  │
   │     AI/human writes a distinct evolution idea    │
   │     into each                                    │
   ├──────────────────────────────────────────────────┤
   │  3. run each branch once                         │
   │     lyra run --strategy <dir>/v0(N+1)a ...       │
   ├──────────────────────────────────────────────────┤
   │  4. lyra compare <dir> --siblings                │
   │     AI/human compares branch summaries +         │
   │     per-trade diagnosis                          │
   ├──────────────────────────────────────────────────┤
   │  5. write lessons.md: one section per branch +   │
   │     one judgment section (continue / prune /     │
   │     whether to crossover)                        │
   ├──────────────────────────────────────────────────┤
   │  6. (optional) lyra merge <new> --from <a>       │
   │     --from <b>                                   │
   │     synthesize a new branch from parts of two    │
   │     (crossover)                                  │
   ├──────────────────────────────────────────────────┤
   │  7. lyra push-direction <dir>                    │
   │     upload new versions + lessons to OCI         │
   └──────────────┬───────────────────────────────────┘
                  ▼ back to 1
```

**Comparison with nova**:

| Dimension | nova | lyra |
|---|---|---|
| Primary unit | 12 flat YAMLs (`directions/*.yaml`) | **direction folders (extendable)**, each with hypothesis + lessons + vNN version tree |
| Direction set | fixed at 12 (README says "twelve fixed") | **open to extension**: initial 12 + `_new/` self-created |
| Hypothesis | one `hypothesis:` string in the YAML | **standalone `hypothesis.md`** with kill criteria + history + active branches |
| Iteration | none (one direction one YAML, edit in place) | **version tree**: one parent can spawn multiple candidate branches; each version must fill `parent` + `driven_by_lesson` |
| Multi-candidate comparison | no mechanism | **`lyra compare --siblings`** + a judgment section in lessons (AI/human calls continue / prune / cross) |
| Crossover (mutation) | no mechanism | **fully decided by the strategy-finding AI** (whole-part / per-parameter / modified, granularity unrestricted); the framework ensures the AI has the capability (context includes full YAML + params); the AI declares provenance in `inherited` for audit |
| Failure diagnosis | `runs/directions/review_findings.json` (after-the-fact audit) | **`lessons.md` (evolution main driver, written before next version)** |
| Abandon direction | no mechanism | `hypothesis.md` `status: killed` + kill criteria (**all** active branches failing N consecutive rounds); a single failing branch → prune, not kill |
| New direction | no mechanism | `strategies/_new/<name>/` + same hypothesis/lessons/vNN structure |

**Extendability rules for the direction set**:

- The initial 12 directions are a **seed**, not a closed list. Nova's
  12 already cover hypothesis dimensions like "trend / mean reversion /
  structure / volume / volatility / session / relative strength", but
  new hypothesis dimensions will naturally emerge during research
  (e.g. "liquidity gap", "cross-session spillover"); the direction set
  must be allowed to grow.
- Admissions bar for a new direction (**soft standard — a
  recommendation, not a hard gate**): it **should be a testable,
  independent market hypothesis**, and ideally not duplicate an existing
  direction (i.e., not equivalently expressible as a combination of an
  existing direction's entry/exit). If it can be expressed that way, it
  is **recommended** to open a new **version** of that direction instead
  of a new one. Lyra does not build a direction-equivalence checker
  (stays "stable + light").
- New directions live under `strategies/_new/<name>/`; naming uses
  snake_case verb phrases (e.g. `liquidity_gap`, `cross_session_spillover`);
  must not collide with the initial 12 names.
- New and initial directions are **fully peer**: same `hypothesis.md` /
  `lessons.md` / vNN structure, same B11/B12 constraints, same kill
  criteria mechanism. Initial directions have no privilege; extended
  directions have no extra hurdle.
- When an initial direction is `killed`, its folder is **not deleted** —
  it stays as research history. Its hypothesis space may be inherited by
  a new direction (noted in the new direction's `hypothesis.md` History
  as "inherits from <killed direction>").
- No cap on direction count, but every direction must be independently
  runnable and independently killable; **directions must not share
  state** (a direction is a container for a hypothesis, not a node in a
  module-dependency graph).

**Boundary rules** (appended to §3):

| # | Rule | Consequence of violation |
|---|---|---|
| B11 | Each direction folder must contain `hypothesis.md` + `lessons.md`; missing either blocks push | direction loses its hypothesis or evolution history |
| B12 | vNN.yaml (N≥2) must carry `parent` (crossover branches: `parents`) + `driven_by_lesson` fields pointing to an existing version in the same direction; pruned / killed branch files are retained, never deleted | version tree broken; "why this design" no longer traceable |

### 2.4 `runs/` (run results)

**Nature**: **closed-source**, the core of alpha.
**Writer**: `lyra run` completes → `lyra push-run <run_id>`.
**Reader**: user via `lyra pull-run <run_id>` or `lyra list runs`.
**Immutable**: a `<strategy_id>/<date>/` directory, once present, is
**never overwritten**; re-runs produce `<strategy_id>/<date>_2/`,
`<date>_3/`, …
**Contents**:
  - `run_meta.json`: strategy name, timeframe, instrument list, time
    window, feature snapshot id, git commit, date, lyra version.
  - `trades.csv`: per-trade (entry_time, exit_time, direction,
    entry_fill, exit_fill, return, costs, …).
  - `monthly.csv`: per-instrument per-month (instrument, month, trades,
    net_return, win_rate).
  - `report.md`: human-readable summary.

```
oci://<bucket>/lyra/runs/
  trend_hold_v3/
    2026-11-05/
      run_meta.json
      trades.csv
      monthly.csv
      report.md
    2026-11-06/
      run_meta.json
      ...
  ema_pullback_short/
    2026-11-05/
      ...
  README.md
```

### 2.5 `index/` (index, optional)

**Nature**: **closed-source**, pure metadata (no business data).
**Writer**: `lyra rebuild-index` (manual trigger).
**Purpose**: `lyra list strategies` / `lyra list runs` reads
`index/*.json` **once** instead of fetching files individually.
**Files**:
  - `strategies.json`: `[{id, path, timeframe, summary, status,
    last_run, annualized_score}]`
  - `features.json`: `[{name, path, contract, version, created_at}]`
  - `runs.json`: `[{run_id, strategy, date, instruments, annualized_score,
    trades_count}]`

## 3. Boundary rules (hard constraints)

| # | Rule | Consequence of violation |
|---|---|---|
| B1 | git contains **none** of the contents of `alpha/`, any **direction folder** under `strategies/` (`hypothesis.md` / `lessons.md` / `vNN.yaml`), or `runs/` | alpha leak → arbitraged away |
| B2 | `config/config.yml` (with PAR URL) not in git | credential leak |
| B3 | `lyra run` does **not** auto-push (explicit `lyra push-run` required) | accidental alpha push to public bucket |
| B4 | `lyra pull` by default fetches `data/` only, **not** `alpha/` `strategies/` `runs/` | accidental alpha on local disk |
| B5 | `alpha/features/*.py` must carry `contracts/<name>.md` + `tests/test_<name>.py` | semantic drift |
| B6 | Direction folders (including those with `killed` status) and branch files (including `pruned` ones) are not deletable; only the status field in `hypothesis.md` may be updated and the full version tree must be retained | loss of research history |
| B7 | `runs/<strategy>/<date>/` not overwritable (re-runs produce `_2` `_3`) | loss of research history |
| B8 | `index/*.json` is **derived**, rebuildable at any time from `alpha/` `strategies/` `runs/` | consistency |
| B9 | OCI files are **two-tier**: **(a) Immutable** (`data/**`, `runs/**`, `strategies/**/vNN.yaml`, `alpha/features/**`) — same path + same sha256 → idempotent, different sha256 → **reject**; **(b) Append-only** (`strategies/**/hypothesis.md`, `strategies/**/lessons.md`, `index/*.json`) — content may move forward (new content ⊇ old content); `push` validates "new sha256 corresponds to a superset of old content" and rejects otherwise | (a) data drift / broken audit chain; (b) deadlock — direction iteration cannot sync lessons |
| B10 | Credentials (PAR URL / OCI auth) read only from `config.yml` or `~/.lyra/credentials`, **not** from environment variables (avoids shell-history leak) | credential leak |
| B13 | OCI mirrors (`data/` `strategies/` `runs/` **`alpha/`**) resolve to a path **outside the repository** by default (`~/.lyra/<workspace>/…`); if `lyra pull` / `lyra push` targets a path inside the git working tree, it must **warn and require `--inside-repo` to proceed** (anti-footgun; prevents alpha from landing in the git working tree or being accidentally committed) | accidental-commit risk ↑; `git status` noise |
| B14 | `strategies/examples/` (open-source examples) is the **only** strategies subtree tracked by git; at runtime `lyra` must **not** read/write it as alpha | open-source examples treated as alpha, or alpha mixed into examples |
| B11 | Each direction folder must contain `hypothesis.md` + `lessons.md`; missing either blocks push | direction loses its hypothesis or iteration history |
| B12 | vNN.yaml (N≥2) must carry `parent` (crossover branches: `parents`) + `driven_by_lesson` fields pointing to an existing version in the same direction; pruned / killed branch files are retained, never deleted | version tree broken; "why this design" no longer traceable |

## 4. Credential management

**Recommended**: PAR URL (Pre-Authenticated Request), simplest, no SDK
dependency.
  - PAR URL generated in the OCI console with an expiry (recommended 90
    days).
  - PAR URL authorizes **read** only; writes need a separate PAR URL or
    OCI auth.
  - `config.yml` has separate `oci.par_url_read` and `oci.par_url_write`.

**Optional**: OCI SDK (`oci` Python package), for push to avoid signing.
  - `~/.lyra/credentials`: OCI auth file (`[DEFAULT]` section with
    `fingerprint` / `tenancy` / `user` / `key_file` / `region`).
  - **Not** via environment variables (avoids shell-history leak).

## 5. Multi-machine reuse (optional)

**Scenario**: machine A pulls data + computes features; machine B pulls
features directly and runs strategies.
**How**: A runs `lyra push-data` to push `data/features/` back to OCI;
B runs `lyra pull --kind features --minutes 60` to fetch features
directly, skipping clean + aggregate.
**Note**: `data/` is **shareable** (non-alpha); pushing it back to OCI
does not violate B1-B14.

## 6. Open questions

| # | Question | Current lean |
|---|---|---|
| Q1 | snapshot_id: integer or timestamp? | **integer** (monotonic, simple) |
| Q2 | `runs/` grouped by strategy_id or by date? | **by strategy_id** (research perspective) |
| Q3 | `alpha/features/` sub-grouped by family? | **no** (filename = registered name is enough) |
| Q4 | `index/*.json` mirrored into git as read-only? | **no** (alpha boundary) |
| Q5 | PAR URL expires every 90 days — what then? | `lyra-doctor` detects + prompts regeneration |
| Q6 | Support S3 / GCS (future)? | **no** (OCI is the only store for now) |

## 7. Approval

- [ ] User reviews the directory layout
- [ ] User reviews boundary rules B1-B14
- [ ] User reviews the credential management plan
- [ ] User reviews the multi-machine reuse plan
- [ ] AI review (second model)
- [ ] Land decision doc `0001-repo-and-oci-split.md`

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft. |
| 2026-11-05 | 0.2 | §2.3 `strategies/` rewritten: primary unit changed to **direction folders** (hypothesis + lessons + vNN version chain); B11/B12 boundary rules added; comparison with nova's 12 flat YAMLs; explicit "iteration is the primary production process of alpha". |
| 2026-11-05 | 0.3 | §2.3 added an **extendability rules** block: initial 12 are a seed, not a closed list; new-direction admissions bar (testable + not derivable from existing); `_new/` naming; initial and extended directions are fully peer; killed directions are not deleted. Comparison table gains a "Direction set" row. |
| 2026-11-05 | 0.4 | New-direction admissions bar settled as a **soft standard (option A)**: testable independence is a recommendation, not a hard gate; Lyra does not build a direction-equivalence checker. |
| 2026-11-05 | 0.5 | Removed leftover `active/` `archived/` model: top-level tree now shows direction folders; B1 reworded to "git contains no direction-folder contents under `strategies/`"; B6 reworded to "direction folders (incl. killed) are not deletable". |
| 2026-11-05 | 0.6 | Added **B13** (OCI mirrors default to outside the repo at `~/.lyra/<workspace>/…`; landing inside the git working tree requires an explicit `--inside-repo`, preventing alpha from entering the working tree / accidental commit) and **B14** (`strategies/examples/` is the only git-tracked strategies subtree; runtime must not read/write it as alpha). |
| 2026-11-05 | 0.7 | All B-rule references unified to **B1-B14** (multi-machine reuse §5, the 0001 decision doc, AGENTS.md previously still said B1-B10). |
| 2026-11-05 | 0.8 | §2.3 made **AI a first-class writer** + added the **AI efficiency requirement**: context self-contained in the direction folder; `lyra context <direction>` emits a single-file context bundle; AI write loop = read 1 / write 1 / run 1 / log 1, never touching the rest of the repo; hypothesis/lessons/vNN formats stay LLM-friendly. |
| 2026-11-05 | 0.9 | §2.3 upgraded to a **version tree** model (user decision: single-threaded deep search falls into local optima): one parent can spawn 1..N candidate branches (`v02a`/`v02b`), `compare --siblings` side-by-side run summaries, `merge --from <a> --from <b>` crossover (provenance declared in `inherited`), branch lifecycle active→pruned (files retained, never deleted), kill criteria now "all active branches failing N consecutive rounds"; context bundle item 4 changed to a sibling-branch run-summary comparison table; B12 reworded from `supersedes` to `parent`/`parents`. |
| 2026-11-06 | 0.10 | Batch-2 adversarial review fixes: B9 made **two-tier** (Immutable data/runs/vNN/alpha + Append-only hypothesis/lessons/index, new ⊇ old), removing the lessons-iteration push deadlock (L1); B13 adds `alpha/` (L5); §2.3 crossover gains an **I8 boundary** (modification limited to the strategy layer; feature underlying parameters are off-limits, L2). |
