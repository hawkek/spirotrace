"""Reading conditions: what the readers noticed, kept as data for the rules.

Reading never decides a severity. Where v0.3.16 raised a flag inside reading
(a row placed by position, a header only partly read, a token repaired), the
port records a :class:`Condition` with a stable code; a rule in the checks
layer turns conditions into flags.
"""

from __future__ import annotations

from dataclasses import dataclass

from spirotrace.model import ObservationKey


@dataclass(frozen=True, slots=True)
class Condition:
    """Something a reader noticed, with a stable code and a human detail."""

    code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReadingCondition:
    """A :class:`Condition` placed on a record, a page or one observation."""

    record_id: str
    page: int | None
    key: ObservationKey | None
    code: str
    detail: str = ""


# Table reader
HEADER_GRAPH_HEADING_IGNORED = "header_graph_heading_ignored"
HEADER_OVER_OTHER_COLUMN = "header_over_other_column"
COLUMNS_NAMED_BY_POSITION = "columns_named_by_position"
HEADER_VALUE_COUNT_MISMATCH = "header_value_column_count_mismatch"
HEADER_SPACING_INCONSISTENT = "header_spacing_inconsistent"
VALUE_COLUMN_UNMATCHED = "value_column_unmatched"
HEADER_PARTLY_READ = "header_partly_read_columns_inferred"
COLUMNS_GENERIC_NAMES = "columns_generic_names"
COLUMNS_UNDETERMINED = "columns_undetermined"
COLUMN_NAME_TWICE = "column_name_twice"
ROW_LABELS_DISAGREE_WITH_ORDER = "row_labels_disagree_with_order"
ROW_UNRECOGNISED_IGNORED = "row_unrecognised_ignored"
ROW_NOT_FOUND = "row_not_found"
TOKEN_NOT_UNDER_COLUMN = "token_not_under_column"
ROW_NO_VALUES = "row_no_values"
# Cells
ROW_PLACED_BY_GAP = "row_placed_by_gap"
ROW_PLACED_BY_TEMPLATE = "row_placed_by_template"
ROW_LABEL_CONFLICT = "row_label_conflict"
CELL_EMPTY_IN_FILLED_COLUMN = "cell_empty_in_filled_column"
ROW_EMPTY = "row_empty"
# Tokens
OCR_CHAR_SUBSTITUTION = "ocr_char_substitution"
DECIMAL_COMMA = "decimal_comma"
MINUS_GUESSED = "minus_guessed"
NOT_A_NUMBER = "not_a_number"
RATIO_UNPARSEABLE = "ratio_unparseable"
DATE_NOT_PARSED = "date_not_parsed"
# Header fields
FIELD_NO_VALUE = "field_no_value"
FIELD_UNEXPECTED_CATEGORY = "field_unexpected_category"
FIELD_NOT_LOCATED = "field_not_located"
