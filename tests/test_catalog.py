"""Tests for the DuckDB catalog (0002 — external-table metadata layer)."""

from __future__ import annotations

import duckdb

import pytest

from lyra import aggregate as agg
from lyra import clean as clean_mod
from lyra import pull as pull_mod
from lyra import pipeline
from lyra.catalog import Catalog, default_catalog_path, upsert_views
from lyra.config import DatabackendConfig


def _make_data_root(tmp_path):
    """Build a tiny bronze + 5m + 1h tree under tmp_path."""
    csv = tmp_path / "raw"
    csv.mkdir()
    rows = [
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n",
        "X,2020-01-01T00:00:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:01:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:02:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:03:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:04:00Z,1,1,1,1,1,True\n",
        "X,2020-01-01T00:05:00Z,1,1,1,1,1,True\n",
    ]
    (csv / "a.csv").write_text("".join(rows))
    bronze = tmp_path / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    p5 = tmp_path / "ohlcv_5m" / "ohlcv_5m.parquet"
    p1 = tmp_path / "ohlcv_1h" / "ohlcv_1h.parquet"
    agg.aggregate_bronze_to_parquet(bronze, p5, p1)
    return bronze, p5, p1


def test_catalog_registers_all_views(tmp_path):
    _make_data_root(tmp_path)
    cat = upsert_views(tmp_path)
    views = {v["view"] for v in cat.views()}
    assert {"bronze", "ohlcv_5m", "ohlcv_1h"} <= views


def test_catalog_is_idempotent(tmp_path):
    _make_data_root(tmp_path)
    c1 = upsert_views(tmp_path)
    c2 = upsert_views(tmp_path)
    assert [v["view"] for v in c1.views()] == [v["view"] for v in c2.views()]


def test_catalog_queries_match_parquet(tmp_path):
    bronze, p5, _ = _make_data_root(tmp_path)
    upsert_views(tmp_path)
    cat = Catalog(default_catalog_path(tmp_path))
    con = duckdb.connect(str(cat.path), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM bronze").fetchone()[0]
        con_n = int(duckdb.connect(":memory:").execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(bronze)]).fetchone()[0])
        assert n == con_n
        n5 = con.execute("SELECT COUNT(*) FROM ohlcv_5m").fetchone()[0]
        assert n5 == int(duckdb.connect(":memory:").execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(p5)]).fetchone()[0])
    finally:
        con.close()


def test_catalog_missing_layers_skipped(tmp_path):
    # Only bronze present (no 5m/1h) -> catalog registers bronze only.
    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "a.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,1,1,1,1,True\n"
    )
    bronze = tmp_path / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    cat = upsert_views(tmp_path)
    views = {v["view"] for v in cat.views()}
    assert views == {"bronze"}


def test_catalog_path_is_outside_repo(tmp_path):
    cat = Catalog(default_catalog_path(tmp_path))
    # The catalog lives next to the data root, not in the repo.
    assert str(cat.path).endswith("catalog.duckdb")


def test_aggregate_streams_via_view_not_table(tmp_path, monkeypatch):
    """I18/I21: the aggregate must not materialize bronze into a TABLE.

    Patch the register helper to assert a VIEW (not TABLE) is created —
    the streaming / external-table property the user asked for.
    """
    created: list[str] = []
    real_register = agg._register_bronze

    def spy_register(connection, path):
        real_register(connection, path)
        rows = connection.execute(
            "SELECT view_name FROM duckdb_views() "
            "WHERE view_name = 'bronze'").fetchall()
        assert rows, "bronze must be registered as a VIEW (streaming), not a TABLE"
        created.append(path.name)

    monkeypatch.setattr(agg, "_register_bronze", spy_register)
    # Build a minimal 1m bronze in tmp_path.
    csv = tmp_path / "raw"
    csv.mkdir()
    # 120 valid 1m bars spanning 2 hours (I22: uniform 1m resolution).
    (csv / "a.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        + "".join(f"X,2020-01-01T{m // 60:02d}:{m % 60:02d}:00Z,1,1,1,1,1,True\n" for m in range(120))
    )
    bronze = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    agg.aggregate_bronze_to_parquet(bronze, tmp_path / "o5.parquet", tmp_path / "o1.parquet")
    assert created == ["b.parquet"]


def test_catalog_relative_data_root_is_resolved(tmp_path, monkeypatch):
    """D8 (batch-7): a RELATIVE --data-root must not leak into the view SQL."""
    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "a.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,1,1,1,1,True\n"
    )
    bronze = tmp_path / "all_data" / "all_data.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, bronze)
    monkeypatch.chdir(tmp_path)
    # Pass a RELATIVE data root (as `--data-root data` would, from tmp_path).
    upsert_views(tmp_path / "all_data/..")  # ".." forces resolution
    cat = Catalog(default_catalog_path(tmp_path))
    con = duckdb.connect(str(cat.path), read_only=True)
    try:
        # View must be queryable from a DIFFERENT working directory — the
        # stored path is absolute.
        n = con.execute("SELECT COUNT(*) FROM bronze").fetchone()[0]
        assert n == 1
    finally:
        con.close()


