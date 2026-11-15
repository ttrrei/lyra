"""0007 Part B — R12 workflow tests (I18/I21/I22, D5–D9)."""

from __future__ import annotations

import json
import types

import pytest

from lyra import workflow as wf


def _mk_direction(ws, direction="fx-trend"):
    d = ws / "strategies" / direction
    d.mkdir(parents=True, exist_ok=True)
    (d / "hypothesis.md").write_text("# hypothesis\ntrend on 1h\n", encoding="utf-8")
    (d / "lessons.md").write_text(
        "2026-11-01: stop at 2% was binding\n2026-11-03: volume filter helped\n",
        encoding="utf-8",
    )
    (d / "v01.yaml").write_text(
        "id: base\ndirection: fx-trend\nversion: 1\n", encoding="utf-8"
    )
    return d


def _mk_catalog(ws):
    """M1 (batch2): the real feature catalog is the DuckDB file
    ``<data_dir>/catalog.duckdb`` — create that, not a catalog.json."""
    c = ws / "data"
    c.mkdir(parents=True, exist_ok=True)
    (c / "catalog.duckdb").write_bytes(b"FAKE-DUCKDB-CATALOG-BYTES")


def _mk_run(ws, branch, *, trades=5, net=0.012, ann=0.10, win=0.6,
            track=None, direction=None):
    """A 0006 metrics.json artifact whose spec_id references the branch.

    0009 D12 (H1): writes a ``run_meta.json`` sidecar so track-scoped reads
    can attribute the run (``track=None`` keeps the pre-D12 legacy shape).
    """
    run_dir = ws / "runs" / f"{branch}-r1" / "20261110" / "r1234567890abcdef"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_id": branch,
        "run_id": "r1234567890abcdef",
        "per_instrument": {
            "EURUSD": {"trade_count": trades, "annualized": ann,
                        "win_rate": win, "net_return": net},
        },
    }
    (run_dir / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")
    if track is not None:
        (run_dir / "run_meta.json").write_text(json.dumps({
            "direction": direction or "fx-trend", "branch": branch,
            "track_id": track, "spec_id": branch,
            "run_id": "r1234567890abcdef",
        }), encoding="utf-8")
    return run_dir


# --- tracks (I18) ------------------------------------------------------------


def test_tracks_create_freezes_baseline(tmp_path):
    d = _mk_direction(tmp_path)
    _mk_catalog(tmp_path)
    rec = wf.create_track(tmp_path, "fx-trend", "alpha")
    bl = rec["baseline"]
    import hashlib

    expected_hyp = hashlib.sha256((d / "hypothesis.md").read_bytes()).hexdigest()
    assert bl["hypothesis_sha256"] == expected_hyp
    assert bl["feature_catalog_sha256"] is not None
    assert bl["feature_version"] is not None
    assert bl["engine_version"] is not None
    # baseline was frozen at creation (deterministic hash, not wall-clock)
    assert "created_at" in rec
    assert rec["direction"] == "fx-trend"
    assert rec["track_id"] == "alpha"


def test_tracks_create_unknown_direction_fails(tmp_path):
    with pytest.raises(wf.WorkflowError, match="unknown direction"):
        wf.create_track(tmp_path, "nope", "alpha")


def test_tracks_duplicate_id_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="already exists"):
        wf.create_track(tmp_path, "fx-trend", "alpha")
    # different (valid) id is fine — only the exact duplicate is rejected
    wf.create_track(tmp_path, "fx-trend", "alpha2")
    assert len(wf.list_tracks(tmp_path, "fx-trend")) == 2


def test_tracks_invalid_id_fails(tmp_path):
    _mk_direction(tmp_path)
    for bad in ("", "UPPER", "has space", "a/b", "-lead"):
        with pytest.raises(wf.WorkflowError):
            wf.create_track(tmp_path, "fx-trend", bad)


def test_create_track_validate_before_write_h2(tmp_path):
    """H2 (2026-11-15): when the preconditions fail (the track index already
    exists — the "synced machine" inconsistent state), create_track must fail
    fast AND leave NO partial record behind. The pre-fix code wrote
    tracks/<dir>/<track>.json (with a re-frozen baseline) before checking the
    index, so a failed create still silently dropped a record that would then
    clobber provenance on the next push. This pins validate-before-write."""
    _mk_direction(tmp_path)
    # Simulate a synced machine: the index JSONL was pulled from OCI but the
    # record JSON is absent — the exact inconsistent state create_track guards.
    idx = tmp_path / "strategies" / "fx-trend" / "index" / "tgamma.jsonl"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(json.dumps({"op": "create_track", "track_id": "gamma"}) + "\n",
                   encoding="utf-8")
    with pytest.raises(wf.WorkflowError, match="track index already exists"):
        wf.create_track(tmp_path, "fx-trend", "gamma")
    # The invariant: no partial record was written.
    assert not (tmp_path / "tracks" / "fx-trend" / "gamma.json").exists()


# --- cap (I21 / D6 / O13) -----------------------------------------------------


