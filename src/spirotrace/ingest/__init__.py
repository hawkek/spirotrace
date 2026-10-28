"""Read each PDF once: words per page (orientation fixed, deskewed), ink, page images.

Only this package opens PDFs. :func:`load_pdf_cached` is the words cache
(checkpoint 1); page images are rendered on demand, never cached.
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
from .words import BBox, Line, Word, bbox_of, deskew, group_lines

__all__ = [
    "BLANK_MAX_INK",
    "BLANK_MAX_WORDS",
    "WORD_COLUMNS",
    "BBox",
    "IngestError",
    "IngestedFile",
    "IngestedPage",
    "Line",
    "Word",
    "bbox_of",
    "cache_stamp_fields",
    "deskew",
    "file_hash_of",
    "group_lines",
    "ink_fraction",
    "load_pdf",
    "load_pdf_cached",
    "render_page",
]