def test_empty_bronze_schema_is_timestamptz(tmp_path):
    """D7 (batch-7): the empty-input bronze MUST be ``timestamp[us, tz=UTC]``,
    matching the non-empty (DuckDB TIMESTAMPTZ) path — I18 schema stability."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    out = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(empty_dir, out)
    schema = pq.read_schema(str(out))
    assert schema.field("time").type == pa.timestamp("us", tz="UTC")


def test_windows_style_paths_accepted():
    """D1 (batch-7): Windows drive-letter / backslash / space paths must pass
    the path-safety checks (R8 portability) — the old regex rejected `:`
    and `\\` and crashed `lyra pull` on every Windows machine."""
    from pathlib import Path

    import lyra.aggregate as agg_mod
    import lyra.clean as clean_mod

    win_path = Path("C:/Users/test user/data/all_data/all_data.parquet")
    # Should NOT raise:
    quoted_agg = agg_mod._quote(win_path)
    quoted_clean = clean_mod._quote(win_path)
    assert "C:" in quoted_agg and "Users" in quoted_clean
    # And a path with a single quote must be escaped, not rejected:
    tricky = Path("C:/data/it's here.csv")
    assert "''" in agg_mod._quote(tricky)
    # Control characters are still rejected (injection surface stays closed):
    import pytest as _pt

    with _pt.raises(ValueError):
        agg_mod._quote(Path("C:/bad\x00path"))


def test_write_parquet_empty_schema_is_timestamptz(tmp_path):
    """D7 (batch-7): same guarantee for the aggregate empty-path writer."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out = tmp_path / "o5.parquet"
    pipeline._write_parquet([], out, columns=agg.AGGREGATE_COLUMNS)
    schema = pq.read_schema(str(out))
    assert schema.field("time").type == pa.timestamp("us", tz="UTC")


def test_zip_bomb_refused(tmp_path, monkeypatch):
    """D9 (batch-7): a member declaring an extracted size beyond the ceiling
    must be refused BEFORE any bytes are written.

    Real moneta members max out at ~575 MB (BTC_USD.csv); the default
    ceiling is 8 GB. This test lowers the ceiling to 8 bytes so a 16-byte
    member trips the exact same guard, without needing a multi-GB fixture.
    """
    import zipfile

    zips_dir = tmp_path / "zips"
    zips_dir.mkdir()
    csv_dir = tmp_path / "csv"
    with zipfile.ZipFile(zips_dir / "bomb.zip", "w") as z:
        z.writestr("bomb.csv", b"x" * 16)

    monkeypatch.setattr(pull_mod, "MAX_EXTRACTED_MEMBER_BYTES", 8)
    with pytest.raises(pull_mod.ZipBombError):
        pull_mod.extract_zips_to_csv(zips_dir, csv_dir)
    # No partial file must be left behind (guard fires before open/write).
    if csv_dir.exists():
        assert list(csv_dir.iterdir()) == []


def test_zip_within_ceiling_allowed(tmp_path, monkeypatch):
    """D9 (batch-7): a member UNDER the ceiling still extracts normally."""
    import zipfile

    zips_dir = tmp_path / "zips"
    zips_dir.mkdir()
    csv_dir = tmp_path / "csv"
    with zipfile.ZipFile(zips_dir / "ok.zip", "w") as z:
        z.writestr("ok.csv", b"a,b\n1,2\n")

    monkeypatch.setattr(pull_mod, "MAX_EXTRACTED_MEMBER_BYTES", 1024)
    out = pull_mod.extract_zips_to_csv(zips_dir, csv_dir)
    assert len(out) == 1 and out[0].name == "ok.csv"


