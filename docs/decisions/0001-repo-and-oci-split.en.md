# 0001 — Repo and OCI Split (Alpha Boundary)

> **中文**: [0001-repo-and-oci-split.md](./0001-repo-and-oci-split.md)

## Meta

| Field | Value |
|---|---|
| ID | `0001` |
| Title | Division of labor between the repo (git) and OCI (Object Storage); the physical landing of the alpha boundary |
| Status | **Implemented (OCI pull/clean/aggregate via 0002 complete)** |
| Owner | `ttrrei` |
| Created | `2026-11-05` |
| Related proposal | `docs/proposals/oci-alpha-layout.md` |
| Related requirements | `docs/requirements.md` §R6, §R7 |
| Related HLD | `docs/hld.md` §1.3, §2.5, §3, §4 (I11-I12) |
| Supersedes | — (inherits the git/OCI split direction from `nova/docs/DECISIONS_2026-11-03.md` §2, and elevates "OCI sync" from "not yet implemented" to "core feature") |

## 1. Problem

Alpha (custom features + strategies + run results) is the source of
passive income and cannot be open-sourced. Core (data pipeline + compiler
+ backtest engine + metrics) should be open-source for reviewability and
contribution. This feature defines the **physical boundary** between
these two categories, and the mechanism that keeps them in sync (OCI
bidirectional sync), so that Lyra's **primary function** is "stay in
sync with OCI".

## 2. Background

- **moneta**: personal repo, no alpha/core separation; OCI was used only
  for pulling data (`extract_oci.py`), not for backing up strategies/runs.
- **nova**: `DECISIONS_2026-11-03.md` §2 already established the
  **direction** of the git/OCI split (git = open-source code, OCI =
  data + alpha), but listed the "OCI sync mechanism" as "not yet
  implemented / next major build item" (§10). Nova has the **direction**
  but not the **mechanism**.
- **Lyra's increment**: elevate "OCI sync" from a todo item to a **core
  feature** (R7), and provide a landable directory layout
  (`oci-alpha-layout.md`) and hard boundary rules (B1-B14).

## 3. Plan

### 3.1 What we do

1. **Physical boundary**: git carries core only (code + standard features
   + open-source examples + tests + docs + `config_example.yml`); alpha
   all lives in OCI (custom features + all strategies + runs + base
   market data).
2. **OCI directory layout**: per `oci-alpha-layout.md` §1-§2
   (`data/` `alpha/` `strategies/` `runs/` `index/`).
3. **Bidirectional sync**: `lyra pull` / `lyra push` / `lyra backup` /
   `lyra list` (implementation detail in decision docs `0002` and `0007`).
4. **Credentials**: `config/config_example.yml` (in git) +
   `config/config.yml` (gitignored) + optional `~/.lyra/credentials`;
   PAR URL preferred.
5. **Boundary rules B1-B14**: written as static checks in `lyra-doctor`
   + one CI check (scan git for alpha paths / credentials).

### 3.2 What we do NOT do

- No OCI versioning / permission management / multi-bucket routing (see
  `oci-alpha-layout.md` §2.5).
- No S3 / GCS adapters (Q6: OCI is the only store).
- No automatic alpha-feature discovery / registration (user explicitly
  passes `--extend-from <dir>`).
- No live trading / broker integration (R9).

### 3.3 Boundaries

- **Input contract**: the `oci.*` section of `config.yml` (see
  `config_example.yml`).
- **Output contract**: local `data/` `strategies/` `runs/` directories
  are OCI mirrors, **resolved outside the repository by default**
  (`~/.lyra/<workspace>/…`, see B13); `strategies/examples/` is the
  git-tracked open-source examples set, not read/written at runtime (B14).
- **OCI boundary**: `pull` reads only `data/` (default); `push` writes
  only `alpha/` `strategies/` `runs/`; **never** writes any alpha file
  into the git working tree.
- **Alpha boundary**: core code loads alpha features via
  `lyra.features.load_from(directory)`, but **never imports** any
  specific alpha module (keeps core independently runnable).
- **Compatibility boundary**: Moneta's 332 strategy YAMLs are alpha
  (in OCI), not core; Lyra core must be able to `validate` / `run` them
  but does not **own** them.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I11 | Local OCI mirrors (`data/` `strategies/` `runs/` **`alpha/`**) are rebuildable and **live outside the repository by default** (B13) | HLD §4 |
| I12 | Credentials never in git / never in run reports | HLD §4 |
| I15 | git contains **no** alpha paths: all of `alpha/`, the contents of any direction folder under `strategies/`, all of `runs/` | new from this feature |
| I16 | Core never imports any specific alpha module (only the generic loading point) | new from this feature |
| I17 | OCI files are **two-tier** (B9): **(a) Immutable** (`data/**`, `runs/**`, `strategies/**/vNN.yaml`, `alpha/features/**`) — same path + same sha256 idempotent, different sha256 → error; **(b) Append-only** (`strategies/**/hypothesis.md`, `lessons.md`, `index/*.json`) — content may move forward (new ⊇ old) | new from this feature |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_git_has_no_alpha_paths` | scan git-tracked files; assert no alpha paths / credentials |
| `test_config_example_has_no_secrets` | assert `config_example.yml` has no real PAR URL |
| `test_core_imports_no_alpha` | assert `src/lyra/*.py` has no `import <alpha_feature>` |
| `test_pull_reads_only_data` | mock OCI; assert `pull` only requests `data/` prefix |
| `test_pull_target_inside_repo_warns` | target path inside the git working tree → refuse unless `--inside-repo` (B13) |
| `test_examples_not_touched_by_runtime` | `lyra run` must not read/write `strategies/examples/` (B14) |
| `test_push_is_idempotent` | same path + same sha256 second push does not re-upload |
| `test_push_rejects_sha_mismatch` | same path + different sha256 → error |
| `test_credentials_not_in_run_meta` | assert `run_meta.json` has no PAR URL / token |

## 6. Rollback

- Code: revert this feature's commit; `oci.py` is a new file, delete it.
- Data: files on OCI are **not deleted** (two-tier, I17); clear local
  `data/` cache.
- Compatibility: after rollback Lyra reverts to "no OCI sync" state,
  equivalent to Nova; the 332 strategies can still be run manually
  (local `strategies/` retained).

## 7. Approval

- [ ] User reviews directory layout (`oci-alpha-layout.md`)
- [ ] User reviews boundary rules B1-B14
- [ ] User reviews credential management plan
- [ ] AI review (second model)
- [ ] Tests all green
- [ ] OCI end-to-end passes once

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft. |
| 2026-11-05 | 0.2 | I15 wording fixed: `strategies/active/` → contents of any direction folder (aligned with the R12 direction model). |
| 2026-11-05 | 0.3 | I11 now includes "OCI mirrors live outside the repository by default" (B13); §3.3 output contract gains B13/B14; §5 test list gains `test_pull_target_inside_repo_warns` and `test_examples_not_touched_by_runtime`. |
| 2026-11-05 | 0.4 | B-rule references unified to **B1-B14** (§2/§3.1/§7 previously still said B1-B10). |
| 2026-11-06 | 0.5 | Batch-2 adversarial review fixes: I17 made **two-tier** (Immutable: data/runs/vNN/alpha; Append-only: hypothesis/lessons/index, new ⊇ old), removing the lessons-iteration push deadlock (L1); I11 adds `alpha/` (L5); §6 rollback "immutable" wording aligned to I17. |
