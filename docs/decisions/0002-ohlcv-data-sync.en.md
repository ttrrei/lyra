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

> The full three-generation story (moneta → nova → lyra) lives in
> `docs/background.en.md`; this section only cites moneta's data pipeline.

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
lyra pull [--data-root DIR]     # the one user entry: pull + unzip + clean + aggregate
lyra clean   <raw_csv_dir>      # standalone debug entry (reuses pull's internal step)
lyra aggregate <bronze>         # standalone debug entry (reuses pull's internal step)
```

`clean` / `aggregate` are not separate deliverables — they are internal
steps of `lyra pull` (exposed standalone for debugging only); the daily
workflow is a single command: `lyra pull`.

**Re-run semantics (guard against stale derived caches)**: **only the raw
download layer skips on idempotency (I20)**; `clean` and `aggregate`
**always recompute and overwrite their outputs** on every `lyra pull`
(no "output exists → skip") — bronze/5m/1h are all deterministic
functions of the raw data (I18), recomputation costs ≈ one DuckDB scan,
whereas "output exists → skip" would **silently lose data** if bronze
was deleted or corrupted (batch 3, A1).

**New code**:

| File | Responsibility |
|---|---|
| `lyra/config.py` | load the config schema; real values live in **`config/config.yml` (gitignored)**; only `config_example.yml` is in the repo (B10) |
| `lyra/oci_client.py` | PAR object listing (paginated) + object download (streaming, retry, **md5-first / size-fallback** idempotency, path-traversal guard) — mechanism inherited from moneta, idempotency check stronger (moneta used size only, despite listing md5) |
| `lyra/pull.py` | pull + unzip + flatten (equivalent of moneta's `extract_all_zips_to_csv`) |
| `lyra/clean.py` | **equivalent of moneta's `load_data.py` semantics**: ① `is_complete` filter ② dedupe on `(instrument, time)` ③ **deterministic survivor selection** (non-null payload column count desc → source file name → original row order) → bronze 1m Parquet (contract in §3.3) |
| `lyra/aggregate.py` | 1m → 5m/1h (moneta-equivalent, `time_bucket` UTC boundaries, keeps `n_bars`) |
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

- **Input contract** (verified against moneta's real data):
  - OCI holds zip archives containing CSVs;
  - **required columns**: `instrument, time, is_complete`
    (moneta `load_data.py` hard-checks these);
  - **optional columns** (NULL-filled when absent): `volume, mid_o,
    mid_h, mid_l, mid_c, bid_*, ask_*` (real CSVs have 15 columns);
  - `time` is **UTC, 1m granularity**; **non-1m input → rejected with a
    clear error** (aggregation semantics depend on 1m bronze;
    foolproofing);
  - `instrument` naming per moneta `BASE_QUOTE` (O14); the full list is
    enumerated from the data files after the first pull (moneta has 21);
  - **`data_par_url` must be a prefix-level** PAR (not bucket-level), so
    push directories (strategies/features) are never pulled into local
    `data/`.
- **Clean semantics** (equivalent of moneta `load_data.py`;
  determinism is the premise of I18):
  1. `COALESCE(is_complete, FALSE) = TRUE` filter;
  2. dedupe on `(instrument, time)`; duplicates resolved by
     **deterministic survivor selection**: non-null payload column count
     desc → source file name → original row order (moneta's rule; guards
     against `prices_*` backfill overlapping the main CSV on the same key);
  3. write bronze 1m Parquet.
- **Bronze schema (explicit)**: bronze 1m Parquet columns = **the union
  of the input CSV columns**:
  - always present: `instrument, time, volume, mid_o, mid_h, mid_l,
    mid_c`;
  - source-dependent: `bid_*, ask_*` (kept when the moneta sources
    have them);
  - **`is_complete` is NOT carried into bronze** (consumed by clean;
    it would be true for every bronze row, carrying no information).
  This schema is the input contract for 0003 (feature builder).
- **Output contract**:
  - `data/raw_zips/` (raw archives, replay source),
  - `data/raw_csv/` (flat CSVs; **stale top-level CSVs cleared before a
    re-run** (moneta behavior); sub-directories untouched),
  - `data/all_data/all_data.parquet` (bronze 1m),
  - `data/ohlcv_5m/`, `data/ohlcv_1h/` (aggregated, `time_bucket` UTC
    boundaries, `n_bars` truthfully flagging partial bars).
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
| I18 | **Data reproducibility**: same OCI object set (md5 set identical) + same code version → bronze / 5m / 1h Parquet **row-identical in content** (values + row order); file-level byte equality is NOT promised (Parquet bytes vary with arrow versions, and moneta doesn't promise it either). Premises: clean's filter/dedupe/survivor-selection are fully deterministic (§3.3 clean semantics); pull processes objects in name-sorted order (order-independent) | New (R8 made concrete at the data layer) |
| I19 | PAR URLs never enter git, logs, or run reports (redacted to host + first 2 path segments) | I12 (credentials out of git / reports) extended to the data layer |
| I20 | Object downloads idempotent: **skip when md5 matches** (moneta's listing already returns md5); fall back to size when md5 unavailable; same key with different content MUST be re-downloaded | Moneta mechanism + strengthening (download-side guarantee of I11 rebuildability) |
| I21 | Aggregation uses only `time_bucket` UTC boundaries + 1m bars present in the window; `n_bars` truthfully flags partial bars; open/close taken from the window's first/last bar | Moneta `aggregate_ohlcv` (fixed here) |
| I22 | Input must be 1m-granularity UTC; non-1m → rejected (foolproofing; premise of I18) | New |
| I1 | YAML is the only strategy language | HLD §4 (untouched here, trivially holds) |

## 5. Tests

| Test | Scenario |
|---|---|
| `test_oci_list_pagination` | paginated listing: multi-page `nextStartWith` collects all; loop guard |
| `test_oci_download_idempotent_md5` | md5 matches → skipped, no request issued (I20) |
| `test_oci_download_md5_mismatch` | same name + size but different md5 → MUST be re-downloaded (I20 strengthening) |
| `test_oci_unsafe_name_rejected` | `../evil`, absolute paths, `a:/b` object names rejected; legal `EUR..USD.csv` passes |
| `test_pull_zip_to_flat_csv` | nested zips → flat CSVs; collisions `_N`; re-run clears stale top-level CSVs, leaves sub-directories |
| `test_clean_is_complete_filter` | `is_complete` falsy / missing → rows filtered (moneta semantics) |
| `test_clean_dedup_deterministic` | same `(instrument,time)` from multiple sources → unique survivor by "non-null payload count → source file → row order"; two runs identical (I18) |
| `test_clean_non_1m_rejected` | 5m-granularity input → clearly rejected (I22 foolproofing) |
| `test_aggregate_5m_1h_utc` | OHLC across 5m/1h boundaries correct; `n_bars` flags partial bars (I21) |
| `test_aggregate_deterministic` | same input twice → Parquet **row-identical** (I18, not file bytes) |
| `test_clean_bronze_schema` | bronze columns = input union (7 always-present); `is_complete` NOT in bronze (A2) |
| `test_clean_recompute_overwrites` | bronze deleted, re-run `lyra pull` (raw all skipped as idempotent) → bronze still rebuilt (A1) |
| `test_par_expiry_diagnostic` | 403/404 → error includes "PAR may have expired" hint (O5) |
| `test_par_url_redacted_in_logs` | no full PAR URL in logs / exception messages (I19) |

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
| 2026-11-06 | 0.2 | **Self-check + adversarial review (batch 3) fixes**: ① input contract now matches moneta's real column contract (required `instrument,time,is_complete`; mid/bid/ask optional; real CSVs have 15 columns); ② clean semantics completed with moneta `load_data.py`'s three rules (is_complete filter / dedupe on (instrument,time) / deterministic survivor selection), guarding against `prices_*` backfill overlapping the main CSV on the same key; ③ reproducibility invariant corrected from "byte-identical" to **row-identical content** (Parquet file bytes vary with arrow versions; moneta uses the same standard), with its premises defined (deterministic clean + name-sorted pull); ④ download idempotency upgraded to **md5-first / size-fallback** (moneta listed md5 but never used it); ⑤ new foolproofing I22: non-1m granularity input rejected; ⑥ `data_par_url` must be prefix-level; ⑦ CLI clarified (clean/aggregate are debug entries into pull's internal steps); ⑧ invariant numbering corrected to **I18–I22** (0.1 wrongly used I2–I6, colliding with hld §4's taken numbers); ⑨ test list 9→12 (added md5-mismatch re-download, is_complete filter, dedup determinism, non-1m rejection). |
| 2026-11-06 | 0.3 | Batch-3 red team's two real defects landed: **A1 stale derived cache** → settled: only the raw layer is idempotent; clean/aggregate always recompute (otherwise deleting/corrupting bronze silently loses data); **A2 bronze schema undefined** → settled explicitly: bronze columns = input union (7 always-present, bid/ask source-dependent, **no `is_complete`**), as the 0003 input contract; test list 12→14. A3–A5 recorded as accepted boundaries. |