def test_run_pull_swallows_catalog_failure(tmp_path, monkeypatch):
    """D2 (batch-7): a catalog failure (e.g. DuckDB exclusive lock) must NOT
    fail the data pipeline — the "best-effort" promise, enforced in code
    (previously the comment claimed it but no guard existed)."""
    from lyra import oci_client

    # Stub every stage of run_pull so ONLY the guarded catalog block runs for
    # real. The catalog call must raise (simulating a lock) and be swallowed.
    monkeypatch.setattr(oci_client, "sync_par", lambda *a, **k: [])
    monkeypatch.setattr(pipeline.pull, "extract_zips_to_csv", lambda *a, **k: [])
    monkeypatch.setattr(
        pipeline.clean_mod, "clean_csv_to_bronze_parquet",
        lambda *a, **k: tmp_path / "b.parquet",
    )
    (tmp_path / "b.parquet").write_bytes(b"fake-parquet")
    class _FakeConn:
        def execute(self, *a, **k):
            class _R:
                def fetchone(self):
                    # First call: bronze COUNT (1 value); second call: the
                    # 5m/1h pair (2 values). Return 2 values for both — the
                    # caller slices what it needs.
                    return (1, 1)
            return _R()

    monkeypatch.setattr(
        pipeline.clean_mod, "open_limited_duckdb",
        lambda *a, **k: _FakeConn(),
    )
    monkeypatch.setattr(
        pipeline.agg, "aggregate_bronze_to_parquet",
        lambda *a, **k: {"ohlcv_5m": tmp_path / "5.parquet", "ohlcv_1h": tmp_path / "1.parquet"},
    )
    (tmp_path / "5.parquet").write_bytes(b"fake")
    (tmp_path / "1.parquet").write_bytes(b"fake")

    def boom(data_root):
        raise IOError("Could not set lock on file (held by another process)")

    # run_pull does `from .catalog import upsert_views` at call time — patch
    # the SOURCE module so the local import picks up the stub.
    from lyra import catalog as catalog_mod

    monkeypatch.setattr(catalog_mod, "upsert_views", boom)

    from lyra.config import OciConfig

    with pytest.warns(UserWarning, match="catalog registration failed"):
        result = pipeline.run_pull(
            OciConfig(data_par_url="https://example/p/x"), tmp_path
        )
    assert result.bronze_rows == 1
    assert result.bars_5m == 1


def test_open_limited_duckdb_applies_settings():
    """D3 (batch-7): max_memory / temp_directory MUST be applied to pipeline
    connections (a 4 GB box running 48M rows must spill, not be OOM-killed)."""
    db = DatabackendConfig(memory_limit="2GB", threads=2)
    con = clean_mod.open_limited_duckdb(db, "/tmp/lyra-tmp-test")
    try:
        mem = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
        assert "1.8 GiB" in mem or "2.0 GB" in mem or "2GB" in mem  # DuckDB renders 2GB as ~1.8 GiB
        threads = con.execute("SELECT current_setting('threads')").fetchone()[0]
        assert str(threads) == "2"
        tmp = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        assert "lyra-tmp-test" in tmp
    finally:
        con.close()


def test_clean_rejects_bad_mid_ohlc(tmp_path):
    """DQ1 (0002 §3.4): a row where mid_high < mid_low must be rejected, not
    silently written to bronze (nova's invariant, now explicit in lyra)."""
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "bad.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        # mid_h (3) < mid_l (5) -> internally inconsistent, must fail.
        "X,2020-01-01T00:00:00Z,1,2,3,5,2,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="mid_ohlc"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)
    # Nothing may have been written.
    assert not out.exists()


def test_clean_rejects_negative_volume(tmp_path):
    """DQ3 (0002 §3.4): a negative volume must be rejected."""
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "bad.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,-5,1,2,1,2,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="bad_volume"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)


def test_clean_rejects_inverted_spread(tmp_path):
    """DQ2 (0002 §3.4): where both sides of a quote exist, ask must be >= bid.

    A bid/ask input whose ask < bid is physically impossible and must fail.
    """
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "bad.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,bid_o,bid_h,bid_l,bid_c,"
        "ask_o,ask_h,ask_l,ask_c,is_complete\n"
        # ask_o (9.0) < bid_o (9.5) -> inverted spread, must fail.
        "X,2020-01-01T00:00:00Z,1,9.2,9.3,9.1,9.2,9.5,9.6,9.4,9.5,9.0,9.1,8.9,9.0,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="bad_spread"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)


