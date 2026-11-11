# Bar-Coverage Discrepancy Nail-Down Report (lyra vs nova, 1h)

> **Chinese**: [Bar 覆盖差异钉死报告](./0008-bar-coverage-analysis.md)

Generated: 2026-11-11 · read-only analysis · every number comes from real computation (DuckDB / lyra venv), no extrapolation.
Repro scripts and intermediate JSON live in `scratch/barcov/` at the repo root (`main2.py` + `one/*.json` + `sample_table.json`; gitignored — one-off intermediates, see M4 note in §6).

---

## 0. TL;DR

1. **Both sides' raw 1m data is byte-for-byte identical**: all 21 per-instrument CSVs match by SHA256; the nova 1m parquet and the lyra bronze agree row-for-row for **21/21 instruments** in the shared window (2020-01-01 → 2026-10-23T21:00Z) (e.g. EUR_USD 2,505,386 = 2,505,386). Nova additionally ingests 150 `prices_YYYYMMDD_*.csv` (daily snapshots 2026-04-29 → 2026-10-23) that heavily overlap the per-instrument CSVs and add no new data after dedup.
2. **The bar-set difference has nothing to do with raw gaps**: **total delta 183,909 = 179,550 (97.6%, aggregation-rule difference — nova drops partial hours) + 4,359 (2.4%, lyra's data window extends 2026-10-24→11-06 beyond nova's cutoff)**; nova's `aggregate()` drops whole-hour buckets with `source_bars != 60` (manifest self-reports `partial_buckets_dropped = 179550`); lyra's `aggregate.py` keeps every hour with ≥1 1m bar (annotated honestly via `n_bars`). Overlapping 1h bars are **bar-for-bar identical in OHLC + volume** (6 instruments, 195,783 overlapping bars, 0 mismatches).
3. **Attribution identity (holds exactly for all 21 instruments, residual = 0)**:
   `lyra_1h_total = nova_1h_total + partial hours dropped by nova + lyra-only tail bars 2026-10-24→11-06`.
   Partial hours account for **91–99%** of each instrument's delta (179,550 in total, exactly matching nova's manifest); **no hour was found where the two sides' raw data disagree** (every partial hour has 30–59 1m bars in both sides' raw — OANDA rollover/weekend/holiday minute-level gaps, raw identical on both sides; note: byte-identity cannot rule out hours missing on *both* sides — no market-completeness claim is made; narrowed per 2026-11-12 review M3).
4. **lyra is closer to the (project-internal observation of) the consensus basis**: FX normally 24h/day (lyra) vs nova losing 2–6 bars/day; US indices normally 21–23h/day (lyra) vs nova 15–23h/day; crypto 21–24h; gold 21–23h. Nova's "clean but incomplete" series systematically changes monthly/yearly bar counts (notably CN50, JP225, USD_CHF losing 6–9 bars/day).
5. **SPX500 "anomalously high weekly bar count / 3 bars in 2 days"**: under a **UTC basis, neither side** has any day with ≥24 bars; the phenomenon comes from **nova's 60m parquet timestamps being displayed in the machine's local timezone (AEDT/AEST +10/+11)**, which misassigns the 22:00–23:59Z rollover hours to adjacent "local days" — producing 119 local calendar days with only 1–4 bars paired with artificially inflated neighbors. Under lyra's UTC basis the same phenomenon shows up as **1–2 bars every Sunday** (Sunday 22:00/23:00Z rollover bars) — real data (OANDA weekend rollover), not a source outage or a per-day file boundary.

**Recommendation**: take **lyra's bar set as canonical** (UTC buckets + partial hours kept + `n_bars` annotation); no raw re-pull needed (raw is identical and complete); if nova must align, change its `source_bars={minutes}` filter to `>= 1` and pin output timestamps to UTC display.

---

## 1. Raw source identity comparison

### 1.1 File inventory and provenance