def test_new_version_enforces_cap_8(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    for i in range(10, 18):
        wf.new_version(tmp_path, "fx-trend", f"v{i:02d}", track="alpha")
    assert wf.count_active_branches(tmp_path, "fx-trend", "alpha") == 8
    with pytest.raises(wf.WorkflowError, match="branch cap reached"):
        wf.new_version(tmp_path, "fx-trend", "v99", track="alpha")
    # prune one → cap relieved (explicit, never automatic)
    wf.prune_branch(tmp_path, "fx-trend", "alpha", "v10")
    wf.new_version(tmp_path, "fx-trend", "v99", track="alpha")
    assert wf.count_active_branches(tmp_path, "fx-trend", "alpha") == 8


def test_cap_is_per_track_not_global(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.create_track(tmp_path, "fx-trend", "beta")
    for i in range(10, 18):
        wf.new_version(tmp_path, "fx-trend", f"v{i:02d}", track="alpha")
    # track alpha is full; track beta can still fork (I21 互不挤占)
    target = wf.new_version(tmp_path, "fx-trend", "v20", track="beta")
    assert target.exists()
    assert wf.count_active_branches(tmp_path, "fx-trend", "beta") == 1
    with pytest.raises(wf.WorkflowError, match="branch cap reached"):
        wf.new_version(tmp_path, "fx-trend", "v99", track="alpha")


def test_prune_cli_relieves_cap(tmp_path, monkeypatch):
    """审查 U3 回归：`prune_branch` 存在但此前无 CLI 入口——8 分支配额耗尽后
    死锁。`lyra prune` 接通该通道：填满 8 → prune 一个 → 可再 fork。"""
    from typer.testing import CliRunner

    from lyra import cli

    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    # point the CLI workspace root at tmp_path (resolve_data_root override).
    monkeypatch.setenv("LYRA_DATA_ROOT", str(tmp_path / "data"))
    base = []
    r = CliRunner()
    # fill the cap via CLI new-version (proves the CLI path, not just wf API)
    for i in range(10, 18):
        out = r.invoke(cli.app, base + ["new-version", "fx-trend",
                                       "--branch", f"v{i:02d}", "--track", "alpha"])
        assert out.exit_code == 0, out.output
    # cap reached → 9th fork refused
    out = r.invoke(cli.app, base + ["new-version", "fx-trend",
                                   "--branch", "v99", "--track", "alpha"])
    assert out.exit_code != 0
    assert "cap" in out.output.lower()
    # prune one → cap relieved
    out = r.invoke(cli.app, base + ["prune", "fx-trend",
                                   "--branch", "v10", "--track", "alpha"])
    assert out.exit_code == 0, out.output
    assert "7/8 active" in out.output
    # now the 9th fork succeeds
    out = r.invoke(cli.app, base + ["new-version", "fx-trend",
                                   "--branch", "v99", "--track", "alpha"])
    assert out.exit_code == 0, out.output


def test_new_version_unknown_track_fails(tmp_path):
    _mk_direction(tmp_path)
    with pytest.raises(wf.WorkflowError, match="unknown track"):
        wf.new_version(tmp_path, "fx-trend", "v02", track="ghost")


def test_new_version_duplicate_branch_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    # same slug again on the SAME track → duplicate id → fail-fast (no
    # overwrite, no rename)
    with pytest.raises(wf.WorkflowError, match="already exists"):
        wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    # the original file is untouched (0009 D12: track-level layout)
    assert (tmp_path / "strategies" / "fx-trend" / "alpha" / "v02.yaml").exists()


def test_new_version_parent_at_direction_baseline(tmp_path):
    """0009 D12 (H1): a branch can derive from the direction-level baseline
    (v01) even though its own file is track-scoped — the baseline is shared
    and read-only, always a legal parent."""
    _mk_direction(tmp_path)  # provides strategies/fx-trend/v01.yaml baseline
    wf.create_track(tmp_path, "fx-trend", "alpha")
    p = wf.new_version(tmp_path, "fx-trend", "v02", track="alpha", parent="v01")
    assert p == tmp_path / "strategies" / "fx-trend" / "alpha" / "v02.yaml"
    text = p.read_text(encoding="utf-8")
    assert "parent: v01" in text
    # the baseline file is untouched (read-only semantics)
    baseline = tmp_path / "strategies" / "fx-trend" / "v01.yaml"
    assert "parent: v01" not in baseline.read_text(encoding="utf-8")


def test_new_version_same_branch_across_tracks_is_legal(tmp_path):
    """0009 D12 (H1): each track owns its branch namespace — track beta can
    create its own v02 while track alpha's v02 exists. No cross-track
    collision, and each file lives under its own track directory."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.create_track(tmp_path, "fx-trend", "beta")
    a = wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    b = wf.new_version(tmp_path, "fx-trend", "v02", track="beta")
    assert a == tmp_path / "strategies" / "fx-trend" / "alpha" / "v02.yaml"
    assert b == tmp_path / "strategies" / "fx-trend" / "beta" / "v02.yaml"
    assert a.exists() and b.exists()
    # the two files are independent (editing one must not affect the other)
    b.write_text("version: 1\nid: v02-beta-variant\ndirection: fx-trend\n",
                 encoding="utf-8")
    assert "beta-variant" in b.read_text(encoding="utf-8")
    assert "beta-variant" not in a.read_text(encoding="utf-8")


def test_new_version_rejects_non_vnn_slug(tmp_path):
    # 0007 D2: branch files are vNN.yaml (I17 immutable class). An arbitrary
    # slug (b0/foo/mybranch) would classify as unclassified and be
    # fail-closed at push time — so new-version rejects it up front.
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    for bad in ("b0", "foo", "my_branch", "v1.bak", "V01"):
        with pytest.raises(wf.WorkflowError):
            wf.new_version(tmp_path, "fx-trend", bad, track="alpha")


def test_new_version_output_is_push_classifiable(tmp_path):
    # Regression: a branch produced by new-version must classify as immutable
    # so the push layer can carry it (0007 D2/D9 self-consistency).
    from lyra import oci_push

    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    # 0009 D12: the branch now lives under the track subdir — the push
    # classifier must STILL see it as immutable (classified by file name).
    assert oci_push.classify_path("strategies/fx-trend/alpha/v02.yaml") == "immutable"


# --- new-version template (0004 provenance reuse) ------------------------------


def test_new_version_writes_parent_and_lesson(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    target = wf.new_version(tmp_path, "fx-trend", "v02", track="alpha",
                            parent="v01", driven_by_lesson="L2")
    text = target.read_text(encoding="utf-8")
    assert "parent: v01" in text
    assert "parents:" in text and "  - v01" in text
    # H3 (2026-11-15): lesson is single-quoted so the skeleton stays valid YAML.
    assert "driven_by_lesson: 'L2'" in text
    # vNN>=2 without explicit lesson → a *quoted* fill-me placeholder (R12).
    # The whole point: the generated skeleton must parse as valid YAML (the old
    # unquoted `<TODO: …>` was a YAML mapping error → `lyra validate` failed).
    target2 = wf.new_version(tmp_path, "fx-trend", "v03", track="alpha", parent="v01")
    text2 = target2.read_text(encoding="utf-8")
    import yaml as _yaml
    parsed = _yaml.safe_load(text2)
    assert "driven_by_lesson" in parsed
    assert str(parsed["driven_by_lesson"]).startswith("TODO")


def test_new_version_missing_parent_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="not found"):
        wf.new_version(tmp_path, "fx-trend", "v02", track="alpha", parent="v99")


# --- context (I18 isolation) ---------------------------------------------------


def test_context_track_scoped_isolated(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.create_track(tmp_path, "fx-trend", "beta")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    wf.new_version(tmp_path, "fx-trend", "v03", track="beta")

    ctx_a = wf.render_context(tmp_path, "fx-trend", track="alpha")
    assert "track alpha" in ctx_a
    assert "v02" in ctx_a
    # isolation: track B's branch must NOT appear in A's context
    assert "track beta" not in ctx_a
    assert "v03" not in ctx_a

    ctx_b = wf.render_context(tmp_path, "fx-trend", track="beta")
    assert "track beta" in ctx_b
    assert "v02" not in ctx_b

    # unscoped context lists both (synthesis surface)
    ctx_all = wf.render_context(tmp_path, "fx-trend")
    assert "track alpha" in ctx_all and "track beta" in ctx_all


def test_context_contains_siblings_runs(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha", parent="v01")
    _mk_run(tmp_path, "v02", trades=7, net=0.02, ann=0.15, win=0.55, track="alpha")
    ctx = wf.render_context(tmp_path, "fx-trend", track="alpha")
    assert "v02" in ctx
    assert "r123456789" in ctx  # run id surfaced
    assert "trades=7" in ctx
    assert "ann=0.15" in ctx
    assert "EURUSD:" in ctx  # per-instrument, not first-instrument-only
    # hypothesis + lessons included
    assert "hypothesis" in ctx
    assert "volume filter helped" in ctx


def test_context_includes_grammar_and_valid_template_t3(tmp_path):
    """T3 (web-AI no-FS loop): context must carry the strategy grammar AND a
    copyable template, because a web/chat AI (no filesystem, no coding) reads
    the context as its only reference for "how to write this YAML"."""
    _mk_direction(tmp_path)
    ctx = wf.render_context(tmp_path, "fx-trend")
    # The grammar section + the key rules the AI must follow.
    assert "how to write a strategy" in ctx
    assert "timeframe_minutes" in ctx and "5" in ctx and "60" in ctx
    assert "op" in ctx and "stop_loss_pct" in ctx
    # A copyable template the AI can start from.
    assert "```yaml" in ctx
    assert "version: 1" in ctx
    assert "direction: fx-trend" in ctx
    assert "entry:" in ctx and "exit:" in ctx
    assert "stop_loss_pct: 0.02" in ctx


def test_h1_context_does_not_leak_other_track_runs(tmp_path):
    """0009 D12 (H1): track alpha's context must NOT show track beta's runs
    for the same branch — each AI's evidence is its own."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.create_track(tmp_path, "fx-trend", "beta")
    # both tracks own a v02 (legal under D12); each ran it independently.
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="beta")
    # alpha's run has net=0.50; beta's run has a wildly different net=0.01
    _mk_run(tmp_path, "v02", trades=9, net=0.50, ann=0.9, win=0.8, track="alpha")
    # beta's run (same branch slug, different track) — must NOT leak into alpha
    run_dir = tmp_path / "runs" / "v02-beta" / "20261110" / "beta0001"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps({
        "spec_id": "v02", "run_id": "beta0001",
        "per_instrument": {"EURUSD": {"trade_count": 1, "annualized": 0.0,
                                       "win_rate": 0.1, "net_return": 0.01}},
    }), encoding="utf-8")
    (run_dir / "run_meta.json").write_text(json.dumps({
        "direction": "fx-trend", "branch": "v02", "track_id": "beta",
        "spec_id": "v02", "run_id": "beta0001",
    }), encoding="utf-8")

    ctx_alpha = wf.render_context(tmp_path, "fx-trend", track="alpha")
    assert "net=0.5" in ctx_alpha           # alpha's own run is shown (0.50 -> "0.5")
    assert "net=0.01" not in ctx_alpha      # beta's run must NOT leak in
    assert "beta0001" not in ctx_alpha

    # cross-track read (synthesize-style, no track) sees BOTH, labelled
    both = wf._runs_for_branch(tmp_path, "fx-trend", "v02")
    tracks = {r["track_id"] for r in both}
    assert tracks == {"alpha", "beta"}


