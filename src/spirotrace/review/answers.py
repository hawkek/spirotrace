"""Keyboard answers: the text typed in the queue's one input box, validated
server-side and turned into an event action (plan section 3.4).

================  ==============  =====================================================
typed             action          value
================  ==============  =====================================================
``=``             ``as_read``     the value as read is right
``na``            ``not_readable`` the cell cannot be read on the scan
``empty``         ``empty``       the cell is blank
``-``             ``dash``        the cell holds a printed dash
``struck [v]``    ``struck``      struck through; ``v`` replaces the number if given
``x <note>``      ``exclude``     leave the value out of the dataset; the note says why
``withdraw``      ``withdraw``    retract this reviewer's latest answer on the key
anything else     ``typed``       the value as printed; number parameters go through the
                                  token grammar, ratios in their printed form, dates
                                  day first; a text that yields no value is refused
================  ==============  =====================================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from spirotrace.layouts import build_observation, parse_date
from spirotrace.model import (
    ObservationKey,
    ParameterKind,
    ReadMethod,
    ValueState,
    kind_of,
)


class AnswerError(ValueError):
    """An answer the queue refuses; the message is shown to the reviewer."""


@dataclass(frozen=True, slots=True)
class Answer:
    action: str
    value: str = ""
    note: str = ""


_STRUCK = re.compile(r"^struck(?:\s+(\S.*))?$", re.IGNORECASE)
_EXCLUDE = re.compile(r"^x(?:\s+(.*))?$", re.IGNORECASE)
_WORDS = {"=": "as_read", "na": "not_readable", "empty": "empty", "-": "dash"}


def parse_answer(text: str, key: ObservationKey, *, has_own_answer: bool) -> Answer:
    """Validate ``text`` for the cell ``key``; raise :class:`AnswerError` otherwise."""
    t = text.strip()
    if not t:
        raise AnswerError(
            "type an answer (= na empty - struck x withdraw, or the value)"
        )
    lowered = t.lower()
    if lowered in _WORDS:
        return Answer(_WORDS[lowered])
    if lowered == "withdraw":
        if not has_own_answer:
            raise AnswerError("nothing of yours to withdraw on this cell")
        return Answer("withdraw")
    m = _EXCLUDE.match(t)
    if m is not None:
        note = (m.group(1) or "").strip()
        if not note:
            raise AnswerError("exclude needs a note: x <why>")
        return Answer("exclude", note=note)
    m = _STRUCK.match(t)
    if m is not None:
        value = (m.group(1) or "").strip()
        if value:
            _check_value(value, key)
        return Answer("struck", value=value)
    _check_value(t, key)
    return Answer("typed", value=t)


def _check_value(value: str, key: ObservationKey) -> None:
    kind = kind_of(key.parameter)
    if kind is ParameterKind.NUMBER:
        built = build_observation(key, "0", 1, value, None, ReadMethod.MANUAL)
        if built.observation.value_state is not ValueState.VALUE:
            raise AnswerError(
                f"{value!r} is not a number for {key.parameter.value} "
                "(a dash alone is -, a blank cell is empty)"
            )
    elif kind is ParameterKind.DATE:
        if parse_date(value) is None:
            raise AnswerError(f"{value!r} is not a date (day first, e.g. 03/11/2026)")
    # category and text parameters take the text as typed
