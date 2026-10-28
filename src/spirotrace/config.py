"""Load, validate and hash ``spiro.toml`` and ablation profiles.

This module is the only reader of ``spiro.toml`` and ``profiles/<name>.toml``.
It parses them with :mod:`tomllib`, checks every key against :data:`SCHEMA`
(unknown keys are refused, naming the key and the file), fills defaults, and
returns one frozen :class:`Settings` object that every later stage receives.

A profile may set only the keys marked as switches in the schema: rule ids,
rule layers, quirk handlers, image checks and the positional row fallback.
A profile value replaces the base value; lists are not merged.

The settings hash covers the parsed, normalised settings (defaults filled,
keys sorted, set-like lists sorted), never the raw bytes, so comments, key
order and list order do not change it. Keys that describe the machine rather
than the run (template directories, tool paths) are excluded from the hash;
template ids and versions and tool versions are stamped separately.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 2
"""Bumped whenever a schema key is added, removed or renamed. Part of the hash.

2 (28 Oct 2026, G2): ``templates.reader`` added."""

SETTINGS_FILE = "spiro.toml"
PROFILES_DIR = "profiles"

LAYERS: tuple[str, ...] = (
    "input",
    "ocr",
    "range",
    "layout",
    "image",
    "consistency",
    "gli",
    "cohort",
    "free_text",
)
"""Rule layers in ablation order (rewrite plan, Checks)."""

REFERENCE_EQUATIONS: tuple[str, ...] = ("gli_2012", "gli_global")

ReferenceEquations = Literal["gli_2012", "gli_global"]
FieldKind = Literal["bool", "str", "regex", "str_set", "str_list"]


class SettingsError(ValueError):
    """A settings file is missing, unreadable or does not match the schema."""


@dataclass(frozen=True, slots=True)
class SchemaField:
    """One key of ``spiro.toml``.

    Parameters
    ----------
    key
        Dotted ``table.name``.
    kind
        ``bool``, ``str``, ``regex`` (a string that must compile), ``str_set``
        (list of strings, duplicates refused, stored sorted) or ``str_list``
        (list of strings, duplicates refused, order kept).
    default
        Value used when the key is absent. Lists are given as tuples.
    doc
        One line for the generated default file and error messages.
    choices
        Allowed values for ``str`` and ``str_set`` kinds; empty means any.
    switch
        True if a profile may set this key.
    hashed
        False for keys that describe the machine, not the run.
    """

    key: str
    kind: FieldKind
    default: bool | str | tuple[str, ...]
    doc: str
    choices: tuple[str, ...] = ()
    switch: bool = False
    hashed: bool = True

    @property
    def table(self) -> str:
        return self.key.partition(".")[0]

    @property
    def name(self) -> str:
        return self.key.partition(".")[2]


SCHEMA: tuple[SchemaField, ...] = (
    SchemaField(
        "templates.use",
        "str_set",
        (),
        "template ids to use; empty means every template the loader finds",
    ),
    SchemaField(
        "templates.dirs",
        "str_list",
        (),
        "extra template folders, relative to the project folder; "
        "the packaged neutral templates are always included",
        hashed=False,
    ),
    SchemaField(
        "templates.reader",
        "str",
        "",
        "layout reader as package.module:function (folders in templates.dirs are put "
        "on sys.path first); empty means the packaged reader",
        hashed=False,
    ),
    SchemaField(
        "ocr.missing_pages",
        "bool",
        False,
        "run Tesseract on pages with no text layer (v0.3 --ocr-missing)",
    ),
    SchemaField(
        "ocr.second_ocr",
        "bool",
        False,
        "second Tesseract reading of every cell (v0.3 --second-ocr)",
    ),
    SchemaField(
        "reference.equations",
        "str",
        "gli_2012",
        "reference equations for z-scores, LLN and %pred",
        choices=REFERENCE_EQUATIONS,
    ),
    SchemaField(
        "subject_id.pattern",
        "regex",
        "^[0-9]+",
        "regex searched on the file stem; group 1 if present, else the whole match",
    ),
    SchemaField(
        "rules.off",
        "str_set",
        (),
        'rule ids switched off, e.g. "cons.ratio_matches_values"',
        switch=True,
    ),
    SchemaField(
        "rules.layers_off",
        "str_set",
        (),
        "rule layers switched off",
        choices=LAYERS,
        switch=True,
    ),
    SchemaField(
        "quirks.off",
        "str_set",
        (),
        'named quirk handlers switched off, e.g. "clipped_row_under_filter"',
        switch=True,
    ),
    SchemaField(
        "image.checks",
        "bool",
        True,
        "stage 4 image checks: struck numbers, printed but not read",
        switch=True,
    ),
    SchemaField(
        "layout.position_fallback",
        "bool",
        True,
        "positional row fallback measured from the table title "
        "(v0.3 --no-layout-templates switches it off)",
        switch=True,
    ),
    SchemaField(
        "tools.rscript",
        "str",
        "",
        "path to Rscript; empty searches PATH",
        hashed=False,
    ),
    SchemaField(
        "tools.tesseract",
        "str",
        "",
        "path to tesseract; empty searches PATH, then the usual Windows install folder",
        hashed=False,
    ),
)

_BY_KEY: dict[str, SchemaField] = {f.key: f for f in SCHEMA}
_TABLES: tuple[str, ...] = tuple(dict.fromkeys(f.table for f in SCHEMA))
SWITCHES: tuple[str, ...] = tuple(f.key for f in SCHEMA if f.switch)
"""Dotted keys a profile may set."""


# --- The frozen settings object --------------------------------------------


@dataclass(frozen=True, slots=True)
class TemplateSettings:
    use: tuple[str, ...]
    dirs: tuple[str, ...]
    reader: str


@dataclass(frozen=True, slots=True)
class OcrSettings:
    missing_pages: bool
    second_ocr: bool


@dataclass(frozen=True, slots=True)
class ReferenceSettings:
    equations: ReferenceEquations


@dataclass(frozen=True, slots=True)
class SubjectIdSettings:
    pattern: str


@dataclass(frozen=True, slots=True)
class RuleSettings:
    off: tuple[str, ...]
    layers_off: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuirkSettings:
    off: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImageSettings:
    checks: bool


@dataclass(frozen=True, slots=True)
class LayoutSettings:
    position_fallback: bool


@dataclass(frozen=True, slots=True)
class ToolSettings:
    rscript: str
    tesseract: str


@dataclass(frozen=True, slots=True)
class Settings:
    """All settings for one run, mirroring the tables of ``spiro.toml``."""

    templates: TemplateSettings
    ocr: OcrSettings
    reference: ReferenceSettings
    subject_id: SubjectIdSettings
    rules: RuleSettings
    quirks: QuirkSettings
    image: ImageSettings
    layout: LayoutSettings
    tools: ToolSettings

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Return the normalised settings as plain dicts and lists.

        The shape is that of the TOML file with every key present. This is
        what a run folder records as its resolved settings.
        """
        out: dict[str, dict[str, Any]] = {}
        for table_field in dataclass_fields(self):
            table = getattr(self, table_field.name)
            out[table_field.name] = {
                f.name: _plain(getattr(table, f.name)) for f in dataclass_fields(table)
            }
        return out

    def hashed_dict(self) -> dict[str, dict[str, Any]]:
        """Return :meth:`to_dict` without the keys excluded from the hash."""
        out = self.to_dict()
        for field in SCHEMA:
            if not field.hashed:
                del out[field.table][field.name]
        return {table: entries for table, entries in out.items() if entries}

    @property
    def settings_hash(self) -> str:
        """SHA-256 hex digest of the schema version and the hashed settings."""
        payload = {"schema_version": SCHEMA_VERSION, "settings": self.hashed_dict()}
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plain(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


# --- Loading ----------------------------------------------------------------


def default_settings() -> Settings:
    """Return the settings an empty ``spiro.toml`` gives."""
    return _build(_defaults())


def load_settings(project_dir: Path, profile: str | None = None) -> Settings:
    """Load ``spiro.toml`` from a project folder, with an optional profile.

    Parameters
    ----------
    project_dir
        The study project folder holding ``spiro.toml``.
    profile
        Name of ``profiles/<profile>.toml`` to apply on top, or None.

    Returns
    -------
    Settings
        One frozen object with every key present.

    Raises
    ------
    SettingsError
        If a file is missing, is not valid TOML, holds an unknown key, a
        value of the wrong type or outside its choices, or if a profile sets
        a key that is not a switch. All problems in one file are reported
        together.
    """
    project_dir = Path(project_dir)
    base_path = project_dir / SETTINGS_FILE
    if not base_path.is_file():
        raise SettingsError(
            f"{base_path}: not found; a project folder needs a {SETTINGS_FILE}"
        )
    values = _validate(_read_toml(base_path), SETTINGS_FILE, profile=False)
    if profile is not None:
        label = f"{PROFILES_DIR}/{profile}.toml"
        profile_path = project_dir / PROFILES_DIR / f"{profile}.toml"
        if not profile_path.is_file():
            raise SettingsError(f"{profile_path}: profile not found")
        overrides = _validate(_read_toml(profile_path), label, profile=True)
        for table, entries in overrides.items():
            values[table].update(entries)
    return _build(values)


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file as UTF-8, tolerating a byte-order mark."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SettingsError(f"{path}: not UTF-8 ({exc.reason})") from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: not valid TOML: {exc}") from exc


