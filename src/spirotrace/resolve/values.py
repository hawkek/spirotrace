"""Applying events to observations, the resolved status, and the post-review rerun.

This is the only place observations and events meet. Each observation gets a
resolved form (the typed text through the same builder the readers use, read
method ``manual``), a status (seam 3 plus ``open_flag`` and
``reviewer_disagreement``), the highest severity still open on it after the
rules rerun over the resolved values, and the ``confirm`` rules that backed it.
The raw-run flags are never changed; the rerun's flags go to ``flags_resolved``
with their change against the raw run.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import ClassVar

from spirotrace.checks import CheckRun, Flag, Severity, check_records
from spirotrace.config import Settings
from spirotrace.layouts import build_observation
from spirotrace.model import Observation, ObservationKey, ReadMethod, ValueState
from spirotrace.rspiro import GliResults, RspiroBridge
from spirotrace.store import Event, RawStore, ReadRecord, Row

from .events import MergedEvents

STATUSES: tuple[str, ...] = (
    "accepted_unflagged",
    "confirmed",
    "corrected",
    "unreadable",
    "excluded",
    "open_flag",
    "reviewer_disagreement",
)
"""Seam 3's five statuses plus the two added at G2."""

UNUSABLE_STATUSES: frozenset[str] = frozenset(
    {"unreadable", "excluded", "reviewer_disagreement"}
)
"""Statuses derive and the wide table never use (an open error is the other reason)."""

_SEVERITY_RANK = {Severity.ERROR: 3, Severity.CHECK: 2, Severity.NOTE: 1}


def highest(severities: Iterable[Severity]) -> str:
    """The highest of error, check, note; ``""`` when none (confirm does not count)."""
    best: Severity | None = None
    for s in severities:
        if s in _SEVERITY_RANK and (
            best is None or _SEVERITY_RANK[s] > _SEVERITY_RANK[best]
        ):
            best = s
    return "" if best is None else best.value


def _manual(
    obs: Observation, raw: str, state: ValueState, struck: bool = False
) -> Observation:
    """``obs`` with a value state set by the reviewer and no parsed value."""
    return replace(
        obs,
        raw_text=raw,
        parsed_value=None,
        parsed_text=None,
        printed_form=None,
        struck=struck,
        read_method=ReadMethod.MANUAL,
        ocr_confidence=None,
        second_reading_run=False,
        second_reading=None,
        value_state=state,
    )


def _typed(obs: Observation, text: str) -> Observation:
    built = build_observation(
        obs.key,
        obs.record_id,
        obs.template_version,
        text.strip(),
        obs.bbox,
        ReadMethod.MANUAL,
        unit=obs.unit if obs.printed_form is None else None,
    ).observation
    return built


def _same_value(a: Observation, b: Observation) -> bool:
    return (
        a.value_state is ValueState.VALUE
        and b.value_state is ValueState.VALUE
        and a.parsed_value == b.parsed_value
        and a.parsed_text == b.parsed_text
    )


def apply_event(obs: Observation, event: Event) -> tuple[Observation, str]:
    """The observation after ``event`` and the status the event gives it."""
    action = event.action
    if action == "as_read":
        return obs, "confirmed"
    if action == "typed":
        new = _typed(obs, event.value)
        return new, ("confirmed" if _same_value(obs, new) else "corrected")
    if action == "struck":
        new = _typed(obs, event.value) if event.value.strip() else obs
        if new.value_state is ValueState.VALUE:
            new = replace(new, struck=True, read_method=ReadMethod.MANUAL)
        return new, "corrected"
    if action == "not_readable":
        return _manual(obs, obs.raw_text, ValueState.UNREADABLE), "unreadable"
    if action == "empty":
        return _manual(obs, "", ValueState.EMPTY), "corrected"
    if action == "dash":
        return _manual(obs, "-", ValueState.DASH), "corrected"
    if action == "exclude":
        return obs, "excluded"
    raise ValueError(f"event action {action!r} cannot be applied")


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    """One observation after review."""

    observation: Observation
    resolved: Observation
    status: str
    open_severity: str = ""
    machine_confirmed_by: tuple[str, ...] = ()
    last_event_id: str = ""
    reviewers: tuple[str, ...] = ()

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "record_id",
        *ObservationKey.COLUMNS,
        "raw_text",
        "parsed_value",
        "parsed_text",
        "value_state",
        "resolved_value",
        "resolved_text",
        "resolved_value_state",
        "resolved_struck",
        "status",
        "open_severity",
        "machine_confirmed_by",
        "last_event_id",
        "reviewers",
    )

    @property
    def key(self) -> ObservationKey:
        return self.observation.key

    @property
    def usable(self) -> bool:
        """Derive's and the wide table's rule: a value, not unusable, no open error."""
        return (
            self.resolved.value_state is ValueState.VALUE
            and self.status not in UNUSABLE_STATUSES
            and self.open_severity != "error"
        )

    def to_row(self) -> Row:
        o, r = self.observation, self.resolved
        base = o.to_row()
        return {
            "record_id": o.record_id,
            **{c: base[c] for c in ObservationKey.COLUMNS},
            "raw_text": o.raw_text,
            "parsed_value": base["parsed_value"],
            "parsed_text": base["parsed_text"],
            "value_state": o.value_state.value,
            "resolved_value": "" if r.parsed_value is None else repr(r.parsed_value),
            "resolved_text": r.parsed_text or "",
            "resolved_value_state": r.value_state.value,
            "resolved_struck": "true" if r.struck else "false",
            "status": self.status,
            "open_severity": self.open_severity,
            "machine_confirmed_by": " ".join(self.machine_confirmed_by),
            "last_event_id": self.last_event_id,
            "reviewers": " ".join(self.reviewers),
        }


