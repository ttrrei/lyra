"""Feature registry (decision 0003 K3).

The registry is a **pure Python dict** — it is *code*, not data, and travels
with the commit (git is the version history). This is deliberately stronger
than moneta's "column-name-as-contract scattered everywhere" and simpler
than nova's "YAML feature declarations".

Each entry carries nova-style metadata (§2.3 adoption 3) so the 0004
compiler can statically reference ``warmup_bars`` for its F2 assertion
("a NULL after warm-up is a bug") and ``kind``/``unit`` for right-value
semantic checks:

    (name, kind ∈ {VALUE, STATE, EVENT}, unit, warmup_bars, family, params)

Rules enforced here:

* F5 — a name may only be registered once; a conflicting ``register`` call
  (core vs alpha, or alpha vs alpha) raises rather than silently overwriting
  or renaming (feature column names are the SQL right-value contract).
* I13 — any change to a registered feature's *computation semantics or
  parameters* must bump ``FEATURE_VERSION`` (that constant lives in
  :mod:`lyra.features`; the registry is version-agnostic data).
* K8 — window parameters only take the CFD grid {6, 12, 24, 60, 120}
  (enforced by ``tests/test_registry.py::test_grid_only_windows``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class FeatureKind(str, Enum):
    """The kind of value a feature emits (nova ``kind`` metadata)."""

    VALUE = "VALUE"   # a numeric observation at each bar
    STATE = "STATE"   # a discrete state (e.g. psar_bullish, supertrend_bullish)
    EVENT = "EVENT"   # a 0/1 boolean event (e.g. sma_cross_up_6_24)


class RegistryError(ValueError):
    """Raised when a feature name would collide (F5)."""


@dataclass(frozen=True)
class FeatureSpec:
    """One registered feature (K3 metadata card).

    ``compute`` is the pure function that produces the column(s); it is a
    call into :mod:`lyra.indicators` (TA-Lib-backed) or a vectorized
    pandas composition in :mod:`lyra.features`. See 0003 §3.1 API contract.
    """

    name: str
    kind: FeatureKind
    unit: str
    warmup_bars: int
    family: str
    params: Mapping[str, Any] = field(default_factory=dict)
    # The true *window* parameters (K8 grid-guard target). Kept separate from
    # ``params`` so non-window constants (BBANDS nbdev, STOCH matype, PSAR
    # af/maximum, Supertrend multiplier) are not mistaken for off-grid windows.
    window_params: tuple[int, ...] = ()
    compute: Callable[..., Any] | None = None


class Registry:
    """A named, ordered collection of :class:`FeatureSpec` (K3)."""

    def __init__(self) -> None:
        self._specs: dict[str, FeatureSpec] = {}

    def register(
        self,
        name: str,
        compute: Callable[..., Any] | None,
        *,
        kind: FeatureKind | str,
        unit: str,
        warmup_bars: int,
        family: str,
        params: Mapping[str, Any] | None = None,
        window_params: tuple[int, ...] | list[int] | None = None,
    ) -> FeatureSpec:
        """Register a feature. Raises :class:`RegistryError` on a name clash (F5)."""
        if name in self._specs:
            raise RegistryError(
                f"duplicate feature name {name!r}: feature column names are the "
                f"SQL right-value contract; refuse to overwrite (F5)"
            )
        if not isinstance(kind, FeatureKind):
            try:
                kind = FeatureKind(str(kind).upper())
            except ValueError:
                raise ValueError(
                    f"invalid FeatureKind {kind!r}; expected one of "
                    f"{[k.value for k in FeatureKind]}"
                ) from None
        if warmup_bars < 0:
            raise ValueError(f"{name}: warmup_bars must be >= 0, got {warmup_bars}")
        spec = FeatureSpec(
            name=name,
            kind=kind,
            unit=unit,
            warmup_bars=warmup_bars,
            family=family,
            params=dict(params or {}),
            window_params=tuple(window_params or ()),
            compute=compute,
        )
        self._specs[name] = spec
        return spec

    def get(self, name: str) -> FeatureSpec:
        if name not in self._specs:
            raise KeyError(f"feature {name!r} is not registered")
        return self._specs[name]

    def names(self) -> list[str]:
        """Registered names in insertion order (deterministic, F1)."""
        return list(self._specs)

    def by_family(self) -> dict[str, list[FeatureSpec]]:
        out: dict[str, list[FeatureSpec]] = {}
        for spec in self._specs.values():
            out.setdefault(spec.family, []).append(spec)
        return out

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: str) -> bool:
        return name in self._specs
