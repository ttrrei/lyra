# 0002 — OHLCV data sync (OCI pull + landing + aggregation)

> **Chinese**: [0002-ohlcv-data-sync.md](./0002-ohlcv-data-sync.md)

## Metadata

| Field | Value |
|---|---|
| ID | `0002` |
| Title | OHLCV data sync (OCI pull + landing + aggregation) |
| Status | **Proposed** (awaiting user approval) |
| Owner | `ttrrei` |
| Created | `2026-11-06` |
| Related proposal | — |
| Related requirements | `docs/requirements.en.md` R1 / R2 / R4 |
| Related HLD | `docs/hld.en.md` §8 (build order, step 2) |
| Supersedes | — |

## 1. Problem

Lyra needs a **deterministic raw-data entry point**: pull OHLCV raw data
from OCI, land it as reproducible local Parquet, and feed 0003 (feature
builder). Per the user's request, this feature also **reserves PAR slots in
the config yml for future push of strategies / custom features** (consumed
by 0007; 0002 only reserves, never uses them).

## 2. Background

- **How moneta does it** (`pipeline/extract_oci.py`, production-proven):
  1. reads `oci.par_url` from `config/setting.yml` (a **PAR prefix URL**);
  2. lists objects with
     `GET <par_url>/?fields=name,size,md5,timeModified&limit=1000`,
     paginating via `nextStartWith` until exhausted;
  3. for each object builds the object URL via `urljoin(base, name)` and
     streams a `GET` into `data/raw_zips/`; **size-based idempotency**
     (local exists with same size → skip);
  4. extracts all CSVs from all zips into a **flat** `data/raw_csv/`
     (collisions get `_N` suffix; re-runs clear stale top-level CSVs first);
     object names get **path-traversal protection** (judged on path
     *components*, so a legal name like `EUR..USD.csv` is not rejected);
  5. HTTP layer has retry/backoff (429/5xx; only idempotent GETs retried).
  6. Downstream `aggregate_ohlcv.py`: 1m bronze Parquet (UTC,
     `instrument,time,mid_o,mid_h,mid_l,mid_c,volume`) bucketed on UTC
     boundaries into 5m/1h, with `n_bars` flagging partial bars.
- **Why not OCI signing (oracledb signer)**: moneta already proves a
  **PAR prefix URL is sufficient** — zero SDK credentials, zero region
  config, the download side needs only `requests`; credential management
  stays user-side (`config.yml`, gitignored). Signing would drag
  `tenancy/region/key` into the local environment, buying only "push
  without PAR" — and the push side (0007) needs its own write-permission
  model anyway (B9 two-tier). **Decision: pull uses PAR (moneta's proven
  mechanism); the push-side access method is deferred to 0007** — but the
  yml reserves PAR slots for push now (see §3.1).
