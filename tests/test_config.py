"""config.py: load, validate and hash spiro.toml and profiles.

All settings files are synthetic and written to tmp_path; nothing here is
named spiro.toml inside the repository.
"""

import itertools
from dataclasses import FrozenInstanceError
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import get_type_hints

import pytest

from spirotrace import config
from spirotrace.config import (
    SCHEMA,
    SWITCHES,
    ImageSettings,
    LayoutSettings,
    OcrSettings,
    QuirkSettings,
    ReferenceSettings,
    RuleSettings,
    Settings,
    SettingsError,
    SubjectIdSettings,
    TemplateSettings,
    ToolSettings,
    default_settings,
    load_settings,
)

# Pinned so that any schema change (new key, new default, renamed table) fails
# CI and has to be made deliberately, with SCHEMA_VERSION bumped.
DEFAULT_HASH = "d3bc20bbfe2af0ebaca3f85318d0a1416f5bb776d083ae0310720e83db215dfc"


def project(tmp_path: Path, base: str = "", **profiles: str) -> Path:
    """Write a synthetic project folder with spiro.toml and optional profiles."""
    (tmp_path / "spiro.toml").write_text(base, encoding="utf-8")
    if profiles:
        (tmp_path / "profiles").mkdir()
        for name, text in profiles.items():
            (tmp_path / "profiles" / f"{name}.toml").write_text(text, encoding="utf-8")
    return tmp_path


_counter = itertools.count()


def hash_of(tmp_path: Path, text: str) -> str:
    """Hash of the settings a file with ``text`` gives, in a fresh folder."""
    folder = tmp_path / f"p{next(_counter)}"
    folder.mkdir()
    return load_settings(project(folder, text)).settings_hash


# --- missing, empty, defaults -----------------------------------------------


