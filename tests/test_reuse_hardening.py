"""Decision 0019: reuse notice, read-only --verify, attribution, numeric golden."""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest
import typer

from conftest import FakePar, PAR_PREFIX
from lyra import catalog, cli, runner
from test_runner import _STRAT, _bull_bear, _registry, _write_feature


@pytest.fixture
def env(tmp_path):
    """Same deterministic synthetic fixtures as test_runner.env."""
    data_root = tmp_path / "data"
    feat = data_root / "features" / "ohlcv_1h"
    feat.mkdir(parents=True)
    _write_feature(feat, "EURUSD", _bull_bear("EURUSD", 1.0, 10))
    _write_feature(feat, "GBPUSD", _bull_bear("GBPUSD", 1.27, 10))
    cat = catalog.Catalog(data_root / "catalog.duckdb")
    cat.upsert_feature_views(data_root)
    strat = tmp_path / "s.yaml"
    strat.write_text(_STRAT)
    return {"data_root": data_root, "strat": strat, "registry": _registry()}

TRACK = "pilot"
GOLDEN_MESSAGE = (
    "数值输出变化。如果这是有意的数值语义变化：递增 `_ENGINE_VERSION`，"
    "并在同一 commit 更新本金标和决策文档。如果不是有意的：说明引擎被意外改动。"
)
# Logical (timezone-normalized) row digests, not raw parquet bytes: parquet
# metadata/timezone rendering differs between developer machines and CI.
GOLDEN_DIGEST = {
    "signals.parquet": "cdfdc1b1c1946c4c66aec012f80a5b424ad3b61d82b750ced50f5af2a20bb4c5",
    "trades.parquet": "b4e99b913aec2268d96d5507cbe0c65a73676e53206c1d70eb00ea5ff4327801",
}
GOLDEN_METRICS = {
    "costs_bps": {"commission_round_trip": 0.0, "financing_per_day": 10.0,
                  "slippage_per_side": 0.0, "spread": 0.0},
    "instrument_failures": [],
    "per_instrument": {
        "EURUSD": {"annualized": 0.2691243116403663, "avg_bars_held": 1.0,
                   "expectancy": 0.0022104666253828856, "losing_trades": 1,
                   "net_return": 0.006631399876148657, "score": 0.2691243116403663,
                   "trade_count": 3, "win_rate": 0.6666666666666666,
                   "winning_trades": 2,
                   "monthly": [{"actual_entries": 3, "avg_bars_held": 1.0,
                                "month": "2024-01",
                                "net_return_sum": 0.006631399876148657,
                                "win_rate": 0.6666666666666666}]},
        "GBPUSD": {"annualized": 0.18837155052504675, "avg_bars_held": 1.0,
                   "expectancy": 0.001547199593634881, "losing_trades": 1,
                   "net_return": 0.004641598780904643, "score": 0.18837155052504675,
                   "trade_count": 3, "win_rate": 0.6666666666666666,
                   "winning_trades": 2,
                   "monthly": [{"actual_entries": 3, "avg_bars_held": 1.0,
                                "month": "2024-01",
                                "net_return_sum": 0.004641598780904643,
                                "win_rate": 0.6666666666666666}]},
    },
    "stop_trigger_rate": {"EURUSD": 0.0, "GBPUSD": 0.0},
}


@pytest.fixture
def cli_env(env, monkeypatch):
    workspace = env["strat"].parent / "workspace"
    monkeypatch.setattr(cli, "_registry_for", lambda *_a, **_k: env["registry"])
    monkeypatch.setattr(cli, "_workspace", lambda _c: workspace)
    return {**env, "workspace": workspace, "out": workspace / "runs"}


def _cli_kwargs(cli_env, **overrides):
    kwargs = dict(strategy=str(cli_env["strat"]),
                  data_dir=str(cli_env["data_root"]),
                  config="unused", name=None, out=str(cli_env["out"]),
                  track=TRACK, verify=False)
    kwargs.update(overrides)
    return kwargs


def _run_once(cli_env, **overrides):
    return cli.run(**_cli_kwargs(cli_env, **overrides))


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def _set_manifest(run_dir: Path, mutate) -> None:
    path = run_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


# --- B1: reuse notice --------------------------------------------------------