def test_context_unknown_track_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="unknown track"):
        wf.render_context(tmp_path, "fx-trend", track="ghost")


# --- compare / merge / synthesize (I22 / D8) ------------------------------------


def test_compare_siblings_readonly(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    wf.new_version(tmp_path, "fx-trend", "v03", track="alpha")
    _mk_run(tmp_path, "v02", net=0.01)
    _mk_run(tmp_path, "v03", net=0.03, ann=0.2)

    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = wf.compare_siblings(tmp_path, "fx-trend", ["v02", "v03"])
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    assert {p: b for p, b in before.items()} == {p: b for p, b in after.items()}
    rows = {r["branch"]: r for r in result["siblings"]}
    assert rows["v03"]["best"]["net_return"] == 0.03
    assert rows["v02"]["best"]["net_return"] == 0.01


def test_compare_empty_fails(tmp_path):
    _mk_direction(tmp_path)
    with pytest.raises(wf.WorkflowError):
        wf.compare_siblings(tmp_path, "fx-trend", [])


def test_merge_adds_candidate_no_source_change(tmp_path):
    d = _mk_direction(tmp_path)
    ta = d / "alpha"  # 0009 D12: track-level branch files
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha", parent="v01")
    wf.new_version(tmp_path, "fx-trend", "v03", track="alpha", parent="v01")
    src_before = {}
    for name in ("v02.yaml", "v03.yaml", "v01.yaml"):
        p = (ta if name != "v01.yaml" else d) / name
        src_before[name] = p.read_bytes()

    target = wf.merge(tmp_path, "fx-trend", ["v02", "v03"], track="alpha")
    assert target.exists()
    assert target == ta / "v04.yaml"  # merge target is track-scoped (D12)
    for name, data in src_before.items():
        p = (ta if name != "v01.yaml" else d) / name
        assert p.read_bytes() == data, f"source {name} was modified!"

    text = target.read_text(encoding="utf-8")
    assert "parents:" in text
    assert "  - v02" in text and "  - v03" in text
    assert "inherited:" in text
    # C6: provenance by content hash (audit chain survives prunes/renames)
    import hashlib as _h

    assert "# parent_sha256" in text
    v02_sha = _h.sha256((ta / "v02.yaml").read_bytes()).hexdigest()
    v03_sha = _h.sha256((ta / "v03.yaml").read_bytes()).hexdigest()
    assert f"#   v02: {v02_sha}" in text
    assert f"#   v03: {v03_sha}" in text


def test_merge_needs_two_parents(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="at least two parents"):
        wf.merge(tmp_path, "fx-trend", ["v02"], track="alpha")


def test_merge_missing_parent_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="not found"):
        wf.merge(tmp_path, "fx-trend", ["v01", "v99"], track="alpha")


