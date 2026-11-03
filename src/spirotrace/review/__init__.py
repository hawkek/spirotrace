"""Local review app (served on 127.0.0.1 only). Every reviewer action is
appended to an event log and the record's rules are rerun at once.

``resolve`` does the combining of observations and events; this package only
builds the queue, serves the page and writes events. Nothing imports it.
"""

from .answers import Answer, AnswerError, parse_answer
from .queue import (
    QueueItem,
    build_queue,
    core_fields_of,
    is_gli_input,
    raw_open_flags,
    record_sort_key,
    shown_value,
)
from .server import ReviewError, ReviewServer, ReviewService, serve_review

__all__ = [
    "Answer",
    "AnswerError",
    "QueueItem",
    "ReviewError",
    "ReviewServer",
    "ReviewService",
    "build_queue",
    "core_fields_of",
    "is_gli_input",
    "parse_answer",
    "raw_open_flags",
    "record_sort_key",
    "serve_review",
    "shown_value",
]
