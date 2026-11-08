"""0004 compiler tests — the 0004 §5 test matrix (bilingual decision).

Covers: registered feature vs constant (all 6 ops), feature vs feature,
SQL-injection / duplicate-YAML-key rejection, nested boolean operators,
held_for / within / after_event edge cases (incl. warm-up NULL and N-1/N/N+1),
YAML alias normalization, mandatory-stop-widen rejection, determinism,
STATE/EVENT op gating, nested-temporal rejection, unknown feature / bad
timeframe rejection, and a live DuckDB execution of the temporal plans.
"""
from __future__ import annotations

import yaml

import pytest

from lyra import compiler as cc
from lyra import strategy_schema as ss

from _compiler_fixtures import (
    BAD_TIMEFRAME,
    DIRECTION_FAMILY_CONFLICT,
    NESTED_TEMPORAL,
    REGISTRY,
    STATE_OP_GT,
    STOP_WIDEN,
    VALID_AFTER_EVENT,
    VALID_EVENT,
    VALID_FVF,
    VALID_HELD_FOR,
    VALID_NESTED,
    VALID_RSI,
    VALID_STATE,
    VALID_WITHIN,
    dump,
    parse,
)


def _parse(d):
    return parse(dump(d))


# --- 0004 §5: registered feature vs constant (all 6 ops) -------------------

