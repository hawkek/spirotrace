"""The sample manifest, the counts summary and the one call that does everything.

The manifest lists every sampled record with its layout, stratum, coder or
coders, overlap flag, stratum size, number sampled, sampling fraction and
seed. Record ids are participant numbers, so the file is labelled
``_CONTAINS_DATA``. The counts summary holds no record id and is what a
methods section needs: frame size, sampled and fraction per stratum and per
layout, and reports and overlap per coder.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from .allocation import Allocation, allocate_coders, check_frame
from .frame import EvaluateError, SamplingFrame
from .sampling import Sample, SampleDesign, draw_sample
from .workbooks import (
    DEFAULT_INSTRUCTIONS,
    CoreFieldSpec,
    check_core_fields,
    workbook_paths,
    write_coder_workbooks,
)

MANIFEST_NAME = "sample_manifest_CONTAINS_DATA.csv"
COUNTS_NAME = "sample_counts.csv"

MANIFEST_COLUMNS = (
    "record_id",
    "layout",
    "stratum",
    "coders",
    "overlap",
    "stratum_size",
    "sampled_in_stratum",
    "sampling_fraction",
    "seed",
)

COUNT_COLUMNS = (
    "kind",
    "name",
    "frame_size",
    "sampled",
    "sampling_fraction",
    "overlap",
)


@dataclass(frozen=True)
class CountRow:
    """One line of the counts summary; ``frame_size`` and the fraction are blank for coders."""

    kind: str
    name: str
    frame_size: int | None
    sampled: int
    sampling_fraction: float | None
    overlap: int

    def as_row(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "frame_size": "" if self.frame_size is None else str(self.frame_size),
            "sampled": str(self.sampled),
            "sampling_fraction": (
                ""
                if self.sampling_fraction is None
                else f"{self.sampling_fraction:.4f}"
            ),
            "overlap": str(self.overlap),
        }


def _refuse_existing(path: Path) -> None:
    if path.exists():
        raise EvaluateError(f"refusing to overwrite {path.name}")


def write_manifest(allocation: Allocation, sample: Sample, path: Path) -> Path:
    """Write the manifest (UTF-8 with BOM so Excel reads it); never overwrites."""
    _refuse_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for assignment in allocation.assignments:
            record = sample[assignment.record_id]
            writer.writerow(
                {
                    "record_id": record.record_id,
                    "layout": record.layout,
                    "stratum": record.stratum,
                    "coders": " ".join(assignment.coders),
                    "overlap": "true" if assignment.overlap else "false",
                    "stratum_size": str(record.stratum_size),
                    "sampled_in_stratum": str(record.sampled_in_stratum),
                    "sampling_fraction": repr(record.sampling_fraction),
                    "seed": str(sample.seed),
                }
            )
    return path


def count_summary(allocation: Allocation, sample: Sample) -> tuple[CountRow, ...]:
    """Counts per stratum, per layout and per coder, then a total; no record id."""
    overlap_by_stratum = Counter(a.stratum for a in allocation.assignments if a.overlap)
    rows = [
        CountRow(
            "stratum",
            s.stratum,
            s.size,
            s.sampled,
            s.sampling_fraction,
            overlap_by_stratum[s.stratum],
        )
        for s in sample.strata
    ]
    for layout in sample.layouts:
        strata = [s for s in sample.strata if s.layout == layout]
        size = sum(s.size for s in strata)
        sampled = sum(s.sampled for s in strata)
        rows.append(
            CountRow(
                "layout",
                layout,
                size,
                sampled,
                sampled / size,
                sum(overlap_by_stratum[s.stratum] for s in strata),
            )
        )
    for coder in allocation.coders:
        mine = allocation.for_coder(coder)
        rows.append(
            CountRow(
                "coder", coder, None, len(mine), None, sum(a.overlap for a in mine)
            )
        )
    size = sum(s.size for s in sample.strata)
    rows.append(
        CountRow(
            "total",
            "all",
            size,
            len(sample),
            len(sample) / size,
            sum(1 for a in allocation.assignments if a.overlap),
        )
    )
    return tuple(rows)


def format_counts(rows: Collection[CountRow]) -> str:
    """The counts as an aligned text table for the console."""
    header = ("kind", "name", "frame", "sampled", "fraction", "overlap")
    table = [header] + [
        (
            r.kind,
            r.name,
            "" if r.frame_size is None else str(r.frame_size),
            str(r.sampled),
            "" if r.sampling_fraction is None else f"{r.sampling_fraction:.3f}",
            str(r.overlap),
        )
        for r in rows
    ]
    widths = [max(len(line[i]) for line in table) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True))
        for line in table
    )


def write_counts(rows: Collection[CountRow], path: Path) -> Path:
    """Write the counts summary (no record ids); never overwrites."""
    _refuse_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COUNT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_row())
    return path


@dataclass(frozen=True)
class CodingSheets:
    """What one run of the generator produced."""

    sample: Sample
    allocation: Allocation
    workbooks: Mapping[str, Path]
    manifest: Path
    counts: Path
    count_rows: tuple[CountRow, ...]


def generate_coding_sheets(
    frame: SamplingFrame,
    design: SampleDesign,
    exclusions: Mapping[str, Collection[str]],
    core_fields: CoreFieldSpec,
    out_dir: Path,
    instructions: str = DEFAULT_INSTRUCTIONS,
) -> CodingSheets:
    """Draw the sample, allocate coders, write workbooks, manifest and counts; print counts.

    Every check runs before anything is written, and no output file is ever
    overwritten. The console gets counts only.
    """
    check_core_fields(core_fields, frame.layouts)
    check_frame(frame, design, exclusions)
    manifest_path = out_dir / MANIFEST_NAME
    counts_path = out_dir / COUNTS_NAME
    for path in (
        manifest_path,
        counts_path,
        *workbook_paths(out_dir, design.coders).values(),
    ):
        _refuse_existing(path)
    sample = draw_sample(frame, design)
    allocation = allocate_coders(sample, design, exclusions)
    rows = count_summary(allocation, sample)
    workbooks = write_coder_workbooks(
        allocation, core_fields, out_dir, design.seed, instructions
    )
    write_manifest(allocation, sample, manifest_path)
    write_counts(rows, counts_path)
    print(format_counts(rows))
    print(
        f"seed {design.seed}: {len(sample)} reports, {len(workbooks)} workbooks written"
    )
    return CodingSheets(sample, allocation, workbooks, manifest_path, counts_path, rows)