def _defaults() -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {table: {} for table in _TABLES}
    for field in SCHEMA:
        values[field.table][field.name] = field.default
    return values


def _validate(
    raw: dict[str, Any], label: str, *, profile: bool
) -> dict[str, dict[str, Any]]:
    """Check ``raw`` against the schema and return normalised values by table.

    For the base file every key is present afterwards (defaults filled). For a
    profile only the keys the file sets are returned.
    """
    problems: list[str] = []
    values: dict[str, dict[str, Any]] = {table: {} for table in _TABLES}
    for table, entries in raw.items():
        if table not in values:
            problems.append(
                f"unknown key '{table}' (allowed tables: {', '.join(_TABLES)})"
            )
            continue
        if not isinstance(entries, dict):
            problems.append(
                f"'{table}' must be a table [{table}], got {_kind(entries)}"
            )
            continue
        for name, value in entries.items():
            key = f"{table}.{name}"
            field = _BY_KEY.get(key)
            if field is None:
                allowed = ", ".join(f.name for f in SCHEMA if f.table == table)
                problems.append(
                    f"unknown key '{key}' (allowed in [{table}]: {allowed})"
                )
            elif profile and not field.switch:
                problems.append(
                    f"'{key}' is not a switch and cannot be set in a profile "
                    f"(switches: {', '.join(SWITCHES)})"
                )
            else:
                try:
                    values[table][name] = _check_value(field, value)
                except SettingsError as exc:
                    problems.append(str(exc))
    if problems:
        if len(problems) == 1:
            raise SettingsError(f"{label}: {problems[0]}")
        raise SettingsError(f"{label}:\n" + "\n".join(f"  - {p}" for p in problems))
    if not profile:
        for field in SCHEMA:
            values[field.table].setdefault(field.name, field.default)
    return values


