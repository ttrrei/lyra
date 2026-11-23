"""Read-only diagnostics over immutable run artifacts."""
from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq

from lyra.diagnostics import exit_month_diagnostics


def test_exit_month_diagnostics_groups_and_zero_fills_per_instrument(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    metrics = {
        "window": {"start": "2025-01-02 00:00:00", "end": "2025-03-30 00:00:00"},
        "per_instrument": {"AAA": {}, "BBB": {}},
        "instrument_failures": [],
    }
    metrics_path = run / "metrics.json"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    original_metrics = metrics_path.read_bytes()
    pq.write_table(pa.table({
        "instrument": ["AAA", "AAA", "BBB"],
        "exit_time": ["2025-01-10 00:00:00", "2025-03-02 00:00:00",
                      "2025-02-15 00:00:00"],
        "net_return": [0.1, -0.04, 0.02],
        "bars_held": [4, 2, 3],
    }), run / "trades.parquet")

    rows = exit_month_diagnostics(run)
    by_key = {(r["instrument"], r["exit_month"]): r for r in rows}
    assert len(rows) == 6
    assert by_key[("AAA", "2025-01")]["exit_month_trade_count"] == 1
    assert by_key[("AAA", "2025-01")]["exit_month_net_return_sum"] == 0.1
    assert by_key[("AAA", "2025-02")]["exit_month_trade_count"] == 0
    assert by_key[("AAA", "2025-02")]["exit_month_win_rate"] == 0.0
    assert by_key[("BBB", "2025-01")]["exit_month_trade_count"] == 0
    assert metrics_path.read_bytes() == original_metrics


def test_exit_month_diagnostics_empty_window_returns_no_rows(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "metrics.json").write_text(
        json.dumps({"window": {"start": None, "end": None}, "per_instrument": {}}),
        encoding="utf-8")
    pq.write_table(pa.table({"instrument": [], "exit_time": [],
                             "net_return": [], "bars_held": []}),
                   run / "trades.parquet")
    assert exit_month_diagnostics(run) == []