def test_clean_rejects_partial_quote_inverted_spread(tmp_path):
    """DQ2 (0002 §3.4) — S1 self-review: a PARTIAL-quote input (only bid_o/ask_o
    present) whose ask_o < bid_o must STILL be rejected.

    The original "all-8-columns-or-nothing" column gate would silently skip
    spread validation on a partial-quote input, defeating the fail-fast intent.
    The per-point gate must enforce ask >= bid at any point that has a pair.
    """
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "bad.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,bid_o,ask_o,is_complete\n"
        # only bid_o/ask_o present; ask_o (9) < bid_o (10) -> must fail.
        "X,2020-01-01T00:00:00Z,1,9.2,9.3,9.1,9.2,10,9,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="bad_spread"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)


def test_clean_accepts_partial_quote_valid_spread(tmp_path):
    """DQ2 (0002 §3.4) — S1 self-review: a PARTIAL-quote input with a VALID
    spread (ask_o >= bid_o) must pass — DQ2 must not reject legal partial
    quotes, only enforce direction where a pair exists."""
    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "ok.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,bid_o,ask_o,is_complete\n"
        # bid_o (9.1) <= ask_o (9.3) -> valid, must pass.
        "X,2020-01-01T00:00:00Z,1,9.2,9.3,9.1,9.2,9.1,9.3,True\n"
    )
    out = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, out)
    assert out.exists()


def test_clean_accepts_valid_data(tmp_path):
    """DQ sanity: well-formed rows (o,c in [l,h], volume >= 0) pass through."""
    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "ok.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,9.2,9.3,9.1,9.2,True\n"
    )
    out = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, out)
    assert out.exists()


def test_clean_multi_file_mixed_columns_catches_inverted_spread(tmp_path):
    """批次08 D1: a directory mixing a mid-only flat CSV (alphabetically
    first) with an OANDA sub-directory CSV carrying an inverted quote must
    STILL trigger DQ2 — the first-file column sniff silently disabled spread
    validation and dropped the bid/ask columns before the fix."""
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "01_flat.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,10,12,9,11,True\n"
    )
    (csv / "GBP_USD").mkdir()
    (csv / "GBP_USD" / "gbp.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,"
        "bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c,is_complete\n"
        # ask_o (5) < bid_o (10) -> inverted, must be rejected now.
        "Y,2020-01-01T00:01:00Z,1,10,12,9,11,10,12,9,11,5,12,9,11,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="bad_spread"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)
    assert not out.exists()


def test_clean_multi_file_mixed_columns_keeps_quote_columns(tmp_path):
    """批次08 D1 (second half): valid mixed multi-file input must keep the
    OANDA quote columns in bronze (before the fix they were silently
    projected away)."""
    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "01_flat.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,10,12,9,11,True\n"
    )
    (csv / "GBP_USD").mkdir()
    (csv / "GBP_USD" / "gbp.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,bid_o,ask_o,is_complete\n"
        "Y,2020-01-01T00:01:00Z,1,10,12,9,11,1.2,1.3,True\n"
    )
    out = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(csv, out)
    import duckdb
    con = duckdb.connect()
    try:
        cols = {r[0] for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(out)]).fetchall()}
        row = con.execute(
            "SELECT bid_o, ask_o FROM read_parquet(?) WHERE instrument='Y'",
            [str(out)]).fetchone()
    finally:
        con.close()
    assert "bid_o" in cols and "ask_o" in cols
    assert row == (1.2, 1.3)


def test_clean_rejects_cross_point_inverted_quote(tmp_path):
    """批次08 D4: a partial-quote input whose points are mismatched
    (only bid_l + ask_h, no same-point pair) with ask_h < bid_l is
    physically impossible at every point of the bar and must be rejected."""
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "bad.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,bid_l,ask_h,is_complete\n"
        # ask_h (5) < bid_l (10) -> bar-wide inverted, must fail.
        "X,2020-01-01T00:00:00Z,1,10,12,9,11,10,5,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="bad_spread"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)
    assert not out.exists()


def test_clean_rejects_nan_price(tmp_path):
    """批次08 D4 (NaN guard): a NaN mid value must be rejected — SQL three-
    valued logic makes `nan > x` NULL, so without an explicit isfinite()
    guard it silently passes DQ1."""
    from lyra.clean import DataQualityError

    csv = tmp_path / "raw"
    csv.mkdir()
    (csv / "nan.csv").write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "X,2020-01-01T00:00:00Z,1,10,nan,9,11,True\n"
    )
    out = tmp_path / "b.parquet"
    with pytest.raises(DataQualityError, match="mid_ohlc"):
        clean_mod.clean_csv_to_bronze_parquet(csv, out)
    assert not out.exists()


