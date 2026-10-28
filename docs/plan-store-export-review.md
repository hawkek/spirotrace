# Plan: stored formats, resolve, CLI, export, QC report and review queue

Status: draft for approval (gate G2), 28 October 2026. Nothing in it is built.
It settles every ask-first item for the four phase 2 steps: A3 derive,
A4 second OCR, A5 export and A6 review queue. It follows the rewrite plan and
the runtime sequences; section 12 lists every place it departs from them, and
section 13 the decisions still needed. No new runtime dependency is proposed.

Naming in this document: the two layouts are "the portable layout" and "the
lab layout"; "the old script" is the version the port is measured against.

## 1. What is built, in which order

| PR | Branch | Builds | Done when |
| --- | --- | --- | --- |
| 1 | `wp-a5-store-derive` | `store/` (checkpoints, stamps, alongside-writes), `pipeline.py` (the run), `resolve/`, `derive/`, the `derived.*` and `free_text.*` rules that need derived values, `spirotrace run` and the resolve and derive half of `spirotrace export` | A synthetic folder runs end to end into `outputs/raw/`; events applied by a test give the expected statuses, `flags_resolved` changes and derived rows; a value under reviewer disagreement is skipped by derive |
| 2 | `wp-a4-second-ocr` | The second reading on each observation's bbox, its cache, the `ocr.second_reading_*` rules, `ocr.missing_pages` | Cache hit on rerun and miss when the bbox or Tesseract version changes (unit tests); the four rules fire and do not fire on synthetic readings; the live Tesseract test skips with a reason where it is absent |
| 3 | `wp-a5-export` | The dataset files, data dictionary, QC report, export guard and `share/` | Planted identifiers, free text, record ids and never-extract words never reach `share/` (test); the wide CSV blanks exactly what the derive rule blanks |
| 4 | `wp-a6-review` | The flag queue server and page, events, timing, per-record rerun | A browser-free test drives the API: an answer appends one event, the queue shrinks, a corrected value clears its flag; a second submit while saving is ignored |

The study runs on the real reports only after each PR is merged, with the
counts-only command given in that PR's hand-over.

## 2. Project folder and files

The folder is the one in the rewrite plan. The extraction store (checkpoint 2)
has no folder of its own there; it goes under `outputs/raw/`, so `.gitignore`
does not change.

```
my_study/
  spiro.toml
  reports/                       the PDFs, never modified
  cache/
    words/<file_hash>.csv        checkpoint 1: words per page
    words/<file_hash>.pages.csv  page metadata from ingest
    words/<file_hash>.stamp.json
    second_ocr/<file_hash>.csv   Tesseract cell readings (A4)
  outputs/
    raw/                         checkpoint 2: the raw run, never changed by review
      records_CONTAINS_DATA.csv
      pages.csv
      observations_CONTAINS_DATA.csv
      conditions_CONTAINS_DATA.csv
      flags_CONTAINS_DATA.csv
      stamp.json
    resolved_CONTAINS_DATA.csv   checkpoint 4: written by export
    flags_resolved_CONTAINS_DATA.csv
    disagreements_CONTAINS_DATA.csv
    derived_CONTAINS_DATA.csv
    values_long_CONTAINS_DATA.csv
    dataset_wide_CONTAINS_DATA.csv
    dataset_CONTAINS_DATA.xlsx
    status_long_CONTAINS_DATA.csv
    free_text_CONTAINS_DATA.csv
    data_dictionary.csv
    qc_report_CONTAINS_DATA.html
    stamp.json
  review/
    events_<initials>.csv        checkpoint 3: one append-only file per reviewer
  profiles/<name>.toml           optional ablation switches
  runs/<name>/                   the same raw/ and outputs layout for a profile run
  share/                         written only by the export guard
    qc_summary.txt
    variable_summary.csv
    page_summary.csv
    rule_catalogue.csv
```

