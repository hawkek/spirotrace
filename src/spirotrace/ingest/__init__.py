"""Read each PDF once: words per page (orientation fixed, deskewed), ink, page images.

Only this package opens PDFs. :func:`load_pdf_cached` is the words cache
(checkpoint 1); page images are rendered on demand, never cached. The second
reading after read is :mod:`spirotrace.ingest.second_ocr`, imported by its
module name (it needs the layouts' reading conditions, which need this package).
"""

from .cache import WORD_COLUMNS, cache_stamp_fields, load_pdf_cached
from .pdf import (
    BLANK_MAX_INK,
    BLANK_MAX_WORDS,
    IngestedFile,
    IngestedPage,
    IngestError,
    file_hash_of,
    ink_fraction,
    load_pdf,
    render_page,
)
from .tesseract import (
    CELL_CONFIG_LABEL,
    TesseractError,
    TesseractLike,
    TesseractTool,
    TsvWord,
    find_tesseract,
    otsu_binarise,
    parse_tsv,
    parse_version,
    tesseract_tool,
)
from .words import BBox, Line, Word, bbox_of, deskew, group_lines

__all__ = [
    "BLANK_MAX_INK",
    "BLANK_MAX_WORDS",
    "CELL_CONFIG_LABEL",
    "WORD_COLUMNS",
    "BBox",
    "IngestError",
    "IngestedFile",
    "IngestedPage",
    "Line",
    "TesseractError",
    "TesseractLike",
    "TesseractTool",
    "TsvWord",
    "Word",
    "bbox_of",
    "cache_stamp_fields",
    "deskew",
    "file_hash_of",
    "find_tesseract",
    "group_lines",
    "ink_fraction",
    "load_pdf",
    "load_pdf_cached",
    "otsu_binarise",
    "parse_tsv",
    "parse_version",
    "render_page",
    "tesseract_tool",
]
