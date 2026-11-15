"""D6 (审查#128) — batch bundle parse + apply-batch all-or-nothing semantics."""
from __future__ import annotations

import json
import types

import pytest

from lyra import batch as batch_mod


# --- parse_batch -----------------------------------------------------------

def test_parse_batch_valid():
    text = """
version: 1
directions:
  - direction: d1
    track: t1
    branch: v02
    parent: v01
    driven_by_lesson: "L1"
    strategy: |
      version: 1
      id: x
"""
    items = batch_mod.parse_batch(text)
    assert len(items) == 1
    assert items[0].direction == "d1"
    assert items[0].track == "t1"
    assert items[0].branch == "v02"
    assert items[0].parent == "v01"
    assert items[0].driven_by_lesson == "L1"


def test_parse_batch_rejects_bad_version():
    with pytest.raises(batch_mod.BatchError, match="version"):
        batch_mod.parse_batch("version: 2\ndirections: []")


def test_parse_batch_rejects_missing_field():
    with pytest.raises(batch_mod.BatchError, match="required"):
        batch_mod.parse_batch(
            "version: 1\ndirections:\n  - direction: d1\n    track: t1\n")


def test_parse_batch_rejects_empty_directions():
    with pytest.raises(batch_mod.BatchError, match="directions"):
        batch_mod.parse_batch("version: 1\ndirections: []")


# --- apply-batch all-or-nothing (via the CLI runner) -----------------------

def test_apply_batch_all_or_nothing(monkeypatch, tmp_path):
    """1 valid + 1 invalid item → NOTHING is written (the valid one is not
    adopted), and the CLI exits non-zero. This is the core D6 guarantee."""
    from typer.testing import CliRunner
    from lyra import cli
    from lyra import compiler as compiler_mod
    from lyra import strategy_schema as schema_mod
    from lyra import workflow as wf

    reg = object()
    monkeypatch.setattr(cli, "_registry_for", lambda *a, **k: reg)

    good_spec = types.SimpleNamespace(
        id="good", direction="d1", parents=("v01",), driven_by_lesson="L")

    def fake_parse(path, reg):
        text = open(path, encoding="utf-8").read()
        if "bad_feature" in text:
            raise ValueError("unknown feature 'bad_feature'")
        return good_spec
    monkeypatch.setattr(schema_mod, "parse_strategy", fake_parse)
    monkeypatch.setattr(compiler_mod, "compile_strategy", lambda *a, **k: None)

    # a direction + track so a real adopt would succeed if it got that far
    d = tmp_path / "strategies" / "d1"
    d.mkdir(parents=True)
    (d / "v01.yaml").write_text("id: base\n", encoding="utf-8")
    (d / "hypothesis.md").write_text("h\n", encoding="utf-8")
    wf.create_track(tmp_path, "d1", "t1")
    monkeypatch.setattr(cli, "_workspace", lambda *a, **k: tmp_path)

    bundle = tmp_path / "b.yaml"
    bundle.write_text(
        "version: 1\ndirections:\n"
        "  - direction: d1\n    track: t1\n    branch: v02\n"
        "    parent: v01\n    driven_by_lesson: L\n"
        "    strategy: |\n      version: 1\n      id: good\n"
        "  - direction: d1\n    track: t1\n    branch: v03\n"
        "    parent: v01\n    driven_by_lesson: L\n"
        "    strategy: |\n      version: 1\n      id: bad\n"
        "      entry:\n        long:\n          all:\n"
        "            - {feature: bad_feature, op: gt, value: 1}\n",
        encoding="utf-8")

    out = CliRunner().invoke(cli.app, ["apply-batch", str(bundle)])
    assert out.exit_code != 0
    assert "NOTHING written" in out.output
    # the valid item must NOT have been adopted (all-or-nothing)
    assert not (tmp_path / "strategies" / "d1" / "t1" / "v02.yaml").exists()


# --- D9.1: prune records a reason ------------------------------------------