Every file whose rows hold a value, raw text, free text or a record id carries
`_CONTAINS_DATA`. `pages.csv` holds file hashes and page types only.
`data_dictionary.csv` and the `share/` files hold no values.

**Writing rules (all checkpoints).** CSV, UTF-8 without BOM, `\n` line ends,
written with the `csv` module; read with `utf-8-sig`, falling back to cp1252
with a console note (files re-saved by Excel). Row values are the string
encodings the model already defines (`None` is `""`, floats by `repr`,
booleans `true` / `false`, enums by value, lists space-separated). A file is
written fresh under its own name; when that fails because the file is locked
(open in Excel) it is written as `<name>.<timestamp>.csv` alongside with a
console message. Nothing is ever renamed over an existing file (network
drive).

**Stamps.** Each checkpoint has a JSON stamp with `store_schema_version`,
`code_version`, `written_at`, and the fields of the staleness table
(section 10). A stage reads a checkpoint only when every stamp field matches
what it would write now; otherwise it rebuilds and says so.

## 3. Stored formats

### 3.1 Raw cache (checkpoint 1)

`cache/words/<file_hash>.csv`, one row per word: `page`, `index`, `text`,
`x0`, `x1`, `y0`, `y1` (page-normalised, after rotation and deskew, as the
ingest module already produces them), `source` (`text_layer` or `ocr`),
`confidence` (Tesseract word confidence for OCR words, else empty).
`cache/words/<file_hash>.pages.csv` holds one row per page with the `Page`
columns that ingest knows (`rotation`, `skew`, `ink`, `text_source`,
`word_count`); classify adds `page_type` and `footer_page_number` later in
the store. Stamp fields: file hash, code version, Tesseract version and
`ocr.missing_pages` (OCR words depend on both; a text-layer-only run records
them as empty and `false`).

Page images are not cached (departure 12.1): a page renders in about a tenth of
a second from the PDF, while a 300 dpi PNG per page would put hundreds of
megabytes on the network drive. The review server and the image rules render on
demand through `ingest`.

### 3.2 Second-OCR cache

`cache/second_ocr/<file_hash>.csv`, one row per cell read: `page`, `px_x0`,
`px_y0`, `px_x1`, `px_y1` (whole pixels of the crop at the second-OCR render
resolution, 450 dpi as in the old script), `tesseract_version`, `config`
(the page-segmentation mode and character whitelist, so a changed setting
misses), `reading` (the digits read, `""` when nothing), `confidence` (the
lowest word confidence, 0 to 100, empty when nothing was read). A reading is
reused when every key column matches; a moved bbox re-reads only that cell.
This cache is template-independent, as decided.

### 3.3 Extraction store (checkpoint 2), `outputs/raw/`

| File | Columns | Notes |
| --- | --- | --- |
| `records_CONTAINS_DATA.csv` | `Record.COLUMNS` plus `file_name` | Record ids are participant numbers and file names hold them |
| `pages.csv` | `Page.COLUMNS` | Written at classify |
| `observations_CONTAINS_DATA.csv` | `Observation.COLUMNS` | One row per observation; the key columns are the natural key |
| `conditions_CONTAINS_DATA.csv` | `record_id`, `page`, `key`, `code`, `detail` | The reading conditions (the detail can hold raw text). Kept because the rules read them again at resolve time and the QC report counts `free_text_derived` by parameter |
| `flags_CONTAINS_DATA.csv` | `flag_key`, `record_id`, `rule_id`, `layer`, `severity`, `page`, `keys`, `message`, `suggestion_value`, `suggestion_source` | `keys` is the space-separated string form of the observation keys (a key string holds no spaces); `flag_key` is `rule_id|record_id|keys` and identifies a flag across the raw run and the post-review rerun, whose messages differ when a value changes |
| `stamp.json` | section 10 | |

`checks.Flag` gains `to_row()` / `from_row()` and `flag_key`, the same way the
model types have them. Nothing in `spirotrace.model` changes.

### 3.4 Review events (checkpoint 3), `review/events_<initials>.csv`

