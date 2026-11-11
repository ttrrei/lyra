# 0008 — Corpus Migration + Regression (regression complete v0.3)

> **中文**: [0008-migration-and-regression.md](./0008-migration-and-regression.md)
>
> Status: **v0.3 regression complete (2026-11-11, three rulings landed + 12-direction × 21-instrument regression + cross-check, per ACTION_LOG #100)**
> The three recommended rulings of v0.1 (alias table / add rsi_14 /
> ATR-basis divergence on record) are **all superseded** by the user's
> final 2026-11-11 rulings (§2); see the revision log in §6.

## 1. Scope erratum (why this doc is rewritten)

Audit of 2026-11-10 (after the user challenged the unfamiliar "332" and we
recounted every repo):

| Old claim | Fact |
|---|---|
| "moneta left 332 strategy YAMLs" | **Wrong.** moneta has no strategy YAMLs; the 132 S-series are Python libraries (28 with matrix results, 3 instruments vs buy-hold); the 200 research batch is a 50-feature × 2-entry_model template Cartesian product with 7 templated hypotheses and **0 promotions** (pure statistical tail cuts, not AI strategy design) |
| "332 strategies verified in-grammar" | Actually the **total YAML file count** in the nova repo: 17 hand-written strategies + 146 campaign experiment snapshots + 169 manifest/protocol/other runs YAMLs |
| True distinct strategy count | ~**162–169** after deduplication by content sha256 (169 is the 0004 convention: 17 + 146 + minor duplicate elimination) |

**New scope (user ruling 2026-11-10, #99)**:

1. Land the O16 20-gap ruling → 0003 v1.5 (§2)
2. Migrate the 12-direction formal library into `strategies/directions/` + regression (§3)
3. `strategies/temp/` gate (§4, **not** part of the regression set)
4. `background.md` erratum (done)
5. AI triage = **0010** (after 0008; new row in HLD §8)

## 2. O16 gap ruling (20 corpus feature names)

Authoritative check: `lyra.features.build_registry()` (134 registered
features) vs every feature name appearing in the 163 real strategy YAMLs
(17 hand-written + 146 campaign; 24 distinct names, 20 unregistered).

### D table: per-item ruling (**user's three final rulings, 2026-11-11**)

**Ruling 1 — B-class (10): no alias table; rename the registrations
(nova names are the single canonical set).** The user ruled: keep ONE
corpus vocabulary, prefer nova's names; when moneta is decommissioned
the mapping goes with it — no alias layer. The 10 old lyra names are
**removed** and the same computations re-registered under the nova
corpus names (semantic check identical to the v0.1 table):

| Old lyra name (removed) | Registered name (nova canonical) |
|---|---|
| `breakout_up` | `breakout_up_24` |
| `breakout_down` | `breakout_down_24` |
| `failed_breakout_up` | `failed_breakout_up_24` |
| `failed_breakout_down` | `failed_breakout_down_24` |
| `prior24_range_pos` | `range_position_24` |
| `path_eff_24` / `path_eff_60` | `efficiency_24` / `efficiency_60` |
| `rel_quote_activity` | `relative_volume_24` |
| `bar_range_atr` | `range_atr` |
| `prior24_width` | `range_width_atr_24` |
| `shift6_atr` | `return_6_atr` |

Mechanism: direct registry rename in `features.py` (no alias layer);
count stays 134 for the renames, +9 new = **143**; `strategy_schema` /
compiler untouched (names resolve straight against the registry);
moneta-side names get **no** mapping (moneta is being decommissioned).

**Ruling 2 — `rsi_14` NOT added; affected strategies rewritten to
`rsi_12` and rerun (TODO).** User: "don't add rsi14; leave a TODO —
rerun mean_reversion with rsi12". `rsi_12` is already grid-registered,
zero cost. Affected nova direction files (TODO — rewrite rsi_14→rsi_12
verbatim during the §3 migration and rerun):
`momentum_exhaustion.yaml` (8 uses), `pullback_reentry.yaml` (4),
`session_temporal.yaml` (2). Note: the root-level hand-written
`nova/strategies/ema_pullback.yaml` (4 rsi_14 uses) is NOT part of the
12-direction set — outside 0008 scope; rewrite to rsi_12 the same way
if kept. The temp/ YAMLs with rsi_14 (24, measured as the validate
failure set) wait for 0010 triage.

**Ruling 3 — ATR normalization basis rebased: ATR(14)→ATR(12) (K6
basis change).** User: "ATR parameter 14 should be substituted by 12;
affected strategies can be rerun". Landed:
- `features.py`: `ATR_NORM 24 → 12` (12 is in-grid; we do not break the
  K8 grid for the corpus' 14);
- the affected K6 features (`range_atr` / `range_width_atr_24` /
  `return_6_atr`) now divide by ATR(12);
- the **C-class `close_ema60_distance_atr` / `close_sma24_distance_atr`
  also use the ATR(12) denominator** (nova's original ATR(14) /
  SMA(TR,14) denominators are deliberately NOT adopted — single-basis
  K6 wins; the v0.1 "known-divergence" note is void);
- nova strategies whose threshold comparisons used ATR(14)-based
  features legitimately shift after the §3 rerun — recorded in the
  cross-check report as **expected**, not a defect.

**C-class (9) — genuinely new, 0003 v1.5:**

| New feature name | Definition (aligned to nova `features.py` L50-87; denominator per Ruling 3) | Kind |
|---|---|---|
| `psar_direction` | close > SAR ? +1 : −1 (NaN while SAR warms up); domain not equivalent to the {1,0}×2 bullish/bearish flags, which **stay** | STATE |
| `supertrend_direction` | supertrend direction ±1 (same) | STATE |
| `psar_flip_up` | dir==+1 & dir₋₁==−1 (event, NaN warmup) | EVENT |
| `psar_flip_down` | dir==−1 & dir₋₁==+1 | EVENT |
| `supertrend_flip_up` | flip semantics on the supertrend direction series | EVENT |
| `supertrend_flip_down` | flip semantics | EVENT |
| `ema_alignment_6_24` | sign(ema6−ema24) ∈ {+1,−1,0} | STATE |
| `close_ema60_distance_atr` | (close−ema60)/ATR(12) | VALUE |
| `close_sma24_distance_atr` | (close−sma24)/ATR(12) | VALUE |

**9 new registered features + 10 renames** → `FEATURE_VERSION` 4→5
(I13). `rsi_14` is **not** in this table (Ruling 2).

## 3. 12-direction formal library migration

Target layout (0007 H5 naming `^v\d+[a-z]*$` self-consistent):

```
strategies/directions/<family>/v01.yaml   # verbatim copy from nova/strategies/directions/*.yaml
```

Regression gate:
1. `lyra validate` 12/12 pass (after B-class renames + C-class features land; rsi_14 files rewritten to rsi_12 per Ruling 2)
2. `lyra run` 12 directions × 21 instruments × 1h, auditable reports
   (the R10 acceptance requirement of ≥3 long-only/short-only/long+short
   strategies is satisfied by this step)
3. field-for-field cross-check against nova on the same strategies
   (same method as 0005/0006)

## 3.1 Regression results (2026-11-11, #100 closeout)

### Gate 1: validate — PASS
12/12 (after the rsi_14→rsi_12 rewrite).

### Gate 2: lyra run, 12 directions × 21 instruments × 1h — PASS
12/12 directions `OK` (runs archived under `~/.lyra/runs/directions_*/20261111/`,
every direction covers all 21 instruments, auditable metrics reports). Note:
feature tables rebuilt for all 21 instruments under the v1.5 registry
(`feat-5-40e9ea7b446f8e13`).

### Gate 3: cross-check against nova — DONE, with a data-layer finding

Method: same strategy (trend_continuation — no rsi/ATR drift terms), USD_JPY,
full history, aligned on entry_time (902 common entries).

| Field | Result | Verdict |
|---|---|---|
| direction (same entry) | **100% match** | signal logic consistent — PASS |
| exit_reason | **100% match** | exit logic consistent — PASS |
| entry_price | 97% match, 3% offset by 1 bar | data-layer finding — see below |
| trade count | nova 1431 vs lyra 1612 | coverage difference |

**Data-layer finding (not an 0008 code issue)**: lyra and nova OHLC are
**bar-for-bar identical where they overlap** (USD_JPY same-window OHLC equal),
but (1) the **bar sets differ**: lyra has 21 bars/day (gaps incl. full
Saturdays, per-instrument variance), nova 24 bars/day (SPX 3 bars in 2 days);
**O18 nailed down and closed (2026-11-11 user ruling, see `0008-bar-coverage-analysis.md`)**: raw 1m byte-identical on both sides (21/21 SHA256); the difference is 100% aggregation-rule-driven (nova drops `source_bars<60` partial hours — 179,550 bars, 97.6% — and the "21 vs 24 bars/day" was a nova local-timezone display artifact; under UTC, lyra ≥ nova everywhere). **User ruling: lyra's bar set is canonical; any nova-side results entering lyra must be recomputed on lyra bars**;
(2) the 3% 1-bar entry_price offset, ~40% bars_held variance and the
per-trade net_return difference are all downstream of the coverage difference
(different warm-up windows → different signal-bar sets). **100% direction and
exit_reason agreement proves the compiler/trade-engine semantics are correct.**

**rsi_12 drift quantified (Ruling-2 TODO closed)**: momentum_exhaustion
USD_JPY full history — lyra(rsi_12) 177 trades net −0.0271 vs nova(rsi_14)
168 trades net −0.0602. Same sign, magnitude consistent with a parameter
rewrite; recorded. (Exact rsi_14 reproduction belongs to 0010's handling of
the 24 rsi_14 temp/ experiments.)

**Conclusion**: 0008 §3 regression gates complete under the revised scope;
all residual cross-check differences trace to the data-layer bar-coverage
difference (O18, **closed 2026-11-11 — lyra's bar set is canonical per user ruling**). 0008 is ready for acceptance.

## 4. temp/ gate (outside the regression set)

Skeleton already landed (#99): `strategies/temp/{README.md,
README.en.md, nova_campaign/(_index.json + 146×{strategy.yaml,
meta.json}), moneta_s_series/(_index.json)}`.

0008 only requires:
1. `lyra validate` over all 146 temp/ YAMLs, **recording only**
   pass/fail statistics in the report (not a gate failure);
2. after the renames + C-class features land, the temp/ failure count
   should drop materially (baseline: currently failing on unregistered
   features; rsi_14 files still fail — Ruling 2, waiting for 0010).

## 5. Out of 0008 scope

- AI triage / promote (**0010**)
- moneta 200 research batch (confirmed no migration value; archive stays in moneta)
- moneta S-series code rewrite (Python libs; 0010 triage only re-expresses
  the few "worth keeping" as YAML — not this feature)
- R10 real-bucket acceptance (held, #98)

## Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-10 | 0.1 | Scope-revised draft: "332" erratum; O16 20 gaps reclassified (**B 10 alias + C 10 new**); ATR normalization-basis (14 vs 24) known-divergence note added; `close_*_distance_atr` pair into C-class; temp/ skeleton referenced; 0010 split out. |
| 2026-11-11 | 0.2 | **User's three final rulings** (supersede the v0.1 pre-filled recommendations): ① B-class 10 **renamed** to the nova canonical names (no alias table; moneta names unmapped); ② `rsi_14` **not added** — the 3 affected direction files (momentum_exhaustion/pullback_reentry/session_temporal) rewritten to rsi_12 and rerun (TODO); ③ ATR normalization basis **24→12** (replacing the corpus' ATR(14); K6 basis change; C-class distance features on the same basis). C-class 10→**9**. Registry 134→**143**; FEATURE_VERSION 4→5. |
| 2026-11-11 | 0.3 | Regression closeout: §3.1 gate 1/2/3 results recorded (validate 12/12; run 12×21 all OK; cross-check: direction/exit_reason 100% match, entry_price 97% match, residue attributed to data-layer bar coverage → O18 parked; rsi_12 drift quantified). |