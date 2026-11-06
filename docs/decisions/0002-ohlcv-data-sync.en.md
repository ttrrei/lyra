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
  - `instrument` naming per moneta `BASE_QUOTE` (O14); **the full list
    (O14 deliverable, verified on the batch-5/6 real data — 21
    instruments)**:

    | # | instrument | # | instrument |
    |---|---|---|---|
    | 1 | AUD_USD | 12 | NZD_USD |
    | 2 | BCO_USD | 13 | SPX500_USD |
    | 3 | BTC_USD | 14 | UK100_GBP |
    | 4 | CN50_USD | 15 | US30_USD |
    | 5 | DE30_EUR | 16 | USD_CAD |
    | 6 | ETH_USD | 17 | USD_CHF |
    | 7 | EUR_USD | 18 | USD_JPY |
    | 8 | GBP_USD | 19 | WTICO_USD |
    | 9 | HK33_HKD | 20 | XAG_USD |
    | 10 | JP225_USD | 21 | XAU_USD |
    | 11 | NAS100_USD | | |

    **The authoritative source is the data itself**
    (`SELECT DISTINCT instrument FROM bronze`, or
    `Catalog.instruments()`); this table is a 2026-11-06 enumeration
    snapshot of the real moneta data, provided for 0003's tests and
    validation cards. The list is **extensible** (a new instrument appearing
    in the data takes effect without code changes — the whole 0002 pipeline
    generalizes on the `instrument` column and never hard-codes the list).
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
    boundaries, `n_bars` truthfully flagging partial bars),
  - `data/catalog.duckdb` (a **DuckDB metadata / external-table catalog**,
    274 KB of pure schema): holds three VIEWS — `bronze` / `ohlcv_5m` /
    `ohlcv_1h` — each pointing at the corresponding Parquet file. **The data
    still lives in Parquet (I18 single source of truth)**; the catalog is only
    the **named entry point** — 0003/0005 just `SELECT ... FROM bronze` with
    no path to remember and no re-glob. Rebuildable
    (`lyra catalog --refresh`, idempotent `CREATE OR REPLACE VIEW`), and
    **not an asset to back up** (0007 push targets the Parquet, not the
    catalog). **Never in git** (B13, outside the repo).
  All under `~/.lyra/<workspace>/` or `--data-root` (B13), **never in
  git** (B1).
