# Lyra

A lightweight, personal trading-strategy discovery engine for forex, precious
metals, crude oil and equity indices. It is the clean, deliberately small
successor to [Nova](https://github.com/ttrrei/nova) and
[Moneta](https://github.com/ttrrei/moneta).

Lyra runs one universal strategy — identical rules, identical parameters,
identical cost assumptions — across a set of instruments, and reports what
actually happened, trade by trade and instrument by instrument.

## What Lyra is not

- **Not a product.** No multi-tenant, no Web UI, no cloud deployment, no SLA.
- **Not an accounting / compliance / audit system.** No per-account equity,
  CAGR, HWM, Sharpe or margin. Reports show trade-level results.
- **Not a live-trading broker integration.** It produces trade records and
  per-instrument scores, nothing else.
- **Not an open-source alpha repository.** Alpha — custom features, strategy
  definitions, run results — lives in OCI Object Storage, not here. See the
  [git / OCI split](docs/decisions/0001-repo-and-oci-split.md).

## Status

**0001–0009 implemented and verified** (per [hld §8](docs/hld.md)); 0010
(temp/ triage) is next. The single source of truth for build order is
[hld.md §8](docs/hld.md) (EN: [hld.en.md §8](docs/hld.en.md)). Each step =
one decision doc + one commit + a test set.

## How it works

```
OCI (PAR) ──pull──► raw_zips ──clean──► bronze ──aggregate──► ohlcv_5m / ohlcv_1h
                                                                    │
                                                                    ▼
                                   registered causal features (fixed params)
                                                                    │
                                                                    ▼
                                   YAML strategy ──► past-only SQL (DuckDB)
                                                                    │
                                                                    ▼
                                   per-bar trade state machine (2% stop, next-open)
                                                                    │
                                                                    ▼
                                   per-instrument, per-month score (full calendar)
```

A strategy file (illustrative):

```yaml
version: 1
id: ema_pullback
direction: trend_continuation
timeframe_minutes: 60
entry:
  long:
    held_for: {bars: 3, condition: {feature: sma_alignment_6_24, op: eq, value: 1}}
  short:
    held_for: {bars: 3, condition: {feature: sma_alignment_6_24, op: eq, value: -1}}
exit:
  feature: {when: {feature: rsi_12, op: gt, value: 70}}
  time_bars: 24
```

Non-negotiable rules (see `AGENTS.md`):

- **YAML is the only strategy language.** No SQL, no Python, no eval, no callbacks.
- **Feature parameters are fixed** per feature; new features are added, parameters are not swept.
- **Feature-vs-feature comparison is allowed; feature arithmetic is not.**
- **2% mandatory adverse-price stop** from each entry fill (gap/slippage may exceed it).
- **One trade per instrument.** No pyramiding, reversal, or same-bar re-entry.
- **Signals confirm at close, execute at the next observed open.**
- **Monthly opportunities are actual openings**, including zero-entry months.
- **Annualized score = Σ net trade returns ÷ full calendar years (365.25 days).**
- **Per-instrument reporting; never sum returns into a portfolio.**

## Repository layout

```
lyra/
├── README.md                 ← this file
├── AGENTS.md                 working contract for AI contributors
├── pyproject.toml            deps + Python policy (>=3.12,<3.13)
├── requirements.lock         pinned environment (single lock; no requirements.txt)
├── config/
│   └── config_example.yml    in git (documented template, no secrets)
├── docs/
│   ├── requirements.md / hld.md / background.md   (+ .en.md pairs)
│   ├── decisions/            one decision doc per feature (0001–0009, + .en.md)
│   ├── proposals/ / review/ / reviews/ / open-questions.md
│   └── ACTION_LOG.md         central timeline (+ .en.md)
├── lyra/                     runtime package (pull, clean, aggregate, features,
│   │                         compiler, trade_engine, metrics, runner, oci_*,
│   │                         workflow, cli, …)
├── strategies/
│   ├── directions/           12 formal direction families (v01.yaml each)
│   ├── examples/             open-source example strategies
│   └── temp/                 0008 corpus snapshots, read-only (0010 triage target)
├── tests/                    full test suite (pytest)
├── scripts/make_lock.sh      regenerate requirements.lock
└── .github/workflows/ci.yml  py3.12 CI (pyflakes + pytest)
```

## Getting started

Python **3.12** (policy `>=3.12,<3.13`; the lock targets 3.12 — numpy 2.5.4 ships cp312 wheels only).

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.lock      # pinned environment (TA-Lib wheels included)
.venv/bin/pip install -e . --no-deps --no-build-isolation
.venv/bin/pytest -q                             # or: python -m pytest -q
```

Verify your environment with the self-check (hard failures exit 1, data-layer
items are warnings only):

```bash
.venv/bin/lyra doctor --config config/config.yml
```

## CLI command groups

**Data (0002/0003):** `pull`, `clean`, `aggregate`, `catalog`, `oanda`, `features`
**Strategy (0004/0006):** `validate`, `compile`, `run`, `report`
**OCI sync (0007):** `push`, `backup` (=`sync`), `push-strategy`, `push-direction`, `push-runs`, `list`
**Research workflow (0007 R12):** `tracks`, `context`, `new-version`, `compare`, `merge`, `synthesize`
**Meta (0009):** `doctor`, `version`

Run `lyra <command> --help` for options. Data, strategy and run artifacts live
outside the repo under `~/.lyra/<workspace>/…` (B13); alpha and the base market
data live in OCI.

## Configuration

| File | In git? | Purpose |
|---|---|---|
| `config/config_example.yml` | ✅ | Documented shape; no secrets |
| `config/config.yml` | ❌ (gitignored) | Your OCI PAR URLs + OANDA token + local workspace |

**Credential model (M3 ruling):** the ONLY credential path is a signed
Prefix Access (PAR) URL. No OCI SDK, no `~/.lyra/credentials` — a target that
cannot be mounted as a PAR produces an explicit push error rather than a
silent fallback.

## License & alpha boundary

Lyra source code: **Apache-2.0**. This license covers only the code in this
repository. It does **not** cover custom/alpha feature code, strategy YAMLs,
run results, or market data — all of which live in OCI. See
[docs/decisions/0001-repo-and-oci-split.md](docs/decisions/0001-repo-and-oci-split.md).

## Lineage

| Project | Status |
|---|---|
| [Moneta](https://github.com/ttrrei/moneta) | Original research rig; 200-strategy campaign; rich pipeline + OOS machinery. Preserved as read-only reference. |
| [Nova](https://github.com/ttrrei/nova) | First "clean room" rebuild. Validated the 4 core components and a strategy corpus, but retained over-engineering (snapshot dirs, FROZEN_CORE, artifact manifests). |
| **Lyra (this repo)** | Second rebuild: keep the validated core, drop the ceremony, add OCI sync as a first-class feature. |

## Docs

Each doc ships in two versions: the **Chinese** version (default) keeps
English technical terms inline, and the **English** version (`*.en.md`) is a
full translation.

- [Background](docs/background.md) · [EN](docs/background.en.md)
- [Requirements](docs/requirements.md) · [EN](docs/requirements.en.md)
- [High-level design](docs/hld.md) · [EN](docs/hld.en.md)
- [Decision log](docs/decisions/) · [TEMPLATE](docs/decisions/TEMPLATE.md)
- [Action log (timeline)](docs/ACTION_LOG.md) · [EN](docs/ACTION_LOG.en.md)
- [Open questions](docs/open-questions.md) · [EN](docs/open-questions.en.md)

## Contributing

Personal project. External contributions are welcome for **bug fixes, test
coverage, and documentation** on the core engine. Alpha-related code and
strategies are closed-source by design.