def test_prune_records_reason(tmp_path):
    from lyra import workflow as wf

    d = tmp_path / "strategies" / "d1"
    d.mkdir(parents=True)
    (d / "v01.yaml").write_text("id: base\n", encoding="utf-8")
    (d / "hypothesis.md").write_text("h\n", encoding="utf-8")
    wf.create_track(tmp_path, "d1", "t1")
    src = tmp_path / "a.yaml"
    src.write_text("version: 1\nid: a\n", encoding="utf-8")
    spec = types.SimpleNamespace(parents=("v01",), driven_by_lesson="L")
    wf.adopt_branch(tmp_path, "d1", "t1", "v02", src, spec)
    wf.prune_branch(tmp_path, "d1", "t1", "v02", reason="dup of v01")

    idx = next(iter((tmp_path / "strategies" / "d1" / "index").glob("*.jsonl")))
    lines = [json.loads(ln) for ln in idx.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    prunes = [ln for ln in lines if ln.get("op") == "prune"]
    assert prunes and prunes[-1].get("reason") == "dup of v01"


# --- #131 batch-safety regressions ------------------------------------------

_STRAT = """\
      version: 1
      id: s
      direction: d1
      timeframe_minutes: 60
      entry:
        long: {feature: sma_6, op: gt, value: sma_24}
        short: {feature: sma_6, op: lt, value: sma_24}
      exit:
        long: {feature: sma_6, op: lt, value: sma_24}
        short: {feature: sma_6, op: gt, value: sma_24}
        stop_loss_pct: 0.02
        max_holding_bars: 12
      execution:
        spread_bps: 2
        slippage_bps_per_side: 0.2
"""


def test_parse_batch_accepts_bundle_key_alias():
    """P0-2/B1: bundle: and items: are top-level aliases for directions:."""
    for key in ("bundle", "items"):
        text = f"version: 1\n{key}:\n  - direction: d1\n    track: t1\n" \
               f"    branch: v02\n    strategy: |\n{_STRAT}"
        items = batch_mod.parse_batch(text)
        assert items[0].direction == "d1"


def test_parse_batch_mapping_strategy_roundtrips_lossless():
    """P-4/B7: a mapping `strategy:` must survive the round-trip without the
    dict-repr mangling (backslashes, newlines, null, unicode)."""
    tricky = (
        "version: 1\n"
        "id: t\n"
        "direction: d1\n"
        "timeframe_minutes: 60\n"
        'hypothesis: "line1\\nline2  back\\\\slash  —"\n'
        "entry:\n"
        "  long: {feature: sma_6, op: gt, value: null}\n"
        "  short: {feature: sma_6, op: lt, value: null}\n"
        "exit:\n"
        "  long: {feature: sma_6, op: lt, value: null}\n"
        "  short: {feature: sma_6, op: gt, value: null}\n"
        "  stop_loss_pct: 0.02\n"
        "  max_holding_bars: 12\n"
        "execution:\n"
        "  spread_bps: 2\n"
        "  slippage_bps_per_side: 0.2\n"
    )
    text = ("version: 1\ndirections:\n"
            "  - direction: d1\n    track: t1\n    branch: v02\n"
            "    strategy:\n" + "".join("      " + ln + "\n"
                                        for ln in tricky.splitlines()
                                        if ln.strip()))
    item = batch_mod.parse_batch(text)[0]
    # Must parse as a real YAML mapping, not a dict-repr string.
    import yaml as _y
    spec = _y.safe_load(item.strategy_text)
    assert isinstance(spec, dict) and spec["id"] == "t"
    assert "line1\nline2  back\\slash  —" == spec["hypothesis"]


def test_apply_batch_bad_strategy_yaml_is_a_clean_error(tmp_path):
    """B5: a malformed strategy YAML produces a clean CLI error (the item
    name + a SchemaError/YAML message), not a raw traceback dump."""
    from typer.testing import CliRunner
    from lyra import cli
    ws = tmp_path / "ws"
    (ws / "strategies" / "d1").mkdir(parents=True)
    bundle = tmp_path / "b.yaml"
    bundle.write_text(
        "version: 1\ndirections:\n"
        "  - direction: d1\n    track: t1\n    branch: v02\n"
        "    strategy: |\n      entry: [unclosed\n", encoding="utf-8")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"local:\n  workspace: {ws}\n  data: {ws}/data\n"
        f"  strategies: {ws}/strategies\n  runs: {ws}/runs\n"
        f"  alpha: {ws}/alpha\n", encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["apply-batch", str(bundle),
                                     "--config", str(cfg), "--dry-run"])
    assert "d1/t1/v02" in r.output          # clean per-item error line
    assert "Traceback" not in r.output       # no raw Python traceback


