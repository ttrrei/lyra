# Open Questions

> **中文**: [open-questions.md](./open-questions.md)
>
> This document is **live**: each question is either closed by a decision
> doc or escalated into a new decision doc. **Do not make decisions here**
> (decisions go to `docs/decisions/`).

## Currently open

| # | Question | Lean | Status |
|---|---|---|---|
| O1 | snapshot_id: integer or timestamp? | **settled (0002 v0.5)**: 0002 **drops the directory-level snapshot_id** in favor of **single-file external tables** (`all_data.parquet` / `ohlcv_5m.parquet` / `ohlcv_1h.parquet`) + a DuckDB catalog of named views; data provenance is the **raw-layer OCI object md5** set (I20). The integer-vs-timestamp question is **closed by the mechanism being dropped** (batch-7 D4: ACTION_LOG had claimed O1 closed while this file still said "awaiting 0002" — a doc gap now fixed) | **closed** (`0002` v0.5 + batch-7 D4) |
| O2 | `runs/` grouped by strategy_id or by date? | strategy_id | awaiting `0007` decision |
| O3 | alpha features sub-grouped by family? | no (filename = registered name) | awaiting `0003` decision |
| O4 | `index/*.json` mirrored into git as read-only? | no (0001 I15: all of `runs/` + alpha paths never in git; index is derived, rebuildable) | **closed** (0001) |
| O5 | PAR URL expires every 90 days — what then? | **Settled (0002)**: PARs are user-managed (regenerate on expiry, update `config.yml`); `lyra pull` on 403/404 emits a "PAR may have expired" diagnostic; `lyra-doctor` (0009) checks PAR availability in its routine health check | **closed** (`0002` §2) |
| O6 | Support S3 / GCS? | no | closed (OCI only) |
| O7 | After relaxing feature-vs-feature, how many of the 332 strategies actually use it? | 0 (all are feature-vs-constant) | awaiting `0004` verification |
| O8 | Which sample first for supertrend's contract card + golden test? | supertrend (most complex) | awaiting `0003` decision |
| O9 | How many open-source examples in local `strategies/examples/`? | 3 (trend_hold / ema_pullback / mean_reversion) | awaiting `0009` decision |
| O10 | What does `lyra-doctor` check? | see below | awaiting `0009` decision |
| O11 | Cross-generation crossover: how is the generation number computed? (e.g. v02a × v04b → which generation?) | **Decided (user)**: it is the **next generation after the latest parent**, i.e. `max(parent generations) + 1` (v02a×v04b → gen 5) | **closed** (user 2026-11-06) |
| O12 | Naming collision when the same parent pair is explored twice / different params of the same strategy? | **Decided (user)**: any version name may carry a `_1` `_2` … suffix to distinguish the same strategy's different parameter sets / variants (e.g. `v04ab_1`, `v04ab_2`) | **closed** (user 2026-11-06) |
| O13 | Active Branch Cap? | **Decided (user, 2026-11-06): global 8 per direction** (prevents the AI from evading kill criteria by forking infinitely; excess must be pruned explicitly). **Amended by the user on 2026-11-08: the cap is per track — 8 active branches per track, with no slot competition across tracks** ("mutual non-interference" takes precedence; supersedes the 11-06 direction-level global semantics). Landing points: requirements R12 (v0.16), oci-alpha-layout §2.3, consolidated proposal §9 | **Closed (decided 2026-11-06; semantics amended 2026-11-08 — final)** |
| O14 | Instrument code list and naming convention? | **Decided (user)**: code format **inherited from moneta**'s `BASE_QUOTE` convention (`XAU_USD`/`XAG_USD`/`EUR_USD`/`BTC_USD`, not `GOLD`/`WTI`); moneta has no single 21-instrument list file, so the **authoritative full list is enumerated from moneta's actual data files during 0002 data sync** | **closed** (user 2026-11-06; list enumeration deferred to 0002) |
| O15 | How is `financing_per_day` "elapsed day" defined? | **Decided (user)**: counted strictly by **trading days** — **weekends excluded**, and **market holidays (New Year, Christmas, etc.) excluded** (i.e. elapsed = number of trading days in the holding window, not physical calendar days) | **closed** (user 2026-11-06) |
| O16 | Of the features referenced by the 332 legacy strategies, **20 are not in lyra's 0003 registry** (326/332 reference at least one missing feature). Extend 0003? | **Verified during 0004 implementation (2026-11-08)**: lyra's registry has only 134 features; the 332 strategies reference 24 distinct features — **4 match** (`sma_alignment_6_24`/`sma_cross_up_6_24`/`sma_cross_down_6_24`/`utc_hour`), **20 missing** (below). Missing items fall into three classes: (A) **param gap**, 1 — `rsi_14` (lyra has `rsi_{6,12,24,60,120}` but not 14); (B) **naming drift**, 8 — nova's `psar_direction/psar_flip_{up,down}` vs lyra `psar_bullish/bearish`, `supertrend_direction/supertrend_flip_{up,down}` vs lyra `supertrend_bullish/bearish`, `breakout_{up,down}_24` vs lyra `breakout_{up,down}`, `failed_breakout_{up,down}_24` vs lyra `failed_breakout_{up,down}`; (C) **truly missing**, 11 — `range_position_24`(888), `close_sma24_distance_atr`(316), `efficiency_24`(300), `ema_alignment_6_24`(194), `close_ema60_distance_atr`(182), `range_atr`(146, lyra has `bar_range_atr`), `relative_volume_24`(106), `return_6_atr`(60), `range_width_atr_24`(28) etc. | **awaiting user decision** (P0 blocker for the 0008 332-regression gate; see below) |
| O17 | Should 0005 financing elapsed time use calendar days or trading days? | **Default basis locked by 0006 + batch-4 C2 contract refactor (2026-11-09, user delegated to me to rule per my recommendation and record it)**: **default = per-trade calendar days** — deterministic, data-only (no external trading calendar), preserves the 0005 nova cross-check (diff=0), and fits the user's "lightweight / not over-engineered" stance; **batch-4 C2**: the O15 (trading-day basis) compliant escape hatch was refactored from the old flat `trading_days=<n>` + `--financing-days` (which mischarged every trade the same day count — removed in #88) into a **per-trade** counter `simulate(plan, bars, trading_days_for=counter)` (`counter(entry, exit) -> float`), so 0006 can wire a real trading calendar to count R4/O15 trading days per trade. "Real trading-calendar integration (per-trade counting excluding weekends/holidays)" remains a **future enhancement** (not a 0006 defect; engine-side support is in place). O15 remains closed (user ruling 11-06); its ruling is not rewritten here. | **Closed (0006 locks the default basis + #88 C2 contract in place, 2026-11-09)** |

