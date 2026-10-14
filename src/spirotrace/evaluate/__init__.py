"""Reference-standard evaluation.

Implemented: the sampling frame, the stratified draw of the reference sample,
the allocation of sampled reports to coders, the blind coding workbooks and
the sample manifest (:mod:`.frame`, :mod:`.sampling`, :mod:`.allocation`,
:mod:`.workbooks`, :mod:`.manifest`). :func:`generate_coding_sheets` runs
the four steps in order. Still to come: agreement and adjudication,
accuracy, flag sensitivity and silent errors, ablation by check layer.

Inputs are neutral: record ids, layout labels, feature names, coder labels
and a core-field spec built from :class:`~spirotrace.model.Parameter` and
:class:`~spirotrace.model.ColumnRole`. No extracted value enters this
package, so none can reach a coding sheet.
"""

from .allocation import (
    Allocation,
    AllocationError,
    Assignment,
    allocate_coders,
    check_frame,
)
from .frame import EvaluateError, FrameRecord, SamplingFrame
from .manifest import (
    COUNTS_NAME,
    MANIFEST_NAME,
    CodingSheets,
    CountRow,
    count_summary,
    generate_coding_sheets,
    write_manifest,
)
from .sampling import Sample, SampleDesign, SampledRecord, StratumCount, draw_sample
from .workbooks import (
    DEFAULT_INSTRUCTIONS,
    CoreField,
    CoreFieldSpec,
    write_coder_workbooks,
)

__all__ = [
    "COUNTS_NAME",
    "DEFAULT_INSTRUCTIONS",
    "MANIFEST_NAME",
    "Allocation",
    "AllocationError",
    "Assignment",
    "CodingSheets",
    "CoreField",
    "CoreFieldSpec",
    "CountRow",
    "EvaluateError",
    "FrameRecord",
    "Sample",
    "SampleDesign",
    "SampledRecord",
    "SamplingFrame",
    "StratumCount",
    "allocate_coders",
    "check_frame",
    "count_summary",
    "draw_sample",
    "generate_coding_sheets",
    "write_coder_workbooks",
    "write_manifest",
]
