"""YAML → past-only SQL compiler (decision 0004 §3.1 codegen).

Turns a validated :class:`~lyra.strategy_schema.StrategySpec` into a
deterministic DuckDB *signal* SELECT over the timeframe's Catalog feature
view.  This module:

* maps each comparison op (enum) to a fixed SQL token — no user SQL fragments,
  no callbacks, no UDFs, no Jinja (I9 / 0004 adversarial self-check);
* quotes every column identifier (resolved from the Registry / OHLC whitelist)
  and binds every constant with ``?`` — never spliced into the text (0004 §3.1);
* emits only *past-only* windows: ``ROWS BETWEEN N-1 PRECEDING AND CURRENT
  ROW``, ``lag(event, N)``, and ``ROWS`` frames ending at the current row
  (I10 — no ``lead``, no future frames, no future joins);
* preserves SQL three-valued logic: ``not(NULL)`` stays NULL, and only a
  ``TRUE`` result is a candidate signal (C2);
* is deterministic: identical strategy + registry ⇒ identical SQL and identical
  bind-parameter order (no time, no randomness, no process state).

It does **not** execute the SQL, run the trade state machine, compute
stops/slippage/financing, or build reports (0005 / 0006).  Track / AI /
version-tree metadata never enters the SQL AST (0004 invariant: track is a
research identity, not an execution identity).

Temporal semantics (0004 §3.1), all with a *full N-row, non-NULL* gate (C1):

* ``held_for{bars: N, condition}`` — over the N rows ending at the current
  row: TRUE only when every one of the N condition values is TRUE; NULL when
  fewer than N rows are available (partition head) or any of them is NULL.
* ``within{bars: N, condition}`` — over the N rows ending at the current
  row: TRUE only when at least one of the N non-NULL condition values is TRUE
  (and all N are non-NULL); NULL on an incomplete / NULL window.
* ``after_event{bars: N, event, condition}`` — TRUE only when ``event`` was
  TRUE exactly N observed rows before (``lag(event, N)``, past-only) AND the
  ``condition`` is TRUE over the N rows ending at the current row.  NULLs
  never become TRUE.

Nested temporal operators (a temporal inside another temporal's condition or
event) are rejected: each temporal already spans a window frame, and nesting
window functions inside window functions is not valid DuckDB and is outside
the 0004 grammar.  Scalar leaves, ``all/any/not`` may nest freely.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .registry import Registry
from .strategy_schema import (
    AllNode,
    AnyNode,
    AfterEventNode,
    ExprNode,
    HeldForNode,
    NotNode,
    SchemaError,
    StrategySpec,
    WithinNode,
    _LeafNode,
    ComparisonLeaf,
)

__all__ = ["CompiledPlan", "compile_strategy", "sql_for_plan"]


# ---------------------------------------------------------------------------
# Fixed operator → token map (enum only; no user-controlled SQL)
# ---------------------------------------------------------------------------

_OP_TOKEN = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}


def _q(ident: str) -> str:
    """DuckDB identifier quoting.  Rejects any identifier that is not a plain
    ``[a-z0-9_]`` slug (all resolved names are Registry/OHLC slugs, so a
    failure here indicates an internal bug, not a user input — fail closed)."""
    if not ident or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        for ch in ident
    ):
        raise SchemaError(f"unsafe column identifier rejected: {ident!r}")
    return f'"{ident}"'


_INSTR = _q("instrument")
_TIME = _q("time")


# ---------------------------------------------------------------------------
# CompiledPlan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompiledPlan:
    """A deterministic, bindable signal plan for one strategy (0004 §3.1)."""
    strategy_id: str
    view: str
    timeframe_minutes: int
    sql: str
    params: tuple[Any, ...]
    features_used: tuple[str, ...]
    # execution metadata (stop/tp/holding/costs) — carried through, computed in 0005
    stop_loss_pct: float
    take_profit_pct: float | None
    max_holding_bars: int | None
    spread_bps: float | None
    slippage_bps_per_side: float | None
    commission_bps_round_trip: float | None
    financing_bps_per_day: float | None
    # audit metadata (never enters SQL):
    direction: str | None
    parents: tuple[str, ...]
    plan_hash: str
    # deterministic provenance inputs (0004 §5):
    schema_version: int
    feature_catalog_snapshot: str | None
    compiler_version: str

    def summary(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "view": self.view,
            "timeframe_minutes": self.timeframe_minutes,
            "features_used": list(self.features_used),
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "max_holding_bars": self.max_holding_bars,
            "plan_hash": self.plan_hash,
        }


# ---------------------------------------------------------------------------
# Emission context: local accumulator for params + window frames (no globals)
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self) -> None:
        self.params: list[Any] = []

    def const(self, value: Any) -> None:
        self.params.append(value)


def _inline_window(bars: int) -> str:
    """Inline window spec for a single function call.

    Inline (rather than a shared named window) because DuckDB 2.0 rejects a
    named window that carries a frame clause being referenced by more than one
    window function ("cannot copy window ... because it has a frame clause").
    Inline specs keep every call self-contained and version-robust.
    """
    return (
        f"PARTITION BY {_INSTR} ORDER BY {_TIME} "
        f"ROWS BETWEEN {bars - 1} PRECEDING AND CURRENT ROW"
    )


# ---------------------------------------------------------------------------
# Temporal detection (to reject nesting)
# ---------------------------------------------------------------------------

def _is_temporal(node: ExprNode) -> bool:
    return isinstance(node, (HeldForNode, WithinNode, AfterEventNode))


def _contains_temporal(node: ExprNode) -> bool:
    if _is_temporal(node):
        return True
    if isinstance(node, (AllNode, AnyNode)):
        return any(_contains_temporal(c) for c in node.children)
    if isinstance(node, NotNode):
        return _contains_temporal(node.child)
    return False


def _require_no_nested_temporal(node: ExprNode, where: str) -> None:
    if _contains_temporal(node):
        raise SchemaError(
            "nested temporal operators (a temporal inside another temporal's "
            f"{where}) are not allowed — flatten them into scalar conditions",
            yaml_path=where or None)


# ---------------------------------------------------------------------------
# Scalar + temporal emission
# ---------------------------------------------------------------------------

def _emit(node: ExprNode, ctx: _Ctx) -> str:
    if isinstance(node, _LeafNode):
        return _emit_leaf(node.cmp, ctx)
    if isinstance(node, NotNode):
        return f"(NOT {_emit(node.child, ctx)})"
    if isinstance(node, AllNode):
        parts = [_emit(c, ctx) for c in node.children]
        return "(" + " AND ".join(parts) + ")"
    if isinstance(node, AnyNode):
        parts = [_emit(c, ctx) for c in node.children]
        return "(" + " OR ".join(parts) + ")"
    if isinstance(node, (HeldForNode, WithinNode, AfterEventNode)):
        return _emit_temporal(node, ctx)
    raise SchemaError(f"unsupported expression node {type(node).__name__}",
                      yaml_path=getattr(node, "yaml_path", None))


def _emit_leaf(cmp: ComparisonLeaf, ctx: _Ctx) -> str:
    token = _OP_TOKEN[cmp.op]
    left = _q(cmp.left_col)
    if cmp.right_is_const:
        ctx.const(cmp.right_const)
        return f"({left} {token} ?)"
    return f"({left} {token} {_q(cmp.right_col)})"


def _full_non_null_gate(bars: int, cond_node: ExprNode, ctx: _Ctx) -> str:
    """NULL when the N-row window is incomplete (partition head) or has NULLs.

    ``ROW_NUMBER()`` counts total observed rows at the current row (head
    detection); a NULL count over the frame detects warm-up NULLs (C1).
    The condition is emitted *here* so its constant bindings register in the
    same ctx as the count occurrence — each occurrence emits independently and
    the SQL ``?`` count always matches ``ctx.params``.
    """
    cond_sql = _emit(cond_node, ctx)
    rownum = f"ROW_NUMBER() OVER (PARTITION BY {_INSTR} ORDER BY {_TIME})"
    nulls = (f"SUM(CASE WHEN {cond_sql} IS NULL THEN 1 ELSE 0 END) "
             f"OVER ({_inline_window(bars)})")
    return f"(({rownum} >= {bars}) AND ({nulls} = 0))"


def _emit_temporal(node: ExprNode, ctx: _Ctx) -> str:
    if isinstance(node, HeldForNode):
        _require_no_nested_temporal(node.condition, "held_for.condition")
        bars = node.bars
        gate = _full_non_null_gate(bars, node.condition, ctx)
        # emit the condition fresh for the count occurrence (its own param bindings)
        all_true = (f"(SUM(CASE WHEN {_emit(node.condition, ctx)} THEN 1 ELSE 0 END) "
                    f"OVER ({_inline_window(bars)}) = {bars})")
        return f"(CASE WHEN {gate} THEN {all_true} ELSE NULL END)"

    if isinstance(node, WithinNode):
        _require_no_nested_temporal(node.condition, "within.condition")
        bars = node.bars
        gate = _full_non_null_gate(bars, node.condition, ctx)
        any_true = (f"(SUM(CASE WHEN {_emit(node.condition, ctx)} THEN 1 ELSE 0 END) "
                    f"OVER ({_inline_window(bars)}) >= 1)")
        return f"(CASE WHEN {gate} THEN {any_true} ELSE NULL END)"

    if isinstance(node, AfterEventNode):
        _require_no_nested_temporal(node.event, "after_event.event")
        _require_no_nested_temporal(node.condition, "after_event.condition")
        bars = node.bars
        event = _emit(node.event, ctx)
        event_was_true = (
            f"(LAG({event}, {bars}) OVER (PARTITION BY {_INSTR} ORDER BY {_TIME}) = TRUE)"
        )
        gate = _full_non_null_gate(bars, node.condition, ctx)
        all_true = (f"(SUM(CASE WHEN {_emit(node.condition, ctx)} THEN 1 ELSE 0 END) "
                    f"OVER ({_inline_window(bars)}) = {bars})")
        cond_part = f"(CASE WHEN {gate} THEN {all_true} ELSE NULL END)"
        return f"({event_was_true} AND {cond_part})"

    raise SchemaError(f"unsupported temporal node {type(node).__name__}",
                      yaml_path=getattr(node, "yaml_path", None))


# ---------------------------------------------------------------------------
# Select assembly
# ---------------------------------------------------------------------------

def _direction_sql(node: ExprNode | None, ctx: _Ctx) -> str:
    """Emit one direction; an absent direction is the literal ``FALSE`` (C2)."""
    return "FALSE" if node is None else _emit(node, ctx)


def _build_select(spec: StrategySpec) -> tuple[str, list[Any]]:
    ctx = _Ctx()
    entry_long = _direction_sql(spec.entry_long, ctx)
    entry_short = _direction_sql(spec.entry_short, ctx)
    exit_long = _direction_sql(spec.exit_long, ctx)
    exit_short = _direction_sql(spec.exit_short, ctx)

    sql = (
        f"SELECT {_INSTR} AS instrument, "
        f"{_TIME} AS time, "
        f"{entry_long} AS entry_long, "
        f"{entry_short} AS entry_short, "
        f"{exit_long} AS exit_long, "
        f"{exit_short} AS exit_short "
        f"FROM {_q(spec.view)}"
    )
    # NOTE: temporal windows are inlined per-function (DuckDB 2.0 rejects a
    # named window with a frame clause referenced by >1 window function), so
    # no trailing WINDOW clause is needed.
    sql += " ORDER BY instrument, time"
    return sql, ctx.params


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_OHLC_COLS = frozenset({"mid_o", "mid_h", "mid_l", "mid_c"})


def _plan_hash(sql: str, params: tuple[Any, ...], features: tuple[str, ...],
               schema_version: int, compiler_version: str,
               feature_catalog_snapshot: str | None = None) -> str:
    """Deterministic identity of the *signal* a plan selects.

    M4 (batch-2 adversarial review) — hash scope is documented, not implicit:
    * IN  : sql, params, features, schema_version, compiler_version, and the
      feature_catalog_snapshot (the working contract requires snapshot
      identity to cover inputs / timeframe / feature settings & versions —
      the same signal over a different feature build must have a
      different hash).
    * OUT : execution metadata (stop/take-profit/costs/max_holding_bars)
      and audit metadata (direction/parents).  These are *report-layer*
      fields: they never change which bars are selected (the SQL) — the
      stop is mandatory 2% by contract, costs are trade-level inputs — so
      including them would conflate "same signal, different costing" with
      "different signal".  They travel as explicit CompiledPlan fields.
    """
    canonical = "|".join(
        [sql, str(schema_version), compiler_version, ",".join(features),
         feature_catalog_snapshot or ""]
        + [str(p) for p in params]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sql_for_plan(plan: CompiledPlan) -> str:
    """The executable signal SQL for a compiled plan (parameters separate)."""
    return plan.sql


def compile_strategy(
    spec: StrategySpec,
    registry: Registry,
    *,
    feature_catalog_snapshot: str | None = None,
    compiler_version: str = "0004-v0.2",
) -> CompiledPlan:
    """Compile a validated :class:`StrategySpec` into a :class:`CompiledPlan`.

    Deterministic: the same ``spec`` + ``registry`` always yields the same
    ``sql`` and ``params``.  Git commit / track / AI identity are *provenance*
    and are intentionally **not** inputs to the SQL (0004 §5 / user ruling).
    """
    for name in spec.features_used:
        if name not in _OHLC_COLS and name not in registry:
            raise SchemaError(f"feature {name!r} is not registered in the catalog")

    sql, params = _build_select(spec)
    features = tuple(sorted(spec.features_used))

    return CompiledPlan(
        strategy_id=spec.id,
        view=spec.view,
        timeframe_minutes=spec.timeframe_minutes,
        sql=sql,
        params=tuple(params),
        features_used=features,
        stop_loss_pct=spec.execution.stop_loss_pct,
        take_profit_pct=spec.execution.take_profit_pct,
        max_holding_bars=spec.execution.max_holding_bars,
        spread_bps=spec.execution.spread_bps,
        slippage_bps_per_side=spec.execution.slippage_bps_per_side,
        commission_bps_round_trip=spec.execution.commission_bps_round_trip,
        financing_bps_per_day=spec.execution.financing_bps_per_day,
        direction=spec.direction,
        parents=spec.parents,
        plan_hash=_plan_hash(sql, tuple(params), features, spec.version,
                             compiler_version, feature_catalog_snapshot),
        schema_version=spec.version,
        feature_catalog_snapshot=feature_catalog_snapshot,
        compiler_version=compiler_version,
    )