def test_synthesize_requires_explicit_and_writes_reviews_only(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.create_track(tmp_path, "fx-trend", "beta")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    wf.new_version(tmp_path, "fx-trend", "v03", track="beta")
    _mk_run(tmp_path, "v02")

    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    target = wf.synthesize(tmp_path, "fx-trend")
    assert str(target).startswith(str(tmp_path / "reviews"))
    # nothing outside reviews/ changed
    for p, old in before.items():
        assert p.read_bytes() == old, f"{p} was modified by synthesize!"
    # reviews/ contains the new report and nothing else changed there
    reviews = sorted((tmp_path / "reviews").glob("*.md"))
    assert len(reviews) == 1
    text = target.read_text(encoding="utf-8")
    assert "track alpha" in text and "track beta" in text
    # synthesize again → new file, previous untouched
    target2 = wf.synthesize(tmp_path, "fx-trend")
    assert target2 != target
    assert target.read_text(encoding="utf-8") is not None


def test_synthesize_no_tracks_fails(tmp_path):
    _mk_direction(tmp_path)
    with pytest.raises(wf.WorkflowError, match="no tracks"):
        wf.synthesize(tmp_path, "fx-trend")


# ---------------------------------------------------------------------------
# 批次2 (adversarial review 2026-11-10) regression tests
# ---------------------------------------------------------------------------


def test_h7_spec_match_is_exact_not_substring(tmp_path):
    """批次2-H7: querying branch v1 must not match a run whose spec_id is v10
    (the old ``branch in spec`` substring matched across boundaries)."""
    import json as _json

    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    # a run for branch v10 and one for v1
    r10 = tmp_path / "runs" / "r-v10" / "20261110" / "aaa111"
    r10.mkdir(parents=True)
    (r10 / "metrics.json").write_text(_json.dumps({
        "spec_id": "v10", "run_id": "aaa111",
        "per_instrument": {"X": {"trade_count": 99, "annualized": 0.9,
                                  "win_rate": 0.9, "net_return": 0.9}}}),
        encoding="utf-8")
    r1 = tmp_path / "runs" / "r-v1" / "20261110" / "bbb222"
    r1.mkdir(parents=True)
    (r1 / "metrics.json").write_text(_json.dumps({
        "spec_id": "v1", "run_id": "bbb222",
        "per_instrument": {"Y": {"trade_count": 1, "annualized": 0.01,
                                  "win_rate": 0.1, "net_return": 0.01}}}),
        encoding="utf-8")
    # v1 must ONLY see its own run
    got_v1 = wf._runs_for_branch(tmp_path, "fx-trend", "v1")
    assert [r["run_id"] for r in got_v1] == ["bbb222"]
    # v10 must ONLY see its own run
    got_v10 = wf._runs_for_branch(tmp_path, "fx-trend", "v10")
    assert [r["run_id"] for r in got_v10] == ["aaa111"]


def test_h7_all_instruments_carried_not_first_only(tmp_path):
    """批次2-H7: every per-instrument result is carried, not just the first."""
    import json as _json

    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    r = tmp_path / "runs" / "r-x" / "20261110" / "ccc333"
    r.mkdir(parents=True)
    (r / "metrics.json").write_text(_json.dumps({
        "spec_id": "v05", "run_id": "ccc333",
        "per_instrument": {
            "EURUSD": {"trade_count": 5, "annualized": 0.05,
                        "win_rate": 0.5, "net_return": 0.05},
            "XAUUSD": {"trade_count": 12, "annualized": 0.12,
                        "win_rate": 0.7, "net_return": 0.12},
        }}), encoding="utf-8")
    runs = wf._runs_for_branch(tmp_path, "fx-trend", "v05")
    assert len(runs) == 1
    insts = {i["instrument"] for i in runs[0]["instruments"]}
    assert insts == {"EURUSD", "XAUUSD"}
    # compare_siblings.best = the max per-instrument, i.e. XAUUSD here
    comp = wf.compare_siblings(tmp_path, "fx-trend", ["v05"])
    assert comp["siblings"][0]["best"]["instrument"] == "XAUUSD"


def test_h5_sibling_suffix_new_version_accepted(tmp_path):
    """批次2-H5: sibling-suffix branch names (v02a) are legal per
    requirements.md §0.2 and must be creatable + pushable."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02a", track="alpha")
    from lyra import oci_push

    # 0009 D12: track-level path; the classifier (by file name) is still immutable.
    assert oci_push.classify_path("strategies/fx-trend/alpha/v02a.yaml") == "immutable"
    assert (tmp_path / "strategies" / "fx-trend" / "alpha" / "v02a.yaml").exists()


def test_h4_validate_ident_rejects_traversal(tmp_path):
    """批次2-H4: direction/track/branch ids must be single path components."""
    for bad in ("../outside", "a/b", "..", ".", "", "a\\b"):
        with pytest.raises(wf.WorkflowError):
            wf.validate_ident(bad, "direction")
    for good in ("fx-trend", "alpha", "v02a", "track-1"):
        wf.validate_ident(good, "direction")


def test_p25_validate_ident_rejects_trailing_newline(tmp_path):
    """P2-5 (UsageFinalReview): ``re.match`` + ``$`` still accepts a trailing
    newline ("abc\\n") — which would become a hostile filename on disk.  All
    anchored ident validators must now use ``fullmatch`` so "abc\\n" is
    rejected while "abc" passes."""
    for bad in ("abc\n", "v02\n", "track-1\n", "fx-trend\n", "\nabc", "abc\n\n"):
        with pytest.raises(wf.WorkflowError):
            wf.validate_ident(bad, "direction")
    for good in ("abc", "v02", "track-1", "fx-trend"):
        wf.validate_ident(good, "direction")


def test_h10_track_index_is_jsonl_append_only(tmp_path):
    """批次2-H10: the track index is a JSONL event log; a fork appends a new
    line, so the file stays a verbatim line-superset of the earlier version
    (pushable under the append-only gate)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    idx = wf.track_index_path(tmp_path, "fx-trend", "alpha")
    assert idx.suffix == ".jsonl"
    v1 = idx.read_text(encoding="utf-8")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    v2 = idx.read_text(encoding="utf-8")
    # append-only: v1 lines are a prefix (verbatim) of v2
    assert v2.startswith(v1), "event log must be append-only (v1 is a prefix of v2)"
    # replay still yields the right active set
    events = wf.read_index_events(tmp_path, "fx-trend", "alpha")
    assert "v02" in wf.active_branches_of(events)


def test_o12_variant_ordinal_branch_names_accepted():
    """O12 (user ruling): vNN[a-z]*_1/_2 variant ordinals are legal branch
    names; the workflow regex must accept them (mirror of the push
    classifier contract)."""
    from lyra.workflow import _BRANCH_NAME_RE

    assert _BRANCH_NAME_RE.match("v04ab_1")
    assert _BRANCH_NAME_RE.match("v04ab_2")
    assert _BRANCH_NAME_RE.match("v01_1")
    assert _BRANCH_NAME_RE.match("v02a")
    assert not _BRANCH_NAME_RE.match("v04ab_x")
    assert not _BRANCH_NAME_RE.match("v04a1")
    assert not _BRANCH_NAME_RE.match("b0")


# --- 0009 D1: hypothesis content snapshot (R1) ------------------------------


def test_d1_track_freezes_full_hypothesis_text(tmp_path):
    """0009 D1: create_track stores the hypothesis FULL text (not just the
    hash), so the frozen baseline is stable against later edits (R1)."""
    d = _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    rec = wf.get_track(tmp_path, "fx-trend", "alpha")
    bl = rec["baseline"]
    assert bl["hypothesis_snapshot"] == (d / "hypothesis.md").read_text(encoding="utf-8")
    assert bl["hypothesis_sha256"]


def test_d1_context_uses_frozen_snapshot_after_drift(tmp_path):
    """0009 D1: render_context shows the FROZEN hypothesis text, flags drift
    when the live file has changed, and still shows the live file separately."""
    d = _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    # mutate the live hypothesis after the track froze it
    (d / "hypothesis.md").write_text("# hypothesis\nCHANGED after track creation\n",
                                     encoding="utf-8")
    text = wf.render_context(tmp_path, "fx-trend", track="alpha")
    assert "trend on 1h" in text                # frozen snapshot still present
    assert "CHANGED after track creation" in text  # live file shown too
    assert "drifted" in text                     # drift is flagged


def test_d1_context_without_track_shows_live_labelled(tmp_path):
    """0009 D1: direction-level context (no track) shows the live file,
    clearly labelled as not a frozen baseline."""
    _mk_direction(tmp_path)
    text = wf.render_context(tmp_path, "fx-trend")
    assert "not a frozen baseline" in text


# --- 0009 D2/D3: run identity + comparability (R2/R9) -----------------------


def _mk_run_with_meta(ws, direction, branch, track, run_id, snapshot=None,
                      data_digest=None, feature_version=None):
    import json as _json

    run_dir = ws / "runs" / f"{branch}-{run_id}" / "20261110" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_id": f"directions_{direction}",
        "run_id": run_id,
        "feature_snapshot_id": snapshot,
        "per_instrument": {"EURUSD": {"trade_count": 5, "annualized": 0.1,
                                       "win_rate": 0.6, "net_return": 0.02}},
    }
    # 0009 D13 (H2): per-run data identity fields (legacy runs omit both →
    # the comparability verdict degrades to unknown, which the tests assert).
    if data_digest is not None:
        payload["data_digest"] = data_digest
    if feature_version is not None:
        payload["feature_version"] = feature_version
    (run_dir / "metrics.json").write_text(_json.dumps(payload), encoding="utf-8")
    (run_dir / "run_meta.json").write_text(_json.dumps({
        "direction": direction, "branch": branch, "track_id": track,
        "spec_id": f"directions_{direction}", "run_id": run_id,
    }), encoding="utf-8")
    return run_dir