def test_apply_batch_direction_mismatch_rejected_before_write(tmp_path):
    """P1-2/B3: an item whose strategy.direction != item.direction is rejected
    in preflight — NOTHING is adopted."""
    from typer.testing import CliRunner
    from lyra import cli
    import yaml as _y
    ws = tmp_path / "ws"
    d = ws / "strategies" / "d1"
    (d / "t1").mkdir(parents=True)
    base = {"version": 1, "id": "b", "direction": "d1", "timeframe_minutes": 60,
            "entry": {"long": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                      "short": {"feature": "sma_6", "op": "lt", "value": "sma_24"}},
            "exit": {"long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
                     "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                     "stop_loss_pct": 0.02, "max_holding_bars": 12},
            "execution": {"spread_bps": 2, "slippage_bps_per_side": 0.2}}
    (d / "v01.yaml").write_text(_y.safe_dump(base, allow_unicode=True),
                                encoding="utf-8")
    from lyra import workflow as wf
    wf.create_track(ws, "d1", "t1")
    # strategy declares the WRONG direction
    bad = dict(base); bad["id"] = "m"; bad["direction"] = "OTHER"
    bundle = {"version": 1, "directions": [
        {"direction": "d1", "track": "t1", "branch": "v02", "parent": "v01",
         "driven_by_lesson": "L", "hypothesis": "x", "strategy": bad}]}
    bf = tmp_path / "b.yaml"
    bf.write_text(_y.safe_dump(bundle, allow_unicode=True), encoding="utf-8")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"local:\n  workspace: {ws}\n  data: {ws}/data\n"
        f"  strategies: {ws}/strategies\n  runs: {ws}/runs\n"
        f"  alpha: {ws}/alpha\n", encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["apply-batch", str(bf),
                                     "--config", str(cfg), "--dry-run"])
    assert "must match" in r.output
    assert not (d / "t1" / "v02.yaml").exists()


def test_apply_batch_path_escape_rejected_before_write(tmp_path):
    """P0-4: a `../evil` direction is rejected in preflight — no file anywhere."""
    from typer.testing import CliRunner
    from lyra import cli
    ws = tmp_path / "ws"
    (ws / "strategies").mkdir(parents=True)
    bundle = tmp_path / "b.yaml"
    bundle.write_text(
        "version: 1\ndirections:\n"
        "  - direction: ../evil\n    track: t1\n    branch: v01\n"
        "    strategy: |\n" + _STRAT, encoding="utf-8")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"local:\n  workspace: {ws}\n  data: {ws}/data\n"
        f"  strategies: {ws}/strategies\n  runs: {ws}/runs\n"
        f"  alpha: {ws}/alpha\n", encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["apply-batch", str(bundle),
                                     "--config", str(cfg), "--dry-run"])
    assert "invalid direction" in r.output
    assert not (tmp_path / "evil").exists()
    assert not (ws.parent / "evil").exists()


def test_apply_batch_lineage_persisted_in_adopted_file(tmp_path):
    """P-5/B4: item-level parent/driven_by_lesson/hypothesis must be written
    into the ADOPTED branch file on disk (not only the gate's in-memory view)."""
    from typer.testing import CliRunner
    from lyra import cli
    import yaml as _y
    ws = tmp_path / "ws"
    d = ws / "strategies" / "d1"
    (d / "t1").mkdir(parents=True)
    base = {"version": 1, "id": "b", "direction": "d1", "timeframe_minutes": 60,
            "entry": {"long": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                      "short": {"feature": "sma_6", "op": "lt", "value": "sma_24"}},
            "exit": {"long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
                     "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                     "stop_loss_pct": 0.02, "max_holding_bars": 12},
            "execution": {"spread_bps": 2, "slippage_bps_per_side": 0.2}}
    (d / "v01.yaml").write_text(_y.safe_dump(base, allow_unicode=True),
                                encoding="utf-8")
    from lyra import workflow as wf
    wf.create_track(ws, "d1", "t1")
    bundle = {"version": 1, "directions": [
        {"direction": "d1", "track": "t1", "branch": "v02", "parent": "v01",
         "driven_by_lesson": "v01 baseline was too tight",
         "hypothesis": "Wider entry",
         "strategy": dict(base, id="s2")}]}
    bf = tmp_path / "b.yaml"
    bf.write_text(_y.safe_dump(bundle, allow_unicode=True), encoding="utf-8")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"local:\n  workspace: {ws}\n  data: {ws}/data\n"
        f"  strategies: {ws}/strategies\n  runs: {ws}/runs\n"
        f"  alpha: {ws}/alpha\n", encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["apply-batch", str(bf),
                                     "--config", str(cfg)])
    assert r.exit_code == 0, r.output
    adopted = _y.safe_load((d / "t1" / "v02.yaml").read_text(encoding="utf-8"))
    assert "v01" in adopted["parents"]
    assert adopted["driven_by_lesson"] == "v01 baseline was too tight"
    assert adopted["hypothesis"] == "Wider entry"


