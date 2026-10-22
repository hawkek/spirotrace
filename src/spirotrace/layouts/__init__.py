"""Layout-free reading helpers: phrase finding, the token grammar, the table and
field readers, record ids, the observation builder and reading conditions.

Everything that names a layout (its phrases, row labels, measured geometry
and page types) lives outside the public package and imports these helpers.
Behaviour belongs in Python: a layout quirk is a named, tested handler.
"""

from .conditions import Condition, ReadingCondition
from .fields import FieldRead, FieldSpec, header_fields
from .observations import Built, build_observation
from .records import base_record_id, subject_id_from_stem, unique_record_id
from .tables import (
    Cell,
    Col,
    RowSpec,
    TableResult,
    canon_label,
    cluster_x,
    columns_from_header,
    header_name,
    label_text,
    match_label,
    merge_close_lines,
    merge_header_tokens,
    name_columns,
    parse_table,
    value_clusters,
)
from .text import (
    Match,
    find_all_phrase,
    find_phrase,
    has_line_start,
    has_phrase,
    has_title,
    norm,
    ratio,
)
from .tokens import (
    DASH_OCR_VARIANTS,
    DASHES,
    STAR_CHARS,
    NumberParse,
    clean_token,
    is_numericish,
    is_unit,
    parse_date,
    parse_number,
)

__all__ = [
    "DASHES",
    "DASH_OCR_VARIANTS",
    "STAR_CHARS",
    "Built",
    "Cell",
    "Col",
    "Condition",
    "FieldRead",
    "FieldSpec",
    "Match",
    "NumberParse",
    "ReadingCondition",
    "RowSpec",
    "TableResult",
    "base_record_id",
    "build_observation",
    "canon_label",
    "clean_token",
    "cluster_x",
    "columns_from_header",
    "find_all_phrase",
    "find_phrase",
    "has_line_start",
    "has_phrase",
    "has_title",
    "header_fields",
    "header_name",
    "is_numericish",
    "is_unit",
    "label_text",
    "match_label",
    "merge_close_lines",
    "merge_header_tokens",
    "name_columns",
    "norm",
    "parse_date",
    "parse_number",
    "parse_table",
    "ratio",
    "subject_id_from_stem",
    "unique_record_id",
    "value_clusters",
]
