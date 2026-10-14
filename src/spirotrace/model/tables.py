"""In-memory records of the extraction store: Record, Page, ObservationKey, Observation.

Each type is a frozen dataclass validated on construction, with ``COLUMNS``,
``to_row()`` and ``from_row()`` so a later work package can choose the file
format. Row values are all strings. Encoding rules, applied to every column:

- None is ``""`` and ``""`` is None for optional columns; ``raw_text`` is a
  plain string and never None, so it carries no such ambiguity;
- floats use :func:`repr`, which round-trips exactly; integers use :func:`str`;
- booleans are ``"true"`` or ``"false"``; enums use their value;
- ``pages`` is space-separated; ``bbox`` is four columns.

The observation key (seam 1) is file hash, page, template id, parameter,
column role and display position. Its string form, used by review events and
the corrections import, joins those six parts with colons.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar, Self

from .vocab import (
    RATIO_PARAMETERS,
    TRIAL_ROLES,
    VALUE_ROLES,
    ColumnRole,
    Parameter,
    ParameterKind,
    RatioForm,
    ReadMethod,
    TextSource,
    ValueState,
    kind_of,
)

FILE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
"""SHA-256 of the PDF bytes, lowercase hex."""

RECORD_ID_RE = re.compile(r"^([0-9]+|f[0-9a-f]{8})[AB]?(-([2-9]|[1-9][0-9]+))?$")
"""Record id forms.

- ``11``: the subject id from the file name; ``11A`` and ``11B`` when one file
  holds both layouts (the v0.3.16 form).
- ``f`` plus the first eight hex characters of the file hash when the file
  name gives no subject id.
- ``-2``, ``-3``, ... after either form for the second, third ... file with the
  same subject id (an input-layer error is raised alongside).
