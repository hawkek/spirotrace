"""Subject ids from file names and record ids (file x layout)."""

from __future__ import annotations

import re


def subject_id_from_stem(stem: str, pattern: str) -> str:
    """Apply the ``subject_id.pattern`` setting to a file stem.

    Group 1 if the pattern has one, else the whole match; ``""`` when the
    pattern does not match (the input layer flags that).
    """
    m = re.search(pattern, stem)
    if m is None:
        return ""
    return m.group(1) if m.lastindex else m.group(0)


def base_record_id(subject_id: str, file_hash: str) -> str:
    """The subject id, or ``f`` plus eight hex characters of the hash without one."""
    return subject_id if subject_id else "f" + file_hash[:8]


def unique_record_id(record_id: str, used: set[str]) -> str:
    """``record_id``, or ``record_id-2``, ``-3`` ... if it is already used.

    Adds the result to ``used``. A suffix means a duplicate subject id, which
    the caller also records as a condition.
    """
    rid = record_id
    n = 1
    while rid in used:
        n += 1
        rid = f"{record_id}-{n}"
    used.add(rid)
    return rid