def test_d2_runs_for_branch_uses_run_meta_identity(tmp_path):
    """0009 D2: _runs_for_branch matches by run_meta.json identity (the
    direction + branch the CLI recorded), NOT by spec_id naming — so the
    official ``directions_<name>`` spec_id still joins to branch v01."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    _mk_run_with_meta(tmp_path, "fx-trend", "v01", "alpha", "run001")
    got = wf._runs_for_branch(tmp_path, "fx-trend", "v01")
    assert [r["run_id"] for r in got] == ["run001"]
    # a run recorded under a DIFFERENT direction must not leak in
    _mk_run_with_meta(tmp_path, "other-dir", "v01", "beta", "run002")
    got = wf._runs_for_branch(tmp_path, "fx-trend", "v01")
    assert [r["run_id"] for r in got] == ["run001"]


def test_d2_legacy_spec_id_fallback_still_works(tmp_path):
    """0009 D2: runs without a run_meta.json sidecar still match via the
    spec_id fallback (H7 exact-match rule)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    run_dir = tmp_path / "runs" / "legacy" / "20261110" / "leg001"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps({
        "spec_id": "v01", "run_id": "leg001",
        "per_instrument": {"X": {"trade_count": 1, "annualized": 0.0,
                                  "win_rate": 0.5, "net_return": 0.01}}}),
        encoding="utf-8")
    got = wf._runs_for_branch(tmp_path, "fx-trend", "v01")
    assert [r["run_id"] for r in got] == ["leg001"]


def test_d3_compare_marks_incomparable_across_generations(tmp_path):
    """0009 D3/R9: runs over different feature generations (different
    feature_snapshot_id) are flagged comparable=false rather than silently
    side-by-side. (Runs carry full D13 identity so the verdict is a clean
    False, not unknown.)"""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    _mk_run_with_meta(tmp_path, "fx-trend", "v01", "alpha", "runA",
                      snapshot="snap1", data_digest="digX", feature_version=6)
    _mk_run_with_meta(tmp_path, "fx-trend", "v02", "alpha", "runB",
                      snapshot="snap2", data_digest="digX", feature_version=6)
    result = wf.compare_siblings(tmp_path, "fx-trend", ["v01", "v02"])
    assert result["comparable"] is False
    assert result["distinct_feature_generations"] == 2

    # same generation -> comparable (fresh workspace for a clean pair)
    tmp_path2 = tmp_path / "same"
    tmp_path2.mkdir()
    d2 = tmp_path2 / "strategies" / "fx-trend"
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "hypothesis.md").write_text("h", encoding="utf-8")
    wf.create_track(tmp_path2, "fx-trend", "alpha")
    _mk_run_with_meta(tmp_path2, "fx-trend", "v01", "alpha", "runC",
                      snapshot="snapX", data_digest="digY", feature_version=6)
    _mk_run_with_meta(tmp_path2, "fx-trend", "v02", "alpha", "runD",
                      snapshot="snapX", data_digest="digY", feature_version=6)
    result3 = wf.compare_siblings(tmp_path2, "fx-trend", ["v01", "v02"])
    assert result3["comparable"] is True
    assert result3["distinct_feature_generations"] == 1


def test_d13_compare_uses_data_digest_and_feature_version(tmp_path):
    """0009 D13 (H2): comparability now also requires identical data_digest
    and feature_version — same snapshot alone is NOT sufficient."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    # same snapshot, DIFFERENT data digest → not comparable (the H2 case)
    _mk_run_with_meta(tmp_path, "fx-trend", "v01", "alpha", "runE",
                      snapshot="snap1", data_digest="dig1", feature_version=6)
    _mk_run_with_meta(tmp_path, "fx-trend", "v02", "alpha", "runF",
                      snapshot="snap1", data_digest="dig2", feature_version=6)
    result = wf.compare_siblings(tmp_path, "fx-trend", ["v01", "v02"])
    assert result["comparable"] is False
    assert result["distinct_data_digests"] == 2
    # the per-run reason names the differing dimension
    reasons = {r["incomparable_reason"] for row in result["siblings"]
               for r in row["runs"]}
    assert reasons == {"data_digest"}

    # same snapshot + same digest, DIFFERENT feature version → not comparable
    ws2 = tmp_path / "ws2"; ws2.mkdir()
    _mk_direction(ws2)
    wf.create_track(ws2, "fx-trend", "alpha")
    _mk_run_with_meta(ws2, "fx-trend", "v01", "alpha", "runG",
                      snapshot="snap1", data_digest="dig1", feature_version=5)
    _mk_run_with_meta(ws2, "fx-trend", "v02", "alpha", "runH",
                      snapshot="snap1", data_digest="dig1", feature_version=6)
    result2 = wf.compare_siblings(ws2, "fx-trend", ["v01", "v02"])
    assert result2["comparable"] is False
    assert result2["distinct_feature_versions"] == 2
    reasons2 = {r["incomparable_reason"] for row in result2["siblings"]
                for r in row["runs"]}
    assert reasons2 == {"feature_version"}


def test_d13_legacy_run_makes_comparable_unknown(tmp_path):
    """0009 D13 (H2): a run missing identity fields (legacy) → the verdict is
    unknown (None), NEVER presumed comparable; it is counted separately."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    _mk_run_with_meta(tmp_path, "fx-trend", "v01", "alpha", "runI",
                      snapshot="snap1")  # legacy: no data_digest/feature_version
    _mk_run_with_meta(tmp_path, "fx-trend", "v02", "alpha", "runJ",
                      snapshot="snap1", data_digest="dig1", feature_version=6)
    result = wf.compare_siblings(tmp_path, "fx-trend", ["v01", "v02"])
    assert result["comparable"] is None  # unknown — not False, not True
    assert result["runs_without_data_identity"] == 1
    legacy = [r for row in result["siblings"] for r in row["runs"]
              if r["run_id"] == "runI"][0]
    assert legacy["comparable"] is None


