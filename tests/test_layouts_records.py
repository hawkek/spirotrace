"""Subject ids from file names and record ids."""

from spirotrace.layouts import base_record_id, subject_id_from_stem, unique_record_id
from spirotrace.model import RECORD_ID_RE

HASH = "ab" * 32


def test_subject_id_pattern_group_or_whole_match() -> None:
    assert subject_id_from_stem("11 report", "^[0-9]+") == "11"
    assert subject_id_from_stem("sub-0042-x", "sub-([0-9]+)") == "0042"
    assert subject_id_from_stem("report", "^[0-9]+") == ""


def test_record_id_falls_back_to_the_hash() -> None:
    assert base_record_id("11", HASH) == "11"
    assert base_record_id("", HASH) == "fabababab"
    assert RECORD_ID_RE.match(base_record_id("", HASH))


def test_duplicate_subject_ids_get_a_numbered_suffix() -> None:
    used: set[str] = set()
    assert unique_record_id("11", used) == "11"
    assert unique_record_id("11", used) == "11-2"
    assert unique_record_id("11", used) == "11-3"
    assert unique_record_id("11A", used) == "11A"
    assert unique_record_id("11A", used) == "11A-2"
    assert all(RECORD_ID_RE.match(r) for r in used)