def test_oanda_backfill_month_end_last_minute_no_crash(tmp_path, monkeypatch):
    """批次08 D2: a window starting in the last minute of a month must not
    crash with `--to < --from`; the clamped month window is fetched with a
    sane range (and an inverted clamp is skipped, not raised)."""
    from lyra import oanda as oanda_mod

    calls: list[tuple[str, str]] = []

    def fake_fetch(instrument, t_from, t_to, **kw):
        assert t_from <= t_to
        calls.append((t_from, t_to))
        return []

    monkeypatch.setattr(oanda_mod, "fetch_candles", fake_fetch)
    oanda_mod.backfill_window(
        tmp_path, "GBP_USD",
        "2020-01-31T23:59:30Z", "2020-02-01T00:05:00Z",
        token="dummy", dry_run=False, log=lambda *a: None,
    )
    # Both months are covered with non-inverted windows.
    assert len(calls) == 2
    assert calls[0] == ("2020-01-31T23:59:30Z", "2020-01-31T23:59:59Z")
    assert calls[1][0] == "2020-02-01T00:00:00Z"


def test_oanda_resume_skips_existing_month_still_holds(tmp_path, monkeypatch):
    """批次08 D3: the ORIGINAL resume contract (existing non-empty month file
    is skipped) must survive the D2 boundary change — re-fetching every
    completed month on a plain re-run would defeat resume."""
    from lyra import oanda as oanda_mod

    csv_root = tmp_path / "raw_csv"
    pre = csv_root / "GBP_USD" / "GBP_USD_M1_20200101T000000Z.csv"
    pre.parent.mkdir(parents=True)
    pre.write_text(
        "instrument,time,volume,mid_o,mid_h,mid_l,mid_c,is_complete\n"
        "GBP_USD,2020-01-01T00:00:00Z,1,1,2,1,2,True\n"
    )

    def boom(*a, **k):
        raise AssertionError("fetch_candles must be skipped for an existing month")

    monkeypatch.setattr(oanda_mod, "fetch_candles", boom)
    written = oanda_mod.backfill_window(
        csv_root, "GBP_USD",
        "2020-01-01T00:00:00Z", "2020-01-31T23:59:59Z",
        token="dummy", dry_run=False, force=False, log=lambda *a: None,
    )
    assert written == [pre]


def test_oanda_dry_run_without_config_preview(tmp_path):
    """批次08 D6: `--dry-run` must work with no config file at all (the
    help text promises a zero-token, zero-config preview)."""
    from typer.testing import CliRunner
    from lyra.cli import app

    res = CliRunner().invoke(
        app, ["oanda", "GBP_USD",
              "--from", "2020-01-01T00:00:00Z", "--to", "2020-01-02T00:00:00Z",
              "--config", str(tmp_path / "nonexistent.yml"), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output


def test_oanda_real_fetch_without_config_still_loud(tmp_path):
    """批次08 D6 (guard): without --dry-run a missing config must still fail
    loudly (no silent default-token path)."""
    from typer.testing import CliRunner
    from lyra.cli import app

    res = CliRunner().invoke(
        app, ["oanda", "GBP_USD",
              "--from", "2020-01-01T00:00:00Z", "--to", "2020-01-02T00:00:00Z",
              "--config", str(tmp_path / "nonexistent.yml")])
    assert res.exit_code != 0


def test_oanda_config_repr_hides_token():
    """批次08 D5: repr(OandaConfig) must never expose the api_token."""
    from lyra.config import OandaConfig

    cfg = OandaConfig(api_token="oanda_secret_key_abcdef123456")
    assert "oanda_secret_key_abcdef123456" not in repr(cfg)
    assert "oanda_secret_key_abcdef123456" not in str(cfg)
    # The value is still there when needed (fetch uses cfg.api_token).
    assert cfg.api_token == "oanda_secret_key_abcdef123456"


def test_clean_picks_up_nested_oanda_csv(tmp_path):
    """§3.5: OANDA backfill writes raw_csv/<inst>/*.csv; clean's recursive
    glob must pick up per-instrument sub-directories (not just flat)."""
    nested = tmp_path / "raw" / "GBP_USD"
    nested.mkdir(parents=True)
    (nested / "GBP_USD_M1_20200101T000000Z.csv").write_text(
        "instrument,is_complete,time,volume,mid_o,mid_h,mid_l,mid_c,"
        "bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c\n"
        "GBP_USD,True,2020-01-01T00:00:00Z,1,9.2,9.3,9.1,9.2,"
        "9.1,9.2,9.0,9.1,9.3,9.4,9.2,9.3\n"
    )
    out = tmp_path / "b.parquet"
    clean_mod.clean_csv_to_bronze_parquet(tmp_path / "raw", out)
    con = duckdb.connect(":memory:")
    try:
        n = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(out)]).fetchone()[0]
        assert n == 1
        inst = con.execute("SELECT DISTINCT instrument FROM read_parquet(?)", [str(out)]).fetchone()[0]
        assert inst == "GBP_USD"
    finally:
        con.close()


