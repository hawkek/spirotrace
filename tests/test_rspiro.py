"""The rspiro bridge: input and output formats, the fixed grid, and the live run
when Rscript with rspiro is installed (skipped with the reason otherwise)."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from spirotrace.rspiro import (
    INPUT_COLUMNS,
    GliRange,
    GliSubject,
    RspiroBridge,
    RspiroError,
    find_rscript,
    read_output,
    script_path,
    write_input,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gli"


def grid_subjects() -> list[GliSubject]:
    out = []
    with (FIXTURES / "grid_input.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            values = {
                p: (float(r[p]), float(r[f"{p}_h"]))
                for p in ("FEV1", "FVC", "FEV1FVC", "TLCO", "KCO", "VA")
                if r[p] != ""
            }
            out.append(
                GliSubject(
                    r["id"],
                    int(r["sex"]),
                    int(r["eth"]),
                    float(r["age_lo"]),
                    float(r["age_hi"]),
                    float(r["ht_lo"]),
                    float(r["ht_hi"]),
                    values,
                    alt=r["alt"] == "1",
                    si=r["si"] == "1",
                )
            )
    return out


def test_subject_row_and_input_file_round_trip(tmp_path: Path) -> None:
    s = GliSubject(
        "x|pre", 2, 1, 23.5, 24.999, 172.45, 172.55, {"FEV1": (3.85, 0.005)}, alt=True
    )
    row = s.row()
    assert list(row) == list(INPUT_COLUMNS)
    assert row["FEV1"] == "3.85" and row["FEV1_h"] == "0.005" and row["FVC"] == ""
    assert row["alt"] == "1" and row["si"] == "0"
    n = write_input([s], tmp_path / "in.csv")
    assert n == 1 and (tmp_path / "in.csv").read_text(encoding="utf-8").startswith(
        "id,sex,eth"
    )


def test_output_fixture_parses_into_ranges() -> None:
    res = read_output(FIXTURES / "grid_output.csv")
    assert len(res) == 603
    fvc = res[("example|pre", "FVC")]
    # the device's example report: predicted 4.36 L, LLN 3.49 L, z 0.25 for 4.50 L
    assert fvc.pred_min is not None and abs(fvc.pred_min - 4.36) < 0.006
    assert fvc.lln_min is not None and abs(fvc.lln_min - 3.49) < 0.006
    assert (
        fvc.z_min is not None
        and fvc.z_max is not None
        and fvc.z_min <= 0.25 <= fvc.z_max + 0.01
    )
    assert fvc.zeth[0] == (fvc.z_min, fvc.z_max)  # alt: group 1 is the report's group
    assert fvc.zgl_min is not None
    diff = res[("g021|diffusion", "TLCO")]
    assert diff.has_z and diff.zgl_min is None and diff.zeth == (None,) * 5
    assert GliRange.from_row({"pred_min": "NA", "z_min": ""}).pred_min is None


def test_ranges_widen_with_the_rounding_intervals() -> None:
    res = read_output(FIXTURES / "grid_output.csv")
    for (sid, _p), g in res.items():
        if g.has_z and sid.endswith("|pre"):
            assert g.z_min is not None and g.z_max is not None and g.z_min < g.z_max
            assert (
                g.pred_min is not None
                and g.pred_max is not None
                and g.pred_min <= g.pred_max
            )


def test_find_rscript_prefers_the_configured_path(tmp_path: Path) -> None:
    assert find_rscript(str(tmp_path / "missing")) is None
    exe = tmp_path / "Rscript"
    exe.write_text("", encoding="utf-8")
    assert find_rscript(str(exe)) == str(exe)
    assert script_path().name == "rspiro_bridge.R" and script_path().is_file()


def test_a_failing_rscript_raises(tmp_path: Path) -> None:
    bad = tmp_path / ("bad.cmd" if os.name == "nt" else "bad.sh")
    bad.write_text(
        "exit 7\n" if os.name == "nt" else "#!/bin/sh\nexit 7\n", encoding="utf-8"
    )
    bad.chmod(0o755)
    with pytest.raises(RspiroError):
        RspiroBridge(str(bad)).compute(grid_subjects()[:1])


def _live_bridge() -> RspiroBridge:
    path = os.environ.get("SPIROTRACE_RSCRIPT", "")
    found = find_rscript(path)
    if found is None:
        pytest.skip("Rscript not found (set SPIROTRACE_RSCRIPT to its full path)")
    return RspiroBridge(found)


def test_live_rspiro_reproduces_the_fixed_grid() -> None:
    bridge = _live_bridge()
    try:
        res = bridge.compute(grid_subjects())
    except RspiroError as exc:
        pytest.skip(f"rspiro not usable: {exc}")
    want = read_output(FIXTURES / "grid_output.csv")
    assert set(res) == set(want)
    for k, g in want.items():
        got = res[k]
        for name in (
            "pred_min",
            "pred_max",
            "lln_min",
            "lln_max",
            "z_min",
            "z_max",
            "zgl_min",
            "zgl_max",
        ):
            a, b = getattr(g, name), getattr(got, name)
            assert (a is None) == (b is None), (k, name)
            if a is not None:
                assert abs(a - b) < 1e-6, (k, name)
