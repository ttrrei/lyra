# Action Log (Central)

> **中文**: [ACTION_LOG.md](./ACTION_LOG.md)
>
> **History archive**: the complete record of #1–#133 (2026-11-05 to 2026-11-15) is frozen in [ACTION_LOG.archive.en.md](./ACTION_LOG.archive.en.md) (Chinese: [ACTION_LOG.archive.md](./ACTION_LOG.archive.md)). Old numbers cited by other docs live there; look one up with `grep -n "#113" docs/ACTION_LOG.archive.en.md`.
>
> This file is Lyra's **central action log**: a short timeline that answers only "what was done, why, with what result, and where the detail lives". Detail does not go here: decisions go in `docs/decisions/`, reviews in `docs/review/`, code differences are in git.

## Maintenance rules (decision 0011)

1. **When to log**: only when there is a real change (code / docs / config / strategies), or a decision or review conclusion. Pure discussion, analysis or diagnosis that changes nothing is not logged.
2. **How long**: 2–4 sentences per entry (about 120 words at most): what changed, why, the result, where the detail lives. Technical process, test lists and accept/reject tables go in `docs/decisions/` or `docs/review/`; the log carries only the paths to them.
3. **Append-only**: add new entries as the last row of the entries table below, numbered previous + 1; an overturned entry is not deleted — add a new one that says "overturns #N".
4. **One table, one ledger**: every entry goes in the same table with columns `# | Date | Kind | What | Where`; kind is one of decision / doc / review / fix / code.
5. **Current state**: write only "what state the project is in now", at most 10 rows; when the state changes, **overwrite in place** — no history, no "previous update" row. It is the only place in this file that may be edited in place.
6. **Zh/En in sync**: `ACTION_LOG.md` and `ACTION_LOG.en.md` are updated together in the same change; they must carry the same information, not word-for-word translations.

## Current state

| Item | Value |
|---|---|
| Updated | 2026-11-22 |
| Phase | 0001–0009 closed per HLD §8; the web-AI iteration loop (`submit` / `apply-batch` / `digest` / `context`) is landed and verified (details: archive #123–#133). |
| Code | CI and `python -m pytest -q` are the source of truth (the passed-count varies with optional dependencies); `pyflakes lyra tests` and `alpha-gate` must be clean. |
| In progress | Log governance v1 (decision 0011, #135). |
| Next (optional) | P2 enhancements: feature dictionary, `lesson --kind`, `lyra doctor --no-config`; 0010 temp/ triage; clearing existing mypy/ruff debt; generating the 12 `hypothesis.md` files (a content decision). |
| Awaiting user | ① Whether `git push` has happened is answered by GitHub (the old note `origin/main = 526f2ea` is obsolete). ② When the OCI strategies bucket was listed on 2026-11-22, it held 0 objects under `alpha/` and `tracks/` — if the alpha feature code or track baselines exist only on the old machine, they still need to be recovered and backed up. ③ Whether to do the P2 enhancements. |
| Open questions | O1–O18 are closed or decided; GitHub branch protection is not enabled (ruling #127: local pre-commit + CI after push to main + private repo). |

## Entries (from #134)

| # | Date | Kind | What | Where |
|---|---|---|---|---|
| 134 | 2026-11-22 | fix | `pull-strategy` / `pull-runs` returned 404 on a bucket-level PAR (and wrongly hinted that the PAR had expired). Cause: `_pull_direction` listed at `<par>/<prefix>/`, which a bucket-level PAR treats as a read of an object named `<prefix>/`; `push` always lists the root and was unaffected. Fix: list the PAR root and keep the client-side `<prefix>/<direction>/` filter; download URLs are unchanged. Added `_BucketRootPar` regression tests (2 fail before the change, pass after); full test suite, pyflakes and alpha-gate pass. | `lyra/cli.py` (`_pull_direction`), `tests/test_oci_pull.py` |
| 135 | 2026-11-22 | decision | Log governance v1 (decision 0011): the old log was too large (about 157K chars Chinese / 261K English), #1–#83 and #84–#133 lived in two different tables, and the state block was stale. The old logs are frozen whole as `ACTION_LOG.archive(.en).md` (`git mv`, archive banner only); the new log keeps only the rules, a Current state of at most 10 rows and short entries from #134; AGENTS.md changes "every working turn must be logged" to "only real changes or decision/review conclusions, 2–4 sentences, detail goes to decision / review / commit". No code changed; old numbers are unchanged and findable in the archive. | `docs/decisions/0011-action-log-governance.md`, `docs/ACTION_LOG*.md`, `docs/ACTION_LOG.archive*.md`, `AGENTS.md` |
| 136 | 2026-11-22 | fix | A test overwrote the real data: `tests/test_features.py::test_real_data_one_instrument` ran `run_features(…, 60, instruments=["SPX500_USD"])` directly on `~/.lyra/default/data` whenever it existed, and the publish step deletes every instrument file that was not built in the run — so after `pytest` the 1h feature layer held only SPX500_USD (the 5m layer was unaffected) and `lyra run` evaluated SPX only. Fix: the test now symlinks the real `ohlcv_1h` into a scratch directory before running and asserts the real `features/ohlcv_1h` file list is unchanged; reproduced and verified on synthetic data (1 instrument left before the fix, all 3 intact after). To recover an existing environment: `lyra features --minutes 60`. | `tests/test_features.py` |
| 137 | 2026-11-22 | code | `lyra doctor` gains a "feature-layer instrument coverage" check: for every existing `features/<layer>` it compares the parquet set with the instruments in the matching `ohlcv_<layer>` aggregate and warns on missing or extra ones, pointing to `lyra features --minutes N`. Why: in #136 the layer was cut down to one instrument but its manifest was rewritten to match, so the existing "generation consistent" check could not see it. Warning only, exit code unchanged; 4 new tests, one of which reproduces the #136 incident (it fails without the check). | `lyra/features.py` (`layer_coverage`), `lyra/cli.py` (`doctor`), `tests/test_doctor.py` |
