# Lyra working contract

Lyra is the clean, lightweight successor to Nova and Moneta. This contract
takes precedence over any inherited Nova or Moneta proposal. Read
`docs/hld.md` and `docs/requirements.md` before changing scope.

## Where we are (read first)

- **Progress has ONE source of truth: the `## 当前状态 / Current state`
  block at the top of `docs/ACTION_LOG.md`** (kept current with every log
  entry — it is the only mutable section of the log; the entries below it
  are append-only). Do not hard-code progress anywhere else; if a doc
  states "we are at step N", it must say "per ACTION_LOG".
- **Build order has ONE source of truth: `docs/hld.md` §8**
  (0001 repo/OCI split → 0002 pull → 0003 feature builder → 0004 compiler →
  0005 trade engine → 0006 metrics/runner → 0007 push/backup → 0008
  migration → 0009 polish). If README/background say anything else, §8 wins.
- **Core loop (the whole product in one line):**
  OCI ─pull→ local OHLCV ─aggregate→ 1m/5m/60m Parquet ─features→
  DuckDB-queried wide tables ─compile→ YAML→past-only SQL ─run→
  per-instrument trade reports ─push→ OCI.
- **Recent decisions** = last rows of `docs/ACTION_LOG.md`;
  **live questions** = `docs/open-questions.md` (closed rows stay closed —
  re-open by adding a new O-row, never by editing old ones).

## Documentation conventions (load-bearing)

- **Every doc ships as a bilingual pair**: Chinese `.md` (default, English
  terms kept inline) + full English `*.en.md`. `README.md` is the sole
  English-only file.
- **`docs/ACTION_LOG.md` and `docs/ACTION_LOG.en.md` must be updated
  together, in the same change** that changes any doc/rule/decision.
- Decision docs live in `docs/decisions/NNNN-slug.md` (+`.en.md`), are
  written **before** the code, and are append-only.

## Non-negotiables

- **Every working turn must land in `docs/ACTION_LOG.md` + `.en.md`**:
  append a log row AND refresh the `## Current state` block (the file's
  only in-place section). A change without that refresh is incomplete —
  do not finish the turn, do not commit.
- **YAML is the only strategy language.** No SQL, Python, eval, or callbacks
  inside strategy files.
- **Feature parameters are fixed.** New features are registered, not
  re-parameterized. No parameter sweeps.
- **Feature-vs-feature comparison is allowed; feature arithmetic is not.**
- **Mandatory 2% adverse-price stop** from each actual entry fill. Gap and
  slippage losses may exceed 2%. The 2% is a trigger, not a guarantee of
  final net loss.
- **One trade per instrument.** No pyramiding, no reversal, no same-bar
  re-entry.
- **Signals confirm at close, execute at the next observed open.**
- **Monthly opportunities are actual openings**, including zero-entry months.
  Annualized score = arithmetic sum of net trade returns ÷ full calendar
  years (365.25 days/year).
- **Per-instrument reporting.** Never sum returns into a portfolio; no
  CAGR, no HWM, no Sharpe, no sizing, no leverage, no margin, no equity.
- **One strategy = one timeframe.**
- **Strategies are organized by direction** (research family). Each
  direction is a folder with `hypothesis.md` + `lessons.md` + a vNN
  **version tree**; evolution (a version's run + diagnosis spawns
  **multiple** candidate branches; AI compares siblings and judges
  continue / prune / cross) is the core workflow — see
  `docs/requirements.md` §R12. The direction set is **extendable**: the
  initial 12 are a seed, new directions live under `strategies/_new/`
  and are fully peer with them.
- **AI is a first-class writer of strategies**: same commands as the
  user. AI context must be self-contained in the direction folder
  (`lyra context <direction>` → one file, including the sibling-branch
  run-summary comparison); the AI write loop touches exactly one
  context file, one or more new branch YAMLs, one run per branch, and
  one lessons section + one judgment.
