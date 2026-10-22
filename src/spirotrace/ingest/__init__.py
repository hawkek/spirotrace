"""Read each PDF once: words per page (orientation fixed, deskewed), ink, page images.

Only this package opens PDFs. The cache planned for later steps is not here
(v0.3.14 had none).
"""

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
    "BBox",
    "IngestError",
    "IngestedFile",
    "IngestedPage",
    "Line",
    "Word",
    "bbox_of",
    "deskew",
    "file_hash_of",
    "group_lines",
    "ink_fraction",
    "load_pdf",
    "render_page",
]