def test_missing_file_names_the_expected_path(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(tmp_path)
    assert str(tmp_path / "spiro.toml") in str(info.value)
    assert "not found" in str(info.value)


def test_empty_file_gives_all_defaults(tmp_path: Path) -> None:
    settings = load_settings(project(tmp_path, ""))
    assert settings == default_settings()
    assert settings.settings_hash == DEFAULT_HASH


def test_defaults_are_the_expected_object() -> None:
    assert default_settings() == Settings(
        templates=TemplateSettings(use=(), dirs=()),
        ocr=OcrSettings(missing_pages=False, second_ocr=False),
        reference=ReferenceSettings(equations="gli_2012"),
        subject_id=SubjectIdSettings(pattern="^[0-9]+"),
        rules=RuleSettings(off=(), layers_off=()),
        quirks=QuirkSettings(off=()),
        image=ImageSettings(checks=True),
        layout=LayoutSettings(position_fallback=True),
        tools=ToolSettings(rscript="", tesseract=""),
    )


def test_default_subject_id_pattern_takes_leading_digits() -> None:
    import re

    pattern = re.compile(default_settings().subject_id.pattern)
    match = pattern.search("0123_visit1")
    assert match is not None and match.group(0) == "0123"
    assert pattern.search("visit_0123") is None


# --- unknown and refused keys -----------------------------------------------


def test_unknown_table_in_base_refused(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(project(tmp_path, "[ocrs]\nsecond_ocr = true\n"))
    message = str(info.value)
    assert message.startswith("spiro.toml:")
    assert "unknown key 'ocrs'" in message


def test_unknown_key_in_base_refused_and_allowed_keys_listed(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(project(tmp_path, "[ocr]\nsecond = true\n"))
    message = str(info.value)
    assert message.startswith("spiro.toml:")
    assert "unknown key 'ocr.second'" in message
    assert "missing_pages, second_ocr" in message


def test_unknown_key_in_profile_refused_naming_the_profile(tmp_path: Path) -> None:
    folder = project(tmp_path, "", ablate="[rules]\nlayer_off = ['gli']\n")
    with pytest.raises(SettingsError) as info:
        load_settings(folder, profile="ablate")
    message = str(info.value)
    assert message.startswith("profiles/ablate.toml:")
    assert "unknown key 'rules.layer_off'" in message


def test_non_switch_key_in_profile_refused(tmp_path: Path) -> None:
    folder = project(tmp_path, "", ablate="[ocr]\nsecond_ocr = true\n")
    with pytest.raises(SettingsError) as info:
        load_settings(folder, profile="ablate")
    message = str(info.value)
    assert message.startswith("profiles/ablate.toml:")
    assert "'ocr.second_ocr' is not a switch" in message
    for switch in SWITCHES:
        assert switch in message


def test_missing_profile_names_the_expected_path(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(project(tmp_path, ""), profile="nope")
    assert str(tmp_path / "profiles" / "nope.toml") in str(info.value)


def test_all_problems_in_one_file_reported_together(tmp_path: Path) -> None:
    text = "[ocr]\nsecond_ocr = 'yes'\nbogus = 1\n[image]\nchecks = 1\n"
    with pytest.raises(SettingsError) as info:
        load_settings(project(tmp_path, text))
    message = str(info.value)
    assert "'ocr.second_ocr' must be true or false" in message
    assert "unknown key 'ocr.bogus'" in message
    assert "'image.checks' must be true or false" in message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[ocr]\nsecond_ocr = 'true'\n", "'ocr.second_ocr' must be true or false"),
        ("[image]\nchecks = 1\n", "'image.checks' must be true or false"),
        ("[reference]\nequations = 1\n", "'reference.equations' must be a string"),
        (
            "[reference]\nequations = 'gli_2017'\n",
            "'reference.equations' must be one of gli_2012, gli_global; got 'gli_2017'",
        ),
        ("[rules]\noff = 'cons.x'\n", "'rules.off' must be a list of strings"),
        ("[rules]\noff = ['cons.x', 2]\n", "'rules.off' must be a list of strings"),
        ("[rules]\noff = ['cons.x', '']\n", "'rules.off' holds an empty string"),
        (
            "[rules]\noff = ['cons.x', 'cons.x']\n",
            "'rules.off' lists cons.x more than once",
        ),
        (
            "[rules]\nlayers_off = ['gli', 'glee']\n",
            "'rules.layers_off' must contain only",
        ),
        (
            "[subject_id]\npattern = '('\n",
            "'subject_id.pattern' is not a valid regular expression",
        ),
        ("[tools]\nrscript = true\n", "'tools.rscript' must be a string"),
        ("ocr = 1\n", "'ocr' must be a table [ocr], got a number"),
    ],
)
def test_bad_values_refused_naming_file_and_key(
    tmp_path: Path, text: str, expected: str
) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(project(tmp_path, text))
    assert str(info.value).startswith("spiro.toml:")
    assert expected in str(info.value)


def test_toml_syntax_error_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as info:
        load_settings(project(tmp_path, "[ocr\n"))
    assert "spiro.toml" in str(info.value)
    assert "not valid TOML" in str(info.value)


def test_byte_order_mark_is_tolerated(tmp_path: Path) -> None:
    (tmp_path / "spiro.toml").write_bytes(b"\xef\xbb\xbf[image]\nchecks = false\n")
    assert load_settings(tmp_path).image.checks is False


# --- hashing ----------------------------------------------------------------

BASE = """
[templates]
use = ["spiro_b", "spiro_a"]
[rules]
off = ["cons.ratio_matches_values", "ocr.minus_as_tilde"]
layers_off = ["cohort"]
[image]
checks = false
"""

SAME_MEANING = [
    pytest.param(
        "# study settings\n[templates]  # which layouts\nuse = ['spiro_b', 'spiro_a']\n"
        "[rules]\noff = ['cons.ratio_matches_values', 'ocr.minus_as_tilde']  # noisy\n"
        "layers_off = ['cohort']\n[image]\nchecks = false\n",
        id="comments-and-quotes",
    ),
    pytest.param(
        "[image]\nchecks = false\n[rules]\nlayers_off = ['cohort']\n"
        "off = ['cons.ratio_matches_values', 'ocr.minus_as_tilde']\n"
        "[templates]\nuse = ['spiro_b', 'spiro_a']\n",
        id="key-order",
    ),
    pytest.param(
        "[templates]\nuse = ['spiro_a', 'spiro_b']\n[rules]\n"
        "off = ['ocr.minus_as_tilde', 'cons.ratio_matches_values']\n"
        "layers_off = ['cohort']\n[image]\nchecks = false\n",
        id="list-order",
    ),
    pytest.param(
        BASE + "[ocr]\nmissing_pages = false\nsecond_ocr = false\n"
        "[layout]\nposition_fallback = true\n[reference]\nequations = 'gli_2012'\n",
        id="defaults-written-out",
    ),
    pytest.param(
        BASE.replace(
            'use = ["spiro_b", "spiro_a"]',
            'use = ["spiro_b", "spiro_a"]\ndirs = ["templates", "more_templates"]',
        )
        + "[tools]\nrscript = 'C:/R/bin/Rscript.exe'\ntesseract = '/usr/bin/tesseract'\n",
        id="unhashed-machine-keys",
    ),
]


@pytest.mark.parametrize("variant", SAME_MEANING)
def test_equivalent_files_keep_the_hash(tmp_path: Path, variant: str) -> None:
    assert hash_of(tmp_path, variant) == hash_of(tmp_path, BASE)


DIFFERENT_MEANING = [
    pytest.param(BASE.replace("checks = false", "checks = true"), id="image.checks"),
    pytest.param(BASE.replace('"cohort"', '"gli"'), id="rules.layers_off"),
    pytest.param(BASE.replace(', "ocr.minus_as_tilde"', ""), id="rules.off"),
    pytest.param(
        BASE + "[quirks]\noff = ['clipped_row_under_filter']\n", id="quirks.off"
    ),
    pytest.param(
        BASE + "[layout]\nposition_fallback = false\n", id="layout.position_fallback"
    ),
    pytest.param(BASE + "[ocr]\nsecond_ocr = true\n", id="ocr.second_ocr"),
    pytest.param(BASE + "[ocr]\nmissing_pages = true\n", id="ocr.missing_pages"),
    pytest.param(
        BASE + "[reference]\nequations = 'gli_global'\n", id="reference.equations"
    ),
    pytest.param(BASE.replace(', "spiro_a"', ""), id="templates.use"),
    pytest.param(BASE + "[subject_id]\npattern = '^S[0-9]+'\n", id="subject_id"),
]


@pytest.mark.parametrize("variant", DIFFERENT_MEANING)
def test_any_setting_change_alters_the_hash(tmp_path: Path, variant: str) -> None:
    assert hash_of(tmp_path, variant) != hash_of(tmp_path, BASE)


def test_every_switch_change_alters_the_hash_via_a_profile(tmp_path: Path) -> None:
    folder = project(
        tmp_path,
        "",
        rules="[rules]\noff = ['cons.x']\n",
        layers="[rules]\nlayers_off = ['free_text']\n",
        quirks="[quirks]\noff = ['q']\n",
        image="[image]\nchecks = false\n",
        layout="[layout]\nposition_fallback = false\n",
    )
    base_hash = load_settings(folder).settings_hash
    hashes = {
        name: load_settings(folder, profile=name).settings_hash
        for name in ("rules", "layers", "quirks", "image", "layout")
    }
    assert base_hash not in hashes.values()
    assert len(set(hashes.values())) == len(hashes)


def test_schema_version_is_part_of_the_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SCHEMA_VERSION", 2)
    assert default_settings().settings_hash != DEFAULT_HASH


def test_hashed_dict_drops_only_unhashed_keys() -> None:
    hashed = default_settings().hashed_dict()
    assert "dirs" not in hashed["templates"]
    assert "tools" not in hashed
    assert hashed["ocr"] == {"missing_pages": False, "second_ocr": False}


# --- profiles ---------------------------------------------------------------


def test_profile_overrides_switches_and_replaces_lists(tmp_path: Path) -> None:
    base = (
        "[templates]\nuse = ['spiro_a']\n[ocr]\nsecond_ocr = true\n"
        "[rules]\noff = ['cons.a']\nlayers_off = ['cohort']\n[image]\nchecks = true\n"
    )
    folder = project(
        tmp_path,
        base,
        ablate="[rules]\noff = ['cons.b', 'cons.a2']\n[image]\nchecks = false\n",
    )
    settings = load_settings(folder, profile="ablate")
    assert settings == Settings(
        templates=TemplateSettings(use=("spiro_a",), dirs=()),
        ocr=OcrSettings(missing_pages=False, second_ocr=True),
        reference=ReferenceSettings(equations="gli_2012"),
        subject_id=SubjectIdSettings(pattern="^[0-9]+"),
        rules=RuleSettings(off=("cons.a2", "cons.b"), layers_off=("cohort",)),
        quirks=QuirkSettings(off=()),
        image=ImageSettings(checks=False),
        layout=LayoutSettings(position_fallback=True),
        tools=ToolSettings(rscript="", tesseract=""),
    )


def test_profile_with_no_overrides_equals_base(tmp_path: Path) -> None:
    folder = project(tmp_path, "[image]\nchecks = false\n", empty="# nothing\n")
    assert load_settings(folder, profile="empty") == load_settings(folder)


def test_empty_profile_is_not_rejected_for_an_empty_table(tmp_path: Path) -> None:
    folder = project(tmp_path, "", t="[rules]\n")
    assert load_settings(folder, profile="t") == default_settings()


# --- immutability -----------------------------------------------------------


def test_settings_cannot_be_mutated() -> None:
    settings = default_settings()
    with pytest.raises(FrozenInstanceError):
        settings.image = ImageSettings(checks=False)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        settings.image.checks = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        settings.rules.off = ("x",)  # type: ignore[misc]
    assert isinstance(settings.rules.off, tuple)
    assert isinstance(settings.templates.dirs, tuple)
    assert settings.settings_hash == DEFAULT_HASH


def test_settings_is_hashable_and_comparable() -> None:
    assert default_settings() == default_settings()
    assert hash(default_settings()) == hash(default_settings())


# --- schema and object stay in step ----------------------------------------


def test_schema_keys_match_dataclass_fields() -> None:
    table_types = get_type_hints(Settings)
    object_keys = {
        f"{table.name}.{f.name}"
        for table in dataclass_fields(Settings)
        for f in dataclass_fields(table_types[table.name])
    }
    assert object_keys == {f.key for f in SCHEMA}


def test_schema_switches_are_the_five_agreed() -> None:
    assert SWITCHES == (
        "rules.off",
        "rules.layers_off",
        "quirks.off",
        "image.checks",
        "layout.position_fallback",
    )


def test_unhashed_keys_are_machine_description_only() -> None:
    assert [f.key for f in SCHEMA if not f.hashed] == [
        "templates.dirs",
        "tools.rscript",
        "tools.tesseract",
    ]


def test_to_dict_has_every_key_with_plain_types() -> None:
    plain = default_settings().to_dict()
    assert {f"{t}.{k}" for t, d in plain.items() for k in d} == {f.key for f in SCHEMA}
    assert all(
        isinstance(v, bool | str | list) for d in plain.values() for v in d.values()
    )