def test_b1_notice_on_commit_mismatch(cli_env, capsys):
    first = _run_once(cli_env)
    _set_manifest(first.out_dir, lambda m: m.update(git_commit="old123+dirty"))
    before = _snapshot(first.out_dir)
    second = _run_once(cli_env)
    out = capsys.readouterr().out
    assert second.reused is True
    assert "reused existing run" in out
    assert "note: 该 run 由 commit old123+dirty 产出" in out
    assert "--verify" in out and "_ENGINE_VERSION" in out
    assert _snapshot(second.out_dir) == before  # notice writes nothing


def test_b1_no_notice_when_commit_matches(cli_env, capsys):
    _run_once(cli_env)
    capsys.readouterr()
    second = _run_once(cli_env)
    out = capsys.readouterr().out
    assert second.reused is True
    assert "reused existing run" in out
    assert "note:" not in out


def test_b1_legacy_manifest_shows_legacy(cli_env, capsys):
    first = _run_once(cli_env)
    _set_manifest(first.out_dir, lambda m: m.pop("git_commit", None))
    _run_once(cli_env)
    out = capsys.readouterr().out
    assert "legacy" in out


# --- B2: read-only --verify --------------------------------------------------

def test_b2_identical(cli_env, capsys, monkeypatch):
    _run_once(cli_env)
    monkeypatch.setattr(cli, "_oci_run_preflight",
                        lambda *_a, **_k: pytest.fail("preflight must not run"))
    before = _snapshot(cli_env["out"])
    cli.run(**_cli_kwargs(cli_env, verify=True))
    out = capsys.readouterr().out
    assert "VERIFY: IDENTICAL" in out
    assert _snapshot(cli_env["out"]) == before


def test_b2_descriptive_only_lists_fields(cli_env, capsys, monkeypatch):
    _run_once(cli_env)
    monkeypatch.setattr(runner, "_git_commit", lambda *_a, **_k: "zzz999+dirty")
    before = _snapshot(cli_env["out"])
    cli.run(**_cli_kwargs(cli_env, verify=True))
    out = capsys.readouterr().out
    assert "VERIFY: DESCRIPTIVE_ONLY" in out
    assert "git_commit" in out
    assert _snapshot(cli_env["out"]) == before


def test_b2_numeric_difference_exits_2(cli_env, capsys, monkeypatch):
    _run_once(cli_env)
    original = runner.metrics_mod.compute_metrics

    def altered(*args, **kwargs):
        result = original(*args, **kwargs)
        result["annualized"] = result["annualized"] + 0.01
        return result

    monkeypatch.setattr(runner.metrics_mod, "compute_metrics", altered)
    monkeypatch.setattr(cli, "_oci_run_preflight",
                        lambda *_a, **_k: pytest.fail("preflight must not run"))
    before = _snapshot(cli_env["out"])
    with pytest.raises(typer.Exit) as exc:
        cli.run(**_cli_kwargs(cli_env, verify=True))
    assert exc.value.exit_code == 2
    out = capsys.readouterr().out
    assert "VERIFY: NUMERIC_DIFFERENCE" in out
    assert "annualized" in out and "_ENGINE_VERSION" in out
    assert _snapshot(cli_env["out"]) == before


def test_b2_missing_run_errors(cli_env, capsys):
    with pytest.raises(typer.Exit) as exc:
        cli.run(**_cli_kwargs(cli_env, verify=True))
    assert exc.value.exit_code == 1
    assert "VERIFY FAILED" in capsys.readouterr().err


# --- B3: attribution ---------------------------------------------------------

def test_b3_branch_mismatch_fails_closed(cli_env, capsys):
    _run_once(cli_env)
    other = cli_env["strat"].parent / "other_branch.yaml"
    other.write_text(cli_env["strat"].read_text(encoding="utf-8"), encoding="utf-8")
    before = _snapshot(cli_env["out"])
    with pytest.raises(typer.Exit) as exc:
        cli.run(**_cli_kwargs(cli_env, strategy=str(other)))
    assert exc.value.exit_code == 1
    err = capsys.readouterr().err
    assert "branch s" in err and "other_branch" in err
    assert _snapshot(cli_env["out"]) == before


def test_b3_track_mismatch_fails_closed_with_explicit_name(cli_env, capsys):
    _run_once(cli_env, name="shared")
    before = _snapshot(cli_env["out"])
    with pytest.raises(typer.Exit) as exc:
        cli.run(**_cli_kwargs(cli_env, name="shared", track="other_track"))
    assert exc.value.exit_code == 1
    err = capsys.readouterr().err
    assert "track pilot" in err and "other_track" in err
    assert _snapshot(cli_env["out"]) == before


