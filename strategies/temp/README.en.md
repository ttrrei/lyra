# temp/ — pending-triage candidate pool (input to 0010 AI triage)

> **中文**: [README.md](./README.md)

This directory holds **historical corpus candidates** awaiting 0010 (AI
triage) classification by direction. **It is not the formal strategy
library, it is outside the 0008 regression gate, and it must not be
executed directly via `lyra run`.**

## Contents

| Subdir | Source | Count | Form | Status |
|---|---|---|---|---|
| `nova_campaign/` | ttrrei/nova `runs/research_campaign/` | 146 | YAML + meta.json | each has a 21-instrument full-history matrix; pass distribution in `_index.json` |
| `moneta_s_series/` | ttrrei/moneta `strategy/` | 132 (read-only refs, code NOT copied) | Python lib | 28 have matrix results (3 instruments vs buy-hold); mostly single-indicator rules |

Not included: the moneta SR-20261031-200 research batch (Cartesian
product of 50 features × 2 entry_model templates, 7 templated
hypotheses, 0 promotions, pure statistical tail cuts — confirmed no
migration value; kept as archive in the moneta repo).

## Rules

1. **Read-only**: strategies in temp/ must not be consumed directly by
   `lyra run` / `lyra compile`; promotion goes through 0010 triage →
   copy into `strategies/directions/<family>/vXX/`.
2. **Outside the 0008 gate**: 0008 regression only covers the formal
   `directions/` library and promoted versions.
3. **meta.json is the sole triage input contract**: `id / family /
   hypothesis / pass_instruments / total_instruments / source_repo /
   source_path / content_sha256_12`.
4. **Verdict is tri-state**: 0010 assigns each entry `promote` / `drop` /
   `archive`; `promote` triggers copy + 0007 track flow; `drop` keeps the
   file but records the verdict; `archive` may be deleted.
5. **New corpus**: any future "to-be-classified" strategy enters temp/
   first; never directly into directions/.

## Source snapshots

- nova campaign: read-only copy from `/home/ubuntu/work/nova`
  (rev `38b0195`) on 2026-11-10 (YAML + generated meta.json).
- moneta S-series: read-only reference to `/home/ubuntu/work/moneta`
  (rev `67896d6`), **code not copied** (alpha and repo-boundary policy).