## O16 detail: the 332-strategy feature gap (verified 2026-11-08)

**Context**: `requirements.md` R10/R11 acceptance is "all 332 legacy strategies pass `lyra validate`".
During 0004 compiler implementation + self-check (2026-11-08), a per-feature cross-check against
lyra's registry found: **326 of the 332 strategies reference at least one feature not in lyra's
0003 registry**. This is **not a 0004 compiler bug** — the compiler correctly fails closed on
unknown features (unknown feature ⇒ error); the gap is in 0003's feature coverage.

**Method**: grepped all `feature:` references across nova's read-only dirs (`runs/research_campaign`
293, `strategies/directions` 12, `runs/directions` 12, `strategies` 7) and cross-referenced against
`build_registry()` (134 features). 24 distinct features: 4 match, 20 missing. Missing items by
reference count (count = number of expressions in nova referencing the feature):

| # | missing feature | refs | class | lyra candidate |
|---|---|---|---|---|
| 1 | `range_position_24` | 888 | C truly missing | — |
| 2 | `close_sma24_distance_atr` | 316 | C truly missing | — |
| 3 | `efficiency_24` | 300 | C truly missing | — |
| 4 | `rsi_14` | 210 | **A param gap** | `rsi_{6,12,24,60,120}`, no 14 |
| 5 | `ema_alignment_6_24` | 194 | C truly missing | (lyra has `sma_alignment_6_24`) |
| 6 | `close_ema60_distance_atr` | 182 | C truly missing | — |
| 7 | `range_atr` | 146 | C truly missing | `bar_range_atr` (semantics to confirm) |
| 8 | `supertrend_direction` | 112 | **B naming drift** | `supertrend_bullish/bearish` |
| 9 | `relative_volume_24` | 106 | C truly missing | — |
| 10 | `breakout_up_24` | 91 | **B naming drift** | `breakout_up` |
| 11 | `breakout_down_24` | 91 | **B naming drift** | `breakout_down` |
| 12 | `psar_direction` | 86 | **B naming drift** | `psar_bullish/bearish` |
| 13 | `psar_flip_up` | 78 | **B naming drift** | — (no flip event in lyra) |
| 14 | `psar_flip_down` | 78 | **B naming drift** | — (no flip event in lyra) |
| 15 | `return_6_atr` | 60 | C truly missing | — |
| 16 | `failed_breakout_up_24` | 39 | **B naming drift** | `failed_breakout_up` |
| 17 | `failed_breakout_down_24` | 39 | **B naming drift** | `failed_breakout_down` |
| 18 | `utc_hour` | 36 | match | `utc_hour` |
| 19 | `range_width_atr_24` | 28 | C truly missing | — |
| 20 | `supertrend_flip_up` | 2 | **B naming drift** | — (no flip event in lyra) |
| — | `supertrend_flip_down` | 2 | **B naming drift** | — (no flip event in lyra) |

**Disposal options per class** (awaiting user decision):

