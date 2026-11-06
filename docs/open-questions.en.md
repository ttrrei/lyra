# Open Questions

> **中文**: [open-questions.md](./open-questions.md)
>
> This document is **live**: each question is either closed by a decision
> doc or escalated into a new decision doc. **Do not make decisions here**
> (decisions go to `docs/decisions/`).

## Currently open

| # | Question | Lean | Status |
|---|---|---|---|
| O1 | snapshot_id: integer or timestamp? | integer | awaiting `0002` decision |
| O2 | `runs/` grouped by strategy_id or by date? | strategy_id | awaiting `0007` decision |
| O3 | alpha features sub-grouped by family? | no (filename = registered name) | awaiting `0003` decision |
| O4 | `index/*.json` mirrored into git as read-only? | no (0001 I15: all of `runs/` + alpha paths never in git; index is derived, rebuildable) | **closed** (0001) |
| O5 | PAR URL expires every 90 days — what then? | `lyra-doctor` detects + prompts | awaiting `0007` decision |
| O6 | Support S3 / GCS? | no | closed (OCI only) |
| O7 | After relaxing feature-vs-feature, how many of the 332 strategies actually use it? | 0 (all are feature-vs-constant) | awaiting `0004` verification |
| O8 | Which sample first for supertrend's contract card + golden test? | supertrend (most complex) | awaiting `0003` decision |
| O9 | How many open-source examples in local `strategies/examples/`? | 3 (trend_hold / ema_pullback / mean_reversion) | awaiting `0009` decision |
| O10 | What does `lyra-doctor` check? | see below | awaiting `0009` decision |
| O11 | Cross-generation crossover: how is the generation number computed? (e.g. v02a × v04b → which generation?) | **Decided (user)**: it is the **next generation after the latest parent**, i.e. `max(parent generations) + 1` (v02a×v04b → gen 5) | **closed** (user 2026-11-06) |
| O12 | Naming collision when the same parent pair is explored twice / different params of the same strategy? | **Decided (user)**: any version name may carry a `_1` `_2` … suffix to distinguish the same strategy's different parameter sets / variants (e.g. `v04ab_1`, `v04ab_2`) | **closed** (user 2026-11-06) |
| O13 | Active Branch Cap per direction? | **Decided (user, 2026-11-06): 8.** Meaning: a cap on **simultaneously-active branches** per direction (prevents the AI from evading kill criteria by forking infinitely); excess must be pruned explicitly. User prefers a high ceiling (8) | **Closed (decision, 2026-11-06)** |
| O14 | Instrument code list and naming convention? | **Decided (user)**: code format **inherited from moneta**'s `BASE_QUOTE` convention (`XAU_USD`/`XAG_USD`/`EUR_USD`/`BTC_USD`, not `GOLD`/`WTI`); moneta has no single 21-instrument list file, so the **authoritative full list is enumerated from moneta's actual data files during 0002 data sync** | **closed** (user 2026-11-06; list enumeration deferred to 0002) |
| O15 | How is `financing_per_day` "elapsed day" defined? | **Decided (user)**: counted strictly by **trading days** — **weekends excluded**, and **market holidays (New Year, Christmas, etc.) excluded** (i.e. elapsed = number of trading days in the holding window, not physical calendar days) | **closed** (user 2026-11-06) |

## O10 candidate list (lyra-doctor checks)

- [ ] Python version ≥ 3.12
- [ ] All dependencies importable (per `requirements.lock`)
- [ ] `config.yml` exists and `oci.par_url_read` is non-empty
- [ ] PAR URL reachable (HEAD request, 5s timeout)
- [ ] PAR URL expiry > 7 days (else prompt regeneration)
- [ ] Local `data/` directory writable
- [ ] git working tree clean (`git status --porcelain` empty)
- [ ] git has no alpha paths (B1)
- [ ] git has no credentials (B2 / I12)
- [ ] core code has no alpha imports (I16)
- [ ] 332 strategy YAMLs all pass `lyra validate` (if locally present)
- [ ] TA-Lib available (`import talib`)
- [ ] DuckDB version inside the lock file

## Closed (historical)

| # | Question | Decision | Decision doc |
|---|---|---|---|
| — | Keep the OOS ledger? | No (R9) | `requirements.md` §R9 |
| — | Keep HWM drawdown? | No (only 2% stop) | `background.md` §5 |
| — | Keep SHA256 directory names? | No (use integer snapshot_id) | `hld.md` §2.1 |
| — | Keep FROZEN_CORE? | No | `hld.md` §1.5 |

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-05 | 0.1 | Initial draft. |
| 2026-11-06 | 0.2 | O4 closed (0001 I15 already bounds index out of git); added **O11-O15**: cross-generation generation-number formula, naming collision, Active Branch Cap, 21-instrument code list, financing day definition (all from the batch-2 adversarial review; pending user decision or later-feature closure). |
| 2026-11-06 | 0.3 | User decisions: **O11** closed (max+1), **O12** closed (`_1`/`_2` suffix), **O13** closed (**Active Branch Cap = 8**), **O14** closed (inherit moneta BASE_QUOTE format; full list enumerated in 0002), **O15** closed (trading days, weekends+holidays excluded); **O11-O15 all closed**. |
