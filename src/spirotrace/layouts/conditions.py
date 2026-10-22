"""Reading conditions: what the readers noticed, kept as data for the rules.

Reading never decides a severity. Where v0.3.14 raised a flag inside reading
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
DASH_READ_AS_VARIANT = "dash_read_as_variant"
NOT_A_NUMBER = "not_a_number"
RATIO_UNPARSEABLE = "ratio_unparseable"
DATE_NOT_PARSED = "date_not_parsed"
# Header fields
FIELD_NO_VALUE = "field_no_value"
FIELD_UNEXPECTED_CATEGORY = "field_unexpected_category"
FIELD_NOT_LOCATED = "field_not_located"
# Record and page level, raised by a layout's driver and page parsers
FILE_HOLDS_BOTH_LAYOUTS = "file_holds_both_layouts"
PAGE_TYPE_DUPLICATE = "page_type_duplicate"
PAGE_NOT_RECOGNISED = "page_not_recognised"
PAGE_NO_TEXT = "page_no_text"
PAGE_BLANK = "page_blank"
REPORT_TYPE_NOT_RECOGNISED = "report_type_not_recognised"
FILE_UNREADABLE = "file_unreadable"
PARSER_CRASHED = "parser_crashed"
SUBJECT_ID_DUPLICATE = "subject_id_duplicate"
SUBJECT_ID_MISSING = "subject_id_missing"
CORE_FIELD_NOT_EXTRACTED = "core_field_not_extracted"
COLUMN_UNMAPPED = "column_unmapped"
TABLE_HEADER_NOT_FOUND = "table_header_not_found"
TABLE_NOT_FOUND = "table_not_found"
SECTION_NOT_FOUND = "section_not_found"
SECOND_Z_COLUMN = "second_z_column"
BEST_COLUMN_MISSING_RENUMBERED = "best_column_missing_renumbered"
POST_BLOCK_FILTER_LINE_NOT_READ = "post_block_filter_line_not_read"
POST_VALUES_WITHOUT_QUALITY_LINE = "post_values_without_quality_line"
POST_ROW_CLIPPED = "post_row_clipped"
TREND_DATE_ROW_NOT_FOUND = "trend_date_row_not_found"
TREND_DATE_UNREADABLE = "trend_date_unreadable"
TREND_LAYOUT_UNEXPECTED = "trend_layout_unexpected"
TREND_NO_VALUES = "trend_no_values"
COLUMNS_OFF_STANDARD_LAYOUT = "columns_off_standard_layout"
COLUMNS_FROM_STANDARD_LAYOUT = "columns_from_standard_layout"
FREE_TEXT_DERIVED = "free_text_derived"
DUPLICATE_KEY_DROPPED = "duplicate_key_dropped"
INTERPRETATION_FINDING_NOT_RECOGNISED = "interpretation_finding_not_recognised"