| Item | lyra | nova |
|---|---|---|
| Per-instrument 1m CSVs | `/home/ubuntu/.lyra/default/data/raw_csv/<SYM>.csv` (21) | `/home/ubuntu/work/nova/data/raw_csv/<SYM>.csv` (21) |
| **SHA256** | **21/21 identical** (e.g. AUD_USD `8023df0e…`, SPX500 `9e6ce710…`, EUR_USD `0d21206f…`) | same |
| Time range (21 instruments) | 2020-01-01/02 → 2026-10-23T20:59/21:00Z | same (per-instrument manifest `start/end`) |
| Extra inputs | Per instrument, 2 × `*_M1_20191101T000000Z.csv`, `*_M1_20191201T000000Z.csv` (**Nov/Dec 2019**, 19k–21k rows each, `is_complete=True`; plus 150 daily files such as `prices_20260505…csv` in lyra's raw dir) | 21 per-instrument CSVs + 150 × `prices_YYYYMMDD_*.csv` (2026-04-29 → 2026-10-23, 9.06M rows, OANDA daily snapshots) + `OUTPUT_BASE.csv` (from 2025-11) |
| 1m artifact | `catalog.duckdb::bronze` (48,846,896 rows, 21 instruments) | `data/market/1m/041914943d0ac7eb/<SYM>.parquet` (60,958,698 input rows → deduped; manifest `duplicate_complete_rows_removed=12,367,671`) |
| 1h artifact | `ohlcv_1h/ohlcv_1h.parquet` (838,272 rows, UTC buckets, with `n_bars`) | `data/market/60m/ecaa0a6c6cd7eb46/<SYM>.parquet` (`gap_filling=False`, `partial_buckets_dropped=179,550`) |

**Conclusion: same source** (same OANDA provider, same batch of downloads, byte-identical). The only difference is **side-bench files each directory has that the other does not**:

- lyra additionally has **Nov/Dec 2019 M1 files** (`<SYM>/<SYM>_M1_20191101T000000Z.csv` etc., `is_complete=True`, 42 files, 943,529 rows) — **present in the raw layer but NOT in bronze** (measured `bronze WHERE time < 2020-01-01` = **0 rows**; lyra's `ohlcv_1h` min timestamp is likewise 2020-01-01, verified per instrument). So the 2019 data currently **enters no artifact layer** and contributes **nothing** to the 1h bar set (corrected after 0008 batch-1 review H2: the earlier "enters bronze → enters 1h" wording was wrong).
- nova additionally has **150 prices daily snapshots + OUTPUT_BASE** (2026, overlapping the per-instrument CSV window; absorbed by nova clean's (instrument,time) dedup; measured 1m row counts for all 21 instruments equal "per-instrument CSVs only").

### 1.2 Per-instrument 1m row-count consistency (shared window 2020-01-01 → 2026-10-23T21:00Z)

21/21 instruments: `nova_1m = lyra_bronze` **exactly equal** (e.g. EUR_USD 2,505,386; SPX500_USD 2,331,264; JP225_USD 2,293,844).
lyra bronze total (48,846,896) exceeds nova 1m (48,588,451) by **258,445 rows**, **exactly equal to the count of bronze 1m rows with `time > 2026-10-23T21:00:00Z`** (lyra data updated to 2026-11-06; nova raw stops at 10-23) — i.e. the **entire** delta comes from the time-window tail; the 2019 M1 files are not in bronze (see §1.1). (The earlier "125,815 = 2019 + tail" figure used a wrong basis; corrected after 2026-11-12 review H2. Per-instrument equality within the shared cutoff window is unchanged: 21/21.)

### 1.3 OHLC validation of overlapping 1h bars (full join, 6 instruments)

| Instrument | Overlapping 1h bars | OHLC mismatches | volume mismatches |
|---|---|---|---|
| AUD_USD | 31,105 | 0 | 0 |
| EUR_USD | 36,698 | 0 | 0 |
| XAU_USD | 36,418 | 0 | 0 |
| BTC_USD | 39,579 | 0 | 0 |
| US30_USD | 34,130 | 0 | 0 |
| SPX500_USD | 28,363 | 0 | 0 |

(Consistent with the 0008 cross-check "overlapping bars are OHLC-identical"; here extended to volume, also identical.)

---

## 2. Sample-day × (lyra, nova, missing hours, cause) detail

Sampling: 2020-01-03 → 2026-11-05, ~10-week spacing, 26 days (Sundays skipped to avoid rollover-artifact confusion).
`miss_nova` = hours with ≥1 1m bar in raw but absent from nova 1h (= partial hours dropped by the 60-bar filter); `partial` is the same set, with the actual 1m bar counts in brackets (examples in `one/*.json::partial_bars`). All hours are **UTC**.

### SPX500_USD

| day | lyra | nova | miss_nova (UTC h) | cause |
|---|---|---|---|---|
| 2020-01-03 | 22 | 3 | 0–12,14,16–19,21 | First day after New Year holiday; minute-level raw gaps all day, 10–59 bars per hour |
| 2020-04-13 | 23 | 22 | 20 | Hour 20 has <60 1m bars (20:00Z rollover/gap) |
| 2020-07-21 | 23 | 11 | 0,1,3–5,9–12,20,22,23 | July 4th holiday; 5–59 bars per affected hour |
| 2020-10-29 | 23 | 21 | 4, 20 | partials dropped by nova |
| 2021-05-17 | 23 | 20 | 20,22,23 | same |
| 2022-03-12 | 21 | 21 | – | no partials that day |
| 2023-07-25 | 21 | 19 | 20,22 | day before July 4th |
| 2024-12-06 | 21 | 17 | 20,21,22,23 | pre-Christmas |
| 2025-06-23 | 21 | 19 | 20,23 | |
| 2026-11-05 | 19 | 16 | 4,20,23 | data tail |

(The other 26 sample days are structurally identical: the hours nova is missing == exactly the hours with <60 1m bars in raw that day, all concentrated in the 20:00–23:59Z rollover band and on holidays.)

### EUR_USD

| day | lyra | nova | miss_nova | cause |
|---|---|---|---|---|
| 2021-01-12 | 24 | 21 | 21,22,23 (58/44/59 bars) | raw minute gaps; nova drops them |
| 2023-06-12 | 17 | 15 | 21,22 (53/59 bars) | same |
| 2025-06-10 | 24 | 22 | 21,22 (40/59) | same |
| 2026-05-12 | 24 | 22 | 21,23 (55/59) | same |

EUR_USD normal state across the year: **lyra 24 bars/day on 1,415/1,765 active days; nova's normal mode is 22 bars/day** (of the three daily rollover hours 21/22/23, ~2.7 on average are partial).

### XAU_USD / BTC_USD / US30_USD / DE30_EUR (excerpts)

| day | XAU l/n | BTC l/n | US30 l/n | DE30 l/n |
|---|---|---|---|---|
| 2023-07-25 | 22/19 (miss 20,22,23) | 24/23 (miss 22) | 21/18 | 20/18 |
| 2024-12-06 | 22/20 | 24/22 | 20/17 | 20/18 |
| 2026-11-05 | 22/19 | 24/22 | 18/16 | 20/18 |

BTC/ETH (crypto) have the fewest partials: BTC averages 1.47 partial hours/day (91.2% of its delta is still explained by partials, plus 220 tail bars).

Full 21-instrument × 26-day detail: `scratch/barcov/sample_table.json`.

---

## 3. Attribution: delta = f(raw missing hours) + g(nova 60-bar filter) + other

**Identity (holds exactly for all 21 instruments, residual = 0):**

```
lyra_1h = nova_1h  +  H_partial (partial hours dropped by nova)  +  E (lyra-only tail 2026-10-24→11-06)
```

| Instrument | lyra | nova | Δ | H_partial | E | H as % of Δ |
|---|---|---|---|---|---|---|
| AUD_USD | 42,638 | 31,105 | 11,533 | 11,313 | 220 | 98.1% |
| BCO_USD | 38,817 | 29,303 | 9,514 | 9,312 | 202 | 97.9% |
| BTC_USD | 42,074 | 39,579 | 2,495 | 2,275 | 220 | 91.2% |
| CN50_USD | 35,512 | 19,637 | 15,875 | 15,694 | 181 | 98.9% |
| DE30_EUR | 35,606 | 27,591 | 8,015 | 7,824 | 191 | 97.6% |
| ETH_USD | 41,619 | 38,609 | 3,010 | 2,790 | 220 | 92.7% |
| EUR_USD | 42,643 | 36,698 | 5,945 | 5,725 | 220 | 96.3% |
| GBP_USD | 42,643 | 35,192 | 7,451 | 7,231 | 220 | 97.0% |
| HK33_HKD | 28,326 | 22,933 | 5,393 | 5,239 | 154 | 97.1% |
| JP225_USD | 40,492 | 24,906 | 15,586 | 15,376 | 210 | 98.7% |
| NAS100_USD | 40,434 | 36,344 | 4,090 | 3,880 | 210 | 94.9% |
| NZD_USD | 42,647 | 30,271 | 12,376 | 12,156 | 220 | 98.2% |
| SPX500_USD | 40,435 | 28,363 | 12,072 | 11,862 | 210 | 98.3% |
| UK100_GBP | 34,489 | 23,122 | 11,367 | 11,186 | 181 | 98.4% |
| US30_USD | 40,437 | 34,130 | 6,307 | 6,097 | 210 | 96.7% |
| USD_CAD | 42,644 | 34,429 | 8,215 | 7,995 | 220 | 97.3% |
| USD_CHF | 42,639 | 28,265 | 14,374 | 14,154 | 220 | 98.5% |
| USD_JPY | 42,644 | 37,416 | 5,228 | 5,008 | 220 | 95.8% |
| WTICO_USD | 40,510 | 30,909 | 9,601 | 9,391 | 210 | 97.8% |
| XAG_USD | 40,509 | 29,143 | 11,366 | 11,156 | 210 | 98.2% |
| XAU_USD | 40,514 | 36,418 | 4,096 | 3,886 | 210 | 94.9% |
| **Total** | | | **183,909** | **179,550** | 4,359 | **97.6%** |

- **f(hours where the two sides' raw disagree) = 0**. For every whole hour, the minute-level coverage is identical across both sides' raw (same source files); the "missing" part is a **minute-level gap inside the hour** (30–59 bars/hour), not a missing hour. (Wording narrowed: no claim that "the market never lacked an hour" — byte-identity cannot exclude a gap shared by both sides.)
- **g(nova's 60-bar filter) = 179,550 bars**, bit-exact with nova's manifest `partial_buckets_dropped`. The partial hours are heavily concentrated in the **20:00–23:59Z OANDA rollover/weekend-stoppage band** (each instrument's top partial hours are almost all in hours 20–23, then the 0–6 holiday band).
- **Other = 4,359 bars (2.4%)**: **entirely** lyra's data window extending 2026-10-24 → 2026-11-06 beyond nova's cutoff (lyra raw updated to 11-06; nova raw stopped at 10-23T21:00Z). No other component (the earlier "+ SPX500 2019 monthly files" attribution is removed — the 2019 files are in neither bronze nor 1h, see §1.1).

**Explanation of the 0008 sample's "lyra 21/day, nova 24/day"**: that sampling necessarily counted **local display days** (nova's parquet timestamps are local AEDT/AEST); under a local-day basis, rollover hours get shifted to adjacent days, producing a "shuffling" artifact where one local day shows 24 bars and a neighbor 21. Under the **UTC basis** (this report's basis), **lyra ≥ nova day-by-day holds with no counterexample** (21 instruments × all active days).

---

## 4. Consensus-basis comparison

"Consensus" = the normal daily quoting hours for each instrument class (OANDA semantics, UTC) — **a project-internal observation/judgment, no external benchmark source** (flagged by 2026-11-12 review M3; the conclusions do not depend on an external-completeness claim from this table):

| Class | Consensus bars/day | lyra normal (mode) | nova normal (mode) | Closer to consensus |
|---|---|---|---|---|
| FX (EUR/AUD/GBP/NZD/USD_x, 7) | 23–24 (24h market, only rollover + weekend 1–3h off) | **24** (1,413–1,415/1,765 active days) | 22 (drops ~2–3 partial hours/day) | **lyra** |
| US indices (SPX500/US30/NAS100) | 21–23 (16.5h regular + weekend/holiday partial; 24h CFD quoting) | **21–23** (23 on 1,351/1,760 non-Sunday days) | 15–23 varying (drops 2–8 hours) | **lyra** |
| EU indices (DE30/UK100) | ~19–21 (7.5h regular + pre/post) | **20–21** | 18–21 | **lyra** (close; DE30 20 vs the 21 upper bound — both sides agree) |
| Asia indices (JP225/HK33/CN50) | 8–9 regular + OANDA long tail → actually 19–23 | **21–23** (JP225 23 on 1,341/1,760) | 15–22 (drops 5–7 hours) | **lyra** |
| Crypto (BTC/ETH) | 24 (7×24, minimal outages) | **24** (1,397/1,756 days) | 22–23 (drops 1–2 hours) | **lyra** |
| Gold/oil (XAU/XAG/WTICO) | 22–23 (near-24h, weekend 1–2h off + rollover) | **21–23** (XAU 23 on 1,363/1,760) | 19–23 (drops 2–4 hours) | **lyra** |

**Judgment**: lyra's bar set = "every UTC whole hour that had any quote in raw" — the **largest usable set**, consistent with each class's consensus; nova's series is systematically 2–8 bars short of consensus on every rollover/holiday day. If a research basis demanded "every whole hour must have a full 60 minutes," nova is cleaner, but the cost is **dropping the genuine rollover window (20:00–23:59Z, containing important liquidity events)** from the sample, and the monthly machine bar counts (per instrument, including zero-entry months) change directly.

**Recommendation**:
1. **Take lyra's bar set as canonical** (UTC `time_bucket` + partial hours kept + `n_bars` honestly annotated — downstream can down-weight or drop `n_bars<60` itself; no information lost).
2. **No raw re-pull needed**: both sides' raw are byte-identical and complete; the difference is 100% in aggregation rules and data window.
3. If nova must align: change `data.py::aggregate()`'s `WHERE source_bars={minutes}` to `WHERE source_bars >= 1` (keep the `source_bars` column for downstream filtering); pin output/display timestamps to UTC (the current parquet displays local AEST — the visual root of the "weekly bar anomaly").
4. Both sides should align their data windows to the same cutoff (lyra 11-06 vs nova 10-23), otherwise ~4,359 tail bars will never match.

---

## 5. SPX500 "high weekly bar count" and "3 bars / 2 days" — dedicated analysis

**Under the UTC basis (the correct one)**:
- lyra: SPX500 has no day with ≥24 bars; max 23 (1,352 non-Sunday days).
- nova: SPX500 likewise has no day with ≥24 bars (UTC); minimum is Sunday rollover days with 1–2 bars.
- I.e. **"anomalously high weekly bar count" does not exist on either side under UTC**.

**The true cause of the phenomenon (nova's local-timezone display)**:
- nova's 60m parquet `bar_open_time` carries a **local AEDT(+11)/AEST(+10) display** (example: 2020-01-02 09:00 AEDT == 2020-01-01 22:00 UTC; 2020-07-01 00:01 AEST == 2020-06-30 14:01 UTC).
- Counting by **local day** misassigns OANDA's Sunday/Monday rollover bars (UTC Sunday 22:00/23:00) to local Monday/Tuesday, producing **119 local days with only 1–4 bars** (e.g. local 2020-01-04 = 3 bars, all from UTC 2020-01-03 hours 13/15/20) + inflated neighbors — this is the "3 bars/2 days" and "some week anomalously high" pairing artifact.
- Example week (UTC basis, 2023-04-08→14, Easter week): lyra per day = [–, 2, 23, 23, 23, 23, 21]; nova = [–, 0, 7, 10, 10, 11, 10]. Sunday's 2 bars = UTC Sunday 22/23 rollover bars (57/58 1m bars, <60 so nova drops them whole; lyra keeps them with `n_bars=57/58`); Mon–Thu nova additionally drops 10–16 bars/day (more partial hours that week; raw identical on both sides).

**Raw-side evidence for "3 bars/2 days"** (EUR_USD 2021-01-12 22:00Z hour, 44/60 bars): the missing minutes = {26, 34, …} (scattered minute-level holes) — an OANDA rollover/low-liquidity gap; raw identical on both sides; nova drops it for <60; lyra keeps it (`n_bars=44`).

---

## 6. Repro snippets

```sql
-- 1) raw same-source: 21/21 SHA256 match
sha256sum /home/ubuntu/work/nova/data/raw_csv/<SYM>.csv
sha256sum /home/ubuntu/.lyra/default/data/raw_csv/<SYM>.csv

-- 2) per-instrument 1m row counts equal (shared window)
select count(*) from read_parquet('nova/data/market/1m/041914943d0ac7eb/EUR_USD.parquet')
 where timezone('UTC',bar_open_time) <= timestamptz '2026-10-23T21:00:00Z';   -- 2,505,386
select count(*) from bronze where instrument='EUR_USD'
  and time <= timestamptz '2026-10-23T21:00:00Z';                              -- 2,505,386

-- 3) per-day/per-hour bar counts and the difference set (UTC basis; nova MUST use timezone('UTC',…))
select cast(timezone('UTC',time) as date) d, extract(hour from timezone('UTC',time)) hh, count(*)
from ohlcv_1h where instrument='SPX500_USD' group by 1,2 order by 1,2;
select cast(timezone('UTC',bar_open_time) as date) d, extract(hour from timezone('UTC',bar_open_time)) hh, count(*)
from read_parquet('nova/data/market/60m/ecaa0a6c6cd7eb46/SPX500_USD.parquet') group by 1,2 order by 1,2;

-- 4) attribution identity
lyra = nova + partial + E
partial = sum over days of |{UTC whole hours: raw has ≥1 1m bar there but nova 1h has none}|
```

**Note**: the analysis scripts live in `scratch/barcov/` at the repo root (not strategy/product code; no lyra/nova code touched; gitignored). Per 2026-11-12 review M4: this report must not present those scratch outputs as permanent in-repo repro evidence — the stable repro path is the SQL above plus the 21 SHA256 fingerprints.