- **O5 (PAR 90-day expiry) is settled by this feature**: PARs are managed
  user-side (regenerate on expiry, update `config.yml`); on `lyra pull`
  failure we emit an **explicit expiry diagnostic** (403/404 + "PAR may
  have expired" hint); `lyra-doctor` (0009) checks PAR availability in its
  routine health check.

## 3. Design

### 3.1 In scope

**CLI** (the `lyra/` package is created with this feature):

```
lyra pull [--data-root DIR]     # pull raw OHLCV (zip/CSV) → local data/
lyra clean  (internal step)     # schema validation → bronze 1m Parquet
lyra aggregate (internal step)  # 1m → 5m / 1h (UTC boundaries, n_bars)
```

**New code**:

| File | Responsibility |
|---|---|
| `lyra/config.py` | load the `config/config_example.yml` schema (real values in local `config.yml`) |
| `lyra/oci_client.py` | PAR object listing (paginated) + object download (streaming, retry, size idempotency, path-traversal guard) — mechanism inherited from moneta |
| `lyra/pull.py` | pull + unzip + flatten (equivalent of moneta's `extract_all_zips_to_csv`) |
| `lyra/clean.py` | schema validation → bronze 1m Parquet (column contract in §3.3) |
| `lyra/aggregate.py` | 1m → 5m/1h (moneta-equivalent, keeps `n_bars`) |
| `lyra/cli.py` | typer entry point (the `lyra` command) |
| `tests/` | all cases from §5 |

**Config reservation (user request)** — the `oci:` section of
`config/config_example.yml` now carries 3 PAR slots:

```yaml
oci:
  # ---- pull (used by this feature) ----
  data_par_url: "https://<ns>.compatibility.<region>.oraclecloud.com/<bucket>/<prefix>/"
  # ---- push (used by 0007; reserved only, never read by this feature) ----
  strategies_par_url: "https://.../strategies-upload/"   # strategy YAML + lessons
  features_par_url:     "https://.../features-upload/"   # custom features + contract cards
```

### 3.2 Out of scope

- **No push / backup** (0007) — the PAR slots exist only in the yml and
  the config model; this feature's code never reads or validates them.
- **No feature builder / compiler / trade engine** (0003-0005).
- **No OOS machinery / no data mutation** — pull is read-only download +
  local derivation.
- **No OCI signer** (within this feature) — re-evaluated at 0007.

### 3.3 Boundaries

- **Input contract**: OCI holds zip archives containing CSVs (same
  structure as moneta: `instrument,time,mid_o,mid_h,mid_l,mid_c,volume`,
  UTC time, 1m granularity, instrument naming per moneta `BASE_QUOTE`
  (O14)).
- **Output contract**:
  - `data/raw_zips/` (raw archives, replay source),
  - `data/raw_csv/` (flat CSVs),
  - `data/all_data/all_data.parquet` (bronze 1m),
  - `data/ohlcv_5m/`, `data/ohlcv_1h/` (aggregated, with `n_bars`).
  All under `~/.lyra/<workspace>/` or `--data-root` (B13), **never in
  git** (B1).
- **Credential boundary**: PAR URLs appear only in `config.yml`
  (gitignored); logs / reports / run summaries **never print a full PAR
  URL** (redacted to host + first 2 path segments).
- **Alpha boundary**: this feature does not touch `alpha/`, strategies,
  or `strategies/examples/`.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I? | Same PAR content + same code version → byte-identical local Parquet (pull/clean/aggregate fully deterministic; no randomness, no clock written into data) | New (R8 made concrete at the data layer) |
| I? | PAR URLs never enter git, logs, or run reports (redacted to host + first 2 path segments) | Extension of 0001 credential boundary |
| I? | Object downloads are idempotent (same size → skip); re-runs never alter existing local files | Moneta-proven mechanism |
| I? | Aggregation uses UTC boundaries + only 1m bars present in the window; `n_bars` truthfully flags partial bars | Moneta `aggregate_ohlcv` |
| I1 | YAML is the only strategy language | HLD §4 (untouched here, trivially holds) |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_oci_list_pagination` | paginated listing: multi-page `nextStartWith` collects all; loop guard |
| `test_oci_download_idempotent` | exists with same size → skipped, no request issued |
| `test_oci_unsafe_name_rejected` | `../evil`, absolute paths, `a:/b` object names rejected; legal `EUR..USD.csv` passes |
| `test_pull_zip_to_flat_csv` | nested zips → flat CSVs; collisions `_N`; re-run clears stale |
| `test_clean_schema_validation` | missing columns / wrong types → clear error; clean pass → bronze Parquet |
| `test_aggregate_5m_1h_utc` | OHLC across 5m/1h boundaries correct; `n_bars` flags partial bars |
| `test_aggregate_deterministic` | same input twice → byte-identical Parquet |
| `test_par_expiry_diagnostic` | 403/404 → error includes "PAR may have expired" hint (O5) |
| `test_par_url_redacted_in_logs` | no full PAR URL in logs / exception messages |

## 6. Rollback

- **Code**: revert this feature's commit (`lyra/` modules are new and
  isolated; 0001's docs and scaffold untouched).
- **Data**: local `data/` is derived — just delete it; **zero write
  operations on OCI**, nothing to roll back remotely.
- **Compatibility**: moneta / nova unaffected (this feature only reads
  OCI; it borrows the mechanism but implements independently, importing
  nothing from moneta/nova).

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Tests green
- [ ] 332-strategy regression (n/a — this feature doesn't touch strategies)
- [ ] OCI end-to-end run (**requires the user's real PAR URL**)

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-06 | 0.1 | First draft. Settled: pull uses PAR prefix URL (moneta's proven mechanism); O5 settled (user-managed PARs + expiry diagnostic + 0009 doctor health check); yml reserves three PAR slots: pull / strategies / features (push belongs to 0007). |
