# 0008 — Corpus Migration + Regression (scope-revised v0.1)

> **中文**: [0008-migration-and-regression.md](./0008-migration-and-regression.md)
>
> Status: **pending → scope-revised draft v0.1 (2026-11-10, per ACTION_LOG #99)**
> The previous scope ("332-strategy migration") is superseded by the erratum, §1.

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

### D table: per-item ruling (pre-filled with recommendations; final user
confirmation required before implementation)

**B-class (10) — same concept, different name; alias table, registered
names unchanged:**

| Corpus name (nova) | Current lyra name | Semantic check |
|---|---|---|
| `breakout_up_24` | `breakout_up` | close > prior24 high, identical |
| `breakout_down_24` | `breakout_down` | close < prior24 low, identical |
| `failed_breakout_up_24` | `failed_breakout_up` | wick swept above prior high, close back inside, identical |
| `failed_breakout_down_24` | `failed_breakout_down` | identical |
| `range_position_24` | `prior24_range_pos` | (close−prior_low)/prior_range, identical |
| `efficiency_24` | `path_eff_24` | \|Δc\|/Σ\|Δc\|, identical (lyra docstring is the nova efficiency contract) |
| `relative_volume_24` | `rel_quote_activity` | volume/SMA(volume,24), identical |
| `range_atr` † | `bar_range_atr` | same formula (h−l)/ATR but **different ATR basis** (†) |
| `range_width_atr_24` † | `prior24_width` | same formula prior_range/ATR, **different ATR basis** (†) |
| `return_6_atr` † | `shift6_atr` | same formula \|c−c₋₆\|/ATR, **different ATR basis** (†) |

† **ATR normalization-basis divergence (known, on record)**: nova uses
**ATR(14)** (and `close_sma24_distance_atr` even uses SMA(TR,14)), lyra
uses **ATR(24)** per K6. The three † rows are therefore **not pointwise
equal** — threshold comparisons (e.g. `range_atr < 1.5`) shift slightly.
This is a "known divergence" in the O-0005-1 class, recorded in the
cross-check, **not** treated as an alias error. If 0010 triage finds a
strategy whose outcome is sensitive to it, we may register ATR-14
variants then (default: no).

B-class mechanism: an **alias table** in `strategy_schema.py` (corpus
name → registered name); the compiler resolves aliases before the
registry lookup. The 134 registered names are **not** renamed (R11: the
17 registered feature names stay unchanged).

**C-class (10) — genuinely new, 0003 v1.5:**

| New feature name | Definition (aligned to nova `features.py` L50-87) | Kind |
|---|---|---|
| `psar_direction` | close > SAR ? +1 : −1 (NaN where SAR invalid); lyra's bullish/bearish are {1,0}×2, domain not equivalent | STATE |
| `supertrend_direction` | supertrend direction ±1 (same, not equivalent to bullish/bearish) | STATE |
| `psar_flip_up` | dir==+1 & dir₋₁==−1 (event boolean, NaN warmup) | EVENT |
| `psar_flip_down` | dir==−1 & dir₋₁==+1 | EVENT |
| `supertrend_flip_up` | flip semantics on the supertrend direction series | EVENT |
| `supertrend_flip_down` | flip semantics | EVENT |
| `ema_alignment_6_24` | sign(ema6−ema24) ∈ {+1,−1,0} | STATE |
| `close_ema60_distance_atr` † | (close−ema60)/ATR(14) (nova L69; † same ATR-basis note as B-class) | VALUE |
| `close_sma24_distance_atr` † | (close−sma24)/SMA(TR,14) (nova L66-68, denominator is SMA of TR, not ATR) | VALUE |
| `rsi_14` | RSI(14) (TA-Lib; K8-grid exception: corpus compat) | VALUE |

**10 new registered features** → `FEATURE_VERSION` 4→5 (I13).
`close_*_distance_atr` are implemented with nova's original denominators
(ATR-14 / SMA(TR,14)) — as C-class new features they have full
implementation freedom and are **not** rebased to lyra's atr_24.

> Note: `rsi_14` is a parameter value outside the K8 grid
> (6/12/24/60/120). Ruling basis: corpus compatibility wins. If the user
> refuses the exception, aliasing `rsi_14 → rsi_12` is not viable
> (different parameter semantics), and the affected strategy YAMLs would
> need rewriting — 0010 triage can mark them drop. **Default: add rsi_14.**

## 3. 12-direction formal library migration

Target layout (0007 H5 naming `^v\d+[a-z]*$` self-consistent):

```
strategies/directions/<family>/v01.yaml   # verbatim copy from nova/strategies/directions/*.yaml
```

Regression gate:
1. `lyra validate` 12/12 pass (after B-class alias + C-class features land)
2. `lyra run` 12 directions × 21 instruments × 1h, auditable reports
   (the R10 acceptance requirement of ≥3 long-only/short-only/long+short
   strategies is satisfied by this step)
3. field-for-field cross-check against nova on the same strategies
   (same method as 0005/0006)

## 4. temp/ gate (outside the regression set)

Skeleton already landed (#99): `strategies/temp/{README.md,
README.en.md, nova_campaign/(_index.json + 146×{strategy.yaml,
meta.json}), moneta_s_series/(_index.json)}`.

0008 only requires:
1. `lyra validate` over all 146 temp/ YAMLs, **recording only**
   pass/fail statistics in the report (not a gate failure);
2. after the alias table + C-class features land, the temp/ failure
   count should drop materially (baseline: currently all fail on
   unregistered features).

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