Append-only, one file per reviewer, UTF-8, header written when the file is
created, one row appended per answer under a file lock held only for the
append (no instance lock). Columns:

| Column | Meaning |
| --- | --- |
| `schema_version` | 1 |
| `event_id` | 32 hex characters (uuid4) |
| `sequence` | 1, 2, ... within this file; the tie-breaker when two events of one reviewer carry the same time |
| `time` | ISO 8601 with the local offset, `2026-11-02T14:03:11+13:00` |
| `reviewer` | initials, as typed once per session |
| `record_id`, `key` | the record and the key's string form |
| `action` | `typed`, `as_read`, `not_readable`, `empty`, `dash`, `struck`, `exclude`, `withdraw` |
| `value` | the text typed for `typed` (as printed, decimal point or comma) and optionally for `struck`; else `""` |
| `before_raw`, `before_value` | the raw text and the parsed value or text the reviewer saw (the "before" of the audit trail) |
| `note` | free text from the reviewer; required for `exclude` |
| `open_rules` | space-separated rule ids open on the item when answered |
| `elapsed_ms` | milliseconds from the item being shown to Enter (the timing the master prompt asks for) |
| `source` | `app` (an import would write `import` with a fingerprint; not built) |
| `source_fingerprint` | `""` for the app |
| `tool_version`, `template_id`, `template_version` | what read the value |

Keyboard answers in the queue map to actions as follows: a value typed is
`typed` (validated by the token grammar for number parameters; `-` alone is
`dash`); `=` is `as_read`; `na` is `not_readable`; `empty` is `empty`;
`struck` (optionally `struck 2.98`) is `struck`; `x` with a note is `exclude`;
`withdraw` retracts this reviewer's earlier answer. `empty`, `dash`, `exclude`
and `withdraw` go beyond the decided four (value, `=`, `na`, struck) and are
section 13 questions; without them a reviewer cannot say "the cell is empty"
(the evaluation treats empty and unreadable differently) or produce the
`excluded` status that seam 3 defines.

### 3.5 Outputs (checkpoint 4), `outputs/`

| File | One row per | Columns |
| --- | --- | --- |
| `resolved_CONTAINS_DATA.csv` | observation | the key columns and `record_id`; `raw_text`, `parsed_value`, `parsed_text`, `value_state` (as read); `resolved_value`, `resolved_text`, `resolved_value_state`, `resolved_struck`; `status`; `open_severity`; `machine_confirmed_by` (space-separated rule ids of `confirm` flags from the rerun); `last_event_id`; `reviewers` (initials of everyone with an event on the key) |
| `flags_resolved_CONTAINS_DATA.csv` | flag after the post-review rerun, plus every raw flag that cleared | the flag columns plus `resolved_status` of the first flagged value and `change` (`new`, `cleared`, `unchanged`, by `flag_key`) |
| `disagreements_CONTAINS_DATA.csv` | key with reviewers whose latest answers differ | key, record id, one column pair per reviewer (`action`, `value`) |
| `derived_CONTAINS_DATA.csv` | derived value per record | section 5 |
| `values_long_CONTAINS_DATA.csv` | observation | the dataset view of `resolved`: `record_id`, `layout`, `name` (section 7), `value`, `value_state`, `status`, `raw_text`, `read_method`, `page`, `machine_confirmed_by`; blanked by the derive rule like the wide file, with the reason in `status_long` |
| `dataset_wide_CONTAINS_DATA.csv` | record | section 7 |
| `dataset_CONTAINS_DATA.xlsx` | | sheets `Data` (the wide table), `Status` (the long status file), `Dictionary` (the data dictionary), `Derived`; number formats from the printed decimals; no colours or comments, so nothing invites hand editing |
| `status_long_CONTAINS_DATA.csv` | blanked cell of the wide table | `record_id`, `name`, `value_state`, `status`, `open_severity`, `reason` |
| `free_text_CONTAINS_DATA.csv` | free-text observation | `record_id`, `page`, `parameter`, `raw_text`, `parsed_text`, `status`; every parameter with `contains_free_text` goes here and never into the wide table |
| `data_dictionary.csv` | column of the wide table | section 7 |
| `qc_report_CONTAINS_DATA.html` | | section 8 |
| `stamp.json` | | section 10 |