def test_d13_compare_single_run_is_comparable(tmp_path):
    """0009 D13 (H2): a single fully-identified run is comparable (True) —
    nothing to disagree with."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    _mk_run_with_meta(tmp_path, "fx-trend", "v01", "alpha", "runK",
                      snapshot="snap1", data_digest="dig1", feature_version=6)
    result = wf.compare_siblings(tmp_path, "fx-trend", ["v01"])
    assert result["comparable"] is True
    row = result["siblings"][0]
    assert row["runs"][0]["comparable"] is True
    assert row["runs"][0]["incomparable_reason"] is None


def test_submit_fail_closed_invalid_does_not_run(tmp_path):
    """H4: `lyra submit` on an INVALID strategy exits 1 and NEVER runs the engine."""
    from typer.testing import CliRunner
    from lyra import cli

    bad = tmp_path / "bad.yaml"
    bad.write_text("id: bad\ndirection: x\nversion: 0\n", encoding="utf-8")  # unsupported version
    r = CliRunner()
    out = r.invoke(cli.app, ["submit", str(bad), "--data-dir", str(tmp_path / "data")])
    assert out.exit_code == 1
    assert "INVALID" in (out.output or "") + (out.stderr or "")
    # fail-closed: no run artifact dir was created (run never ran)
    assert not (tmp_path / "data").exists() or not any((tmp_path / "data").iterdir())


def test_submit_valid_delegates_to_run(monkeypatch, tmp_path):
    """H4: `lyra submit` on a VALID strategy delegates to `run` with the same args."""
    from typer.testing import CliRunner
    from lyra import cli
    from lyra import strategy_schema as schema_mod

    reg = object()
    spec = types.SimpleNamespace(id="directions_good", direction="fx-trend")
    monkeypatch.setattr(schema_mod, "parse_strategy", lambda *a, **k: spec)
    import lyra.compiler as compiler_mod
    monkeypatch.setattr(compiler_mod, "compile_strategy", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_registry_for", lambda *a, **k: reg)

    calls = {}

    def fake_run(**kw):
        calls.update(kw)

    # Adoption target (gap #2): --track requires --branch; mock the workflow
    # adopt so no real track is needed. Run returns None (submit tolerates).
    from lyra import workflow as wf
    def fake_adopt(*a, **k):
        return a[4] if len(a) > 4 else k.get("source_yaml")  # the source path
    monkeypatch.setattr(wf, "adopt_branch", fake_adopt)
    monkeypatch.setattr(cli, "run", fake_run)
    good = tmp_path / "good.yaml"
    good.write_text("id: good\ndirection: fx-trend\nversion: 1\n", encoding="utf-8")
    r = CliRunner()
    out = r.invoke(cli.app, ["submit", str(good), "--data-dir", str(tmp_path / "d"),
                             "--track", "t01", "--branch", "v01", "--strict", "--name", "n1"])
    assert out.exit_code == 0
    assert calls["strategy"] == str(good)
    assert calls["data_dir"] == str(tmp_path / "d")
    assert calls["track"] == "t01"
    assert calls["strict"] is True
    assert calls["name"] == "n1"


# ---- 审查 #125 (web-AI loop): gaps #1/#2/#3/#5 regression tests -----------

def test_append_lesson_writes_and_is_append_only(tmp_path):
    """审查 #125 gap #3: a lesson appends one timestamped line; repeat calls
    append (not overwrite); empty text is rejected (fail-closed)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    p1 = wf.append_lesson(tmp_path, "fx-trend", "alpha", "v01 was too loose")
    p2 = wf.append_lesson(tmp_path, "fx-trend", "alpha", "v02: tighten stop")
    assert p1 == p2
    lines = p1.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "v01 was too loose" in lines[0]
    assert "v02: tighten stop" in lines[1]
    # append-only: the first line is preserved verbatim by the second call
    assert lines[0].endswith("v01 was too loose")


def test_append_lesson_unknown_track_fails(tmp_path):
    _mk_direction(tmp_path)
    with pytest.raises(wf.WorkflowError, match="unknown track"):
        wf.append_lesson(tmp_path, "fx-trend", "ghost", "hello")


def test_append_lesson_empty_text_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="empty"):
        wf.append_lesson(tmp_path, "fx-trend", "alpha", "   ")


def _spec(parents=(), lesson=None):
    """A minimal stand-in for a parsed StrategySpec (lineage fields only)."""
    return types.SimpleNamespace(parents=tuple(parents),
                                 driven_by_lesson=lesson)


def test_adopt_branch_writes_ai_yaml_into_track(tmp_path):
    """审查 #125 gap #2: the AI's strategy file (already validated upstream)
    becomes the track's branch file verbatim — not a skeleton.
    审查#128 M2: candidates start at v02 and must declare lineage."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "ai_written.yaml"
    src.write_text("version: 1\nid: ai_good\n# AI-authored body\n",
                   encoding="utf-8")
    dest = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src,
                           spec=_spec(parents=("v01",), lesson="stop was binding"))
    assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    # index event recorded (append-only)
    idxdir = tmp_path / "strategies" / "fx-trend" / "index"
    idxs = list(idxdir.glob("*.jsonl")) if idxdir.exists() else []
    assert idxs, "no index jsonl written by adopt_branch"
    idx = idxs[0]
    assert "v02" in idx.read_text(encoding="utf-8")


def test_adopt_branch_immutable_same_content_idempotent(tmp_path):
    """审查#128 M1: re-adopting an EXISTING branch with byte-identical content
    is a safe no-op (no overwrite, no second index event, no cap consumed)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "a.yaml"
    src.write_text("version: 1\nid: same\n", encoding="utf-8")
    spec = _spec(parents=("v01",), lesson="L")
    dest = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src, spec)
    before = (tmp_path / "strategies" / "fx-trend" / "index")
    first = before.joinpath(list(before.glob("*.jsonl"))[0].name)
    n_before = len(first.read_text(encoding="utf-8").splitlines())
    # second adopt of the same content → no new event
    dest2 = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src, spec)
    assert dest2 == dest
    n_after = len(first.read_text(encoding="utf-8").splitlines())
    assert n_before == n_after, "idempotent re-adopt must not append a new event"