def test_submit_missing_direction_is_actionable(tmp_path):
    """Self-check (round-1 friction): a strategy YAML with NO direction/family
    must fail with the actionable 'no direction' error, NOT the cryptic
    path-escape 'invalid direction None'."""
    from typer.testing import CliRunner
    from lyra import cli
    import yaml as _y
    ws = tmp_path / "ws"
    d = ws / "strategies" / "d1"
    (d / "t1").mkdir(parents=True)
    base = {"version": 1, "id": "b", "timeframe_minutes": 60,   # NOTE: no direction/family
            "entry": {"long": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                      "short": {"feature": "sma_6", "op": "lt", "value": "sma_24"}},
            "exit": {"long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
                     "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                     "stop_loss_pct": 0.02, "max_holding_bars": 12},
            "execution": {"spread_bps": 2, "slippage_bps_per_side": 0.2}}
    (d / "v01.yaml").write_text(_y.safe_dump(base, allow_unicode=True), encoding="utf-8")
    from lyra import workflow as wf
    wf.create_track(ws, "d1", "t1")
    draft = tmp_path / "draft.yaml"
    draft.write_text(_y.safe_dump(base, allow_unicode=True), encoding="utf-8")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(f"local:\n  workspace: {ws}\n  data: {ws}/data\n  strategies: {ws}/strategies\n  runs: {ws}/runs\n  alpha: {ws}/alpha\n", encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["submit", str(draft), "--track", "t1",
                                     "--branch", "v02", "--config", str(cfg),
                                     "--data-dir", str(tmp_path / "data")])
    assert "no direction" in r.output or "add a top-level `direction:" in r.output
    assert "invalid direction None" not in r.output   # the old cryptic message is gone


def test_warn_zero_cost_fires_on_zero_strategy(tmp_path):
    """F-3 (UsageLastReview): a strategy that backtests with zero commission
    AND zero financing must trigger the optimistic-bias warning (printed, not
    raised); a costed strategy must NOT trigger it."""
    import io
    import contextlib
    from lyra import cli

    class _Plan:
        def __init__(self, comm, fin):
            self.commission_bps_round_trip = comm
            self.financing_bps_per_day = fin

    # zero + zero → warning fires
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        cli._warn_zero_cost(_Plan(0, 0))
    assert "zero-cost" in buf.getvalue()
    assert "optimistically biased" in buf.getvalue()

    # commission set, financing zero → no warning (one real cost is enough)
    buf2 = io.StringIO()
    with contextlib.redirect_stderr(buf2):
        cli._warn_zero_cost(_Plan(0.2, 0))
    assert "zero-cost" not in buf2.getvalue()

    # financing set, commission zero → no warning
    buf3 = io.StringIO()
    with contextlib.redirect_stderr(buf3):
        cli._warn_zero_cost(_Plan(0, 0.1))
    assert "zero-cost" not in buf3.getvalue()

    # both non-zero → no warning
    buf4 = io.StringIO()
    with contextlib.redirect_stderr(buf4):
        cli._warn_zero_cost(_Plan(0.2, 0.1))
    assert "zero-cost" not in buf4.getvalue()


def test_apply_batch_strategy_missing_direction_rejected(tmp_path):
    """DEV-03/RED-05 (UsageLastReview #2): a strategy YAML with NO direction
    (and no legacy family:) must be rejected in batch preflight — the outer
    item.direction must NOT stand in for it. Zero writes."""
    from typer.testing import CliRunner
    from lyra import cli
    import yaml as _y
    ws = tmp_path / "ws"
    d = ws / "strategies" / "d1"
    (d / "t1").mkdir(parents=True)
    base = {"version": 1, "id": "b", "direction": "d1", "timeframe_minutes": 60,
            "entry": {"long": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                      "short": {"feature": "sma_6", "op": "lt", "value": "sma_24"}},
            "exit": {"long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
                     "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
                     "stop_loss_pct": 0.02, "max_holding_bars": 12},
            "execution": {"spread_bps": 2, "slippage_bps_per_side": 0.2}}
    (d / "v01.yaml").write_text(_y.safe_dump(base, allow_unicode=True),
                                encoding="utf-8")
    from lyra import workflow as wf
    wf.create_track(ws, "d1", "t1")
    # the STRATEGY omits direction (only the item carries d1)
    no_dir = {k: v for k, v in base.items() if k != "direction"}
    no_dir["id"] = "s2"
    bundle = {"version": 1, "directions": [
        {"direction": "d1", "track": "t1", "branch": "v02", "parent": "v01",
         "driven_by_lesson": "v01 baseline was too tight",
         "hypothesis": "Wider entry",
         "strategy": no_dir}]}
    bf = tmp_path / "b.yaml"
    bf.write_text(_y.safe_dump(bundle, allow_unicode=True), encoding="utf-8")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"local:\n  workspace: {ws}\n  data: {ws}/data\n"
        f"  strategies: {ws}/strategies\n  runs: {ws}/runs\n  alpha: {ws}/alpha\n",
        encoding="utf-8")
    r = CliRunner().invoke(cli.app, ["apply-batch", str(bf), "--config", str(cfg)])
    assert r.exit_code != 0
    assert "no direction" in r.output or "declares no direction" in r.output
    # zero writes: the branch file must NOT exist
    assert not (d / "t1" / "v02.yaml").exists()