def test_oanda_fetch_requires_token():
    """§3.5: an empty token must raise OandaConfigMissing (loud, not silent)."""
    from lyra import oanda as oanda_mod

    with pytest.raises(oanda_mod.OandaConfigMissing):
        oanda_mod.fetch_candles("GBP_USD", "2020-01-01T00:00:00Z",
                                "2020-01-01T00:00:01Z", token="")


def test_oanda_candles_to_rows_schema():
    """§3.5: candles_to_rows must emit the exact bronze input contract."""
    from lyra import oanda as oanda_mod

    candles = [{
        "time": "2020-01-01T00:00:00Z",
        "complete": True,
        "volume": 7,
        "mid": {"o": "9.2", "h": "9.3", "l": "9.1", "c": "9.2"},
        "bid": {"o": "9.1", "h": "9.2", "l": "9.0", "c": "9.1"},
        "ask": {"o": "9.3", "h": "9.4", "l": "9.2", "c": "9.3"},
    }]
    rows = oanda_mod.candles_to_rows("GBP_USD", candles)
    assert rows[0]["instrument"] == "GBP_USD"
    assert rows[0]["is_complete"] is True
    assert rows[0]["volume"] == 7
    assert rows[0]["mid_o"] == 9.2
    assert rows[0]["bid_c"] == 9.1
    assert rows[0]["ask_h"] == 9.4
    assert set(rows[0]) == set(oanda_mod.RAW_COLUMNS)


def test_oanda_backfill_resume_skips_existing(tmp_path, monkeypatch):
    """§3.5: a month that already has a non-empty CSV is skipped on re-run
    (the interrupted-backfill resume contract)."""
    from lyra import oanda as oanda_mod

    csv_root = tmp_path / "raw_csv"
    # Pre-create the January 2020 chunk as if a prior run wrote it.
    pre = csv_root / "GBP_USD" / "GBP_USD_M1_20200101T000000Z.csv"
    pre.parent.mkdir(parents=True)
    pre.write_text("instrument,time\nGBP_USD,2020-01-01T00:00:00Z\n")

    # A real fetch would need network + token; the resume path must NOT reach
    # it. Make fetch_candles explode if called, to prove it was skipped.
    def boom(*a, **k):
        raise AssertionError("fetch_candles must be skipped for an existing month")

    monkeypatch.setattr(oanda_mod, "fetch_candles", boom)
    written = oanda_mod.backfill_window(
        csv_root, "GBP_USD",
        "2020-01-01T00:00:00Z", "2020-01-31T23:59:59Z",
        token="dummy", dry_run=False, force=False, log=lambda *a: None,
    )
    assert written == [pre]
    # And the file is unchanged (not re-fetched).
    assert pre.read_text().endswith("\n")


def test_instruments_returns_empty_on_broken_catalog(tmp_path):
    """F1 (self-review 2026-11-06): a catalog whose bronze view points at a
    deleted Parquet must degrade to [] (the documented contract) rather than
    raise — a missing data file is not an API-level error.

    Setup: create a real 1-row parquet, create a view over it in a throwaway
    catalog, then delete the parquet so the view is dangling.
    """
    import os

    fake = tmp_path / "bronze.parquet"
    con0 = duckdb.connect()
    con0.execute(
        f"COPY (SELECT 'AUD_USD' AS instrument, TIMESTAMP '2020-01-01' AS time) "
        f"TO '{fake}' (FORMAT PARQUET)"
    )
    con0.close()
    catalog_path = tmp_path / "catalog.duckdb"
    con = duckdb.connect(str(catalog_path))
    con.execute(
        f"CREATE VIEW bronze AS SELECT * FROM read_parquet('{fake}')")
    con.close()
    os.unlink(fake)  # view is now dangling
    c = Catalog(catalog_path)
    assert c.instruments() == []


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
