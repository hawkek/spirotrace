"""Rules that turn reading conditions into flags: the input, ocr and layout
layers. Reading recorded what it noticed with a stable code; the severity is
declared here (coding file: never inside reading code).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from spirotrace.layouts import ReadingCondition
from spirotrace.layouts import conditions as cond
from spirotrace.model import ColumnRole, Parameter, ValueState

from .context import RecordContext, decimals_of
from .flags import Flag, Severity
from .registry import rule
from .thresholds import DEVICE_DECIMALS, Z_DECIMALS

E, C, N = Severity.ERROR, Severity.CHECK, Severity.NOTE

# condition code -> (rule id, message). One flag per condition, on its key when it
# has one; the rule's declared severity applies.
SIMPLE: dict[str, tuple[str, str]] = {
    cond.FILE_HOLDS_BOTH_LAYOUTS: (
        "input.file_holds_both_layouts",
        "file holds both report layouts; split into records (compare their dates)",
    ),
    cond.PAGE_TYPE_DUPLICATE: (
        "input.page_type_duplicate",
        "page type appears twice (page scanned twice, or two visits in one file?)",
    ),
    cond.PAGE_NOT_RECOGNISED: (
        "input.page_not_recognised",
        "page type not recognised; its words stay in the cache",
    ),
    cond.PAGE_NO_TEXT: (
        "input.page_no_text",
        "no text layer (run OCR, or set ocr.missing_pages)",
    ),
    cond.PAGE_BLANK: ("input.page_blank", "blank page skipped"),
    cond.REPORT_TYPE_NOT_RECOGNISED: (
        "input.report_type_not_recognised",
        "report type not recognised on any page; nothing extracted",
    ),
    cond.PARSER_CRASHED: ("input.stage_failed", "a reading stage failed on this page"),
    cond.FILE_UNREADABLE: (
        "input.file_unreadable",
        "file could not be read; re-save or re-scan it",
    ),
    cond.SUBJECT_ID_DUPLICATE: (
        "input.subject_id_duplicate",
        "subject id already used by another file; record id suffixed",
    ),
    cond.SUBJECT_ID_MISSING: (
        "input.subject_id_missing",
        "file name gives no subject id; record id from the file hash",
    ),
    cond.NOT_A_NUMBER: ("ocr.not_a_number", "not a number"),
    cond.RATIO_UNPARSEABLE: ("ocr.not_a_number", "not a ratio"),
    cond.OCR_CHAR_SUBSTITUTION: (
        "ocr.char_substitution",
        "OCR character substitution applied",
    ),
    cond.DECIMAL_COMMA: (
        "ocr.decimal_comma",
        "comma or dot variant read as decimal point",
    ),
    cond.MINUS_GUESSED: (
        "ocr.minus_guessed",
        "leading '~' or '_' read as a minus sign",
    ),
    cond.DASH_READ_AS_VARIANT: (
        "ocr.dash_variant",
        "OCR variant of a printed dash read as a dash",
    ),
    cond.DATE_NOT_PARSED: ("ocr.date_not_parsed", "date not parsed"),
    cond.ROW_PLACED_BY_GAP: (
        "layout.row_placed_by_gap",
        "row label not recognised; row identified by position",
    ),
    cond.ROW_LABEL_CONFLICT: (
        "layout.row_label_conflict",
        (
            "row label looks like a different row but was placed here by its position "
            "(check it is this row)"
        ),
    ),
    cond.ROW_EMPTY: (
        "layout.row_empty",
        "no value read for this row (OCR missed it); please type it from the scan",
    ),
    cond.ROW_NOT_FOUND: ("layout.row_not_found", "row not found"),
    cond.ROW_NO_VALUES: ("layout.row_no_values", "row found but no values read"),
    cond.ROW_UNRECOGNISED_IGNORED: (
        "layout.row_unrecognised_ignored",
        "unrecognised row with values ignored",
    ),
    cond.TOKEN_NOT_UNDER_COLUMN: (
        "layout.token_not_under_column",
        "token in a row not under any column",
    ),
    cond.ROW_LABELS_DISAGREE_WITH_ORDER: (
        "layout.row_labels_disagree_with_order",
        "row labels disagree with row order; using labels",
    ),
    cond.HEADER_GRAPH_HEADING_IGNORED: (
        "layout.header_graph_heading_ignored",
        "header ignored: no values under it (probably the z-score graph heading)",
    ),
    cond.HEADER_OVER_OTHER_COLUMN: (
        "layout.header_over_other_column",
        "header sits over a column read as another",
    ),
    cond.COLUMNS_NAMED_BY_POSITION: (
        "layout.columns_named_by_position",
        "column header not read; columns named by position",
    ),
    cond.HEADER_VALUE_COUNT_MISMATCH: (
        "layout.header_value_count_mismatch",
        "header and value columns differ in number; using header positions",
    ),
    cond.HEADER_SPACING_INCONSISTENT: (
        "layout.header_spacing_inconsistent",
        (
            "header positions inconsistent with the value columns; spacing taken "
            "from the values"
        ),
    ),
    cond.VALUE_COLUMN_UNMATCHED: (
        "layout.value_column_unmatched",
        "value column could not be matched to a header",
    ),
    cond.HEADER_PARTLY_READ: (
        "layout.header_partly_read",
        "column header only partly read; missing names inferred from layout",
    ),
    cond.COLUMNS_GENERIC_NAMES: (
        "layout.columns_generic_names",
        "column header not read; generic column names",
    ),
    cond.COLUMNS_UNDETERMINED: (
        "layout.columns_undetermined",
        "could not determine columns (header not read)",
    ),
    cond.COLUMN_NAME_TWICE: (
        "layout.column_name_twice",
        "column name appears twice in the header",
    ),
    cond.SECOND_Z_COLUMN: (
        "layout.second_z_column",
        (
            "second z-score column (another reference equation) kept at position 2; "
            "the GLI check tells which equation it matches"
        ),
    ),
    cond.BEST_COLUMN_MISSING_RENUMBERED: (
        "layout.best_column_missing_renumbered",
        (
            "the first column's FEV1 and FVC appear in no other column, so it is not the "
            "Best column: columns renumbered; best values come from the summary page"
        ),
    ),
    cond.POST_BLOCK_FILTER_LINE_NOT_READ: (
        "layout.post_block_filter_line_not_read",
        (
            "trial page seems to have a post-bronchodilator block, but its 'Inline "
            "Filter' line was not read; post trial values not extracted"
        ),
    ),
    cond.POST_VALUES_WITHOUT_QUALITY_LINE: (
        "layout.post_values_without_quality_line",
        "post trial values present but no 'Session Quality Post' line",
    ),
    cond.POST_ROW_CLIPPED: (
        "layout.post_fev1_row_clipped",
        "post FEV1 trial row is printed half-hidden under the marker line",
    ),
    cond.COLUMNS_OFF_STANDARD_LAYOUT: (
        "layout.columns_off_standard_layout",
        (
            "columns not where the standard layout puts them: check this table's values "
            "are in the right columns"
        ),
    ),
    cond.COLUMNS_FROM_STANDARD_LAYOUT: (
        "layout.columns_from_standard_layout",
        (
            "header not read: columns placed by the standard report layout (checked "
            "against the title position)"
        ),
    ),
    cond.TREND_DATE_ROW_NOT_FOUND: (
        "layout.trend_table_issue",
        "trend: date row not found",
    ),
    cond.TREND_DATE_UNREADABLE: (
        "layout.trend_table_issue",
        "trend: date not readable; its column is skipped",
    ),
    cond.TREND_LAYOUT_UNEXPECTED: (
        "layout.trend_table_issue",
        "trend: column layout not as expected; values not stored",
    ),
    cond.TREND_NO_VALUES: (
        "layout.trend_table_issue",
        "trend: rows found but no values read",
    ),
    cond.COLUMN_UNMAPPED: (
        "layout.trend_table_issue",
        "trend: column without a parameter",
    ),
    cond.SECTION_NOT_FOUND: ("layout.section_not_found", "section not found"),
    cond.CORE_FIELD_NOT_EXTRACTED: (
        "layout.core_field_not_extracted",
        (
            "not extracted (this part of the table could not be read); please type it "
            "from the scan, or 'na' if it is not printed"
        ),
    ),
    cond.FIELD_NO_VALUE: ("layout.field_no_value", "no value read"),
    cond.FIELD_UNEXPECTED_CATEGORY: (
        "range.category_vocabulary",
        "unexpected value; expected one of the printed vocabulary",
    ),
    cond.DUPLICATE_KEY_DROPPED: (
        "layout.duplicate_key_dropped",
        "a second reading of this key was dropped; the first is kept",
    ),
}

SESSION_QUALITY_PARAMETERS: frozenset[Parameter] = frozenset(
    {
        Parameter.FEV1_GRADE,
        Parameter.FVC_GRADE,
        Parameter.FEV1_VARIABILITY,
        Parameter.FVC_VARIABILITY,
        Parameter.FEV1_VARIABILITY_PCT,
        Parameter.FVC_VARIABILITY_PCT,
    }
)

SPIROMETRY_PARAMETERS: frozenset[Parameter] = frozenset(
    {
        Parameter.FEV1,
        Parameter.FVC,
        Parameter.FEV1_FVC,
        Parameter.FEV6,
        Parameter.FIVC,
        Parameter.PEF,
        Parameter.PIF,
        Parameter.FEF2575,
        Parameter.FET,
        Parameter.BEV,
    }
)


def _simple(ctx: RecordContext, rule_id: str) -> Iterator[Flag]:
    for code, (rid, message) in SIMPLE.items():
        if rid != rule_id:
            continue
        for c in ctx.conditions_of(code):
            yield _flag_for(ctx, rid, message, c)


def _flag_for(
    ctx: RecordContext, rule_id: str, message: str, c: ReadingCondition
) -> Flag:
    msg = f"{message}: {c.detail}" if c.detail else message
    keys = (c.key,) if c.key is not None else ()
    return ctx.flag(rule_id, msg, keys, page=c.page)


def _register_simple(rule_id: str, layer: str, severity: Severity, why: str) -> None:
    @rule(rule_id, layer, severity, why)
    def fn(ctx: RecordContext) -> Iterator[Flag]:
        return _simple(ctx, rule_id)


for _rid, _layer, _sev, _why in (
    (
        "input.file_holds_both_layouts",
        "input",
        N,
        "A file split into two records should have its dates compared",
    ),
    (
        "input.page_type_duplicate",
        "input",
        C,
        "A page type twice in one file means a page scanned twice or two visits",
    ),
    (
        "input.page_not_recognised",
        "input",
        C,
        "A page of the record's family with an unknown kind was not read",
    ),
    (
        "input.page_no_text",
        "input",
        E,
        "A page with no text layer was not read; it needs OCR",
    ),
    (
        "input.page_blank",
        "input",
        N,
        "A blank sheet is skipped, not reported as missing OCR",
    ),
    (
        "input.report_type_not_recognised",
        "input",
        E,
        "A file with no recognisable page is not a report of any layout",
    ),
    (
        "input.stage_failed",
        "input",
        E,
        "A reading stage that fails must leave a visible trace, not silence",
    ),
    (
        "input.file_unreadable",
        "input",
        E,
        "A PDF that cannot be opened must show in the outputs, not stop the run",
    ),
    (
        "input.subject_id_duplicate",
        "input",
        E,
        "Two files with one subject id must not be mixed up",
    ),
    (
        "input.subject_id_missing",
        "input",
        E,
        "A file name with no subject id gets a hash id and needs a look",
    ),
    ("ocr.not_a_number", "ocr", E, "Text in a numeric cell cannot be a value"),
    ("ocr.char_substitution", "ocr", C, "A letter-for-digit repair may be wrong"),
    (
        "ocr.decimal_comma",
        "ocr",
        N,
        "A comma or stray dot was read as the decimal point",
    ),
    (
        "ocr.minus_guessed",
        "ocr",
        C,
        "A leading '~' or '_' taken as a minus sign may be a dash or noise",
    ),
    (
        "ocr.dash_variant",
        "ocr",
        N,
        "A cell read as '~', '_' or '=' is taken as a printed dash",
    ),
    (
        "ocr.date_not_parsed",
        "ocr",
        C,
        "A date field whose text is not a date was not read",
    ),
    (
        "layout.row_placed_by_gap",
        "layout",
        C,
        "A row inferred between recognised labels may be the wrong row",
    ),
    (
        "layout.row_label_conflict",
        "layout",
        C,
        "A garbled label that looks like a different row was placed by order",
    ),
    ("layout.row_empty", "layout", C, "A row with no values at all was missed by OCR"),
    ("layout.row_not_found", "layout", C, "An expected row is absent from the table"),
    (
        "layout.row_no_values",
        "layout",
        C,
        "A row label was found but no values under it",
    ),
    (
        "layout.row_unrecognised_ignored",
        "layout",
        C,
        "A row with values whose label matched nothing was dropped",
    ),
    (
        "layout.token_not_under_column",
        "layout",
        C,
        "A token in a row that fits no column was dropped",
    ),
    (
        "layout.row_labels_disagree_with_order",
        "layout",
        C,
        "Labels and row order disagree; labels were used",
    ),
    (
        "layout.header_graph_heading_ignored",
        "layout",
        N,
        "A heading with no values under it was dropped, not taken as a column",
    ),
    (
        "layout.header_over_other_column",
        "layout",
        C,
        "A header token sits over a column named differently from the expected order",
    ),
    (
        "layout.columns_named_by_position",
        "layout",
        N,
        "Header not read; columns named from the expected order",
    ),
    (
        "layout.header_value_count_mismatch",
        "layout",
        C,
        "Header and value columns disagree in number",
    ),
    (
        "layout.header_spacing_inconsistent",
        "layout",
        C,
        "A partial header implies a spacing that does not fit the values",
    ),
    (
        "layout.value_column_unmatched",
        "layout",
        C,
        "A value column could not be matched to any header",
    ),
    (
        "layout.header_partly_read",
        "layout",
        N,
        "Missing column names were inferred from the layout",
    ),
    (
        "layout.columns_generic_names",
        "layout",
        N,
        "Trial header not read; columns are display positions only",
    ),
    (
        "layout.columns_undetermined",
        "layout",
        E,
        "Columns could not be determined, so the table was not read",
    ),
    (
        "layout.column_name_twice",
        "layout",
        C,
        "The same column name read twice in one header means a header misread",
    ),
    (
        "layout.second_z_column",
        "layout",
        N,
        "A second z-score column comes from another reference equation",
    ),
    (
        "layout.best_column_missing_renumbered",
        "layout",
        C,
        "Header not read and the first column repeats no trial: Best was missed",
    ),
    (
        "layout.post_block_filter_line_not_read",
        "layout",
        C,
        "A post block seems present but its marker line was not read",
    ),
    (
        "layout.post_values_without_quality_line",
        "layout",
        C,
        "Post trial values without their session-quality line",
    ),
    (
        "layout.post_fev1_row_clipped",
        "layout",
        C,
        "The post FEV1 trial row prints half under the filter line",
    ),
    (
        "layout.columns_off_standard_layout",
        "layout",
        C,
        "A fully read header whose columns sit away from the measured layout may hold values in the wrong column",
    ),
    (
        "layout.columns_from_standard_layout",
        "layout",
        N,
        "Header not read; columns placed by the measured layout",
    ),
    (
        "layout.trend_table_issue",
        "layout",
        N,
        "A trend page that could not be read fully",
    ),
    (
        "layout.section_not_found",
        "layout",
        N,
        "A comments or interpretation section was not found on a page that has one",
    ),
    (
        "layout.core_field_not_extracted",
        "layout",
        C,
        "A core spirometry cell the main page should have was not extracted at all",
    ),
    ("layout.field_no_value", "layout", C, "A label was found with nothing after it"),
    (
        "range.category_vocabulary",
        "range",
        C,
        "Sex and smoker must come from the printed vocabulary",
    ),
    (
        "layout.duplicate_key_dropped",
        "layout",
        C,
        "A second observation for a stored key was dropped",
    ),
):
    _register_simple(_rid, _layer, _sev, _why)


@rule(
    "layout.table_not_found",
    "layout",
    (E, C, N),
    "A main table missing from its page leaves core values unread",
)
def table_not_found(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.TABLE_HEADER_NOT_FOUND) + ctx.conditions_of(
        cond.TABLE_NOT_FOUND
    ):
        detail = c.detail.lower()
        if "trend" in detail:
            sev = N  # the old script noted a missing trend table
        elif "volume" in detail:
            sev = C
        else:
            sev = E
        yield ctx.flag(
            "layout.table_not_found",
            f"table not found: {c.detail}",
            page=c.page,
            severity=sev,
        )


@rule(
    "layout.field_not_located",
    "layout",
    C,
    "A header or reference-line label was not found, so the value must be typed",
)
def field_not_located(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.FIELD_NOT_LOCATED):
        if c.key is not None and c.key.parameter in SESSION_QUALITY_PARAMETERS:
            continue
        yield _flag_for(
            ctx,
            "layout.field_not_located",
            "not found (label not read); please type it from the scan",
            c,
        )


@rule(
    "layout.session_quality_field_not_found",
    "layout",
    C,
    "A grade or variability was not found in the session-quality line",
)
def session_quality_field_not_found(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.FIELD_NOT_LOCATED):
        if c.key is not None and c.key.parameter in SESSION_QUALITY_PARAMETERS:
            yield _flag_for(
                ctx,
                "layout.session_quality_field_not_found",
                "not found in session quality line",
                c,
            )


def _table_group(parameter: Parameter) -> str:
    return (
        "spirometry"
        if parameter in SPIROMETRY_PARAMETERS
        else "volumes and gas transfer"
    )


@rule(
    "layout.row_placed_by_template",
    "layout",
    N,
    "Rows placed by their height from the layout template have no label backing them",
)
def row_placed_by_template(ctx: RecordContext) -> Iterator[Flag]:
    # once per table, not per cell (G1 rework): the read method on each observation
    # already says position_fallback
    groups: dict[tuple[int | None, str], list[ReadingCondition]] = defaultdict(list)
    for c in ctx.conditions_of(cond.ROW_PLACED_BY_TEMPLATE):
        group = _table_group(c.key.parameter) if c.key is not None else "table"
        groups[(c.page, group)].append(c)
    for (page, group), cs in sorted(
        groups.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1])
    ):
        keys = tuple(c.key for c in cs if c.key is not None)
        yield ctx.flag(
            "layout.row_placed_by_template",
            f"{group}: {len(cs)} cells placed by row height from the layout template",
            keys,
            page=page,
        )


@rule(
    "layout.cell_empty_in_filled_column",
    "layout",
    C,
    "An empty cell in a column that has values elsewhere is probably an OCR drop",
)
def cell_empty_in_filled_column(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.CELL_EMPTY_IN_FILLED_COLUMN):
        if c.key is None:
            continue
        slot = (c.key.parameter, c.key.column_role, c.key.display_position)
        if slot in ctx.empty_by_format:
            continue  # cohort.column_empty_by_format reports it as a note
        yield ctx.flag(
            "layout.cell_empty_in_filled_column",
            "cell empty although column has values in other rows (possible OCR drop)",
            (c.key,),
        )


@rule(
    "cohort.column_empty_by_format",
    "cohort",
    N,
    "A column empty in nearly every report of one layout is the report's format, not a drop",
)
def column_empty_by_format(ctx: RecordContext) -> Iterator[Flag]:
    for c in ctx.conditions_of(cond.CELL_EMPTY_IN_FILLED_COLUMN):
        if c.key is None:
            continue
        slot = (c.key.parameter, c.key.column_role, c.key.display_position)
        if slot in ctx.empty_by_format:
            yield ctx.flag(
                "cohort.column_empty_by_format",
                "cell empty, as in nearly every report of this layout (its format)",
                (c.key,),
            )


@rule(
    "layout.trial_number_repeated",
    "layout",
    C,
    "Two trial columns with the same printed number mean a header was misread",
)
def trial_number_repeated(ctx: RecordContext) -> Iterator[Flag]:
    for role in (ColumnRole.TRIAL, ColumnRole.POST_TRIAL):
        seen: dict[float, list] = defaultdict(list)
        for pos in ctx.positions(Parameter.TRIAL_NUMBER, role):
            o = ctx.get(Parameter.TRIAL_NUMBER, role, pos)
            if o is not None and o.parsed_value is not None:
                seen[o.parsed_value].append(o)
        for number, obs in seen.items():
            if len(obs) > 1:
                yield ctx.flag(
                    "layout.trial_number_repeated",
                    f"trial number {number:g} printed on {len(obs)} columns",
                    obs,
                )


@rule(
    "ocr.decimal_places",
    "ocr",
    C,
    "The device prints fixed decimals; another count means a lost or extra digit",
)
def decimal_places(ctx: RecordContext) -> Iterator[Flag]:
    if not ctx.has_role(ColumnRole.TRIAL):
        return  # only layouts with a trials table are device output with fixed decimals
    value_roles = (
        ColumnRole.PRE,
        ColumnRole.POST,
        ColumnRole.LLN,
        ColumnRole.POST_LLN,
        ColumnRole.TRIAL,
        ColumnRole.POST_TRIAL,
    )
    for (param, role, _pos), obs in sorted(ctx.by_slot.items(), key=lambda kv: kv[0]):
        for o in obs:
            if o.value_state is not ValueState.VALUE:
                continue
            dec = decimals_of(o)
            if dec is None:
                continue
            if role in value_roles and param in DEVICE_DECIMALS:
                exp = DEVICE_DECIMALS[param]
                if dec != exp:
                    yield ctx.flag(
                        "ocr.decimal_places",
                        f"expected {exp} decimal places, got {dec}",
                        [o],
                    )
            elif role in (ColumnRole.Z, ColumnRole.POST_Z) and dec != Z_DECIMALS:
                yield ctx.flag(
                    "ocr.decimal_places",
                    f"expected {Z_DECIMALS} decimal places for z-score, got {dec}",
                    [o],
                )