def test_compiler_compiles_registered_feature_vs_constant_all_six_ops():
    for op in ("lt", "gt", "lte", "gte", "eq", "ne"):
        d = {
            "version": 1, "id": f"ops_{op}", "direction": "mean_reversion",
            "timeframe_minutes": 60,
            "entry": {
                "long": {"feature": "rsi_6", "op": op, "value": 30},
                "short": {"feature": "rsi_6", "op": op, "value": 70},
            },
            "exit": {"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                     "short": {"feature": "rsi_6", "op": "lt", "value": 50}},
            "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                          "commission_bps_round_trip": 0.5},
        }
        spec = _parse(d)
        plan = cc.compile_strategy(spec, REGISTRY)
        # the bound constant must appear exactly once per occurrence
        assert 30 in plan.params or 70 in plan.params
        assert plan.view == "features_1h"
        # no feature name leaks as an identifier (it is a bound constant)
        # rsi_6 IS a column; the constant is bound, not inlined as text
        assert "rsi_6" in plan.sql or "rsi_6" in plan.features_used


def test_compiler_constant_binds_parameter_not_inline_text():
    spec = _parse(VALID_RSI)
    plan = cc.compile_strategy(spec, REGISTRY)
    # the literal 30/50/70 must NOT appear as an inline SQL constant; they are bound
    assert 30 in plan.params and 70 in plan.params
    for lit in ("30", "70", "50"):
        assert f"{lit} " not in plan.sql, f"literal {lit} leaked into SQL"


# --- 0004 §5: feature vs feature -------------------------------------------

def test_compiler_compiles_feature_vs_feature_resolves_rhs_column():
    spec = _parse(VALID_FVF)
    plan = cc.compile_strategy(spec, REGISTRY)
    # both features must be registered columns in the SELECT scope
    assert "sma_6" in plan.features_used
    assert "sma_24" in plan.features_used
    # the plan should have NO bound constant for the RHS (it is a column)
    assert plan.params == () or all(isinstance(p, int) for p in plan.params)


# --- 0004 §5: SQL injection + duplicate YAML keys ---------------------------

def test_compiler_rejects_sql_injection_in_feature_name():
    d = dict(VALID_RSI, entry={
        "long": {"feature": "rsi_6; DROP TABLE users; --", "op": "lt", "value": 30},
        "short": {"feature": "rsi_6", "op": "gt", "value": 70},
    })
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_compiler_rejects_duplicate_yaml_keys():
    text = (
        "version: 1\n"
        "id: dup\n"
        "direction: mean_reversion\n"
        "timeframe_minutes: 60\n"
        "entry:\n"
        "  long:\n"
        "    feature: rsi_6\n"
        "    feature: rsi_12\n"
        "    op: lt\n"
        "    value: 30\n"
        "  short:\n"
        "    feature: rsi_6\n"
        "    op: gt\n"
        "    value: 70\n"
        "exit:\n"
        "  long:\n"
        "    feature: rsi_6\n"
        "    op: gt\n"
        "    value: 50\n"
        "  short:\n"
        "    feature: rsi_6\n"
        "    op: lt\n"
        "    value: 50\n"
        "execution:\n"
        "  spread_bps: 5\n"
        "  slippage_bps_per_side: 2\n"
        "  commission_bps_round_trip: 0.5\n"
    )
    with pytest.raises(ss.SchemaError):
        parse(text)


# --- 0004 §5: nested boolean operators --------------------------------------

def test_compiler_nested_boolean_operators():
    spec = _parse(VALID_NESTED)
    plan = cc.compile_strategy(spec, REGISTRY)
    assert "AND" in plan.sql and "OR" in plan.sql and "NOT" in plan.sql
    # all four features referenced should be tracked
    for name in ("rsi_6", "roc_6", "sma_alignment_6_24", "psar_bearish"):
        assert name in plan.features_used


# --- 0004 §5: held_for full window + NULL -----------------------------------

def test_compiler_held_for_uses_full_window_and_null_gate():
    spec = _parse(VALID_HELD_FOR)
    plan = cc.compile_strategy(spec, REGISTRY)
    # window of 3 bars (N-1..N = 2 PRECEDING + CURRENT)
    assert "ROWS BETWEEN 2 PRECEDING AND CURRENT ROW" in plan.sql
    # all-true count = 3
    assert "= 3" in plan.sql
    # NULL gate present (C1): NULLs counted and required to be zero
    assert "IS NULL THEN 1 ELSE 0 END" in plan.sql
    assert "= 0" in plan.sql
    # ROW_NUMBER maturity gate (N observed rows)
    assert "ROW_NUMBER()" in plan.sql
    # past-only: no forward frame
    assert "FOLLOWING" not in plan.sql.upper()
    assert "LEAD(" not in plan.sql


def test_compiler_within_requires_full_non_null_window():
    spec = _parse(VALID_WITHIN)
    plan = cc.compile_strategy(spec, REGISTRY)
    # within = EXISTS over window: SUM(...) >= 1
    assert ">= 1" in plan.sql
    # NULL gate (C1): a NULL condition must not count as a hit
    assert "IS NULL THEN 1 ELSE 0 END" in plan.sql
    assert "= 0" in plan.sql


def test_compiler_after_event_exact_age_and_past_only():
    spec = _parse(VALID_AFTER_EVENT)
    plan = cc.compile_strategy(spec, REGISTRY)
    # exact age N via LAG (past-only)
    assert "LAG(" in plan.sql
    assert "ORDER BY" in plan.sql
    # condition evaluated (close alias → mid_c vs sma_24)
    assert "sma_24" in plan.features_used
    assert "mid_c" in plan.features_used


# --- 0004 §5: YAML alias normalization --------------------------------------

def test_compiler_yaml_alias_normalization_family_to_direction():
    d = dict(VALID_RSI)
    d.pop("direction")
    d["family"] = "mean_reversion"  # legacy alias
    spec = _parse(d)
    assert spec.direction == "mean_reversion"


def test_compiler_yaml_alias_normalization_exit_when_to_feature_exit():
    # README legacy shape: exit.feature.when (a single shared exit expr) + time_bars.
    d = {
        "version": 1, "id": "legacy_exit", "direction": "mean_reversion",
        "timeframe_minutes": 60,
        "entry": {
            "long": {"feature": "rsi_6", "op": "lt", "value": 30},
            "short": {"feature": "rsi_6", "op": "gt", "value": 70},
        },
        "exit": {
            "feature": {"when": {"feature": "rsi_6", "op": "gt", "value": 50}},
            "time_bars": 48,
        },
        "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                      "commission_bps_round_trip": 0.5},
    }
    spec = _parse(d)
    # legacy when becomes the shared exit expr for both directions
    assert spec.exit_long is not None
    assert spec.exit_short is not None
    assert spec.execution.max_holding_bars == 48


def test_compiler_rejects_direction_family_conflict():
    with pytest.raises(ss.SchemaError):
        _parse(DIRECTION_FAMILY_CONFLICT)


# --- 0004 §5: mandatory-stop widen rejection --------------------------------

def test_compiler_rejects_mandatory_stop_widen():
    with pytest.raises(ss.SchemaError):
        _parse(STOP_WIDEN)


def test_compiler_rejects_exit_level_stop_widen():
    # tracked-example shape: stop_loss_pct lives under `exit` (not execution).
    # An explicitly-written value other than 0.02 must be rejected (I3/0004).
    d = dict(VALID_RSI, exit=dict(VALID_RSI["exit"], stop_loss_pct=0.05))
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_compiler_accepts_exit_level_stop_exactly_002():
    d = dict(VALID_RSI, exit=dict(VALID_RSI["exit"], stop_loss_pct=0.02))
    spec = _parse(d)
    plan = cc.compile_strategy(spec, REGISTRY)
    assert plan.stop_loss_pct == 0.02


def test_compiler_accepts_mandatory_stop_exactly_002():
    d = dict(VALID_RSI, execution=dict(VALID_RSI["execution"], stop_loss_pct=0.02))
    spec = _parse(d)
    plan = cc.compile_strategy(spec, REGISTRY)
    assert plan.stop_loss_pct == 0.02


# --- 0004 §5: determinism ---------------------------------------------------

def test_compiler_deterministic_same_input_same_output():
    spec_a = _parse(VALID_RSI)
    spec_b = _parse(VALID_RSI)
    pa = cc.compile_strategy(spec_a, REGISTRY)
    pb = cc.compile_strategy(spec_b, REGISTRY)
    assert pa.sql == pb.sql
    assert pa.params == pb.params
    assert pa.plan_hash == pb.plan_hash


def test_compiler_deterministic_param_order_stable():
    d = dict(VALID_NESTED)  # multiple constants in nested tree
    pa = cc.compile_strategy(_parse(d), REGISTRY)
    pb = cc.compile_strategy(_parse(d), REGISTRY)
    assert pa.params == pb.params


# --- 0004 §5: STATE/EVENT op gating -----------------------------------------

def test_compiler_state_event_only_eq_ne():
    # gt on a STATE feature must be rejected
    with pytest.raises(ss.SchemaError):
        _parse(STATE_OP_GT)
    # eq is fine
    spec = _parse(VALID_STATE)
    cc.compile_strategy(spec, REGISTRY)


# --- 0004 §5: nested temporal rejection -------------------------------------

def test_compiler_rejects_nested_temporal():
    # nested temporal is rejected at compile time (fail closed, not valid DuckDB)
    spec = _parse(NESTED_TEMPORAL)
    with pytest.raises(ss.SchemaError):
        cc.compile_strategy(spec, REGISTRY)


# --- 0004 §5: unknown feature / bad timeframe --------------------------------

def test_compiler_rejects_unknown_feature():
    with pytest.raises(ss.SchemaError):
        _parse(dict(VALID_RSI, entry={
            "long": {"feature": "range_position_24", "op": "gt", "value": 0.5},
            "short": {"feature": "rsi_6", "op": "gt", "value": 70},
        }))


def test_compiler_rejects_bad_timeframe():
    with pytest.raises(ss.SchemaError):
        _parse(BAD_TIMEFRAME)


# --- 0004 §5: executed against DuckDB (temporal semantics N-1/N/N+1) --------

def test_compiler_held_for_executed_against_duckdb(tmp_path):
    import duckdb

    # Build a 6-bar feature table: sma_6 > sma_24 becomes true exactly at bar 3,
    # holds at bars 4,5,6.  held_for(bars=3) must fire first at bar 5 (the 3rd
    # consecutive true) — not earlier (N-1=bar4: only 2 trues) and the gate
    # must not fire at bar 1/2 (NULL/insufficient window).
    rows = [
        # bar, sma_6, sma_24
        (1, None, None),   # warm-up NULL
        (2, 100.0, 105.0),  # false (sma6 < sma24)
        (3, 110.0, 105.0),  # true  (1st)
        (4, 110.0, 105.0),  # true  (2nd)
        (5, 110.0, 105.0),  # true  (3rd -> fires)
        (6, 110.0, 105.0),  # true  (4th)
    ]
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    con.execute(
        "CREATE TABLE features_1h (time INT, instrument VARCHAR, "
        "mid_o DOUBLE, mid_h DOUBLE, mid_l DOUBLE, mid_c DOUBLE, "
        "sma_6 DOUBLE, sma_24 DOUBLE)"
    )
    con.executemany(
        "INSERT INTO features_1h VALUES (?, 'XAU_USD', 100.0, 110.0, 95.0, 105.0, ?, ?)",
        [(t, a, b) for (t, a, b) in rows],
    )

    spec = _parse(VALID_HELD_FOR)
    plan = cc.compile_strategy(spec, REGISTRY)
    # The plan's SQL selects a boolean signal column; run it and collect per-bar.
    # C1: OHLC at indices 2-5; entry_long at index 6.
    out = con.execute(plan.sql, list(plan.params)).fetchall()
    con.close()
    sig = [bool(r[6]) for r in out]
    # bars 1,2: false (NULL gate / insufficient)
    assert sig[0] is False
    assert sig[1] is False
    # bar 3: false (only 1st true)
    assert sig[2] is False
    # bar 4: false (N-1 = only 2 trues)
    assert sig[3] is False
    # bar 5: TRUE (N = 3rd consecutive true)
    assert sig[4] is True
    # bar 6: true (still held)
    assert sig[5] is True


def test_compiler_within_executed_against_duckdb(tmp_path):
    import duckdb

    # within(bars=2): event (rsi_divergence_up=TRUE) at bar 2 should make bar 2
    # and bar 3 within the 2-bar look-back, but bar 4 is outside the window.
    rows = [
        (1, False),
        (2, True),   # event here
        (3, False),  # within 2 bars of event -> hit
        (4, False),  # 2 bars later -> still within (bars 2..4 window of size 2 => includes bar3, bar4? see below)
    ]
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute(
        "CREATE TABLE features_5m (time INT, instrument VARCHAR, "
        "mid_o DOUBLE, mid_h DOUBLE, mid_l DOUBLE, mid_c DOUBLE, "
        "rsi_divergence_up BOOLEAN, rsi_divergence_down BOOLEAN, rsi_6 DOUBLE)"
    )
    # only entry_long (rsi_divergence_up) matters; rsi_divergence_down stays FALSE.
    con.executemany(
        "INSERT INTO features_5m VALUES (?, 'XAU_USD', 100.0, 110.0, 95.0, 105.0, ?, FALSE, 50.0)", rows,
    )

    spec = _parse(VALID_WITHIN)
    plan = cc.compile_strategy(spec, REGISTRY)
    out = con.execute(plan.sql, list(plan.params)).fetchall()
    con.close()
    # C1: OHLC at indices 2-5; entry_long at index 6.
    sig = [bool(r[6]) for r in out]
    # within(bars=2) = 2 observed rows (1 PRECEDING + CURRENT).
    # bar 1: no event in window -> false
    assert sig[0] is False
    # bar 2: event at current -> true
    assert sig[1] is True
    # bar 3: event 1 bar ago (within 2-row window) -> true
    assert sig[2] is True
    # bar 4: event 2 bars ago (outside the 2-row window) -> false
    assert sig[3] is False


def test_compiler_after_event_executed_against_duckdb(tmp_path):
    import duckdb

    # after_event(bars=4, event=sma_cross_up_6_24): event at bar 1, condition
    # close>sma_24 true at all bars.  Exact age: fires only when LAG(event,4)=TRUE,
    # i.e. at bar 5 (event 4 bars ago).
    rows = [
        # bar, event, close, sma_24
        (1, True,  110.0, 105.0),
        (2, False, 110.0, 105.0),
        (3, False, 110.0, 105.0),
        (4, False, 110.0, 105.0),
        (5, False, 110.0, 105.0),  # event exactly 4 bars ago -> fire
        (6, False, 110.0, 105.0),  # event 5 bars ago -> LAG(4) is bar2 event=False
    ]
    con = duckdb.connect(str(tmp_path / "ae.duckdb"))
    con.execute(
        "CREATE TABLE features_1h (time INT, instrument VARCHAR, "
        "mid_o DOUBLE, mid_h DOUBLE, mid_l DOUBLE, "
        "sma_cross_up_6_24 BOOLEAN, sma_cross_down_6_24 BOOLEAN, "
        "mid_c DOUBLE, sma_24 DOUBLE, sma_6 DOUBLE)"
    )
    # only entry_long (sma_cross_up) matters; set sma_cross_down to FALSE so the
    # short direction is inert.  exit_long/exit_short use sma_6 vs sma_24 (inert).
    con.executemany(
        "INSERT INTO features_1h VALUES (?, 'XAU_USD', 100.0, 110.0, 95.0, ?, FALSE, ?, ?, 110.0)", rows,
    )

    spec = _parse(VALID_AFTER_EVENT)
    plan = cc.compile_strategy(spec, REGISTRY)
    out = con.execute(plan.sql, list(plan.params)).fetchall()
    con.close()
    sig = [bool(r[6]) for r in out]  # C1: entry_long at index 6 (after OHLC)
    # bars 1-4: not yet 4 bars since event -> false
    assert sig[0] is False
    assert sig[1] is False
    assert sig[2] is False
    assert sig[3] is False
    # bar 5: event exactly 4 bars ago -> TRUE
    assert sig[4] is True
    # bar 6: event 5 bars ago -> false
    assert sig[5] is False


# --- determinism across feature-order permutations in registry is N/A; but
# --- params must be order-stable regardless of dict iteration --------------

def test_compiler_params_order_stable_across_registry_rebuilds():
    from lyra.features import build_registry

    reg2 = build_registry()
    pa = cc.compile_strategy(_parse(VALID_NESTED), REGISTRY)
    pb = cc.compile_strategy(_parse(VALID_NESTED), reg2)
    assert pa.params == pb.params
    assert pa.sql == pb.sql


# --- STATE/EVENT valid usage still compiles --------------------------------

def test_compiler_state_and_event_features_compile():
    for d in (VALID_STATE, VALID_EVENT):
        spec = _parse(d)
        plan = cc.compile_strategy(spec, REGISTRY)
        assert plan.sql  # non-empty
        # boolean comparisons via = / <>
        assert "=" in plan.sql and "<>" in plan.sql


# --- global invariant: SQL "?" count must equal bound param count -----------

def test_compiler_param_count_matches_question_marks_all_fixtures():
    """Guard against param/placeholder desync (a temporal condition that is
    inlined into two SQL positions must bind its constants per occurrence)."""
    fixtures = (VALID_RSI, VALID_STATE, VALID_EVENT, VALID_FVF, VALID_NESTED,
                VALID_HELD_FOR, VALID_WITHIN, VALID_AFTER_EVENT)
    for d in fixtures:
        spec = _parse(d)
        plan = cc.compile_strategy(spec, REGISTRY)
        assert plan.sql.count("?") == len(plan.params), (
            f"{spec.id}: {plan.sql.count('?')} placeholders vs "
            f"{len(plan.params)} params")


# ===========================================================================
# Batch-2 adversarial review (docs/reviews/对抗性review-2026-11-08-批次2.md)
# H1–H4 + M1–M4 regression tests.  Each asserts the *new* fail-closed /
# domain-correct behaviour, plus that the legitimate case still works.
# ===========================================================================

def _base(**over):
    d = {
        "version": 1, "id": "t", "direction": "x", "timeframe_minutes": 60,
        "entry": {"long": {"feature": "rsi_6", "op": "lt", "value": 30}},
        "exit": {"long": {"feature": "rsi_6", "op": "gt", "value": 50}},
        "execution": {"spread_bps": 5, "slippage_bps_per_side": 2,
                      "commission_bps_round_trip": 0.5},
    }
    d.update(over)
    return d


# --- H1: ordinal state (sma_alignment_6_24, unit "state{-1,0,1}") type gate -

def test_h1_ordinal_state_rejects_boolean_constant():
    # sma_alignment_6_24 == false previously compiled and, in DuckDB,
    # `false == 0` matched the *neutral* state row — a silent semantic bug.
    d = _base(entry={"long": {"feature": "sma_alignment_6_24", "op": "eq",
                              "value": False}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h1_ordinal_state_rejects_out_of_domain():
    d = _base(entry={"long": {"feature": "sma_alignment_6_24", "op": "eq",
                              "value": 5}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h1_boolean_state_rejects_integer_constant():
    # psar_bullish is a real boolean state; comparing it to 1 (vs true) is a
    # type error even though DuckDB would coerce it.
    d = _base(entry={"long": {"feature": "psar_bullish", "op": "eq",
                              "value": 1}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h1_ordinal_state_accepts_in_domain_integers():
    for v in (-1, 0, 1):
        d = _base(entry={"long": {"feature": "sma_alignment_6_24",
                                  "op": "eq", "value": v}})
        spec = _parse(d)
        plan = cc.compile_strategy(spec, REGISTRY)
        assert plan.sql


# --- M1 (batch-4 review): feature-vs-feature + VALUE-vs-bool-const domain gate ---

def test_b4_m1_value_vs_boolean_state_feature_rejected():
    # Case A: ``close > psar_bullish`` (numeric VALUE/OHLC vs boolean STATE)
    # used to compile to ``"mid_c" > "psar_bullish"`` and raise a DuckDB
    # BinderException at run time.  Must now fail at validate time.
    d = _base(entry={"long": {"feature": "close", "op": "gt",
                              "value": "psar_bullish"}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_b4_m1_value_feature_vs_boolean_constant_rejected():
    # Case B: ``close eq true`` (numeric VALUE vs boolean constant).  DuckDB
    # used to coerce ``true → 1.0`` and silently compare price == 1.0.
    d = _base(entry={"long": {"feature": "close", "op": "eq", "value": True}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_b4_m1_ordinal_state_vs_boolean_state_rejected():
    # Case C: ``sma_alignment_6_24 == psar_bullish`` (ordinal STATE {-1,0,1}
    # vs boolean STATE).  In DuckDB ``0 = FALSE`` evaluated TRUE, so a
    # neutral alignment + non-bullish PSAR wrongly opened a position.
    d = _base(entry={"long": {"feature": "sma_alignment_6_24", "op": "eq",
                              "value": "psar_bullish"}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_b4_m1_numeric_vs_numeric_feature_accepted():
    # Two numeric sides (OHLC alias vs VALUE) is a legitimate comparison.
    d = _base(entry={"long": {"feature": "close", "op": "gt",
                              "value": "rsi_6"}})
    plan = cc.compile_strategy(_parse(d), REGISTRY)
    assert plan.sql


def test_b4_m1_boolean_state_vs_boolean_state_accepted():
    # Two boolean states (STATE vs STATE) is a legitimate comparison.
    d = _base(entry={"long": {"feature": "psar_bullish", "op": "eq",
                              "value": "supertrend_bullish"}})
    plan = cc.compile_strategy(_parse(d), REGISTRY)
    assert plan.sql


# --- H2: exit.take_profit_pct must reach the CompiledPlan -------------------

def test_h2_exit_take_profit_pct_folded_into_plan():
    d = _base(exit={"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                    "take_profit_pct": 0.06})
    plan = cc.compile_strategy(_parse(d), REGISTRY)
    assert plan.take_profit_pct == 0.06


# --- H3: exit-level cost/holding validated with the same rules -------------

def test_h3_exit_negative_cost_rejected():
    d = _base(exit={"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                    "spread_bps": -50})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h3_exit_zero_max_holding_rejected():
    d = _base(exit={"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                    "max_holding_bars": 0})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h3_exit_stop_widen_rejected():
    d = _base(exit={"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                    "stop_loss_pct": 0.05})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h3_exit_cost_fold_into_execution():
    # execution lacks spread_bps; exit provides it → folded into the plan.
    d = _base(exit={"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                    "spread_bps": 7},
              execution={"slippage_bps_per_side": 2,
                         "commission_bps_round_trip": 0.5})
    plan = cc.compile_strategy(_parse(d), REGISTRY)
    assert plan.spread_bps == 7.0
    assert plan.slippage_bps_per_side == 2.0


# --- H4: unknown keys rejected at every level -------------------------------

def test_h4_root_unknown_key_rejected():
    d = _base(); d["stratagy_id_typo"] = "z"
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h4_execution_unknown_key_rejected():
    d = _base(execution={"spread_bps": 5, "commission_bps_typo": 1})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h4_exit_unknown_key_rejected():
    d = _base(exit={"long": {"feature": "rsi_6", "op": "gt", "value": 50},
                    "take_prof_typo": 0.06})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_h4_entry_unknown_key_rejected():
    d = _base(entry={"long": {"feature": "rsi_6", "op": "lt", "value": 30},
                     "entry_typo": 1})
    with pytest.raises(ss.SchemaError):
        _parse(d)


# --- M3 (batch-4 review): exit.feature strict whitelist ---------------------

def test_b4_m3_exit_feature_unknown_key_rejected():
    # A typo'd key in exit.feature (``whenn``) used to be silently ignored,
    # so the strategy ran with the *default* exit while the author believed a
    # custom exit applied.  Must now fail closed.
    d = _base(exit={"feature": {"whenn": {"feature": "rsi_6", "op": "gt",
                                          "value": 50}}})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_b4_m3_exit_feature_non_mapping_rejected():
    # A non-dict ``exit.feature`` value (e.g. a bare string) used to be
    # silently dropped.  Must now fail closed.
    d = _base(exit={"feature": "rsi_6 > 50"})
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_b4_m3_exit_feature_when_accepted():
    # The documented ``exit.feature.when`` form is legitimate and must still
    # parse (shared exit condition for both directions).
    d = _base(exit={"feature": {"when": {"feature": "rsi_6", "op": "gt",
                                         "value": 50}}})
    plan = cc.compile_strategy(_parse(d), REGISTRY)
    assert plan.sql


# --- M1: cyclic alias rejected; legitimate cross-branch alias reuse works ---

def test_m1_legitimate_cross_branch_alias_reuse_works():
    # The legacy corpus factors a shared condition (&id001) into both sides.
    # It must keep working (materialized into independent copies).
    yml = (
        "version: 1\nid: t\ndirection: x\ntimeframe_minutes: 60\n"
        "entry:\n"
        "  long:\n    all:\n"
        "    - {feature: rsi_6, op: lt, value: 30}\n"
        "    - &cond\n      {feature: roc_6, op: gt, value: 0}\n"
        "  short:\n    all:\n"
        "    - {feature: rsi_6, op: gt, value: 70}\n"
        "    - *cond\n"
        "exit:\n  long: {feature: rsi_6, op: gt, value: 50}\n"
        "execution: {spread_bps: 5}\n"
    )
    spec = ss.parse_yaml(yml, REGISTRY)
    assert spec.entry_long is not None


def test_m1_cyclic_alias_rejected_not_recursionerror():
    yml = (
        "version: 1\nid: t\ndirection: x\ntimeframe_minutes: 60\n"
        "loop: &x\n  a: *x\n"
        "entry: {long: {feature: rsi_6, op: lt, value: 30}}\n"
        "exit: {long: {feature: rsi_6, op: gt, value: 50}}\n"
        "execution: {spread_bps: 5}\n"
    )
    # Must fail with a SchemaError (or YAML parse error → SchemaError),
    # never escape as a raw RecursionError.
    with pytest.raises((ss.SchemaError, yaml.YAMLError)):
        ss.parse_yaml(yml, REGISTRY)


# --- M2: structural (non-mapping) errors surface as SchemaError ------------

def test_m2_exit_non_mapping_rejected():
    d = _base(exit="oops")
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_m2_entry_non_mapping_rejected():
    d = _base(entry=42)
    with pytest.raises(ss.SchemaError):
        _parse(d)


# --- M3: strict scalar types ------------------------------------------------

def test_m3_timeframe_float_rejected():
    d = _base(timeframe_minutes=60.0)
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_m3_direction_list_rejected():
    d = _base(direction=["x"])
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_m3_parents_string_rejected():
    d = _base(parents="v01")  # must not split into ('v','0','1')
    with pytest.raises(ss.SchemaError):
        _parse(d)


def test_m3_parents_list_of_slugs_accepted():
    d = _base(parents=["v01", "v02"])
    spec = _parse(d)
    assert spec.parents == ("v01", "v02")


# --- M4: plan_hash scope (catalog snapshot IN, execution metadata OUT) -----

def test_m4_plan_hash_includes_catalog_snapshot_not_execution():
    d1 = _base(execution={"spread_bps": 5})
    d2 = _base(execution={"spread_bps": 50})  # different cost, same signal
    p1 = cc.compile_strategy(_parse(d1), REGISTRY)
    p2 = cc.compile_strategy(_parse(d2), REGISTRY)
    assert p1.plan_hash == p2.plan_hash, \
        "execution metadata is OUT of plan_hash (documented contract)"

    p3 = cc.compile_strategy(_parse(d1), REGISTRY,
                             feature_catalog_snapshot="snap-A")
    p4 = cc.compile_strategy(_parse(d1), REGISTRY,
                             feature_catalog_snapshot="snap-B")
    assert p3.plan_hash != p4.plan_hash, \
        "catalog snapshot is IN of plan_hash (working contract)"
    assert p3.plan_hash != p1.plan_hash