**Statuses** (seam 3, extended by the 14 October disagreement decision):
`accepted_unflagged`, `confirmed`, `corrected`, `unreadable`, `excluded`,
`open_flag` (an error or check flag with no settling event), and
`reviewer_disagreement`. `open_severity` is the highest severity among the
flags still open on the key after the rerun (`error`, `check`, `note`, or
empty). A `note` does not change the status.

## 4. The resolve module

`resolve/` is the only code that combines observations and events. It exposes
two functions and writes nothing itself except through `store`.

`merge_events(review_dir) -> Events`: reads every `events_*.csv`, validates
the schema version, keeps for each (key, reviewer) the latest event by
(`time`, `sequence`), drops the key when that event is `withdraw`, and lists
the keys whose reviewers' latest events differ in action or in parsed value
(`disagreements`). Events whose key does not exist in the store are listed as
orphans in the console counts and in the QC report, never dropped.

`resolve_records(store, events, settings, bridge) -> Resolved`: for each
observation builds the resolved value:

| Latest settling event | resolved value and state | status |
| --- | --- | --- |
| none | as read | `accepted_unflagged`, or `open_flag` when an error or check flag is open after the rerun |
| `as_read` | as read | `confirmed` |
| `typed` | the typed text through the same builder the readers use (number, ratio, category, date), read method `manual`; a text that does not parse is refused at entry, so none reaches here | `corrected` |
| `struck` | the typed text if given else as read; `resolved_struck = true` | `corrected` |
| `dash`, `empty` | that state, no value | `corrected` |
| `not_readable` | `unreadable`, no value | `unreadable` |
| `exclude` | as read, kept for the record | `excluded` |
| reviewers disagree | as read | `reviewer_disagreement` |

Then it reruns the rules: the resolved observations are wrapped as the
`RecordInput` the checks already accept (resolved value in place of the parsed
value; the conditions from the store), `check_records` runs with the same
settings, and the bridge is called once for the whole run. From the rerun it
fills `machine_confirmed_by` (the `confirm` flags on each key), `open_severity`,
and `flags_resolved` with `change` computed by `flag_key` against the raw flags.
The raw flags in `outputs/raw/` are never touched.

The review queue uses the same functions in memory for one record at a time
(section 9); export runs them over the whole store and writes checkpoint 4.

## 5. Derive

`derive/` reads only `Resolved`. An input is usable when its status is not
`unreadable`, `excluded` or `reviewer_disagreement` and its `open_severity` is
not `error`; open checks pass and are recorded. Every derived row carries
`inputs` (space-separated key strings), `input_statuses`, `input_open_severities`
and `status` (`computed`, `not computed: <reason>`, or
`not computed: rspiro absent`).

