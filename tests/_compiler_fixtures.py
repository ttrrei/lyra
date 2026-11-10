"""Fixtures for 0004 compiler tests (0004 §5 test matrix).

All strategies use registered features only (the 143-feature core registry).
Built as Python dicts and serialized to YAML so the parser's YAML path is
exercised exactly as in production.
"""
from __future__ import annotations

import yaml

from lyra.registry import Registry


def _registry() -> Registry:
    from lyra.features import build_registry

    return build_registry()


REGISTRY = _registry()


def dump(d) -> str:
    return yaml.safe_dump(d, sort_keys=False)


def parse(yaml_text: str):
    from lyra import strategy_schema as ss

    return ss.parse_yaml(yaml_text, REGISTRY)


def compile_it(spec):
    from lyra import compiler as cc

    return cc.compile_strategy(spec, REGISTRY)


# --- valid, registered-feature strategies ---------------------------------

VALID_RSI = {
    "version": 1,
    "id": "rsi_meanrev",
    "direction": "mean_reversion",
    "timeframe_minutes": 60,
    "entry": {
        "long": {"feature": "rsi_6", "op": "lt", "value": 30},
        "short": {"feature": "rsi_6", "op": "gt", "value": 70},
    },
    "exit": {
        "long": {"feature": "rsi_6", "op": "gt", "value": 50},
        "short": {"feature": "rsi_6", "op": "lt", "value": 50},
    },
    "execution": {
        "spread_bps": 5.0,
        "slippage_bps_per_side": 2.0,
        "commission_bps_round_trip": 0.5,
    },
}