def _check_value(field: SchemaField, value: Any) -> Any:
    """Return ``value`` normalised for ``field`` or raise with the key named."""
    key = field.key
    if field.kind == "bool":
        if not isinstance(value, bool):
            raise SettingsError(f"'{key}' must be true or false, got {_kind(value)}")
        return value
    if field.kind in ("str", "regex"):
        if not isinstance(value, str):
            raise SettingsError(f"'{key}' must be a string, got {_kind(value)}")
        if field.choices and value not in field.choices:
            raise SettingsError(
                f"'{key}' must be one of {', '.join(field.choices)}; got '{value}'"
            )
        if field.kind == "regex":
            try:
                re.compile(value)
            except re.error as exc:
                raise SettingsError(
                    f"'{key}' is not a valid regular expression: {exc}"
                ) from exc
        return value
    # str_set or str_list
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SettingsError(f"'{key}' must be a list of strings, got {_kind(value)}")
    if any(v == "" for v in value):
        raise SettingsError(f"'{key}' holds an empty string")
    duplicates = sorted({v for v in value if value.count(v) > 1})
    if duplicates:
        raise SettingsError(f"'{key}' lists {', '.join(duplicates)} more than once")
    if field.choices:
        bad = [v for v in value if v not in field.choices]
        if bad:
            raise SettingsError(
                f"'{key}' must contain only {', '.join(field.choices)}; "
                f"got {', '.join(bad)}"
            )
    return tuple(sorted(value)) if field.kind == "str_set" else tuple(value)


def _kind(value: Any) -> str:
    """Describe a TOML value's type in the words a user would recognise."""
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, int | float):
        return "a number"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "a table"
    return type(value).__name__


def _build(values: dict[str, dict[str, Any]]) -> Settings:
    return Settings(
        templates=TemplateSettings(**values["templates"]),
        ocr=OcrSettings(**values["ocr"]),
        reference=ReferenceSettings(**values["reference"]),
        subject_id=SubjectIdSettings(**values["subject_id"]),
        rules=RuleSettings(**values["rules"]),
        quirks=QuirkSettings(**values["quirks"]),
        image=ImageSettings(**values["image"]),
        layout=LayoutSettings(**values["layout"]),
        tools=ToolSettings(**values["tools"]),
    )
