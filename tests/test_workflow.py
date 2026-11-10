"""0007 Part B — R12 workflow tests (I18/I21/I22, D5–D9)."""

from __future__ import annotations

import json

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
    c = ws / "data" / "features"
    c.mkdir(parents=True, exist_ok=True)
    (c / "catalog.json").write_text(json.dumps({"features": ["sma"]}), encoding="utf-8")


def _mk_run(ws, branch, *, trades=5, net=0.012, ann=0.10, win=0.6):
    """A 0006 metrics.json artifact whose spec_id references the branch."""
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


def test_new_version_unknown_track_fails(tmp_path):
    _mk_direction(tmp_path)
    with pytest.raises(wf.WorkflowError, match="unknown track"):
        wf.new_version(tmp_path, "fx-trend", "v02", track="ghost")


def test_new_version_duplicate_branch_fails(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    # same slug again → duplicate id → fail-fast (no overwrite, no rename)
    with pytest.raises(wf.WorkflowError, match="already exists"):
        wf.new_version(tmp_path, "fx-trend", "v02", track="alpha")
    # the original file is untouched
    assert (tmp_path / "strategies" / "fx-trend" / "v02.yaml").exists()


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
    assert oci_push.classify_path("strategies/fx-trend/v02.yaml") == "immutable"


# --- new-version template (0004 provenance reuse) ------------------------------


def test_new_version_writes_parent_and_lesson(tmp_path):
    _mk_direction(tmp_path)
    wf.create_track(tmp_path, "fx-trend", "alpha")
    target = wf.new_version(tmp_path, "fx-trend", "v02", track="alpha",
                            parent="v01", driven_by_lesson="L2")
    text = target.read_text(encoding="utf-8")
    assert "parent: v01" in text
    assert "parents:" in text and "  - v01" in text
    assert "driven_by_lesson: L2" in text
    # vNN>=2 without explicit lesson → placeholder required (R12)
    target2 = wf.new_version(tmp_path, "fx-trend", "v03", track="alpha", parent="v01")
    text2 = target2.read_text(encoding="utf-8")
    assert "driven_by_lesson: <TODO" in text2


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
    _mk_run(tmp_path, "v02", trades=7, net=0.02, ann=0.15, win=0.55)
    ctx = wf.render_context(tmp_path, "fx-trend", track="alpha")
    assert "v02" in ctx
    assert "r123456789" in ctx  # run id surfaced
    assert "trades=7" in ctx
    assert "ann=0.15" in ctx
    # hypothesis + lessons included
    assert "hypothesis" in ctx
    assert "volume filter helped" in ctx


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
    wf.create_track(tmp_path, "fx-trend", "alpha")
    wf.new_version(tmp_path, "fx-trend", "v02", track="alpha", parent="v01")
    wf.new_version(tmp_path, "fx-trend", "v03", track="alpha", parent="v01")
    src_before = {}
    for name in ("v02.yaml", "v03.yaml", "v01.yaml"):
        p = d / name
        src_before[name] = p.read_bytes()

    target = wf.merge(tmp_path, "fx-trend", ["v02", "v03"], track="alpha")
    assert target.exists()
    for name, data in src_before.items():
        assert (d / name).read_bytes() == data, f"source {name} was modified!"

    text = target.read_text(encoding="utf-8")
    assert "parents:" in text
    assert "  - v02" in text and "  - v03" in text
    assert "inherited:" in text
    # C6: provenance by content hash (audit chain survives prunes/renames)
    import hashlib as _h

    assert "# parent_sha256" in text
    v02_sha = _h.sha256((d / "v02.yaml").read_bytes()).hexdigest()
    v03_sha = _h.sha256((d / "v03.yaml").read_bytes()).hexdigest()
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
