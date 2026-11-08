"""Strategy YAML schema model (decision 0004 §3.1 — normalized YAML model).

This module owns the *parse + validate* half of the 0004 compiler:
  * safe YAML load with duplicate-key / alias / NaN rejection
  * schema validation against the feature Registry and Catalog view
  * normalization of legacy aliases (``family``→``direction``,
    ``exit.feature.when``→both-direction exit, ``time_bars``→``max_holding_bars``)
  * the frozen execution metadata (``stop_loss_pct`` mandatory 2%,
    ``take_profit_pct``, ``max_holding_bars``, ``execution.*`` cost fields)

It does **not** generate SQL (that is :mod:`lyra.compiler`) and does
**not** execute any trade logic (0005).  Track / AI / version-tree
metadata is carried as structured audit fields only; it never enters the
SQL AST (0004 invariant: track is a research identity, not an execution
identity).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .registry import FeatureKind, Registry

__all__ = [
    "SchemaError",
    "StrategySpec",
    "ExecutionMeta",
    "ComparisonLeaf",
    "ExprNode",
    "HeldForNode",
    "WithinNode",
    "AfterEventNode",
    "AllNode",
    "AnyNode",
    "NotNode",
    "load_strategy_yaml",
    "parse_strategy",
    "MANDATORY_STOP_PCT",
    "ALLOWED_TIMEFRAMES",
    "OHLC_ALIASES",
]

# ---------------------------------------------------------------------------
# Constants (0004 §3.1)
# ---------------------------------------------------------------------------

#: The mandatory adverse-price stop.  A strategy may only *state* it (0.02),
#: never widen or disable it (0004 adversarial self-check, last row).
MANDATORY_STOP_PCT = 0.02

#: Only the Catalog views that exist (0003 §3.1 / catalog.py:37-38).
ALLOWED_TIMEFRAMES: dict[int, str] = {
    5: "features_5m",
    60: "features_1h",
}

#: Legacy / README raw-column aliases (0004 §3.1 comparison-leaf rule).
OHLC_ALIASES: dict[str, str] = {
    "open": "mid_o",
    "high": "mid_h",
    "low": "mid_l",
    "close": "mid_c",
}

#: YAML schema version (NOT the direction version tree v01/v02).
SCHEMA_VERSION = 1

#: Comparison operators allowed on numeric (VALUE / STATE / EVENT) columns.
_NUMERIC_OPS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte"})
#: Comparison operators allowed on boolean-ish columns (STATE / EVENT).
_BOOL_OPS = frozenset({"eq", "ne"})

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SchemaError(ValueError):
    """A strategy YAML failed schema / registry / timeframe validation.

    ``yaml_path`` is the dotted field path inside the YAML (e.g.
    ``entry.long.all[0].feature``) and ``file`` is the source path, so
    the error message always locates the offending field (0004 §3.1
    strict-schema rule: "错误至少报告文件路径和 YAML 字段").
    """

    def __init__(self, message: str, *, file: str | None = None,
                 yaml_path: str | None = None) -> None:
        loc = ""
        if file:
            loc += f" [{file}"
        if yaml_path:
            loc += f" @ {yaml_path}"
        loc += "]"
        super().__init__(f"{message}{loc}")
        self.file = file
        self.yaml_path = yaml_path


# ---------------------------------------------------------------------------
# AST nodes (0004 §3.1 "规范化 YAML 模型")
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComparisonLeaf:
    """``{feature: <col>, op: <enum>, value: <const|col>}``.

    Exactly one of ``right_const`` / ``right_col`` is meaningful, selected by
    ``right_is_const``.  ``right_const`` holds the *actual* Python value for a
    bound constant; the codegen emits ``?`` and the plan collects these values
    in tree order.  ``right_col`` holds the resolved column name for a
    feature-vs-feature comparison.
    """
    left_col: str                # resolved registry / OHLC column name
    op: str                      # one of eq/ne/gt/gte/lt/lte
    right_is_const: bool         # True → right_const holds the bound value
    right_const: Any = None      # the bound constant value (when right_is_const)
    right_col: str | None = None # resolved right column (when not a constant)
    left_kind: FeatureKind | None = None  # kind of the left column (op gating)


@dataclass(frozen=True)
class ExprNode:
    """Base marker for the expression AST (discriminated by subclass)."""


@dataclass(frozen=True)
class _LeafNode(ExprNode):
    cmp: ComparisonLeaf
    yaml_path: str = ""


@dataclass(frozen=True)
class AllNode(ExprNode):
    children: tuple[ExprNode, ...]
    yaml_path: str = ""


@dataclass(frozen=True)
class AnyNode(ExprNode):
    children: tuple[ExprNode, ...]
    yaml_path: str = ""


@dataclass(frozen=True)
class NotNode(ExprNode):
    child: ExprNode
    yaml_path: str = ""


@dataclass(frozen=True)
class HeldForNode(ExprNode):
    bars: int
    condition: ExprNode
    yaml_path: str = ""


@dataclass(frozen=True)
class WithinNode(ExprNode):
    bars: int
    condition: ExprNode
    yaml_path: str = ""


@dataclass(frozen=True)
class AfterEventNode(ExprNode):
    bars: int
    event: ExprNode
    condition: ExprNode
    yaml_path: str = ""


# ---------------------------------------------------------------------------
# Execution metadata (0004 §3.1; cost *calculation* stays in 0005)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionMeta:
    stop_loss_pct: float = MANDATORY_STOP_PCT
    take_profit_pct: float | None = None
    max_holding_bars: int | None = None
    spread_bps: float | None = None
    slippage_bps_per_side: float | None = None
    commission_bps_round_trip: float | None = None
    financing_bps_per_day: float | None = None


@dataclass
class StrategySpec:
    """The validated, normalized strategy model (0004 §3.1 input to codegen)."""
    version: int
    id: str
    direction: str | None
    hypothesis: str | None
    timeframe_minutes: int
    view: str                      # resolved Catalog view (features_5m / 1h)
    entry_long: ExprNode | None
    entry_short: ExprNode | None
    exit_long: ExprNode | None
    exit_short: ExprNode | None
    execution: ExecutionMeta
    # Audit metadata (retained, never enters the SQL — 0004 §3.1):
    parents: tuple[str, ...] = ()
    driven_by_lesson: str | None = None
    inherited: tuple[str, ...] = ()
    # The set of registry feature columns actually referenced (for the plan):
    features_used: frozenset[str] = field(default_factory=frozenset)

    def bound_params(self) -> list[Any]:
        """Bound constants in the same order the codegen emits ``?`` (stable)."""
        out: list[Any] = []
        for node in (self.entry_long, self.entry_short, self.exit_long, self.exit_short):
            if node is not None:
                _collect_params(node, out)
        return out


def _collect_params(node: ExprNode, out: list[Any]) -> None:
    if isinstance(node, _LeafNode):
        if node.cmp.right_is_const:
            out.append(node.cmp.right)
    elif isinstance(node, (AllNode, AnyNode)):
        for c in node.children:
            _collect_params(c, out)
    elif isinstance(node, NotNode):
        _collect_params(node.child, out)
    elif isinstance(node, (HeldForNode, WithinNode)):
        _collect_params(node.condition, out)
    elif isinstance(node, AfterEventNode):
        _collect_params(node.event, out)
        _collect_params(node.condition, out)


# ---------------------------------------------------------------------------
# Safe YAML load (0004 §3.1 strict schema: reject duplicate keys, aliases,
# NaN/Infinity, recursive structures)
# ---------------------------------------------------------------------------

class _SafeLoader(yaml.SafeLoader):
    """A safe loader that additionally rejects duplicate mapping keys."""


def _construct_mapping_no_dup(loader: _SafeLoader, node: yaml.MappingNode,
                              deep: bool = False) -> dict:
    mapping: dict = {}
    seen: set = set()
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        value = loader.construct_object(value_node, deep=deep)
        try:
            key_hash = hash(key)
        except TypeError:
            key_hash = id(key)
        if key_hash in seen:
            raise SchemaError(
                f"duplicate YAML key {key!r} (strict schema: last-key-wins is "
                f"forbidden so audit and semantics cannot diverge)")
        seen.add(key_hash)
        mapping[key] = value
    return mapping


_SafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_dup)


def _reject_nan_inf(node: Any, path: str) -> None:
    if isinstance(node, float) and (math.isnan(node) or math.isinf(node)):
        raise SchemaError(f"NaN/Infinity is not allowed at {path}")
    if isinstance(node, dict):
        for k, v in node.items():
            _reject_nan_inf(v, f"{path}.{k}")
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            _reject_nan_inf(v, f"{path}[{i}]")


# load_strategy_yaml / _load_yaml_text / parse_yaml / parse_strategy /
# _validate_doc are defined below (after _normalize_exit).

# ---------------------------------------------------------------------------
# Registry-aware helpers
# ---------------------------------------------------------------------------

def _resolve_column(name: str, registry: Registry, *, file: str | None,
                    yaml_path: str) -> tuple[str, FeatureKind | None]:
    """Resolve a YAML column/feature name to a concrete column + kind.

    Accepts: a registered registry feature, or a whitelisted OHLC alias
    (open/high/low/close → mid_o/mid_h/mid_l/mid_c).  Anything else is an
    unknown-column error (0004 §3.1: "未知字符串即未知列错误").
    """
    if name in OHLC_ALIASES:
        return OHLC_ALIASES[name], None
    if name in registry:
        return name, registry.get(name).kind
    raise SchemaError(
        f"unknown feature or column {name!r} (must be a registered feature "
        f"or one of open/high/low/close)",
        file=file, yaml_path=f"{yaml_path}.feature" if yaml_path else None)


def _collect_features(node: ExprNode, acc: set[str]) -> None:
    """Collect the concrete registry/OHLC columns referenced by an AST node."""
    if isinstance(node, _LeafNode):
        acc.add(node.cmp.left_col)
        if node.cmp.right_is_const is False and node.cmp.right_col:
            acc.add(node.cmp.right_col)
    elif isinstance(node, (AllNode, AnyNode)):
        for c in node.children:
            _collect_features(c, acc)
    elif isinstance(node, NotNode):
        _collect_features(node.child, acc)
    elif isinstance(node, (HeldForNode, WithinNode)):
        _collect_features(node.condition, acc)
    elif isinstance(node, AfterEventNode):
        _collect_features(node.event, acc)
        _collect_features(node.condition, acc)


# ---------------------------------------------------------------------------
# Expression-tree parser
# ---------------------------------------------------------------------------

def _parse_value_rhs(value: Any, registry: Registry, *, file: str | None,
                     yaml_path: str) -> tuple[bool, Any, str | None]:
    """Resolve the RHS ``value`` to either a bound constant or a column.

    Returns ``(is_const, const_value, col_name)`` — exactly one of
    ``const_value`` / ``col_name`` is set, selected by ``is_const``.
    """
    if isinstance(value, bool):
        return True, value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value) or math.isinf(value):
            raise SchemaError("NaN/Infinity not allowed as a comparison value",
                              file=file, yaml_path=f"{yaml_path}.value")
        return True, value, None
    if isinstance(value, str):
        col, _kind = _resolve_column(value, registry, file=file, yaml_path=yaml_path)
        return False, None, col
    raise SchemaError(
        f"comparison value must be a number, boolean, or known column name, "
        f"got {type(value).__name__}",
        file=file, yaml_path=f"{yaml_path}.value")


def _parse_expr(node: Any, registry: Registry, *, file: str | None,
                yaml_path: str) -> ExprNode:
    """Recursively parse a YAML expression node into the AST."""
    if isinstance(node, dict):
        keys = set(node.keys())
        # comparison leaf: {feature, op, value}
        if keys == {"feature", "op", "value"}:
            left_col, left_kind = _resolve_column(node["feature"], registry,
                                                  file=file, yaml_path=yaml_path)
            op = node["op"]
            if not isinstance(op, str) or op not in _NUMERIC_OPS:
                raise SchemaError(f"unknown comparison op {op!r}",
                                  file=file, yaml_path=f"{yaml_path}.op")
            if left_kind in (FeatureKind.STATE, FeatureKind.EVENT) and op not in _BOOL_OPS:
                raise SchemaError(
                    f"boolean/event column {left_col!r} only supports eq/ne, got {op!r}",
                    file=file, yaml_path=f"{yaml_path}.op")
            is_const, const_value, right_col = _parse_value_rhs(
                node["value"], registry, file=file, yaml_path=yaml_path)
            return _LeafNode(cmp=ComparisonLeaf(
                left_col=left_col, op=op, right_is_const=is_const,
                right_const=const_value, right_col=right_col, left_kind=left_kind),
                yaml_path=yaml_path)

        # all / any: non-empty list of sub-expressions
        if keys == {"all"} or keys == {"any"}:
            tag = keys.pop()
            items = node[tag]
            if not isinstance(items, (list, tuple)) or len(items) == 0:
                raise SchemaError(f"{tag} must be a non-empty list",
                                  file=file, yaml_path=f"{yaml_path}.{tag}")
            children = tuple(_parse_expr(c, registry, file=file,
                                         yaml_path=f"{yaml_path}.{tag}[{i}]") for i, c in enumerate(items))
            if tag == "all":
                return AllNode(children=children, yaml_path=yaml_path)
            return AnyNode(children=children, yaml_path=yaml_path)

        # not: single sub-expression
        if keys == {"not"}:
            child = _parse_expr(node["not"], registry, file=file,
                                yaml_path=f"{yaml_path}.not")
            return NotNode(child=child, yaml_path=yaml_path)

        # held_for: {bars: N, condition: expr}
        if keys == {"held_for"}:
            hf = node["held_for"]
            return _parse_temporal("held_for", hf, "condition", registry,
                                   file=file, yaml_path=f"{yaml_path}.held_for")

        # within: {bars: N, condition: expr}
        if keys == {"within"}:
            wf = node["within"]
            return _parse_temporal("within", wf, "condition", registry,
                                   file=file, yaml_path=f"{yaml_path}.within")

        # after_event: {bars: N, event: expr, condition: expr}
        if keys == {"after_event"}:
            ae = node["after_event"]
            need = {"bars", "event", "condition"}
            if not need.issubset(ae.keys()):
                raise SchemaError(
                    f"after_event requires bars, event, condition "
                    f"(got {sorted(ae.keys())})",
                    file=file, yaml_path=f"{yaml_path}.after_event")
            bars = _check_bars(ae.get("bars"), file, f"{yaml_path}.after_event")
            event = _parse_expr(ae["event"], registry, file=file,
                                yaml_path=f"{yaml_path}.after_event.event")
            condition = _parse_expr(ae["condition"], registry, file=file,
                                    yaml_path=f"{yaml_path}.after_event.condition")
            return AfterEventNode(bars=bars, event=event, condition=condition,
                                  yaml_path=yaml_path)

        raise SchemaError(
            f"unrecognized expression shape with keys {sorted(keys)} "
            f"(expected feature/op/value, all, any, not, held_for, within, or after_event)",
            file=file, yaml_path=yaml_path)

    raise SchemaError(
        f"expression node must be a mapping, got {type(node).__name__}",
        file=file, yaml_path=yaml_path)


def _parse_temporal(kind: str, block: Any, cond_key: str, registry: Registry,
                    *, file: str | None, yaml_path: str) -> ExprNode:
    if not isinstance(block, dict):
        raise SchemaError(f"{kind} must be a mapping", file=file, yaml_path=yaml_path)
    if "bars" not in block or cond_key not in block:
        raise SchemaError(f"{kind} requires bars and {cond_key}",
                          file=file, yaml_path=yaml_path)
    bars = _check_bars(block["bars"], file, yaml_path)
    condition = _parse_expr(block[cond_key], registry, file=file,
                            yaml_path=f"{yaml_path}.{cond_key}")
    if kind == "held_for":
        return HeldForNode(bars=bars, condition=condition, yaml_path=yaml_path)
    return WithinNode(bars=bars, condition=condition, yaml_path=yaml_path)


def _check_bars(bars: Any, file: str | None, yaml_path: str) -> int:
    if isinstance(bars, bool) or not isinstance(bars, int) or bars < 1:
        raise SchemaError(f"bars must be a positive integer, got {bars!r}",
                          file=file, yaml_path=f"{yaml_path}.bars")
    return bars


# ---------------------------------------------------------------------------
# Top-level parse (strategy → StrategySpec)
# ---------------------------------------------------------------------------

def _parse_execution(raw: Mapping | None, *, file: str | None,
                     yaml_path: str) -> ExecutionMeta:
    """Normalize exit/execution metadata; enforce the mandatory 2% stop."""
    raw = dict(raw or {})

    # stop_loss_pct: optional; if present it MUST be exactly 0.02 (0004 rule).
    stop = raw.get("stop_loss_pct", MANDATORY_STOP_PCT)
    if isinstance(stop, bool) or not isinstance(stop, (int, float)):
        raise SchemaError("stop_loss_pct must be a number", file=file,
                          yaml_path=f"{yaml_path}.stop_loss_pct")
    if abs(float(stop) - MANDATORY_STOP_PCT) > 1e-9:
        raise SchemaError(
            f"stop_loss_pct is mandatory at {MANDATORY_STOP_PCT}; a strategy "
            f"cannot widen or disable it (got {stop!r})",
            file=file, yaml_path=f"{yaml_path}.stop_loss_pct")

    tp = raw.get("take_profit_pct")
    if tp is not None:
        if isinstance(tp, bool) or not isinstance(tp, (int, float)) or float(tp) <= 0:
            raise SchemaError("take_profit_pct must be a positive number",
                              file=file, yaml_path=f"{yaml_path}.take_profit_pct")

    mhb = raw.get("max_holding_bars")
    if mhb is not None and (isinstance(mhb, bool) or not isinstance(mhb, int) or mhb < 1):
        raise SchemaError("max_holding_bars must be a positive integer",
                          file=file, yaml_path=f"{yaml_path}.max_holding_bars")

    def _opt_bps(name: str) -> float | None:
        v = raw.get(name)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) < 0:
            raise SchemaError(f"{name} must be a non-negative number", file=file,
                              yaml_path=f"{yaml_path}.{name}")
        return float(v)

    return ExecutionMeta(
        stop_loss_pct=MANDATORY_STOP_PCT,
        take_profit_pct=float(tp) if tp is not None else None,
        max_holding_bars=mhb,
        spread_bps=_opt_bps("spread_bps"),
        slippage_bps_per_side=_opt_bps("slippage_bps_per_side"),
        commission_bps_round_trip=_opt_bps("commission_bps_round_trip"),
        financing_bps_per_day=_opt_bps("financing_bps_per_day"),
    )


def _normalize_exit(exit_raw: Mapping | None, registry: Registry, *,
                    file: str | None, yaml_path: str) -> tuple[ExprNode | None, ExprNode | None]:
    """Return (exit_long, exit_short) from the ``exit`` block.

    Normalizes the README legacy shape ``exit.feature.when`` into the same
    exit expression for both directions (0004 §3.1).
    """
    if exit_raw is None:
        return None, None
    exit_raw = dict(exit_raw)

    # Legacy README form: exit.feature.when → shared for both directions.
    legacy_when = None
    feature_block = exit_raw.get("feature")
    if isinstance(feature_block, dict) and "when" in feature_block:
        legacy_when = feature_block["when"]
        exit_raw = {k: v for k, v in exit_raw.items() if k != "feature"}

    long_expr = exit_raw.get("long")
    short_expr = exit_raw.get("short")

    exit_long = _parse_expr(long_expr, registry, file=file,
                            yaml_path=f"{yaml_path}.long") if long_expr else None
    exit_short = _parse_expr(short_expr, registry, file=file,
                             yaml_path=f"{yaml_path}.short") if short_expr else None

    if legacy_when is not None:
        shared = _parse_expr(legacy_when, registry, file=file,
                             yaml_path=f"{yaml_path}.feature.when")
        # Tracked-example canonical fields take priority over the legacy alias.
        if exit_long is None:
            exit_long = shared
        if exit_short is None:
            exit_short = shared

    return exit_long, exit_short


def load_strategy_yaml(path: str | Path) -> Any:
    """Safely load a strategy YAML (duplicate keys / NaN / Inf rejected)."""
    p = Path(path)
    if not p.is_file():
        raise SchemaError(f"strategy file not found: {p}", file=str(p))
    raw = p.read_text(encoding="utf-8")
    return _load_yaml_text(raw, file=str(p))


def _load_yaml_text(raw: str, file: str) -> Any:
    """Load YAML text with the safe loader (duplicate keys / NaN / Inf rejected)."""
    try:
        data = yaml.load(raw, Loader=_SafeLoader)
    except yaml.YAMLError as exc:
        msg = getattr(exc, "problem", None) or str(exc)
        raise SchemaError(f"YAML parse error: {msg}", file=file) from exc
    if not isinstance(data, dict):
        raise SchemaError("top-level YAML must be a mapping", file=file)
    _reject_nan_inf(data, "$")
    return data


def parse_yaml(text: str, registry: Registry) -> StrategySpec:
    """Parse + validate strategy YAML **text** into a :class:`StrategySpec`.

    Same validation as :func:`parse_strategy`; accepts an in-memory YAML string
    (useful for tests and the CLI).  Does **not** run SQL (0004 §3.1).
    """
    data = _load_yaml_text(text, file="<yaml>")
    return _validate_doc(data, registry, file="<yaml>")


def parse_strategy(path: str | Path, registry: Registry) -> StrategySpec:
    """Parse + validate a strategy YAML into a normalized :class:`StrategySpec`.

    This is the *cheap pre-run* validation of 0004 §3.1: field presence,
    feature/registry membership, comparison types, timeframe resolution, and
    temporal-op shape are all checked here.  It does **not** run SQL.
    """
    data = load_strategy_yaml(path)
    return _validate_doc(data, registry, file=str(path))


def _validate_doc(data: dict, registry: Registry, file: str) -> StrategySpec:
    """Validate an already-loaded strategy mapping into a :class:`StrategySpec`."""
    if "version" not in data:
        raise SchemaError("missing required field: version", file=file, yaml_path="version")
    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise SchemaError(f"unsupported YAML schema version {version!r} (expected {SCHEMA_VERSION})",
                          file=file, yaml_path="version")

    sid = data.get("id")
    if not isinstance(sid, str) or not _SLUG_RE.match(sid):
        raise SchemaError(f"id must be a safe slug (lowercase alnum/_/-), got {sid!r}",
                          file=file, yaml_path="id")

    tfm = data.get("timeframe_minutes")
    if tfm not in ALLOWED_TIMEFRAMES:
        raise SchemaError(
            f"timeframe_minutes must be one of {sorted(ALLOWED_TIMEFRAMES)} "
            f"(matching an existing Catalog view), got {tfm!r}",
            file=file, yaml_path="timeframe_minutes")
    view = ALLOWED_TIMEFRAMES[tfm]

    # direction (canonical) with `family` as a compatibility alias (0004 §3.1).
    direction = data.get("direction")
    family = data.get("family")
    if direction is not None and family is not None and direction != family:
        raise SchemaError(
            f"direction={direction!r} and family={family!r} both present and "
            f"differ; drop one (direction is canonical, family is a legacy alias)",
            file=file, yaml_path="direction")
    direction = direction if direction is not None else family

    hypothesis = data.get("hypothesis")
    if hypothesis is not None and not isinstance(hypothesis, str):
        raise SchemaError("hypothesis must be a string", file=file, yaml_path="hypothesis")

    # --- entry / exit expression trees ------------------------------------
    entry_raw = data.get("entry")
    entry_long = entry_short = None
    if isinstance(entry_raw, dict):
        for side, key in (("long", "long"), ("short", "short")):
            expr = entry_raw.get(key)
            if expr is None:
                continue
            node = _parse_expr(expr, registry, file=file,
                               yaml_path=f"entry.{key}")
            if side == "long":
                entry_long = node
            else:
                entry_short = node
    if entry_long is None and entry_short is None:
        raise SchemaError("entry must define at least one of long/short",
                          file=file, yaml_path="entry")

    exit_long, exit_short = _normalize_exit(data.get("exit"), registry,
                                            file=file, yaml_path="exit")

    # exit-level stop_loss_pct (README / tracked-example shape): if explicitly
    # written it MUST be exactly the mandatory 2% — a strategy may not widen or
    # disable the stop (0004 §3.1 / I3).  Reject any other value (fail closed).
    if isinstance(data.get("exit"), dict):
        e_stop = data["exit"].get("stop_loss_pct")
        if e_stop is not None:
            if isinstance(e_stop, bool) or not isinstance(e_stop, (int, float)):
                raise SchemaError("exit.stop_loss_pct must be a number",
                                  file=file, yaml_path="exit.stop_loss_pct")
            if abs(float(e_stop) - MANDATORY_STOP_PCT) > 1e-9:
                raise SchemaError(
                    f"exit.stop_loss_pct is mandatory at {MANDATORY_STOP_PCT}; a "
                    f"strategy may not widen/disable it, got {e_stop!r}",
                    file=file, yaml_path="exit.stop_loss_pct")

    # --- execution metadata ----------------------------------------------
    execution = _parse_execution(data.get("execution"), file=file, yaml_path="execution")
    # exit-level cost fields (README legacy top-of-exit) fold into execution.
    if isinstance(data.get("exit"), dict):
        for bps_key in ("spread_bps", "slippage_bps_per_side",
                        "commission_bps_round_trip", "financing_bps_per_day"):
            v = data["exit"].get(bps_key)
            if v is not None and getattr(execution, bps_key, None) is None:
                execution = _replace(execution, {bps_key: v})
        mhb = data["exit"].get("max_holding_bars")
        if mhb is not None and execution.max_holding_bars is None:
            execution = _replace(execution, {"max_holding_bars": mhb})
        # legacy alias time_bars → max_holding_bars (0004 §3.1)
        tb = data["exit"].get("time_bars")
        if tb is not None and execution.max_holding_bars is None:
            if isinstance(tb, bool) or not isinstance(tb, int) or tb < 1:
                raise SchemaError("time_bars must be a positive integer",
                                  file=file, yaml_path="exit.time_bars")
            execution = _replace(execution, {"max_holding_bars": tb})

    # --- audit metadata (retained, never enters SQL) -----------------------
    parents = tuple(data.get("parents") or ([data["parent"]] if data.get("parent") else []))
    if data.get("parent") and not isinstance(data["parent"], str):
        raise SchemaError("parent must be a string", file=file, yaml_path="parent")
    inherited = tuple(data.get("inherited") or ())

    # --- collect referenced features --------------------------------------
    acc: set[str] = set()
    for node in (entry_long, entry_short, exit_long, exit_short):
        if node is not None:
            _collect_features(node, acc)
    # keep only registry/OHLC columns (drop @param sentinels, which we already
    # excluded because _collect_features only records concrete columns).
    features_used = frozenset(c for c in acc if not c.startswith("@p"))

    return StrategySpec(
        version=version,
        id=sid,
        direction=direction,
        hypothesis=hypothesis,
        timeframe_minutes=tfm,
        view=view,
        entry_long=entry_long,
        entry_short=entry_short,
        exit_long=exit_long,
        exit_short=exit_short,
        execution=execution,
        parents=parents,
        driven_by_lesson=data.get("driven_by_lesson"),
        inherited=inherited,
        features_used=features_used,
    )


def _replace(execution: ExecutionMeta, updates: dict) -> ExecutionMeta:
    base = execution.__dict__.copy()
    base.update(updates)
    return ExecutionMeta(**base)