def test_adopt_branch_immutable_diff_content_refused(tmp_path):
    """审查#128 M1: re-adopting an EXISTING branch with DIFFERENT content is
    refused (a branch is immutable; its historical runs point at it)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "a.yaml"
    src.write_text("version: 1\nid: v1-content\n", encoding="utf-8")
    wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src,
                    spec=_spec(parents=("v01",), lesson="L"))
    src.write_text("version: 1\nid: v2-different\n", encoding="utf-8")
    with pytest.raises(wf.WorkflowError, match="IMMUTABLE"):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src,
                        spec=_spec(parents=("v01",), lesson="L"))


def test_adopt_refresh_existing_branch_at_cap(tmp_path):
    """D8.1 (审查#128): at the 8-branch cap, re-submitting an EXISTING branch
    (idempotent, byte-identical) must NOT consume a new slot — only a genuinely
    new branch hits the cap."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "a.yaml"
    src.write_text("version: 1\nid: x\n", encoding="utf-8")
    spec = _spec(parents=("v01",), lesson="L")
    # fill the cap with 8 distinct branches
    for i in range(2, 10):
        s = tmp_path / f"b{i}.yaml"
        s.write_text(f"version: 1\nid: b{i}\n", encoding="utf-8")
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", f"v{i:02d}", s, spec)
    # re-adopt an EXISTING branch with identical content → allowed at cap
    existing = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02",
                               tmp_path / "b2.yaml", spec)
    assert existing.exists()
    # but a genuinely NEW 9th branch is still refused
    new = tmp_path / "n9.yaml"
    new.write_text("version: 1\nid: n9\n", encoding="utf-8")
    with pytest.raises(wf.WorkflowError, match="cap"):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v99", new, spec)


def test_lesson_with_newlines_stays_one_line(tmp_path):
    """D8.2 (审查#128): a pasted multi-line lesson is flattened to ONE line
    (embedded newlines → spaces), so the one-line-per-lesson invariant holds
    and the digest renders it as a single entry."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.append_lesson(tmp_path, "fx-trend", "alpha", "line one\nline two\n  line three")
    p = wf.track_lessons_path(tmp_path, "fx-trend", "alpha")
    body = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(body) == 1, f"expected 1 line, got {body!r}"
    assert "line one line two  line three" in body[0] or "line one line two line three" in body[0]


def test_adopt_branch_v01_reserved(tmp_path):
    """审查#128 M2: v01 is the direction baseline — a track must not own it."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "x.yaml"
    src.write_text("version: 1\nid: x\n", encoding="utf-8")
    with pytest.raises(wf.WorkflowError, match="baseline.*is reserved"):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v01", src)


def test_adopt_branch_vnn_requires_lineage(tmp_path):
    """审查#128 M2: a track vNN (N>=2) must declare parent + driven_by_lesson."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "x.yaml"
    src.write_text("version: 1\nid: x\n", encoding="utf-8")
    # no parent, no lesson → rejected
    with pytest.raises(wf.WorkflowError, match="lineage"):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v03", src,
                        spec=_spec(parents=(), lesson=None))
    # parent + lesson present → accepted
    dest = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v03", src,
                           spec=_spec(parents=("v01",), lesson="L"))
    assert dest.exists()


def test_adopt_branch_unknown_parent_refused(tmp_path):
    """审查#128 M2: a parent that resolves to neither the baseline nor an
    existing track branch is refused — lineage cannot be fabricated."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "x.yaml"
    src.write_text("version: 1\nid: x\n", encoding="utf-8")
    with pytest.raises(wf.WorkflowError, match="does not exist"):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v03", src,
                        spec=_spec(parents=("v99",), lesson="L"))


def test_adopt_branch_invalid_slug_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "x.yaml"
    src.write_text("version: 1\nid: x\n", encoding="utf-8")
    with pytest.raises(wf.WorkflowError):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "not a slug!", src)
    with pytest.raises(wf.WorkflowError):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "bad", src)  # needs v-prefix