| Name | Value | Method (ported from the old script unless noted) |
| --- | --- | --- |
| `ratio_below_lln`, `fvc_below_lln`, `fev1_below_lln`, `tlc_below_lln` | `yes` / `no` | printed z below -1.645 when the z is usable, else value below the printed LLN; `basis` column says `z` or `lln` |
| `pattern` | `normal`, `obstruction`, `obstruction, possible mixed`, `possible restriction`, `restriction`, `mixed`, `non-specific` | the ATS/ERS 2022 flowchart on the pre-bronchodilator ratio and FVC, with TLC on the lab layout; `derived.pattern_not_computed` when the inputs are missing |
| `prism` | `yes` / `no` | normal ratio with FEV1 below the LLN |
| `fev1_severity` | `within normal limits`, `mild`, `moderate`, `severe` | FEV1 z bands -1.645, -2.5, -4.0 (ATS/ERS 2022) |
| `bdr_fev1_pct_pred`, `bdr_fvc_pct_pred` | change as % of predicted, 1 decimal | the printed BDR column when it agrees with post minus pre %pred within 1.5 points, else post minus pre %pred; `derived.bdr_column_not_pct_pred` as in the curated list |
| `bdr_positive_2022` | `yes` / `no` | any change >= 10% of predicted; `derived.bdr_exactly_threshold` at exactly 10 |
| `bdr_positive_2005` | `yes` / `no` | >= 12% and >= 200 mL from baseline |
| `report_pattern` | `normal`, `obstructive`, `restrictive`, `mixed`, `nonspecific`, `other` | the interpretation-pattern phrase first; otherwise the three per-test findings combined as the flowchart does (restrictive spirometry with normal volumes is non-specific; restriction needs low volumes), a port of the described 0.3.16 behaviour; otherwise the whole comment text for "within normal limits" / "normal spirometry" |
| `grade_fev1`, `grade_fvc` | the harmonised grade | session-quality line first, else the technical comments; a note when they differ |
| `gli_<param>_<phase>_z`, `_lln`, `_pred`, `_pctpred` | recalculated reference values | new to the port: FEV1, FVC and FEV1/FVC pre and post, and TLCO, KCO and VA on the lab layout, from the resolved value, age, height, sex and ethnic group through the one rspiro bridge under `reference.equations`; point values (the bridge gains a point mode beside its interval mode). Blank with status `not computed: rspiro absent` without Rscript |

The pattern rests on the printed z and LLN, as the old script did, not on the
recalculated values (departure 12.4 explains the choice). The rules
`free_text.report_pattern_vs_computed`, `free_text.bdr_statement_vs_computed`
and the three `derived.*` rules run after derive on the derived rows and are
written to `flags_resolved` with layer `derived` or `free_text`.

## 6. Second OCR and missing-page OCR (A4)

Tesseract is called as a subprocess (`tools.tesseract`, never assumed on
PATH; the Windows install folder is tried when the setting is empty, as the
config already documents). No `pytesseract`: the TSV output gives words,
boxes and confidences. Its version is read once per run from `tesseract
--version` and stamped.

**Second reading.** After read, for every observation of a number parameter in
a table role (`pre`, `post`, `lln`, `post_lln`, `uln`, `predicted`, `pctpred`,
`post_pctpred`, `z`, `post_z`, `bdr`, `pctchg`, `trial`, `post_trial`) with a
bbox and read method `text_layer`, `ocr` or `position_fallback`: the page is
rendered at 450 dpi (once per page, in memory), the cell is cropped with the
old script's margins (an empty cell looks in the column slot to its left), the
crop is binarised with an Otsu threshold and padded, and Tesseract runs with
page-segmentation mode 7 and the digit whitelist `0123456789.-,`. The reading
goes into `second_reading` with `second_reading_run = true`; the rules are
those of the curated list: `ocr.second_reading_agrees` (confirm, exact numeric
equality after the token grammar), `ocr.second_reading_disagrees` (check, note
when confidence is below 50), `ocr.second_reading_suggestion` (check with a
suggestion when the first reading is unreadable or empty), and
`ocr.second_reading_failed` (note, once per record). Header fields, trend rows
and free text are not re-read, as in the old script. With `second_ocr = true`
and no Tesseract the run stops before ingest.

**Missing pages.** With `ocr.missing_pages = true`, a page with no text layer
that is not blank is rendered at 300 dpi and read by Tesseract whole-page (TSV,
default segmentation); words with positive confidence become the page's words
with `text_source = ocr`, and the observations read from them carry read method
`ocr` with the lowest word confidence of the cell. This happens in `ingest`
(the only module that opens PDFs), is cached with the words, and the stamp
carries the Tesseract version and the setting. Without Tesseract the run stops
with the same message.

## 7. Export: dataset, column names, data dictionary