"""

TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

ROTATIONS = (0, 90, 180, 270)

Row = dict[str, str]


class ModelError(ValueError):
    """A record violates a data invariant."""


# --- Row encoding helpers ---------------------------------------------------


def _enc(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _opt_str(text: str) -> str | None:
    return text if text != "" else None


def _opt_int(text: str) -> int | None:
    return int(text) if text != "" else None


def _opt_float(text: str) -> float | None:
    return float(text) if text != "" else None


def _bool(text: str) -> bool:
    if text == "true":
        return True
    if text == "false":
        return False
    raise ModelError(f"boolean column must be true or false, got {text!r}")


def _check_hash(file_hash: str) -> None:
    if not FILE_HASH_RE.match(file_hash):
        raise ModelError("file_hash must be 64 lowercase hex characters (SHA-256)")


def _check_record_id(record_id: str) -> None:
    if not RECORD_ID_RE.match(record_id):
        raise ModelError(
            "record_id must be digits or f+8 hex, an optional A or B and an "
            f"optional -n (n >= 2), got {record_id!r}"
        )


def _check_finite(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise ModelError(f"{name} must be finite, got {value!r}")


def _pick(row: Mapping[str, str], columns: tuple[str, ...], name: str) -> Row:
    missing = [c for c in columns if c not in row]
    if missing:
        raise ModelError(f"{name} row lacks columns: {', '.join(missing)}")
    return {c: row[c] for c in columns}


# --- Record -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Record:
    """One file x one layout.

    Parameters
    ----------
    record_id
        ``11``, or ``11A`` / ``11B`` when one file holds both layouts; see
        :data:`RECORD_ID_RE` for the no-subject-id and duplicate-subject forms.
        Not part of the observation key.
    file_hash
        SHA-256 of the PDF bytes, lowercase hex.
    layout
        The template id that read this record.
    subject_id
        From the file name via the ``spiro.toml`` pattern; ``""`` when the
        pattern did not match, which the input layer flags.
    pages
        1-based page numbers in the file belonging to this record, ascending.
    """

    record_id: str
    file_hash: str
    layout: str
    subject_id: str
    pages: tuple[int, ...]

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "record_id",
        "file_hash",
        "layout",
        "subject_id",
        "pages",
    )

    def __post_init__(self) -> None:
        _check_record_id(self.record_id)
        _check_hash(self.file_hash)
        if not TEMPLATE_ID_RE.match(self.layout):
            raise ModelError(f"layout must be a template id, got {self.layout!r}")
        if not self.pages:
            raise ModelError("pages must not be empty")
        if any(p < 1 for p in self.pages) or list(self.pages) != sorted(
            set(self.pages)
        ):
            raise ModelError("pages must be 1-based and strictly increasing")

    def to_row(self) -> Row:
        return {
            "record_id": self.record_id,
            "file_hash": self.file_hash,
            "layout": self.layout,
            "subject_id": self.subject_id,
            "pages": " ".join(str(p) for p in self.pages),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> Self:
        r = _pick(row, cls.COLUMNS, "Record")
        return cls(
            record_id=r["record_id"],
            file_hash=r["file_hash"],
            layout=r["layout"],
            subject_id=r["subject_id"],
            pages=tuple(int(p) for p in r["pages"].split()),
        )


# --- Page -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Page:
    """One page of one file, written at classify.

    Parameters
    ----------
    page_type
        The template's page name; None when no fingerprint matched.
    footer_page_number
        The printed page number, if read.
    rotation
        Degrees turned to make the page upright: 0, 90, 180 or 270.
    skew
        Degrees of skew detected after rotation.
    ink
        Dark-pixel fraction, 0 to 1 (the blank-page check).
    """

    file_hash: str
    page: int
    page_type: str | None
    footer_page_number: int | None
    word_count: int
    rotation: int
    skew: float
    ink: float
    text_source: TextSource

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "file_hash",
        "page",
        "page_type",
        "footer_page_number",
        "word_count",
        "rotation",
        "skew",
        "ink",
        "text_source",
    )

    def __post_init__(self) -> None:
        _check_hash(self.file_hash)
        if self.page < 1:
            raise ModelError("page must be 1-based")
        if self.page_type == "":
            raise ModelError("page_type must be None rather than an empty string")
        if self.footer_page_number is not None and self.footer_page_number < 1:
            raise ModelError("footer_page_number must be positive")
        if self.word_count < 0:
            raise ModelError("word_count must not be negative")
        if self.rotation not in ROTATIONS:
            raise ModelError(
                f"rotation must be one of {ROTATIONS}, got {self.rotation}"
            )
        _check_finite("skew", self.skew)
        if not 0.0 <= self.ink <= 1.0:
            raise ModelError(f"ink must be between 0 and 1, got {self.ink!r}")
        if not isinstance(self.text_source, TextSource):
            raise ModelError("text_source must be a TextSource")

    def to_row(self) -> Row:
        return {
            "file_hash": self.file_hash,
            "page": _enc(self.page),
            "page_type": _enc(self.page_type),
            "footer_page_number": _enc(self.footer_page_number),
            "word_count": _enc(self.word_count),
            "rotation": _enc(self.rotation),
            "skew": _enc(self.skew),
            "ink": _enc(self.ink),
            "text_source": self.text_source.value,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> Self:
        r = _pick(row, cls.COLUMNS, "Page")
        return cls(
            file_hash=r["file_hash"],
            page=int(r["page"]),
            page_type=_opt_str(r["page_type"]),
            footer_page_number=_opt_int(r["footer_page_number"]),
            word_count=int(r["word_count"]),
            rotation=int(r["rotation"]),
            skew=float(r["skew"]),
            ink=float(r["ink"]),
            text_source=TextSource(r["text_source"]),
        )


# --- ObservationKey ---------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class ObservationKey:
    """The natural key of a value read from a report (seam 1).

    Trial columns are keyed by display position (Best = 1, then 2, 3, ...);
    the printed trial number is its own observation, never part of the key.
    """

    file_hash: str
    page: int
    template_id: str
    parameter: Parameter
    column_role: ColumnRole
    display_position: int

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "file_hash",
        "page",
        "template_id",
        "parameter",
        "column_role",
        "display_position",
    )
    SEPARATOR: ClassVar[str] = ":"

    def __post_init__(self) -> None:
        _check_hash(self.file_hash)
        if self.page < 1:
            raise ModelError("page must be 1-based")
        if not TEMPLATE_ID_RE.match(self.template_id):
            raise ModelError(
                f"template_id must be a template id, got {self.template_id!r}"
            )
        if not isinstance(self.parameter, Parameter):
            raise ModelError("parameter must be a Parameter")
        if not isinstance(self.column_role, ColumnRole):
            raise ModelError("column_role must be a ColumnRole")
        if self.display_position < 1:
            raise ModelError("display_position must be 1 or more")
        if (
            self.parameter is Parameter.TRIAL_NUMBER
            and self.column_role not in TRIAL_ROLES
        ):
            raise ModelError("trial_number must have role trial or post_trial")

    def to_string(self) -> str:
        """Colon-joined form for events and the corrections import."""
        return self.SEPARATOR.join(
            (
                self.file_hash,
                str(self.page),
                self.template_id,
                self.parameter.value,
                self.column_role.value,
                str(self.display_position),
            )
        )

    @classmethod
    def from_string(cls, text: str) -> Self:
        parts = text.split(cls.SEPARATOR)
        if len(parts) != 6:
            raise ModelError(f"key must have six colon-separated parts, got {text!r}")
        file_hash, page, template_id, parameter, role, position = parts
        try:
            return cls(
                file_hash=file_hash,
                page=int(page),
                template_id=template_id,
                parameter=Parameter(parameter),
                column_role=ColumnRole(role),
                display_position=int(position),
            )
        except ValueError as exc:
            raise ModelError(f"bad key {text!r}: {exc}") from exc

    def to_row(self) -> Row:
        return {
            "file_hash": self.file_hash,
            "page": _enc(self.page),
            "template_id": self.template_id,
            "parameter": self.parameter.value,
            "column_role": self.column_role.value,
            "display_position": _enc(self.display_position),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> Self:
        r = _pick(row, cls.COLUMNS, "ObservationKey")
        return cls(
            file_hash=r["file_hash"],
            page=int(r["page"]),
            template_id=r["template_id"],
            parameter=Parameter(r["parameter"]),
            column_role=ColumnRole(r["column_role"]),
            display_position=int(r["display_position"]),
        )


# --- Observation ------------------------------------------------------------

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Observation:
    """One value read from a report, with its provenance.

    Raw text, parsed value and (later) resolved value are kept apart. The
    parsed value lives in ``parsed_value`` for number parameters and in
    ``parsed_text`` for category, date and text parameters, and only when
    ``value_state`` is ``VALUE``. Nothing is ever coerced to zero.

    Parameters
    ----------
    key
        The natural key.
    record_id
        The record the value belongs to; not part of the key.
    template_version
        Version of the template that read it; recorded, not keyed.
    raw_text
        The cell text as read; ``""`` when nothing was read or the cell is not
        on the page.
    parsed_value, parsed_text
        See above. Dates are ISO ``YYYY-MM-DD`` in ``parsed_text``.
    unit
        As declared by the template, e.g. ``"L"``; None for ratios and for
        non-numeric kinds.
    printed_form
        ``percent`` or ``fraction`` for a ratio value in a value-like role;
        None otherwise.
    marked
        True when the report marked the value itself (its asterisk for
        outside the normal range).
    bbox
        ``(x0, y0, x1, y1)`` in page points; None for inferred, manual and
        not-on-page values.
    read_method, ocr_confidence
        How the text was read and Tesseract's 0 to 100 confidence. The
        confidence is allowed only when ``read_method`` is ``ocr``.
        ``ocr_cell`` is refused here: the second reading never replaces the
        first without a reviewer event.
    second_reading_run, second_reading
        Whether the per-cell second OCR (read method ``ocr_cell``) ran, and
        what it read (``""`` when it ran and read nothing; None when it did
        not run). This is the only place the second reading is stored. It
        runs on the observation's bbox, so it needs one and never runs on a
        not-on-page, inferred or manual value.
    value_state
        What the cell held.
    """

    key: ObservationKey
    record_id: str
    template_version: int
    raw_text: str
    parsed_value: float | None
    parsed_text: str | None
    unit: str | None
    printed_form: RatioForm | None
    marked: bool
    bbox: BBox | None
    read_method: ReadMethod
    ocr_confidence: float | None
    second_reading_run: bool
    second_reading: str | None
    value_state: ValueState

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "record_id",
        *ObservationKey.COLUMNS,
        "template_version",
        "raw_text",
        "parsed_value",
        "parsed_text",
        "unit",
        "printed_form",
        "marked",
        "bbox_x0",
        "bbox_y0",
        "bbox_x1",
        "bbox_y1",
        "read_method",
        "ocr_confidence",
        "second_reading_run",
        "second_reading",
        "value_state",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.key, ObservationKey):
            raise ModelError("key must be an ObservationKey")
        _check_record_id(self.record_id)
        if self.template_version < 1:
            raise ModelError("template_version must be 1 or more")
        if not isinstance(self.value_state, ValueState):
            raise ModelError("value_state must be a ValueState")
        if not isinstance(self.read_method, ReadMethod):
            raise ModelError("read_method must be a ReadMethod")
        if self.read_method is ReadMethod.OCR_CELL:
            raise ModelError(
                "ocr_cell is the second reading's method; it lives in second_reading"
            )
        self._check_parsed()
        self._check_printed_form()
        if self.unit == "":
            raise ModelError("unit must be None rather than an empty string")
        if (
            self.unit is not None
            and kind_of(self.key.parameter) is not ParameterKind.NUMBER
        ):
            raise ModelError("unit is only allowed on number parameters")
        self._check_bbox()
        self._check_ocr_fields()

    def _check_ocr_fields(self) -> None:
        if self.ocr_confidence is not None:
            if self.read_method is not ReadMethod.OCR:
                raise ModelError(
                    "ocr_confidence is only allowed when read_method is ocr"
                )
            _check_finite("ocr_confidence", self.ocr_confidence)
            if not 0.0 <= self.ocr_confidence <= 100.0:
                raise ModelError(
                    f"ocr_confidence must be between 0 and 100, got {self.ocr_confidence!r}"
                )
        if self.second_reading_run:
            if self.second_reading is None:
                raise ModelError(
                    "second_reading must be a string when second_reading_run is true"
                )
            if self.bbox is None or self.value_state is ValueState.NOT_ON_PAGE:
                raise ModelError("second_reading_run needs a bbox on the page to crop")
            if self.read_method in (ReadMethod.MANUAL, ReadMethod.INFERRED):
                raise ModelError(
                    "second_reading_run is not allowed on a manual or inferred value"
                )
        elif self.second_reading is not None:
            raise ModelError(
                "second_reading must be None when second_reading_run is false"
            )

    def _check_parsed(self) -> None:
        kind = kind_of(self.key.parameter)
        if self.value_state is not ValueState.VALUE:
            if self.parsed_value is not None or self.parsed_text is not None:
                raise ModelError(
                    f"value_state {self.value_state.value} must not carry a parsed value"
                )
            blank = self.raw_text.strip() == ""
            if self.value_state is ValueState.EMPTY and not blank:
                raise ModelError("value_state empty requires blank raw_text")
            if self.value_state is ValueState.DASH and blank:
                raise ModelError(
                    "value_state dash requires the printed dash in raw_text"
                )
            return
        if kind is ParameterKind.NUMBER:
            if self.parsed_value is None or self.parsed_text is not None:
                raise ModelError(
                    "a number parameter with a value needs parsed_value only"
                )
            _check_finite("parsed_value", self.parsed_value)
            return
        if (
            self.parsed_text is None
            or self.parsed_text == ""
            or self.parsed_value is not None
        ):
            raise ModelError(
                f"a {kind.value} parameter with a value needs parsed_text only"
            )
        if kind is ParameterKind.DATE:
            try:
                date.fromisoformat(self.parsed_text)
            except ValueError as exc:
                raise ModelError(
                    f"parsed_text must be an ISO date, got {self.parsed_text!r}"
                ) from exc

    def _check_printed_form(self) -> None:
        is_ratio_value = (
            self.key.parameter in RATIO_PARAMETERS
            and self.key.column_role in VALUE_ROLES
            and self.value_state is ValueState.VALUE
        )
        if is_ratio_value:
            if not isinstance(self.printed_form, RatioForm):
                raise ModelError("a ratio value needs printed_form")
            assert self.parsed_value is not None
            if not 0.0 <= self.parsed_value <= 1.0:
                raise ModelError(
                    f"a ratio is stored as a fraction, got {self.parsed_value!r}"
                )
            if self.unit is not None:
                raise ModelError(
                    "a ratio has no unit; printed_form records how it was printed"
                )
        elif self.printed_form is not None:
            raise ModelError(
                "printed_form is only for ratio values in value-like roles"
            )

    def _check_bbox(self) -> None:
        if self.value_state is ValueState.NOT_ON_PAGE:
            if self.raw_text != "" or self.bbox is not None:
                raise ModelError("not_on_page requires empty raw_text and no bbox")
            return
        if self.bbox is None:
            return
        if len(self.bbox) != 4:
            raise ModelError("bbox must have four numbers")
        for v in self.bbox:
            _check_finite("bbox", v)
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ModelError("bbox must be x0 <= x1 and y0 <= y1")

    def to_row(self) -> Row:
        bbox = self.bbox if self.bbox is not None else (None, None, None, None)
        return {
            "record_id": self.record_id,
            **self.key.to_row(),
            "template_version": _enc(self.template_version),
            "raw_text": self.raw_text,
            "parsed_value": _enc(self.parsed_value),
            "parsed_text": _enc(self.parsed_text),
            "unit": _enc(self.unit),
            "printed_form": _enc(self.printed_form),
            "marked": _enc(self.marked),
            "bbox_x0": _enc(bbox[0]),
            "bbox_y0": _enc(bbox[1]),
            "bbox_x1": _enc(bbox[2]),
            "bbox_y1": _enc(bbox[3]),
            "read_method": self.read_method.value,
            "ocr_confidence": _enc(self.ocr_confidence),
            "second_reading_run": _enc(self.second_reading_run),
            "second_reading": _enc(self.second_reading),
            "value_state": self.value_state.value,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> Self:
        r = _pick(row, cls.COLUMNS, "Observation")
        corners = (r["bbox_x0"], r["bbox_y0"], r["bbox_x1"], r["bbox_y1"])
        bbox: BBox | None
        if all(c == "" for c in corners):
            bbox = None
        elif any(c == "" for c in corners):
            raise ModelError("bbox columns must all be set or all be empty")
        else:
            bbox = (
                float(corners[0]),
                float(corners[1]),
                float(corners[2]),
                float(corners[3]),
            )
        run = _bool(r["second_reading_run"])
        return cls(
            key=ObservationKey.from_row(r),
            record_id=r["record_id"],
            template_version=int(r["template_version"]),
            raw_text=r["raw_text"],
            parsed_value=_opt_float(r["parsed_value"]),
            parsed_text=_opt_str(r["parsed_text"]),
            unit=_opt_str(r["unit"]),
            printed_form=RatioForm(r["printed_form"]) if r["printed_form"] else None,
            marked=_bool(r["marked"]),
            bbox=bbox,
            read_method=ReadMethod(r["read_method"]),
            ocr_confidence=_opt_float(r["ocr_confidence"]),
            second_reading_run=run,
            second_reading=r["second_reading"] if run else None,
            value_state=ValueState(r["value_state"]),
        )
