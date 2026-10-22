"""The rule registry: every check is a named rule with an id, a layer, the
severities it may raise and one sentence of rationale.

Severity is declared here, never decided inside reading code. A rule raises
only the severities it declares (the first is its usual one); a few rules
declare two because the old script graded them by what it saw (an error on a
number, a check on text). Rules run in layer order and, within a layer, in registration order; a
per-record rule sees the record and the flags raised before it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .flags import LAYERS, Flag, Severity

RuleFn = Callable[..., Iterable[Flag]]


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    layer: str
    severities: tuple[Severity, ...]
    why: str
    scope: str
    fn: RuleFn

    @property
    def severity(self) -> Severity:
        return self.severities[0]


RULES: dict[str, Rule] = {}


def rule(
    id: str,
    layer: str,
    severity: Severity | tuple[Severity, ...],
    why: str,
    *,
    scope: str = "record",
) -> Callable[[RuleFn], RuleFn]:
    """Register ``fn`` as the rule ``id``.

    ``scope`` is ``record`` (runs once per record), ``cohort`` (runs once over
    all records) or ``gli`` (runs per record with the recalculated ranges).
    """
    sevs = (severity,) if isinstance(severity, Severity) else tuple(severity)
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r} for rule {id}")
    if not id.startswith(layer + "."):
        raise ValueError(f"rule id {id!r} must start with its layer {layer!r}")
    if scope not in ("record", "cohort", "gli"):
        raise ValueError(f"unknown scope {scope!r} for rule {id}")
    if not why.strip():
        raise ValueError(f"rule {id} needs its one-sentence rationale")

    def deco(fn: RuleFn) -> RuleFn:
        if id in RULES:
            raise ValueError(f"rule {id} registered twice")
        RULES[id] = Rule(id, layer, sevs, why.strip(), scope, fn)
        return fn

    return deco


def enabled_rules(
    off: Iterable[str] = (), layers_off: Iterable[str] = ()
) -> list[Rule]:
    """The registered rules in layer order, minus those switched off by id or layer."""
    off_ids, off_layers = set(off), set(layers_off)
    order = {layer: i for i, layer in enumerate(LAYERS)}
    rules = [
        r for r in RULES.values() if r.id not in off_ids and r.layer not in off_layers
    ]
    return sorted(
        rules, key=lambda r: order[r.layer]
    )  # stable: registration order within a layer


def check_flag(flag: Flag) -> Flag:
    """Refuse a flag whose rule or severity was not declared."""
    r = RULES.get(flag.rule_id)
    if r is None:
        raise ValueError(f"flag from unregistered rule {flag.rule_id}")
    if flag.layer != r.layer:
        raise ValueError(f"flag of {flag.rule_id} has layer {flag.layer}")
    if flag.severity not in r.severities:
        raise ValueError(
            f"rule {flag.rule_id} raised {flag.severity}, declared {r.severities}"
        )
    return flag