@dataclass(frozen=True, slots=True)
class ResolvedFlag:
    """A flag of the post-review rerun, or a raw flag that cleared."""

    flag: Flag
    resolved_status: str
    change: str
    """``new``, ``cleared`` or ``unchanged`` against the raw run, by ``flag_key``."""

    COLUMNS: ClassVar[tuple[str, ...]] = (*Flag.COLUMNS, "resolved_status", "change")

    def to_row(self) -> Row:
        return {
            **self.flag.to_row(),
            "resolved_status": self.resolved_status,
            "change": self.change,
        }


@dataclass(slots=True)
class Resolved:
    values: dict[ObservationKey, ResolvedValue] = field(default_factory=dict)
    records: list[ReadRecord] = field(default_factory=list)
    """The resolved records, as the rules and derive see them."""
    flags_resolved: list[ResolvedFlag] = field(default_factory=list)
    check: CheckRun = field(default_factory=CheckRun)
    disagreements: dict[str, dict[str, Event]] = field(default_factory=dict)
    orphans: list[Event] = field(default_factory=list)
    events_count: int = 0
    reviewers: frozenset[str] = frozenset()

    def of_record(self, record_id: str) -> dict[ObservationKey, ResolvedValue]:
        return {
            k: v for k, v in self.values.items() if v.observation.record_id == record_id
        }

    def open_flags(self, record_id: str) -> list[Flag]:
        return [
            r.flag
            for r in self.flags_resolved
            if r.flag.record_id == record_id
            and r.change != "cleared"
            and r.flag.severity in (Severity.ERROR, Severity.CHECK)
        ]


def resolve_records(
    store: RawStore,
    merged: MergedEvents,
    settings: Settings,
    *,
    bridge: RspiroBridge | None = None,
    gli_results: GliResults | None = None,
    record_ids: Iterable[str] | None = None,
) -> Resolved:
    """Apply the merged events to the store's observations and rerun the rules.

    ``record_ids`` limits the work to those records (the review queue's
    per-record rerun; cohort rules then see only them). Without it every
    record is resolved and the cohort pass runs over the resolved values.
    """
    wanted = None if record_ids is None else set(record_ids)
    out = Resolved(
        disagreements=dict(merged.disagreements),
        events_count=merged.count,
        reviewers=merged.reviewers,
    )
    provisional: dict[ObservationKey, str] = {}
    known_keys = {k.to_string() for k in store.observations()}
    out.orphans = [
        e
        for by_reviewer in merged.latest.values()
        for e in by_reviewer.values()
        if e.key not in known_keys
    ]
    for rec in store.records:
        if wanted is not None and rec.record_id not in wanted:
            continue
        resolved_obs: dict[ObservationKey, Observation] = {}
        superseded: set[ObservationKey] = set()
        for key, obs in rec.observations.items():
            ks = key.to_string()
            event = merged.settled(ks)
            if ks in merged.disagreements:
                new, status, last = obs, "reviewer_disagreement", ""
            elif event is None:
                new, status, last = obs, "", ""
            else:
                new, status = apply_event(obs, event)
                last = event.event_id
                if new is not obs:
                    # the reviewer's reading replaces the reader's: its conditions
                    # (not a number, row placed by template ...) no longer apply
                    superseded.add(key)
            resolved_obs[key] = new
            provisional[key] = status
            out.values[key] = ResolvedValue(
                obs, new, status, last_event_id=last, reviewers=merged.reviewers_of(ks)
            )
        conditions = [c for c in rec.conditions if c.key not in superseded]
        out.records.append(ReadRecord(rec.record, resolved_obs, conditions))
    out.check = check_records(
        out.records, settings, bridge=bridge, gli_results=gli_results
    )
    open_by_key: dict[ObservationKey, list[Severity]] = defaultdict(list)
    confirmed_by: dict[ObservationKey, list[str]] = defaultdict(list)
    for f in out.check.flags:
        for k in f.keys:
            if f.severity is Severity.CONFIRM:
                confirmed_by[k].append(f.rule_id)
            else:
                open_by_key[k].append(f.severity)
    for key, rv in list(out.values.items()):
        open_sev = highest(open_by_key.get(key, ()))
        status = rv.status
        if status == "":
            status = (
                "open_flag" if open_sev in ("error", "check") else "accepted_unflagged"
            )
        out.values[key] = replace(
            rv,
            status=status,
            open_severity=open_sev,
            machine_confirmed_by=tuple(sorted(set(confirmed_by.get(key, ())))),
        )
    out.flags_resolved = _flags_resolved(
        store.flags, out.check.flags, out.values, wanted
    )
    return out


def _flags_resolved(
    raw_flags: Iterable[Flag],
    rerun_flags: Iterable[Flag],
    values: Mapping[ObservationKey, ResolvedValue],
    wanted: set[str] | None,
) -> list[ResolvedFlag]:
    raw = {f.flag_key: f for f in raw_flags if wanted is None or f.record_id in wanted}
    seen: set[str] = set()
    out: list[ResolvedFlag] = []

    def status_of(f: Flag) -> str:
        if not f.keys:
            return ""
        v = values.get(f.keys[0])
        return "" if v is None else v.status

    for f in rerun_flags:
        seen.add(f.flag_key)
        out.append(
            ResolvedFlag(f, status_of(f), "unchanged" if f.flag_key in raw else "new")
        )
    for fk, f in raw.items():
        if fk not in seen:
            out.append(ResolvedFlag(f, status_of(f), "cleared"))
    return out