VALID_STATE = {
    "version": 1,
    "id": "psar_trend",
    "direction": "trend_momentum",
    "timeframe_minutes": 5,
    "entry": {
        "long": {"feature": "psar_bullish", "op": "eq", "value": True},
        "short": {"feature": "psar_bearish", "op": "eq", "value": True},
    },
    "exit": {
        "long": {"feature": "psar_bullish", "op": "ne", "value": True},
        "short": {"feature": "psar_bearish", "op": "ne", "value": True},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

VALID_EVENT = {
    "version": 1,
    "id": "sma_cross",
    "direction": "trend_momentum",
    "timeframe_minutes": 60,
    "entry": {
        "long": {"feature": "sma_cross_up_6_24", "op": "eq", "value": True},
        "short": {"feature": "sma_cross_down_6_24", "op": "eq", "value": True},
    },
    "exit": {
        "long": {"feature": "sma_cross_up_6_24", "op": "ne", "value": True},
        "short": {"feature": "sma_cross_down_6_24", "op": "ne", "value": True},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

VALID_FVF = {
    "version": 1,
    "id": "feature_vs_feature",
    "direction": "trend_momentum",
    "timeframe_minutes": 60,
    "entry": {
        "long": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
        "short": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
    },
    "exit": {
        "long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
        "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

VALID_NESTED = {
    "version": 1,
    "id": "nested_bool",
    "direction": "mean_reversion",
    "timeframe_minutes": 60,
    "entry": {
        "long": {
            "all": [
                {"feature": "rsi_6", "op": "lt", "value": 35},
                {"any": [
                    {"feature": "roc_6", "op": "gt", "value": 0},
                    # H1 (batch-2 adversarial review): sma_alignment_6_24 is
                    # ordinal {-1,0,+1}; the fixture's old `eq true` compiled
                    # and, in DuckDB, `true == 1` matched the bullish row —
                    # semantically plausible but type-wrong.  Use the domain.
                    {"feature": "sma_alignment_6_24", "op": "eq", "value": 1},
                ]},
                {"not": {"feature": "psar_bearish", "op": "eq", "value": True}},
            ]
        },
        "short": {
            "all": [
                {"feature": "rsi_6", "op": "gt", "value": 65},
                {"any": [
                    {"feature": "roc_6", "op": "lt", "value": 0},
                    # H1: ordinal domain {-1,0,+1} (old `eq false` matched the
                    # neutral 0-state in DuckDB — rejected by the type gate).
                    {"feature": "sma_alignment_6_24", "op": "eq", "value": -1},
                ]},
            ]
        },
    },
    "exit": {
        "long": {"feature": "rsi_6", "op": "gt", "value": 55},
        "short": {"feature": "rsi_6", "op": "lt", "value": 45},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

VALID_HELD_FOR = {
    "version": 1,
    "id": "held_for",
    "direction": "trend_momentum",
    "timeframe_minutes": 60,
    "entry": {
        "long": {"held_for": {"bars": 3,
                              "condition": {"feature": "sma_6", "op": "gt", "value": "sma_24"}}},
        "short": {"held_for": {"bars": 3,
                               "condition": {"feature": "sma_6", "op": "lt", "value": "sma_24"}}},
    },
    "exit": {
        "long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
        "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

VALID_WITHIN = {
    "version": 1,
    "id": "within",
    "direction": "mean_reversion",
    "timeframe_minutes": 5,
    "entry": {
        "long": {"within": {"bars": 2,
                            "condition": {"feature": "rsi_divergence_up", "op": "eq", "value": True}}},
        "short": {"within": {"bars": 2,
                             "condition": {"feature": "rsi_divergence_down", "op": "eq", "value": True}}},
    },
    "exit": {
        "long": {"feature": "rsi_6", "op": "gt", "value": 55},
        "short": {"feature": "rsi_6", "op": "lt", "value": 45},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

VALID_AFTER_EVENT = {
    "version": 1,
    "id": "after_event",
    "direction": "trend_momentum",
    "timeframe_minutes": 60,
    "entry": {
        "long": {"after_event": {"bars": 4,
                                 "event": {"feature": "sma_cross_up_6_24", "op": "eq", "value": True},
                                 "condition": {"feature": "close", "op": "gt", "value": "sma_24"}}},
        "short": {"after_event": {"bars": 4,
                                  "event": {"feature": "sma_cross_down_6_24", "op": "eq", "value": True},
                                  "condition": {"feature": "close", "op": "lt", "value": "sma_24"}}},
    },
    "exit": {
        "long": {"feature": "sma_6", "op": "lt", "value": "sma_24"},
        "short": {"feature": "sma_6", "op": "gt", "value": "sma_24"},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}

# --- invalid / edge cases --------------------------------------------------

UNKNOWN_FEATURE = dict(VALID_RSI, entry={
    "long": {"feature": "range_position_24", "op": "gt", "value": 0.5},
    "short": {"feature": "range_position_24", "op": "lt", "value": 0.5},
})

BAD_TIMEFRAME = dict(VALID_RSI, timeframe_minutes=15)

STATE_OP_GT = dict(VALID_STATE, entry={
    "long": {"feature": "psar_bullish", "op": "gt", "value": 0},
    "short": {"feature": "psar_bearish", "op": "gt", "value": 0},
})

STOP_WIDEN = dict(VALID_RSI, execution=dict(VALID_RSI["execution"], stop_loss_pct=0.05))

NESTED_TEMPORAL = dict(VALID_HELD_FOR, entry={
    "long": {"held_for": {"bars": 2,
                          "condition": {"within": {"bars": 2,
                                                   "condition": {"feature": "rsi_6", "op": "lt", "value": 30}}}}},
    "short": {"feature": "rsi_6", "op": "gt", "value": 70},
})

DIRECTION_FAMILY_CONFLICT = {
    "version": 1,
    "id": "conflict",
    "direction": "trend_momentum",
    "family": "mean_reversion",
    "timeframe_minutes": 60,
    "entry": {
        "long": {"feature": "rsi_6", "op": "lt", "value": 30},
        "short": {"feature": "rsi_6", "op": "gt", "value": 70},
    },
    "exit": {
        "long": {"feature": "rsi_6", "op": "gt", "value": 50},
        "short": {"feature": "rsi_6", "op": "lt", "value": 50},
    },
    "execution": {"spread_bps": 5.0, "slippage_bps_per_side": 2.0,
                  "commission_bps_round_trip": 0.5},
}


def valid_rsi_yaml() -> str:
    return dump(VALID_RSI)


def example_missing_feature_yaml() -> str:
    """A strategy referencing a feature not in the registry (mirrors nova's 332)."""
    return dump(UNKNOWN_FEATURE)
