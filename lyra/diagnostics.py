"""Read-only diagnostics derived from immutable run artifacts."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def exit_month_diagnostics(run_dir: Path) -> list[dict[str, Any]]:
    """Group trades by exit month and zero-fill the run window per instrument.

    This is an independent diagnostic projection. It never updates metrics.json
    or any other run artifact.
    """
    run_dir = Path(run_dir)
    metrics_path = run_dir / "metrics.json"
    trades_path = run_dir / "trades.parquet"
    if not metrics_path.is_file() or not trades_path.is_file():
        raise FileNotFoundError(f"run needs metrics.json and trades.parquet: {run_dir}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    window = metrics.get("window") or {}
    if not window.get("start") or not window.get("end"):
        return []

    def parse_time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"invalid run window timestamp: {value!r}")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    start, end = parse_time(window.get("start")), parse_time(window.get("end"))
    if start > end:
        raise ValueError("run window start is after end")
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1

    import pyarrow.parquet as pq
    rows = pq.read_table(trades_path, columns=[
        "instrument", "exit_time", "net_return", "bars_held",
    ]).to_pylist()
    instruments = set(metrics.get("per_instrument", {}))
    instruments.update(f.get("instrument") for f in metrics.get("instrument_failures", [])
                       if f.get("instrument"))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        instrument = row.get("instrument")
        exit_time = row.get("exit_time")
        if not instrument or not exit_time:
            continue
        instruments.add(instrument)
        month_key = str(exit_time)[:7]
        grouped.setdefault((instrument, month_key), []).append(row)

    out = []
    for instrument in sorted(instruments):
        for month_key in months:
            trades = grouped.get((instrument, month_key), [])
            returns = [float(t.get("net_return") or 0.0) for t in trades]
            bars = [int(t.get("bars_held") or 0) for t in trades]
            out.append({
                "instrument": instrument,
                "exit_month": month_key,
                "exit_month_trade_count": len(trades),
                "exit_month_net_return_sum": sum(returns),
                "exit_month_win_rate": (sum(1 for value in returns if value > 0) / len(returns)
                                         if returns else 0.0),
                "exit_month_avg_bars_held": (sum(bars) / len(bars) if bars else 0.0),
            })
    return out
