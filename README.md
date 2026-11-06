# Lyra

A lightweight, personal trading-strategy discovery engine for forex, precious
metals, crude oil and equity indices. It is the clean, deliberately small
successor to [Nova](https://github.com/ttrrei/nova) and
[Moneta](https://github.com/ttrrei/moneta).

Lyra runs one universal strategy — identical rules, identical parameters,
identical cost assumptions — across a set of instruments, and reports what
actually happened, trade by trade and instrument by instrument.

## What Lyra is not

- **Not a product.** No multi-tenant, no Web UI, no cloud deployment, no
  SLA. It is a tool for one person, used in spare time, on a small AI
  budget.
- **Not an accounting / compliance / audit system.** No cryptographic
  reproducibility ceremony, no per-run artifact-hash manifests, no frozen
  core guard. Tests pin the semantics of features and the trade engine,
  and run reports show what happened. That is the whole audit story.
- **Not a live-trading broker integration.** It produces trade records and
  per-instrument scores, nothing else.
- **Not an open-source alpha repository.** Alpha — custom features, strategy
  definitions, run results — lives in OCI Object Storage, not in this
  repository. See the [git / OCI split](docs/decisions/0001-repo-and-oci-split.md)
  for the rules.

## Current status

This repository is in the **documentation phase**: the requirements, the
target architecture, the OCI alpha-layout proposal and the decision log are
being written and reviewed. No source code is committed yet.

**The single source of truth for build order is
[hld.md §8](docs/hld.md) (EN: [hld.en.md §8](docs/hld.en.md)).**
Each step = one decision doc (written **before** the code) + one commit +
a test set. In short:

1. **0001 repo + OCI split** — the boundary rule set (done in docs)
2. **0002 OCI pull + clean + aggregate** — the first *code* component:
   data sync is the repo's primary function (R7)
3. **0003 Feature builder** → **0004 YAML compiler** → **0005 Trade
   engine** → **0006 Metrics & runner** — the four validated core
   components, ported semantics-intact from Nova, each on fixture data
   first, then real OCI data
4. **0007 OCI push + backup** — the other half of the core feature
5. **0008 332-strategy migration + regression** → **0009 Polish**

## How it works (target design)

```
OCI (PAR) ──download──► local OHLCV ──aggregate──► 1m / 5m / 60m Parquet
                                                            │
                                                            ▼
                              Registered causal features (fixed params)
                                                            │
                                                            ▼
                              YAML strategy ──► past-only SQL (DuckDB)
                                                            │
                                                            ▼
                              Per-bar trade state machine (2% stop, next-open)
                                                            │
                                                            ▼
                              Per-instrument, per-month score (full calendar)
```

A single strategy file looks like this (illustrative, full grammar defined
in the compiler design doc):

```yaml
version: 1
id: ema_pullback
timeframe_minutes: 60
entry:
  long:
    held_for:
      bars: 3
      condition: {feature: sma_alignment_6_24, op: eq, value: 1}
  short:
    held_for:
      bars: 3
      condition: {feature: sma_alignment_6_24, op: eq, value: -1}
exit:
  feature:
    when: {feature: rsi_14, op: gt, value: 70}
  time_bars: 24
```

Rules that are non-negotiable (see `AGENTS.md`):

- **YAML is the only strategy language.** No SQL, no Python, no eval, no
  callbacks inside strategy files.
- **Feature parameters are fixed.** Parameters are registered per feature.
  New features are added; parameters are not swept.
- **Feature-vs-feature comparison is allowed; feature arithmetic is not.**
- **2% mandatory adverse-price stop** from each actual entry fill. Gap and
  slippage losses may exceed 2% — this is a trigger, not a guarantee of
  final net loss.
- **One trade per instrument.** No pyramiding, no reversal, no same-bar
  re-entry.
- **Signals confirm at close, execute at the next observed open.**
- **Monthly opportunities are actual openings**, including zero-entry
  months. Annualized score = arithmetic sum of net trade returns ÷ full
  calendar years (365.25 days).
- **Per-instrument reporting; never sum returns into a portfolio.**

## Repository layout

```
lyra/
├── README.md                 ← this file (English)
├── LICENSE                   Apache-2.0
├── AGENTS.md                 working contract for AI contributors
├── pyproject.toml
├── requirements.lock
├── config/
│   └── config_example.yml    in git (documented template, no secrets)
├── docs/
│   ├── requirements.md       功能需求
│   ├── background.md         背景：moneta → nova → lyra 的演进
│   ├── hld.md                高层设计决策
│   ├── proposals/            待讨论方案（OCI 布局、alpha 边界、…）
│   ├── decisions/            决策记录（按 feature 逐条推进）
│   │   ├── 0001-repo-and-oci-split.md
│   │   ├── TEMPLATE.md       后续每个功能一个决策文档
│   │   └── 0002-ohlcv-data-sync.md   (placeholder — 待写)
│   │   └── 0003-feature-builder.md   (placeholder — 待写)
│   └── open-questions.md     当前待回答的问题清单
├── src/                      (未开始)
├── tests/                    (未开始)
├── strategies/examples/      (未开始 — 仅开源示例，alpha 全在 OCI)
└── scripts/                  (未开始)
```

## Getting started (when code lands)

Python 3.12+ is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
.venv/bin/python -m pytest -q
```

`lyra-doctor` will verify environment, dependencies, OCI reachability
(when configured) and sample data integrity before a run.

## Configuration

| File | In git? | Purpose |
|---|---|---|
| `config/config_example.yml` | ✅ | Documented shape; no secrets |
| `config/config.yml` | ❌ (gitignored) | Your OCI PAR URL, local paths, alpha feature dir |
| `~/.lyra/credentials` (optional) | ❌ | OCI auth if not using PAR |

OCI credentials and local paths never enter the repository.

## License & alpha boundary

Lyra source code: **Apache-2.0**. This license covers only the code in this
repository. It does **not** cover:

- Custom / alpha feature code (lives in OCI)
- Strategy YAMLs (live in OCI)
- Run results, trade records, analysis (live in OCI)
- Market data (live in OCI)

This split is deliberate and load-bearing: the alpha is the income source,
and it must not be shared with enough people to be arbitraged away ("被均摊").

See [docs/proposals/oci-alpha-layout.md](docs/proposals/oci-alpha-layout.md)
for the proposed OCI directory structure and [docs/decisions/0001-repo-and-oci-split.md](docs/decisions/0001-repo-and-oci-split.md)
for the rule set.

## Lineage

| Project | Status |
|---|---|
| [Moneta](https://github.com/ttrrei/moneta) | Original research rig; 200-strategy campaign; rich pipeline + OOS machinery. Preserved as read-only reference. |
| [Nova](https://github.com/ttrrei/nova) | First "clean room" rebuild (Nov 2026). Validated the 4 core components and 332 in-grammar strategies, but retained too much over-engineering (SHA256 snapshot dirs, FROZEN_CORE, artifact manifests). |
| **Lyra (this repo)** | Second rebuild: keep the validated core, drop the ceremony, add the OCI sync as a first-class feature. |

## Docs

Each doc below ships in two versions: the **Chinese** version (default)
keeps English technical terms inline, and the **English** version
(`*.en.md`) is a full translation.

- [Background: moneta → nova → lyra](docs/background.md) · [EN](docs/background.en.md)
- [Requirements (中文)](docs/requirements.md) · [EN](docs/requirements.en.md)
- [High-level design decisions](docs/hld.md) · [EN](docs/hld.en.md)
- [Decision log](docs/decisions/) · [TEMPLATE](docs/decisions/TEMPLATE.md) · [EN](docs/decisions/TEMPLATE.en.md)
- [Action log (central timeline)](docs/ACTION_LOG.md) · [EN](docs/ACTION_LOG.en.md)
- [Open questions](docs/open-questions.md) · [EN](docs/open-questions.en.md)
- [OCI alpha layout proposal](docs/proposals/oci-alpha-layout.md) · [EN](docs/proposals/oci-alpha-layout.en.md)

## Contributing

Personal project. External contributions are welcome for **bug fixes,
test coverage improvements, and documentation** on the core engine.
Alpha-related code and strategies are closed-source by design and are not
accepted here.