**Wide column names.** One column per (parameter, role, display position) that
occurs in the cohort, named `<parameter>_<role>` with `_<position>` appended
for trial roles (`FEV1_pre`, `FEV1_z`, `FEV1_post_pctpred`, `FEV1_trial_1`,
`FEV1_post_trial_3`, `TLC_measured`, `age_measured`). `trial_number` columns
follow the same rule. Trend values go to `values_long` only (one row per
visit position), not to the wide table. Derived columns take their section 5
names. Fixed first columns: `record_id`, `layout`, `pages`, `n_open_errors`,
`n_open_checks`, `n_corrected`. The old script's column names are not used
anywhere in the package (the private key map stays private).

**Blanking rule.** A cell is blank when the value's status is `unreadable`,
`excluded`, `reviewer_disagreement` or its `open_severity` is `error`, and when
the value state is not `value`; the reason goes to `status_long`. A struck value
is written (the strikethrough is a column in `values_long`). Ratios are
written as fractions with three decimals.

**Data dictionary.** Generated, one row per wide column: `name`, `parameter`,
`column_role`, `display_position`, `kind`, `unit`, `stored_form` (fraction for
ratios), `source` (`extracted` or `derived`), `description` (from the
vocabulary and the derive table), `blank_when` (the rule above), `n_records`,
`n_blank`. A second section lists every rule from the registry: `rule_id`,
`layer`, `severities`, `rationale`, so the methods table of the paper comes
from the same file.

**Free text.** Every parameter marked `contains_free_text` (comments,
interpretation texts and findings, referral reason, medication, consent,
provisional status, testing room, smoking status, bronchodilator given,
salbutamol dose) goes to `free_text_CONTAINS_DATA.csv` only.

## 8. QC report

`qc_report_CONTAINS_DATA.html`, one self-contained page, inline SVG for the
charts, no script library. Sections, each a table or a chart with its counts:

1. Run: files, records by layout, pages by type, files failed, blank pages,
   pages without a text layer, settings hash, code and tool versions.
2. Flags by layer and severity, raw and after review; flags by rule with the
   correction yield among reviewed flags (answered, value changed, kept,
   unreadable), labelled as yield, never accuracy.
3. Review effort: events per reviewer, minutes per reviewer (sum of
   `elapsed_ms`), median seconds per answer, answers per record; open
   disagreements.
4. Completeness per variable (per wide column): applicable, read, confident
   (no open error or check), machine-confirmed, corrected, unreadable; the
   "flagged when marked vs not" rates once the image rule sets `marked` on the
   lab layout.
5. Variable distributions: for every numeric wide column and layout, n, min,
   quartiles, max, and a strip-and-box chart (one dot per record, box for the
   middle half) with values outside 3 x IQR listed by record id. This is the
   browse chart of the old review tool, moved to the report.
6. Derived: pattern, severity, PRISm and BDR counts by layout; computed pattern
   against the report's pattern (agree, near miss, disagree, not computed);
   derived values resting on open checks.
7. Reading: observations by read method and value state; `free_text_derived`
   counts by parameter; second-OCR agreement, disagreement and suggestions.
8. Orphan events and other warnings.

The export guard writes `share/qc_summary.txt` from sections 1, 2, 3, 6 and 7
as counts and rates, `share/variable_summary.csv` from section 4 (counts and
percentages, no values), `share/page_summary.csv` (page types by layout,
counts) and `share/rule_catalogue.csv` (the rule table). The distributions do
not leave `outputs/`.

**Export guard** (`privacy/`). One function writes to `share/`:
`write_shareable(path, header, rows, numeric_columns)`. It refuses a file name
other than the four above, refuses any column named like a value, raw text,
note or record id, allows digits only in the declared numeric columns, and
replaces every other cell token that is not in the shareable vocabulary
(parameter and role names, layer and rule ids, severities, layout ids, value
states, read methods, column headers it was given) with `???`. A test plants a
record id, a date, a name, an ethnic-group word, a never-extract word and a
free-text sentence in every table and asserts none reaches `share/`. Console
output of every command is counts only.