def test_b3_legacy_sidecar_warns_and_reuses(cli_env, capsys):
    first = _run_once(cli_env)
    meta_path = first.out_dir / "run_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("branch", None)
    meta.pop("track_id", None)
    meta_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    second = _run_once(cli_env)
    assert second.reused is True
    assert "WARN: legacy run_meta.json" in capsys.readouterr().err


def test_b3_attribution_applies_to_preflight_restore(cli_env, monkeypatch, capsys):
    first = _run_once(cli_env)
    name_dir = first.out_dir.parent.parent
    prefix = f"runs/{name_dir.name}/{first.out_dir.parent.name}/{first.run_id}/"
    remote = {prefix + p.relative_to(first.out_dir).as_posix(): p.read_bytes()
              for p in first.out_dir.rglob("*") if p.is_file()}
    hidden = cli_env["workspace"] / "hidden_runs"
    hidden.mkdir(parents=True, exist_ok=True)
    name_dir.rename(hidden / name_dir.name)

    other = cli_env["strat"].parent / "other_branch.yaml"
    other.write_text(cli_env["strat"].read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(cli, "_push_transport", lambda: FakePar(objects=remote))
    monkeypatch.setattr(cli, "load_config", lambda _c: {})
    monkeypatch.setattr(cli, "oci_from_dict",
                        lambda _c: SimpleNamespace(strategies_par_url=PAR_PREFIX,
                                                   data_par_url=None))
    with pytest.raises(typer.Exit) as exc:
        cli.run(**_cli_kwargs(cli_env, strategy=str(other), name=name_dir.name))
    assert exc.value.exit_code == 1
    assert "other_branch" in capsys.readouterr().err
    # Preflight may install the verified OCI original; B3 itself writes nothing,
    # so the restored bytes must match OCI exactly (no local variant).
    restored = cli_env["out"] / name_dir.name / first.out_dir.parent.name / first.run_id
    assert (restored / "run_meta.json").read_bytes() == remote[prefix + "run_meta.json"]


# --- B4: numeric golden + payload guard -------------------------------------

def _logical_digest(path: Path) -> str:
    """Hash canonical rows with timestamps normalized to UTC (portable golden)."""
    rows = pq.read_table(path).to_pylist()

    def canon(value):
        if isinstance(value, dt.datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = dt.datetime.fromisoformat(value)
            except ValueError:
                return value  # non-time strings (instrument, exit_reason, ...)
        else:
            return value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc).isoformat()

    canonical = [{k: canon(v) for k, v in row.items()} for row in rows]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _assert_golden(run_dir: Path) -> None:
    for fname, expected in GOLDEN_DIGEST.items():
        actual = _logical_digest(run_dir / fname)
        assert actual == expected, GOLDEN_MESSAGE + f" ({fname})"
    payload = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    for key, expected in GOLDEN_METRICS.items():
        assert payload.get(key) == expected, GOLDEN_MESSAGE + f" (metrics.json:{key})"


def test_b4_numeric_golden_passes(env, tmp_path):
    res = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"], out_dir=tmp_path / "runs")
    _assert_golden(res.out_dir)


def test_b4_numeric_golden_fails_on_engine_change(env, tmp_path, monkeypatch):
    original = runner.metrics_mod.compute_metrics

    def altered(*args, **kwargs):
        result = original(*args, **kwargs)
        result["annualized"] = result["annualized"] + 0.01
        return result

    monkeypatch.setattr(runner.metrics_mod, "compute_metrics", altered)
    res = runner.run_strategy(env["strat"], env["data_root"],
                              registry=env["registry"], out_dir=tmp_path / "runs")
    with pytest.raises(AssertionError) as exc:
        _assert_golden(res.out_dir)
    assert GOLDEN_MESSAGE in str(exc.value)
    assert "_ENGINE_VERSION" in str(exc.value)


def test_run_id_payload_keys_are_fixed():
    keys = set(inspect.signature(runner._compute_run_id).parameters)
    assert keys == {
        "strategy_yaml_bytes", "plan_hash", "feature_version", "compiler_version",
        "engine_version", "duckdb_version", "params", "trading_days_basis",
        "counter_fingerprint", "data_digest", "feature_snapshot_digest",
        "schema_version", "spec_id", "direction",
    }
