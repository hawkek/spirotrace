"""Reference-standard evaluation.

Implemented: the sampling frame and the stratified draw of the reference
sample (:mod:`.frame`, :mod:`.sampling`). Still to come: coder allocation,
coding workbooks, agreement and adjudication, accuracy, flag sensitivity and
silent errors, ablation by check layer.
"""

from .frame import EvaluateError, FrameRecord, SamplingFrame
from .sampling import Sample, SampleDesign, SampledRecord, StratumCount, draw_sample

__all__ = [
    "EvaluateError",
    "FrameRecord",
    "Sample",
    "SampleDesign",
    "SampledRecord",
    "SamplingFrame",
    "StratumCount",
    "draw_sample",
]