- **B naming drift (8)**: mostly semantically corresponding, but `psar_flip_*` /
  `supertrend_flip_*` (the "flip on this bar" event) have no corresponding EVENT feature in lyra —
  either add flip-event features in 0003, or rewrite nova's flip usage into an equivalent
  within/after_event combination (may change semantics; needs per-case review).
- **A param gap (1: `rsi_14`)**: resolved by adding `rsi_14` to 0003 (add 14 to the param grid).
- **C truly missing (11)**: must be added to 0003 (`range_position_24`, `efficiency_24`,
  `ema_alignment_6_24`, `*_distance_atr`, `relative_volume_24`, `return_6_atr`, `range_width_atr_24`, …),
  each with a contract card + golden test (0003 convention).

**Impact**:
- **Blocks the 0008 332-regression gate** (R10/R11 require all 332 to pass `lyra validate`).
- **Does not block the 0004 compiler itself**: the compiler is fully usable for "strategies written
  with registered features" (`lyra validate` / `lyra compile` are in place; 26+ tests pass, incl.
  live DuckDB temporal assertions).
- lyra's tracked example `momentum_breakout/v01.yaml` also references 3 missing features
  (`range_high_12`/`range_low_12`/`range_position_24`), so `lyra validate` fails closed on it today.
  A new `strategies/examples/rsi_pullback/v01.yaml` (registered features only) now serves as the
  validatable example.

**Suggested path (awaiting user confirmation, not yet executed)**:
1. First settle 0003 v1.5: dispose of B (naming mapping / new flip events) → A (`rsi_14`) → C (11 new features).
2. Each added feature follows the existing 0003 flow (contract card + golden test + `FEATURE_VERSION` bump).
3. Only then does the 0008 332-regression gate make sense.

**User decision needed**:
- [ ] Class B: add flip-event features vs rewrite into within/after_event (may change semantics)?
- [ ] Class C: should all 11 truly-missing features enter 0003 v1.5? priority?
- [ ] Is `range_atr` semantically equivalent to lyra's `bar_range_atr` (needs nova definition check)?

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
| 2026-11-06 | 0.4 | **O5 closed** (settled in `0002` §2: user-managed PARs + `lyra pull` expiry diagnostic + 0009 doctor health check). **O1–O5 and O11–O15 are now all closed; no open questions remain.** |
| 2026-11-08 | 0.6 | **O13 semantics amended (user ruling 2026-11-08)**: the Active Branch Cap changes from "global 8 per direction" to "**8 active branches per track, with no slot competition across tracks**" (multiple AIs are mutually non-interfering; the original intent of preventing infinite forking within one track still holds). O13 is final; the 11-06 decision is retained as history. Landing points: requirements R12 v0.16, oci-alpha-layout §2.3, consolidated proposal §9. |
| 2026-11-06 | 0.5 | **O1 formally closed here** (batch-7 D4): 0002 v0.5 already dropped the directory-level snapshot_id (single-file external tables + raw md5 provenance), but this file still read "awaiting 0002", contradicting ACTION_LOG's "O1 closed" — the ruling is now recorded here, closing the gap. O2/O3 still await 0007 / 0003 respectively. |
| 2026-11-08 | 0.7 | Verified **O16** during 0004 compiler implementation + self-check: 326 of the 332 legacy strategies reference at least one feature not in lyra's 0003 registry (24 distinct features — 4 match / 20 missing, split into A param-gap / B naming-drift / C truly-missing). O16 awaits a user decision and blocks the 0008 332-regression gate; it does **not** block the 0004 compiler itself (already in place; validates/compiles registered-feature strategies). |
| 2026-11-08 | 0.8 | Added **O17**: promoted 0005 O-0005-1 (nova calendar days conflict with R4/O15 trading days) into the central open-question list; preserved closed O15 and parked the ruling before 0006 locks financing cost/report semantics. |
| 2026-11-09 | 0.9 | **O17 closed (0006 locks the basis, user delegated to me to rule per my recommendation and record it)**: default = per-trade calendar days (deterministic / data-only / preserves nova cross-check diff=0 / fits the lightweight stance); `simulate(trading_days=<n>)` + `--financing-days` provide a flat trading-day override as the O15 compliant escape hatch; real trading-calendar per-trade counting is a future enhancement (not a defect). O15 remains closed, unchanged. |
| 2026-11-09 | 1.0 | **O17 contract refinement (batch-4 C2, #88 disposition)**: the O15 trading-day compliant escape hatch was refactored from the old flat `trading_days=<n>` / `--financing-days` (which mischarged every trade the same day count — removed) into a **per-trade** counter `trading_days_for(entry, exit)` — the natural-day default (nova cross-check basis) is unchanged; 0006 can wire a real trading calendar here to count R4/O15 trading days per trade; "real trading-calendar per-trade counting" remains a future enhancement (engine-side support is in place). O15/O17 rulings unchanged; only the contract API was updated. |