## 9. The review queue (A6)

`spirotrace review` starts a standard-library `ThreadingHTTPServer` bound to
127.0.0.1 on a free port (or `--port`), opens the browser unless
`--no-browser`, and serves one HTML page with inline CSS and JavaScript (no
build step; no vendored library is needed for a queue).

**Items.** The queue is built from `outputs/raw/`: every flag of severity
error or check that names at least one key, one item per (record, key),
carrying every open flag's rule id and message, the suggestion if any, the
observation's raw text and parsed value, and the other cells of the same table
row for context. Items answered by the current reviewer are hidden unless
"show answered" is ticked; answers by other reviewers are shown on the item.
Record-level flags appear as a note on the record's items. Order: errors
before checks, then by record id, page and position on the page. `note` and
`confirm` flags are never queued.

**Snippet.** `GET /snippet?record=..&key=..` renders the page at 300 dpi on
demand (one render at a time, the last few pages kept in memory) and crops
the bbox with a margin of 1.5 times the cell height; `GET /page` gives the
whole page with the value boxed. Both are served as PNG from memory. Requests
are accepted only with a `Host` header of 127.0.0.1 or localhost, as the old
tool did.

**Answers.** The input box takes the keyboard answers of section 3.4; Enter
saves; `Alt+Left` / `Alt+Right` move; `Alt+P` toggles the page. `POST /answer`
validates the action and the value server-side (number parameters through the
token grammar, a ratio in its printed form, a date as a date), refuses an empty
answer, appends the event under the file lock, then reruns the record
(section 4) and returns the updated open flags for the record, so neighbouring
items clear or appear at once. A second submit while one is in flight is ignored
(client state and a server-side per-key lock). The reviewer's initials are asked
once per server session (`--reviewer` skips the prompt).

**Timing.** The page records when an item is shown and sends `elapsed_ms` with
the answer; the server also logs session start and end (counts only) to the
console.

**Rerun scope.** Record rules and, when a bridge is configured, the gli rules
for that record (one Rscript call, about two seconds, shown as "checking");
cohort rules wait for the next full run, as the sequences propose. Resolve's
in-memory result is kept for the session; `spirotrace export` writes the
authoritative `flags_resolved`.

Browse, record view, history and export stay deferred to the v1.0 app.

## 10. Stamps and staleness

| Checkpoint | Stamp fields | Rebuilt when |
| --- | --- | --- |
| `cache/words` | file hash, code version, Tesseract version, `ocr.missing_pages` | any field changes |
| `cache/second_ocr` | per row: page, pixel bbox, Tesseract version, config | a row is missing or differs (that cell only) |
| `outputs/raw` | code version, store schema version, settings hash, reader name, template ids and versions, Tesseract version, `ocr.second_ocr`, `ocr.missing_pages`, the sorted list of file hashes | any field changes; `spirotrace run` always rebuilds and reports when the previous stamp differs |
| `review/` | per file: schema version | never |
| `outputs/` | the raw stamp plus the events files' sizes and last event ids, R and rspiro versions | any field changes |

The code version is the package version plus, when the package runs from a git
checkout, the short commit hash, so a development run is distinguishable.

## 11. CLI and the run

```
spirotrace init <folder>
spirotrace run    [--project DIR] [--profile NAME]
spirotrace export [--project DIR] [--profile NAME]
spirotrace review [--project DIR] [--port N] [--no-browser] [--reviewer XX]
```

`--project` defaults to the current folder. `template` and `eval` stay listed
and keep answering "not implemented yet". Exit codes: 0, 1 when any file
failed or a stage was skipped for a missing tool, 2 for a settings error.

`pipeline.run(settings, reader)` does the sequence of flow 2: load, ingest
with the words cache, classify and read through the reader, second OCR (A4),
image rules (when they exist; `image.checks` stays honoured), the rules with
one bridge call, the cohort pass, the store write, then counts to the console.
One bad file gets `input.file_unreadable` and the run continues. `export`
runs resolve, derive, the post-derive rules, the dataset writers, the QC report
and the guard. `init` is flow 1 as decided (never overwrites; PDFs outside
`reports/` counted; tools reported).