- **Efficient read / write contract (DuckDB)**:
  - **Read**: clean / aggregate / catalog all read Parquet through
    **DuckDB external tables / VIEWS** (streaming), **never materializing the
    full table into memory** (batch-6 A2/A3);
  - **Write**: clean streams to disk via `COPY`; aggregate streams via
    `COPY (… ORDER BY …)` with stable row order (I18);
  - **Honest boundary (batch-6 A6)**: aggregate's `time_bucket + ARRAY_AGG +
    GROUP BY` grouping working set peaks ≈**10 GB** at 48M rows (inherent to
    DuckDB hash aggregation, not a streaming bug and not a leak).
    "Streaming" means the bronze reads and the clean `COPY` don't materialize
    the full table; **the grouping working set is not free** — 0003 must plan
    memory accordingly when designing a larger feature surface.
- **Credential boundary**: PAR URLs appear only in `config.yml`
  (gitignored); logs / reports / run summaries **never print a full PAR
  URL** (redacted to host + first 2 path segments).
- **Alpha boundary**: this feature does not touch `alpha/`, strategies,
  or `strategies/examples/`.

### 3.4 Data-quality validation (DQ1–DQ3, fail-fast)

**Motivation**: moneta's `load_data.py` only filters on `is_complete` and
dedupes — it does **not** validate OHLC internal consistency / spread
direction / non-negative volume, so dirty rows (`bid > ask`, `l > h`,
negative volume) silently flow into bronze and contaminate every 0003
feature and 0005 backtest. nova's `data._validate` has these checks; lyra
makes that stage of the moneta→nova→lyra chain **explicit**.

**Timing**: clean runs this **after** the `is_complete` filter +
`(instrument,time)` dedup and **before** the `COPY` writes bronze (it
validates the survivor candidates, so rows dropped by dedup cannot
false-positive). **Fail-fast**: any violation → raise
`DataQualityError` (naming each offender with its count); bronze is not
written.

**Invariants** (each = a WHERE expression matching a *violating* row; NULL
comparisons naturally exclude partial rows):

| # | Invariant | Expression (matches a violation; all NULL-safe) |
|---|---|---|
| DQ1 | mid OHLC positive, finite, internally consistent (o,c ∈ [l,h]) | per-column `IS NOT NULL AND (x<=0 OR NOT isfinite(x))` OR-combined, plus the o/c vs l/h bound checks |
| DQ2 | per-point `ask_p >= bid_p` (enforced where both columns exist), **plus** bar-wide `ask_h >= bid_l` when both exist | `bid_p IS NOT NULL AND ask_p IS NOT NULL AND ask_p < bid_p`; bar-wide: `ask_h IS NOT NULL AND bid_l IS NOT NULL AND ask_h < bid_l` |
| DQ3 | volume, if present, finite and non-negative | `volume IS NOT NULL AND (volume < 0 OR NOT isfinite(volume))` |

**Column-aware (per-point + bar-wide)**: DQ2 is judged **per point** — at any
point p where both `bid_p` and `ask_p` columns exist, `ask_p >= bid_p` is
enforced; a point with only one side (or neither) is skipped (referencing an
absent column under `union_by_name` is a binder error). **The only universal
cross-point inference is bar-high ask ≥ bar-low bid (`ask_h >= bid_l`)** —
enforced additionally when both those columns exist (batch1 (2026-11-07)
adversarial review D4 fixed the boundary: a `bid_l`+`ask_h` partial-pair
inverted spread was previously missed entirely). Note that `bid_h < ask_l`
(bids below asks across the bar) is a **legitimate market** and must NOT be
flagged. DQ2 is disabled as a whole only when
the input carries **no** bid/ask pair column at all. This neither rejects legal
partial quotes (some points only) nor silently skips an inverted spread in a
partial quote (the S1 self-review boundary, found and fixed); DQ1/DQ3 use
`ALWAYS_PRESENT` columns and are always enabled.

**Real-data verification (61,615,338 raw CSV rows, 183 real moneta CSVs)**:
DQ1/DQ2/DQ3 all **0 violations** — fail-fast does not false-positive on real
data, and it turns "moneta's data happens to be clean" from an assumption
into a **code-enforced contract**.

**Design trade-off**: we do not silently drop violating rows (that would
mask a source-data problem) — fail-fast surfaces it upstream, because 0002
is the data entry point and catching dirty data here is far cheaper than
having it surface in 0005 as "the strategy results look weird."

### 3.5 OANDA backfill / gap-fill (`lyra oanda`)

**Motivation**: `lyra pull` only downloads objects **already present** under
the PAR prefix — it has no "fetch missing history by instrument/time window"
capability. moneta's `extract_oanda.py` does (pull 1-min candles from the
OANDA API, chunked by UTC month, resumable). This is the stage of the
moneta→lyra chain that lyra needs: the I22 philosophy is "gaps are
legitimate," but the **tool to fill gaps** should still be provided by the
framework rather than requiring users to hand-write API calls.

**Contract** (carried from moneta's proven implementation, re-written
independently):

- **CLI**: `lyra oanda <instrument> --from <UTC> --to <UTC> [--dry-run] [--force]`
- **Source**: OANDA v3 `/v3/instruments/<inst>/candles`, 1-min granularity,
  `price=MBA` (mid+bid+ask, aligned to the bronze schema).
- **5000-candle page cap**: OANDA rejects `count` with `from`+`to` and caps a
  response at 5000, so the window is paged in `PAGE_SIZE-1` candle steps,
  each page starting one candle before the previous page's last (deliberate
  overlap, removed by clean's `(instrument,time)` dedup).
- **Calendar-month chunking + resume**: output lands at
  `raw_csv/<instrument>/<instrument>_<gran>_<YYYYMM>01T000000Z.csv` (one
  file per UTC month); a month that is already present and non-empty is
  **skipped by default** (`--force` re-fetches), so an interrupted run
  resumes automatically.
- **Month-boundary semantics**: OANDA's `to` parameter is **inclusive**, so
  the month boundary is "first moment of next month − 1s" (batch1 (2026-11-07)
  adversarial review D2 fixed: the original "next-month-start − 1min"
  over-fetched for non-1m granularities, and a start inside the last minute
  of the month crashed with `m_start > m_end`). After clamping, if
  `m_end < m_start` → log a WARN and skip the month; **no exception**.
- **Token is a secret**: it lives only in the gitignored
  `config/config.yml` under `oanda.api_token` and is **never committed**
  (moneta's convention). An empty token → `OandaConfigMissing` (loud
  failure, not a silent skip). `OandaConfig.__repr__` does not expose the
  token (`repr=False`; batch1 (2026-11-07) adversarial review D5 fix).
- **dry-run degrade**: `--dry-run` with a **missing config** warns and
  previews only (no network); non-dry-run with a missing config still fails
  loudly (batch1 (2026-11-07) adversarial review D6 fix — the original
  dry-run path also called `load_config` and crashed when the file was
  absent).
- **UTC only**: no local/DST conversion; all timestamps are ISO-8601 `...Z`.
- **Output schema**: exactly the bronze input contract
  (`instrument,is_complete,time,volume,mid_*,bid_*,ask_*`), picked up by
  clean's recursive `**/*.csv` glob (§3.3 boundary).

**Coupling with §3.3**: clean's CSV glob was promoted from `*.csv` to
`**/*.csv` (DuckDB 2.0 recursive expansion) so per-instrument sub-directories
are first-class; all existing flat-CSV tests remain compatible (verified,
47 tests green).

**Real data VERIFIED (2026-11-07, v1.0)**: using moneta's practice token
(gitignored `config/config.yml` `oanda.api_token`), a real OANDA backfill
was run for **all 21 instruments × 2019-11/12** — **42/42 instrument-months
succeeded, 0 failures**, **943,529 1-min candles** total, spanning
2019-11-01→2019-12-31; the output CSVs carry all 16 columns matching the
bronze input contract (incl. `bid_*`/`ask_*`, UTC `Z`). Resume verified
(an existing month is skipped; `--force` re-fetches).
> Note: an initial `curl` probe returned 401 on both the practice and live
> hosts and was misread as "token expired"; a re-test confirmed that was a
> **transient failure** — the token itself is valid (`requests` straight to
> `/v3/accounts` and `/candles` both return 200), and the full 42/42 run is
> green.

## 4. Invariants

| # | Invariant | Source |
|---|---|---|
| I18 | **Data reproducibility**: same OCI object set (md5 set identical) + same code version → bronze / 5m / 1h Parquet **row-identical in content** (values + row order); file-level byte equality is NOT promised (Parquet bytes vary with arrow versions, and moneta doesn't promise it either). Premises: clean's filter/dedupe/survivor-selection are fully deterministic (§3.3 clean semantics); pull processes objects in name-sorted order (order-independent) | New (R8 made concrete at the data layer) |
| I19 | PAR URLs never enter git, logs, or run reports (redacted to host + first 2 path segments) | I12 (credentials out of git / reports) extended to the data layer |
| I20 | Object downloads idempotent: **skip when md5 matches** (moneta's listing already returns md5); fall back to size when md5 unavailable; same key with different content MUST be re-downloaded | Moneta mechanism + strengthening (download-side guarantee of I11 rebuildability) |
| I21 | Aggregation uses only `time_bucket` UTC boundaries + 1m bars present in the window; `n_bars` truthfully flags partial bars (gaps are legitimate); open/close from the window's first/last bar. **`time` is actually `TIMESTAMPTZ(UTC)`** (source carries `Z`, DuckDB infers; downstream reads need pytz, see pyproject) | Moneta `aggregate_ohlcv` (fixed here); **TIMESTAMPTZ confirmed after the real end-to-end run (batch-5 A7)** |
| I22 | Input's **native resolution must = 1m UTC** (foolproofing; premise of I18). Criterion: the **minimum** inter-bar gap per instrument is ≈1m (59–61 s). **Market gaps (missing bars) are legitimate** — real 1m data is missing bars on weekends/holidays/no-trade (this dataset has 730k gaps ≥5m); these must NOT cause rejection. Only **5m/1h native resolution** (min gap ≥ 5m) is rejected | New; **refined after the real end-to-end run** (the original "every-pair 1m" wrongly rejected legitimate gaps — fixed in batch-5) |
| I23 | **Data quality (DQ1–DQ3, fail-fast)**: bronze candidate rows must satisfy mid-OHLC positive and internally consistent (o,c ∈ [l,h]); where both quote sides exist, ask ≥ bid; volume, if present, finite and non-negative. Any violation → `DataQualityError`, bronze not written. **Real 61,615,338 CSV rows: 0 violations** (no false positives) | New (the equivalent fixation of nova `data._validate`; absent in moneta, restored by lyra); see §3.4 |
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
| `test_clean_rejects_bad_mid_ohlc` | `mid_h < mid_l` row → `DataQualityError` (DQ1/I23) |
| `test_clean_rejects_negative_volume` | `volume < 0` row → `DataQualityError` (DQ3/I23) |
| `test_clean_rejects_inverted_spread` | `ask < bid` (both sides present) → `DataQualityError` (DQ2/I23) |
| `test_clean_rejects_partial_quote_inverted_spread` | partial quote (only bid_o/ask_o) with `ask_o < bid_o` → `DataQualityError` (DQ2 per-point column-aware, S1 self-review) |
| `test_clean_accepts_partial_quote_valid_spread` | partial quote with a valid spread (`ask_o >= bid_o`) passes (DQ2 does not reject legal partials) |
| `test_clean_accepts_valid_data` | well-formed rows pass (DQ no false positive) |
| `test_clean_picks_up_nested_oanda_csv` | `raw_csv/<inst>/*.csv` subdir picked up by recursive glob (§3.5) |
| `test_oanda_fetch_requires_token` | empty token → `OandaConfigMissing` (§3.5, loud failure) |
| `test_oanda_candles_to_rows_schema` | OANDA candle → rows matching the bronze input contract exactly (§3.5) |
| `test_oanda_backfill_resume_skips_existing` | an existing non-empty month is skipped, no network fetch (§3.5 resume) |

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
| 2026-11-06 | 0.4 | **After the real end-to-end run (moneta's real PAR, 12 GB / 48.8M rows): contract refinement + 4 fixture-untestable fixes** — ① **clean rewritten in DuckDB** (pure Python infeasible at 48M rows); ② **I22 criterion changed to "native resolution = 1m"** (per-instrument minimum gap ≈1m) with **market gaps legitimate** — the original "every-pair 1m" wrongly rejected 730k real gaps; ③ `time` confirmed as **TIMESTAMPTZ(UTC)** (inferred from source `Z`) + downstream reads need **pytz** (added to pyproject); ④ `read_parquet(?)` bind params wrapped in `str()`; ⑤ `COPY` gains `ORDER BY` for stable row order (I18). Tests 14→24 (added gapped-1m accepted, 5m-native rejected, COPY determinism, empty-table schema). |
| 2026-11-06 | 0.5 | **Integrity audit + DuckDB efficient read/write / catalog (batch-6)** — ① **three-layer integrity verification all pass**: bronze/5m/1h footers readable with `num_rows` matching the success report + **full row-group decompression scan** (484/484 pages decode cleanly, rows scanned == footer) + raw 163/163 zips match the remote PAR per-object by **md5 AND size** → **confirms the earlier system interruptions left no truncation / page corruption / silent failure**; ② **read path unified on DuckDB external tables / VIEWS** — `_register_bronze` changed from `CREATE TABLE` (materialized the full 48M rows) to `CREATE VIEW` (streaming, A2); ③ **new `lyra/catalog.py`** — a persistent DuckDB catalog (`~/.lyra/default/data/catalog.duckdb`, outside the repo, pure schema metadata) with `bronze`/`ohlcv_5m`/`ohlcv_1h` VIEW named entry points, auto-built at the end of `lyra pull` and rebuildable via the `lyra catalog` CLI (A3); ④ **honest efficiency bound** — aggregate's grouping working set peaks ≈10 GB at 48M rows (inherent to DuckDB hash aggregation, not a bug, not streaming-removable); 0003 must plan memory around this (A6). Real-data regression: after the view change, re-running aggregate yields 5m/1h bars row-identical to batch-5 (I18 holds). Tests 24→30 (added 6 catalog tests, including the VIEW-not-TABLE assertion). |
| 2026-11-06 | 0.6 | **Batch-7 external red-team: all 9 findings accepted and fixed** (0002 first full "second AI" review): ① **D1 (Major)** `_quote` regex rejected Windows paths → SQL single-quote escaping + control-char rejection (R8 portability); ② **D2 (Major)** `upsert_views` had no lock guard → `try/except` + `warnings.warn` ("best-effort" became code, not just a comment); ③ **D3 (Moderate)** `databackend.memory_limit`/`tmp` never reached DuckDB → new `DatabackendConfig` + `open_limited_duckdb()` (`SET max_memory`/`threads`/`temp_directory`), wired through the full pipeline; **same-round footgun fixed**: `config_example.yml` 1 GB example → 16 GB (real data needs ~10 GB working set; 1 GB would OOM); ④ **D4 (Moderate)** O1 doc gap → `open-questions` now records the ruling (0002 drops the directory-level snapshot_id; single-file external tables + raw md5 provenance); ⑤ **D5 (Moderate)** 21-instrument list never written down → §3.3 now carries the table + `Catalog.instruments()` interface (data is authoritative; list is extensible); ⑥ **D6 (Moderate)** `_validate_1m` opaque error → now names offending instruments + measured `min_gap_s`; **rejected** the "relax to multiples of 60s" suggestion (5m-native 300s is a multiple of 60s and would slip through); ⑦ **D7 (Minor)** empty-table naive timestamp → `pa.timestamp("us", tz="UTC")`; ⑧ **D8 (Minor)** catalog relative paths → `Path.resolve()`; ⑨ **D9 (Minor)** no zip-bomb guard → `MAX_EXTRACTED_MEMBER_BYTES` (8 GB; largest real member is 575 MB) + `ZipBombError`. **38 tests green** (+8 new), pyflakes clean. Batch-7 review doc (ZH+EN) gained the disposition table. |
| 2026-11-06 | 0.7 | **Pre-close-out self-review + adversarial self-review**: re-verifying all Batch-7 changes surfaced **F1 real defect** — `Catalog.instruments()`'s docstring promised "return [] when the bronze view is missing/unreadable", but a deleted/corrupt bronze parquet made the `SELECT` raise `IO Error` instead of degrading; fixed with `except duckdb.Error: return []` + regression test `test_instruments_returns_empty_on_broken_catalog` (valid-then-delete reproduces the real path). 3 other candidates checked and dismissed/deferred: run_pull not explicitly closing its two count connections (CPython refcount backstop, not a correctness bug, and a scoped-close refactor would break the D2 test's structure → deferred for 0003 cleanup); the alleged `_count_rows` doc reference (grep proved the doc uses DuckDB `COUNT(*)`, false positive); the alleged `tmp/` leak (DuckDB's legitimate `temp_directory` spill space, false positive). **39 tests green** (+1), pyflakes clean, real-data regression bronze/5m/1h = 48,846,896/9,986,167/838,272 consistent with Batch-5 (I18 holds), `instruments()`=21 verified. **0002 closed out** |
| 2026-11-07 | 0.8 | **Compared against moneta/nova and filled two genuine gaps** (user decided: both into 0002). ① **Data-quality validation (§3.4, DQ1–DQ3, fail-fast)**: the OHLC/spread/volume checks that nova's `data._validate` has but moneta/lyra lacked are now explicit in clean — run after the is_complete filter + dedup, before the COPY, on the survivor candidates; any violation raises `DataQualityError` and bronze is not written. Column-aware (DQ2 avoiding a `union_by_name` binder error; refined to per-point in v0.9). **Real 61,615,338 CSV rows: 0 violations** (no false positives). New invariant I23. Also fixed a **real test-fixture bug**: `test_aggregate.py`'s placeholder bid/ask were inverted (bid_l > ask_l, physically impossible) and were correctly rejected by the new DQ gate — the fixture now uses ask ≥ bid (valid). ② **OANDA backfill / gap-fill (§3.5, `lyra oanda`)**: the "fetch missing 1-min history by instrument/time window" capability moneta's `extract_oanda.py` has but lyra lacked is now independently re-implemented as `lyra/oanda.py` + a `lyra oanda` CLI — OANDA v3 paging (5000-candle cap, one candle of overlap per page), UTC calendar-month chunking, resume (an existing non-empty month is skipped by default), the token lives only in the gitignored config (an empty token fails loudly), and the output matches the bronze input contract. clean's CSV glob was promoted `*.csv`→`**/*.csv` (DuckDB 2.0 recursive expansion) so per-instrument sub-directories are first-class. **47 tests green** (+8), pyflakes clean. A real OANDA fetch is left for the user to verify after filling the token (a secret; needs network) |
| 2026-11-07 | 0.9 | **Self-review + adversarial re-review of the two new features** (user: self-review first, then adversarial, then the 2019-11/12 real-data test). **S1 real defect (fixed)**: DQ2's column gate was "enabled only when all 8 columns present" — a partial-quotes input (e.g. only `bid_o`/`ask_o`) would **silently skip** spread validation, defeating the fail-fast intent (and missing the case nova's `not in (0,8)` rejects). Changed to **per-point column-awareness**: at any point p where both `bid_p` and `ask_p` exist, `ask_p >= bid_p` is enforced (per-point NULL guard is safe); the whole DQ2 is skipped only when no bid/ask pair column exists at all — so it neither rejects legal partial quotes nor silently misses an inverted spread in a partial quote. Added 2 regression tests (`test_clean_rejects_partial_quote_inverted_spread` + `test_clean_accepts_partial_quote_valid_spread`); 5 boundary cases verified (partial inverted rejected / partial valid passes / full inverted rejected / full valid passes / quote-free passes). **Adversarial re-review of the OANDA module**: month computation (`_months_between` + December rollover), paging (`PAGE_SIZE-1` overlap de-dup), resume (non-empty month skipped), token guard (empty token → `OandaConfigMissing`) all verified line-by-line, logic correct. **Real OANDA test blocked (recorded honestly)**: moneta's token (`config/setting.yml`, gitignored, practice environment) returns **401 Insufficient authorization** on both the practice and live hosts — the token is expired/revoked (a gen-1 stale token), not a code problem. The code path is verified via 49 offline tests + `--dry-run` + a real clean+DQ run; a real fetch needs a fresh token from the user. **49 tests green** (+2), pyflakes clean. **0002 closed out**, 0003 ready |
| 2026-11-07 | 1.0 | **Real OANDA backfill verified** (user: run the 2019-11/12 test with moneta's practice token). **All 21 instruments × 2019-11/12 = 42 instrument-months succeeded, 0 failures**, **943,529 1-min candles** (spanning 2019-11-01→2019-12-31); output CSVs carry all 16 bronze-contract columns (incl. bid/ask, UTC Z); resume verified (existing month skipped). **Corrects the #50 401 conclusion**: the initial `curl` double-host 401 was a **transient failure** — a re-test with `requests` to `/v3/accounts` + `/candles` both returned 200, so the token is valid; §3.5 changed from "real data NOT verified" to "VERIFIED". 0002 fully closed out, 0003 ready |
| 2026-11-07 | 1.1 | **Batch1 (2026-11-07) adversarial review D1–D6 fixes**: §3.4 DQ column sniffing now uses whole-directory union DESCRIBE (D1); DQ2 adds bar-wide `ask_h ≥ bid_l` and all DQ1/DQ2/DQ3 clauses are NULL-safe with `isfinite` guards (NaN explicitly rejected, D4); §3.5 month-boundary `to` is inclusive → "next-month-start − 1s" + inverted-clamp loud-skip (D2); `OandaConfig.repr` hides token (D5); dry-run degrades to preview with no config (D6). D3 (resume-by-file granularity) accepted as residual (escape: `--force`). D7/D8 absorbed by 9 new regression tests. 58 tests green, pyflakes clean |
