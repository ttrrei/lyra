"""OANDA historical-candle backfill / gap-fill (0002 §3.5).

The OCI-PAR pull pipeline (``lyra pull``) downloads *whatever is already in
the PAR prefix*. This module is the complementary tool: fetch a specific
``(instrument, time window)`` of 1-minute candles straight from the OANDA
API (moneta's proven approach, re-implemented independently) and drop the
result into ``raw_csv/<instrument>/`` so ``lyra pull``'s clean step picks it
up — clean's recursive ``**/*.csv`` glob makes per-instrument sub-directories
first-class.

Design notes (carried from moneta ``pipeline/extract_oanda.py``):

* **5000-candle page cap** — OANDA rejects ``count`` together with
  ``from``+``to`` and caps a response at 5000 candles, so a window is
  requested in windows of ``PAGE_SIZE - 1`` candles using ``from``/``to``,
  each window starting one candle before the previous window's last
  timestamp (deliberate overlap; de-duplicated by ``(instrument, time)``
  downstream in clean).
* **Calendar-month chunking + resume** — a backfill is written as one CSV
  per UTC calendar month under ``raw_csv/<instrument>/``; a month that is
  already present (by name and non-zero size) is skipped, so an interrupted
  run resumes without re-downloading finished months.
* **Token is a secret** — it lives only in the gitignored
  ``config/config.yml`` under ``oanda.api_token`` and is never committed
  (moneta's convention). An empty token raises :class:`OandaConfigMissing`
  so a mis-configured run is loud, not silent.
* **UTC only** — no local/DST conversion anywhere; all timestamps are
  round-tripped as ISO-8601 ``...Z`` strings.

The output CSV schema matches the bronze input contract exactly
(``instrument,is_complete,time,volume,mid_*,bid_*,ask_*``) so it flows
through ``clean`` unmodified.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PAGE_SIZE = 5000
RAW_COLUMNS = [
    "instrument",
    "is_complete",
    "time",
    "volume",
    "mid_o",
    "mid_h",
    "mid_l",
    "mid_c",
    "bid_o",
    "bid_h",
    "bid_l",
    "bid_c",
    "ask_o",
    "ask_h",
    "ask_l",
    "ask_c",
]
GRANULARITY_MINUTES = {
    "S5": 5 / 60,
    "S10": 10 / 60,
    "S15": 15 / 60,
    "S30": 30 / 60,
    "M1": 1,
    "M2": 2,
    "M4": 4,
    "M5": 5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H2": 120,
    "H3": 180,
    "H4": 240,
    "H6": 360,
    "H8": 480,
    "H12": 720,
    "D": 1440,
    "W": 10080,
    "M": 43200,
}
PRICE_CHOICES = ("M", "B", "A", "MB", "MA", "BA", "MBA")


class OandaError(RuntimeError):
    """Base class for OANDA backfill failures."""


class OandaConfigMissing(OandaError):
    """The configured token is empty or the config has no ``oanda`` section."""


def _build_session() -> requests.Session:
    """HTTP session with retry/backoff for transient OANDA failures (429/5xx)."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _parse_time(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (accepts trailing ``Z``) to an aware UTC dt."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    """Render an aware dt as a UTC ``...Z`` string for the OANDA API."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _advance_candles(value: datetime, granularity: str, count: int) -> datetime:
    """Return *value* advanced by *count* candles of *granularity*.

    For minute/hour granularities we add ``count * minutes`` of seconds;
    for D/W/M we step the date component (calendar-aware for months).
    """
    minutes = GRANULARITY_MINUTES.get(granularity.upper())
    if minutes is None:
        raise OandaError(f"Unsupported OANDA granularity: {granularity!r}")
    g = granularity.upper()
    if g in ("D", "W", "M"):
        if g == "D":
            return value + timedelta(days=count)
        if g == "W":
            return value + timedelta(weeks=count)
        # M: advance month index (moneta's approach — day-of-month clamped).
        month_index = value.year * 12 + value.month - 1 + count
        year, month_offset = divmod(month_index, 12)
        month = month_offset + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)
    # Minute/hour: advance by count * minutes * 60 seconds.
    return value + timedelta(seconds=int(count * minutes * 60))


def fetch_candles(
    instrument: str,
    time_from: str,
    time_to: str,
    *,
    token: str,
    host: str = "api-fxpractice.oanda.com",
    granularity: str = "M1",
    price: str = "MBA",
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch 1-minute candles for *instrument* in the inclusive range
    ``[time_from, time_to]`` (UTC) from the OANDA v3 API.

    Returns a list of OANDA candle dicts (already filtered to the requested
    range and de-duplicated by ``time``). The API's 5000-candle response
    cap is honoured by paging in ``PAGE_SIZE - 1`` candle windows with one
    candle of deliberate overlap per window (de-duplicated downstream).
    """
    if not token:
        raise OandaConfigMissing(
            "OANDA api_token is empty. Set it in config/config.yml under "
            "'oanda.api_token' (a secret; never committed)."
        )
    start = _parse_time(time_from)
    end = _parse_time(time_to)
    if end < start:
        raise OandaError("--to must be at or after --from")
    granularity = granularity.upper()
    if granularity not in GRANULARITY_MINUTES:
        raise OandaError(f"Unsupported OANDA granularity: {granularity!r}")
    price = price.upper()
    if price not in PRICE_CHOICES:
        raise OandaError(f"Unsupported OANDA price component: {price!r}")
    if not instrument or "/" in instrument:
        raise OandaError(
            "Instrument must be an OANDA instrument name such as GBP_USD"
        )

    close_session = session is None
    http = session or _build_session()
    url = f"https://{host}/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {token}"}
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_wanted = _advance_candles(end, granularity, 1)
    cursor = start
    try:
        while True:
            window_end = _advance_candles(cursor, granularity, PAGE_SIZE - 1)
            chunk_to = min(window_end, last_wanted)
            params = {
                "from": _format_time(cursor),
                "to": _format_time(chunk_to),
                "granularity": granularity,
                "price": price,
                "smooth": "false",
            }
            response = http.get(url, params=params, headers=headers, timeout=60)
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                detail = (response.text or "").strip()
                message = f"OANDA returned HTTP {response.status_code} {response.reason}"
                if detail:
                    message += f": {detail}"
                raise requests.HTTPError(message, response=response) from exc
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("errorMessage"):
                raise OandaError(f"OANDA error: {payload.get('errorMessage', payload)!r}")
            candles = payload.get("candles")
            if not isinstance(candles, list):
                raise OandaError(f"Unexpected OANDA response: {payload!r}")

            for candle in candles:
                candle_time = candle.get("time")
                if not candle_time or candle_time in seen:
                    continue
                parsed_time = _parse_time(candle_time)
                if parsed_time < start or parsed_time > end:
                    continue
                collected.append(candle)
                seen.add(candle_time)

            if chunk_to >= last_wanted:
                break
            if chunk_to <= cursor:
                raise OandaError("OANDA time window did not advance")
            cursor = chunk_to
    finally:
        if close_session:
            http.close()

    collected.sort(key=lambda candle: candle["time"])
    return collected


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def candles_to_rows(instrument: str, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OANDA candle dicts to the shared raw-candle CSV schema."""
    rows: list[dict[str, Any]] = []
    for candle in candles:
        row: dict[str, Any] = {
            "instrument": instrument,
            "is_complete": bool(candle.get("complete", True)),
            "time": candle.get("time"),
            "volume": candle.get("volume", 0),
        }
        for component in ("mid", "bid", "ask"):
            values = candle.get(component) or {}
            for field in ("o", "h", "l", "c"):
                row[f"{component}_{field}"] = _number(values.get(field))
        rows.append(row)
    rows.sort(key=lambda r: r.get("time") or "")
    return rows


def write_csv_atomic(rows: list[dict[str, Any]], path: Path) -> Path:
    """Atomically write candle rows to a CSV compatible with clean (0002 §3.3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in RAW_COLUMNS})
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _chunk_path(csv_root: Path, instrument: str, month_start: date, granularity: str) -> Path:
    """One CSV per instrument per UTC calendar month (moneta convention).

    ``raw_csv/<instrument>/<instrument>_<granularity>_<YYYYMM>01T000000Z.csv``.
    """
    return (
        csv_root
        / instrument
        / f"{instrument}_{granularity}_{month_start.year:04d}{month_start.month:02d}01T000000Z.csv"
    )