def test_submit_requires_branch_with_track(monkeypatch, tmp_path):
    """审查 #125 gap #2/#5: --track without --branch must fail-closed (no
    run) — the branch slug is required for adoption + run attribution."""
    from typer.testing import CliRunner
    from lyra import cli
    from lyra import strategy_schema as schema_mod

    reg = object()
    spec = types.SimpleNamespace(id="directions_good", direction="fx-trend")
    monkeypatch.setattr(schema_mod, "parse_strategy", lambda *a, **k: spec)
    import lyra.compiler as compiler_mod
    monkeypatch.setattr(compiler_mod, "compile_strategy", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_registry_for", lambda *a, **k: reg)

    called = {"run": False}

    def fake_run(**kw):
        called["run"] = True

    monkeypatch.setattr(cli, "run", fake_run)
    good = tmp_path / "good.yaml"
    good.write_text("id: good\ndirection: fx-trend\nversion: 1\n", encoding="utf-8")
    r = CliRunner()
    out = r.invoke(cli.app, ["submit", str(good), "--data-dir", str(tmp_path / "d"),
                             "--track", "t01"])
    assert out.exit_code == 1
    assert "--branch" in (out.output or "") + (out.stderr or "")
    assert called["run"] is False  # fail-closed: no run happened


def test_lesson_command_appends(tmp_path, monkeypatch):
    """审查 #125 gap #3: the `lyra lesson` command appends to the track's
    lessons file (so `context --track` shows it next round)."""
    from typer.testing import CliRunner
    from lyra import cli

    # Point the command at our tmp workspace.
    import lyra.workflow as wf
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    monkeypatch.setattr(cli, "_workspace", lambda *a, **k: tmp_path)
    r = CliRunner()
    out = r.invoke(cli.app, ["lesson", "fx-trend",
                             "--track", "alpha",
                             "v01: win 58% but negative EV — v02 tighten stop"])
    assert out.exit_code == 0, out.output
    lessons = tmp_path / "tracks" / "fx-trend" / "alpha.lessons.md"
    assert lessons.exists(), "no lessons file written"
    assert "tighten stop" in lessons.read_text(encoding="utf-8")


# --- #130 sim: hypothesis fallback from v01.yaml (no hypothesis.md) --------


def test_context_hypothesis_falls_back_to_v01_yaml(tmp_path):
    """#130: when a direction has NO hypothesis.md (11/12 real directions),
    render_context must still surface the hypothesis from v01.yaml's field
    so a web-AI knows what the direction is about."""
    d = tmp_path / "strategies" / "me"
    d.mkdir(parents=True)
    # NO hypothesis.md — only v01.yaml with a hypothesis field
    (d / "v01.yaml").write_text(
        "id: me_v01\ndirection: me\nversion: 1\n"
        "hypothesis: A confirmed RSI retreat marks exhaustion\n",
        encoding="utf-8",
    )
    text = wf.render_context(tmp_path, "me")
    assert "RSI retreat marks exhaustion" in text
    assert "from baseline v01.yaml" in text
    assert "(none)" not in text


def test_digest_hypothesis_falls_back_to_v01_yaml(tmp_path):
    """#130: render_digest shows the v01.yaml hypothesis when no hypothesis.md."""
    d = tmp_path / "strategies" / "me"
    d.mkdir(parents=True)
    (d / "v01.yaml").write_text(
        "id: me_v01\ndirection: me\nversion: 1\n"
        "hypothesis: A confirmed RSI retreat marks exhaustion\n",
        encoding="utf-8",
    )
    text = wf.render_digest(tmp_path, "me")
    assert "RSI retreat marks exhaustion" in text
    assert "(from v01.yaml)" in text


def test_digest_standalone_vs_embedded_heading(tmp_path):
    """D-3 (UsageLastReview): a standalone digest uses an H1 heading + the
    global feature count; the embedded (``digest --all``) form uses H2 and
    omits the repeated per-direction feature line (printed once in the header).
    """
    d = tmp_path / "strategies" / "me"
    d.mkdir(parents=True)
    (d / "v01.yaml").write_text(
        "id: me_v01\ndirection: me\nversion: 1\nhypothesis: exhaustion\n",
        encoding="utf-8",
    )
    standalone = wf.render_digest(tmp_path, "me")
    embedded = wf.render_digest(tmp_path, "me", standalone=False)

    # heading level differs
    assert standalone.splitlines()[0].startswith("# digest — me")
    assert embedded.splitlines()[0].startswith("## digest — me")
    assert not embedded.splitlines()[0].startswith("# digest")
    # the GLOBAL feature count appears in standalone, not in the embedded form
    assert "registered (FEATURE_VERSION=" in standalone
    assert "registered (FEATURE_VERSION=" not in embedded


def test_context_no_hypothesis_anywhere_shows_none(tmp_path):
    """#130: truly absent hypothesis (no .md, no v01 field) → '(none)'."""
    d = tmp_path / "strategies" / "me"
    d.mkdir(parents=True)
    (d / "v01.yaml").write_text(
        "id: me_v01\ndirection: me\nversion: 1\n", encoding="utf-8"
    )
    text = wf.render_context(tmp_path, "me")
    assert "(none)" in text


def test_fallback_hypothesis_helper(tmp_path):
    """#130: the helper returns None for missing/empty/non-str hypothesis."""
    d = tmp_path / "strategies" / "me"
    d.mkdir(parents=True)
    assert wf._fallback_hypothesis(d) is None  # no v01 at all
    (d / "v01.yaml").write_text(
        "id: me_v01\ndirection: me\nversion: 1\n", encoding="utf-8")
    assert wf._fallback_hypothesis(d) is None  # no hypothesis field
    (d / "v01.yaml").write_text(
        "id: me_v01\nhypothesis:   \n", encoding="utf-8")
    assert wf._fallback_hypothesis(d) is None  # blank hypothesis
    (d / "v01.yaml").write_text(
        "id: me_v01\nhypothesis: real text\n", encoding="utf-8")
    assert wf._fallback_hypothesis(d) == "real text"


# --- DEV-01 (UsageLastReview #2): variant-suffix branch slugs must be gated ---

def _mk_spec(direction="fx-trend", parent=None, lesson=None):
    class _S:
        pass
    s = _S()
    s.direction = direction
    s.parents = (parent,) if parent else ()
    s.driven_by_lesson = lesson or ""
    return s


def test_dev01_variant_suffix_v02_1_requires_lineage(tmp_path):
    """A legal O12 variant branch `v02_1` must be gated exactly like `v02`
    (the old `_VNN_FILE_RE` missed it → fail-OPEN bypass of the gate)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    # v02_1 with no parent/lesson → must be rejected (NOT silently passed)
    with pytest.raises(wf.WorkflowError, match="lineage"):
        wf._validate_new_branch_lineage(tmp_path, "fx-trend", "alpha",
                                        "v02_1", _mk_spec())
    # with a valid parent + lesson → accepted (gated, not bypassed)
    wf._validate_new_branch_lineage(tmp_path, "fx-trend", "alpha", "v02_1",
                                    _mk_spec(parent="v01", lesson="L1"))


def test_dev01_v01_variant_is_reserved(tmp_path):
    """`v01_1` is generation 1 → the reserved direction baseline, not a
    track candidate (the old gate let it fail open past the reservation)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    with pytest.raises(wf.WorkflowError, match="reserved"):
        wf._validate_new_branch_lineage(tmp_path, "fx-trend", "alpha",
                                        "v01_1", _mk_spec(parent="v01",
                                                          lesson="L1"))


def test_branch_generation_parser(tmp_path):
    assert wf.branch_generation("v01") == 1
    assert wf.branch_generation("v01_1") == 1
    assert wf.branch_generation("v02") == 2
    assert wf.branch_generation("v02a") == 2
    assert wf.branch_generation("v02_1") == 2
    assert wf.branch_generation("v04ab_1") == 4
    assert wf.branch_generation("directions_foo") is None   # not a branch slug
    assert wf.branch_generation("v01.yaml") is None          # not a slug


# --- DEV-02 (UsageLastReview #2): prune → same-byte re-adopt must NOT succeed ---

def test_dev02_pruned_branch_same_byte_reject(tmp_path):
    """prune v02, then re-submit an IDENTICAL v02 → must reject (old code hit
    the idempotent no-op and returned success while the branch stayed
    inactive)."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "v02.yaml"
    body = "version: 1\nid: s\ndirection: fx-trend\n"
    src.write_text(body, encoding="utf-8")
    spec = _mk_spec(parent="v01", lesson="L1")   # valid lineage for v02
    wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src, spec)
    wf.prune_branch(tmp_path, "fx-trend", "alpha", "v02")
    # identical re-submit → reject (not a silent no-op)
    src2 = tmp_path / "v02_again.yaml"
    src2.write_text(body, encoding="utf-8")   # identical bytes
    with pytest.raises(wf.WorkflowError, match="pruned"):
        wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src2, spec)
    # it must remain inactive
    ev = wf.read_index_events(tmp_path, "fx-trend", "alpha")
    assert "v02" not in wf.active_branches_of(ev)


def test_dev02_active_branch_same_byte_still_idempotent(tmp_path):
    """A branch that is STILL active + identical bytes → idempotent no-op."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    src = tmp_path / "v02.yaml"
    body = "version: 1\nid: s\ndirection: fx-trend\n"
    src.write_text(body, encoding="utf-8")
    spec = _mk_spec(parent="v01", lesson="L1")   # valid lineage for v02
    d1 = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src, spec)
    src2 = tmp_path / "v02_b.yaml"
    src2.write_text(body, encoding="utf-8")   # identical, branch still active
    d2 = wf.adopt_branch(tmp_path, "fx-trend", "alpha", "v02", src2, spec)
    assert d1 == d2
    ev = wf.read_index_events(tmp_path, "fx-trend", "alpha")
    assert "v02" in wf.active_branches_of(ev)


# --- RED-02 (UsageLastReview #2): prune_branch validates direction/track ---

def test_red02_prune_validates_direction_and_track(tmp_path):
    """prune_branch must reject path-escape direction/track at the workflow
    boundary, not only in the CLI."""
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    for bad in ("../outside", "a/b", ".", ""):
        with pytest.raises(wf.WorkflowError):
            wf.prune_branch(tmp_path, bad, "alpha", "v02")
    for bad in ("../x", "a/b"):
        with pytest.raises(wf.WorkflowError):
            wf.prune_branch(tmp_path, "fx-trend", bad, "v02")