**The reader.** The package has no layout reader of its own until the template
work; the two study layouts are read by the private module. `run` therefore
takes the reader from a new settings key, `templates.reader`, a
`package.module:function` import path whose function has the signature of the
private `read_file(path, settings, used_ids)`; the folders in `templates.dirs`
are put on `sys.path` first. The key is not hashed (the reader's template ids
and versions are stamped instead), so `SCHEMA_VERSION` becomes 2 and the
default-hash test changes with it. An empty value means the packaged reader,
which until then refuses with a message naming the key. This is an ask-first
config change (section 13, question 1); the alternative is a private driver
script that calls `pipeline.run` with the reader, leaving `spirotrace run`
unusable for the study.

## 12. Departures from the rewrite plan and the runtime sequences

1. **Page images are not cached** (plan: "words and page images per file
   hash"). Rendering is cheap and the files are large on a network drive; only
   Tesseract readings are cached. The staleness table loses the images row.
2. **The extraction store lives in `outputs/raw/`**, not in a folder of its own,
   so `.gitignore` stays as it is.
3. **A `store` module and a `pipeline` module** are added to the package layout
   (the plan has the CLI calling the stages directly). They keep the CLI thin
   and give the private driver and the tests one entry point.
4. **Pattern from printed values.** The plan's derive stage says "GLI z,
   ATS/ERS 2022 pattern ..."; here the pattern, PRISm and severity rest on the
   printed, resolved z and LLN as the old script's did (port first), and the
   recalculated GLI values are their own derived columns. Using the
   recalculated z would change every pattern where the report's reference
   equation differs from `reference.equations`, which is a scientific choice to
   make with the equations, not here.
5. **Statuses `open_flag` and `reviewer_disagreement`** are added to the five
   of seam 3, because a flagged, unanswered value is neither accepted nor
   corrected, and the 14 October decision names the disagreement status.
6. **Four keyboard answers beyond value, `=`, `na`, struck** (`empty`, `-`,
   `x`, `withdraw`; section 3.4).
7. **Conditions are stored** (not in the plan's data model), because the rules
   need them at the rerun and the QC report counts them.
8. **The rerun in the queue includes the gli rules** for the answered record
   (the sequences proposed record rules only); cohort rules still wait.
9. **No pytesseract**: Tesseract runs as a subprocess, reading TSV output. No
   new dependency; `numpy` and `PyYAML` are still not needed.
10. **`templates.reader` settings key** (section 11), a config schema change.
11. **Rule catalogue and data dictionary in one generated file**, so the paper's
    methods table and the dataset's dictionary cannot drift apart.
12. **The corrections import is not built** (decided 14 October); the event
    columns `source` and `source_fingerprint` exist so that nothing in the
    format blocks it later.

## 13. Decisions needed (G2)

1. The reader: the `templates.reader` settings key (recommended; one command,
   stamped), or a private driver script calling `pipeline.run`.
2. The extra keyboard answers `empty`, `-` (printed dash), `x` (exclude, note
   required) and `withdraw`: keep all four (recommended), or only the decided
   four with `na` covering empty cells.
3. The extraction store under `outputs/raw/` (recommended) or a new top-level
   folder, which needs a `.gitignore` line.
4. Page images not cached (recommended) or cached at 300 dpi as the plan says.
5. Pattern and severity from the printed z and LLN (recommended, the port) or
   from the recalculated GLI values.
6. The QC report named `qc_report_CONTAINS_DATA.html` because its
   distributions show values; the shareable counts go to `share/qc_summary.txt`.
7. The queue rerun calling rspiro per answer (recommended, about two seconds)
   or record rules only, with gli flags refreshed at export.
8. Wide column naming `<parameter>_<role>[_<position>]` (recommended).