def _months_between(start_d: date, end_d: date) -> list[date]:
    """Inclusive list of month-start dates between *start_d* and *end_d* (UTC)."""
    if end_d < start_d:
        return []
    months: list[date] = []
    y, m = start_d.year, start_d.month
    end_y, end_m = end_d.year, end_d.month
    while (y, m) <= (end_y, end_m):
        months.append(date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def backfill_window(
    csv_root: Path,
    instrument: str,
    time_from: str,
    time_to: str,
    *,
    token: str,
    host: str = "api-fxpractice.oanda.com",
    granularity: str = "M1",
    price: str = "MBA",
    dry_run: bool = False,
    force: bool = False,
    log=print,
) -> list[Path]:
    """Fetch a window and write it as per-UTC-month CSVs under ``csv_root/<inst>/``.

    Finished months (existing file, non-zero size, matching the expected name)
    are skipped on re-run unless ``force=True`` — this is the resume contract
    (moneta's interrupted-backfill story).

    Returns the list of CSV paths written (or already present) for the window.
    """
    start = _parse_time(time_from)
    end = _parse_time(time_to)
    month_starts = _months_between(start.date(), end.date())
    if not month_starts:
        log(f"[{instrument}] window is empty (start > end); nothing to do.")
        return []

    # D2 fix (批次08): the month-end boundary is the start of the next UTC
    # month — the last candle of every month (at any supported granularity,
    # incl. S5/S10/S15/S30) now falls inside the clamped window; the previous
    # hard-coded "minus one minute" truncated the last fraction of each month.
    written: list[Path] = []
    for month in month_starts:
        # Clamp the fetch window to this UTC calendar month.
        m_start = datetime(month.year, month.month, 1, tzinfo=timezone.utc)
        if month.month == 12:
            next_month_start = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month_start = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
        # The window end must stay strictly inside this calendar month:
        # OANDA treats ``to`` inclusively, so a boundary at the next month's
        # start would admit a candle from the following month. One second
        # before it is the last instant of this month (moneta: ``-1min`` for
        # M1; one second is granularity-neutral and keeps S5/S10/S15/S30
        # whole — the last candle of every month now falls inside).
        m_end = min(next_month_start - timedelta(seconds=1), end)
        m_start = max(m_start, start)
        # D2 fix (批次08): a clamped window can invert (start in the last
        # instant of the month) — skip it loudly instead of crashing in
        # fetch_candles.
        if m_end < m_start:
            log(f"[{instrument}] month {month:%Y-%m} window is empty after "
                f"clamping; skipping.")
            continue
        out = _chunk_path(csv_root, instrument, month, granularity)
        if out.exists() and out.stat().st_size > 0 and not force:
            log(f"[{instrument}] month {month:%Y-%m} already present ({out.name}); skipping.")
            written.append(out)
            continue
        if dry_run:
            log(f"[{instrument}] dry-run: would fetch {month:%Y-%m} -> {out.name}")
            written.append(out)
            continue
        candles = fetch_candles(
            instrument,
            _format_time(m_start),
            _format_time(m_end),
            token=token,
            host=host,
            granularity=granularity,
            price=price,
        )
        rows = candles_to_rows(instrument, candles)
        write_csv_atomic(rows, out)
        log(f"[{instrument}] fetched {len(rows)} candles for {month:%Y-%m} -> {out}")
        written.append(out)
    return written