- **Past-only SQL.** Compiles to `lag` / current-row-ending windows. No
  `lead`, no forward joins.
- **Warm-up NULLs are retained**, not removed. `held_for` / `within`
  require a full N-row non-NULL window to be true.

## Alpha boundary (load-bearing)

- **Git contains core only**: code, standard features, example strategies,
  tests, docs, `config_example.yml`.
- **OCI contains alpha only**: custom feature code + contracts + tests,
  all strategy YAMLs, all runs, base market data.
- **Never commit alpha paths to git.** CI checks this.
- **OCI mirrors stay outside the repo.** Local `data/` `strategies/`
  `runs/` **`alpha/`** resolve to `~/.lyra/<workspace>/…` by default (B13); writing
  them inside the git working tree requires explicit `--inside-repo`.
  `strategies/examples/` is the only git-tracked strategies subtree and
  is never read/written as alpha at runtime (B14).
- **Never import a specific alpha module from core code.** Core uses the
  generic `lyra.features.load_from(directory)` extension point only.
- **Never put credentials in git or in run reports.** `config.yml` is
  gitignored; PAR URL lives only in `config.yml` or `~/.lyra/credentials`.
- **OCI files are two-tier (B9/I17).** (a) Immutable (`data/`, `runs/`,
  `strategies/**/vNN.yaml`, `alpha/features/`): same path + same SHA256 →
  idempotent; different SHA256 → reject. (b) Append-only
  (`strategies/**/hypothesis.md`, `lessons.md`, `index/*.json`): content
  may move forward (new ⊇ old), else reject.

## Working style

- **Scan `docs/ACTION_LOG.md` before acting — first the `## Current state`
  block (where the project is now), then the last 10 entries** — it is the
  central action log; do not re-decide or overturn settled items.
- **MANDATORY, every working turn, no exceptions:** the change you make
  and its effect on progress must be reflected in **both**
  `docs/ACTION_LOG.md` and `docs/ACTION_LOG.en.md` —
  1. append a new log row (category: decision / doc / review / fix), and
  2. **update the `## 当前状态 / Current state` block at the top of the
     file in the same change** (done / next / awaiting-user rows, plus the
     `更新于 / Updated` stamp).
  A change that touches any file (doc, code, config, strategy, review)
  and does NOT refresh the state block is an **incomplete change** — do
  not finish the turn, and do not commit.
- One feature = one commit = one decision doc (`docs/decisions/NNNN-*.md`)
  = a set of tests. Write the decision doc **before** the code.
- Decision docs are append-only. Never delete a historical decision; add a
  new revision row or a new decision doc that supersedes it.
- Review order for each feature: propose → user review → AI review
  (second model) → implement → tests → 332-strategy regression → OCI
  end-to-end.
- The repo's **primary function** is to stay in sync with OCI. If a change
  doesn't serve that, it probably doesn't belong in this release.
- Keep it light. No distributed infrastructure, no cloud-native, no
  **autonomous / unbounded** strategy generation (bounded AI iteration inside
  an approved direction is in scope — see R12), no live trading, no
  multi-tenant, no Web UI.

## References

Each doc below ships in two versions: the **Chinese** version (default)
keeps English technical terms inline, and the **English** version
(`*.en.md`) is a full translation.

- `docs/background.md` / `docs/background.en.md` — why Lyra exists (moneta → nova → lyra)
- `docs/requirements.md` / `docs/requirements.en.md` — the requirements baseline (R0-R12)
- `docs/hld.md` / `docs/hld.en.md` — high-level design (components, invariants I1-I17)
- `docs/proposals/oci-alpha-layout.md` / `.en.md` — the OCI directory layout + B1-B14
- `docs/decisions/` — per-feature decision log (each doc has a Chinese + English pair)
- `docs/ACTION_LOG.md` / `.en.md` — the central action log (timeline ledger)
- `docs/open-questions.md` / `docs/open-questions.en.md` — live question list
