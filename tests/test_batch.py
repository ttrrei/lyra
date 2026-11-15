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
