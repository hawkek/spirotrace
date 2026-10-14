"""Reference-standard evaluation.

Implemented: the sampling frame, the stratified draw of the reference sample
and the allocation of sampled reports to coders (:mod:`.frame`,
:mod:`.sampling`, :mod:`.allocation`). Still to come: coding workbooks,
agreement and adjudication, accuracy, flag sensitivity and silent errors,
ablation by check layer.
"""

from .allocation import (
    Allocation,
    AllocationError,
    Assignment,
    allocate_coders,
    check_frame,
)
from .frame import EvaluateError, FrameRecord, SamplingFrame
from .sampling import Sample, SampleDesign, SampledRecord, StratumCount, draw_sample

__all__ = [
    "Allocation",
    "AllocationError",
    "Assignment",
    "EvaluateError",
    "FrameRecord",
    "Sample",
    "SampleDesign",
    "SampledRecord",
    "SamplingFrame",
    "StratumCount",
    "allocate_coders",
    "check_frame",
    "draw_sample",
]
