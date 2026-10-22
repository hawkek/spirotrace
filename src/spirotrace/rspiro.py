"""The one rspiro bridge: GLI reference values recalculated in R.

Used by the gli rules (stage 5) and later by derive (stage 8). Rscript comes
from ``tools.rscript`` in the settings; inputs and outputs travel through
temporary files; nothing is printed. For each subject the equations are
evaluated at the corners of the age and height intervals implied by the
report's rounding, and over the printed value's rounding interval, so the
result is a range the printed value must fall inside.

Equations: GLI-2012 spirometry (FEV1, FVC, FEV1/FVC, with the ethnic group),
GLI global 2022 (race-neutral, to identify a second z column), and GLI 2017
diffusing capacity (TLCO, KCO, VA). Static lung volumes are not recalculated
(rspiro 0.5 has no GLI 2021 equations; decided 22 Oct 2026).
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

SPIROMETRY_PARAMS: tuple[str, ...] = ("FEV1", "FVC", "FEV1FVC")
DIFFUSION_PARAMS: tuple[str, ...] = ("TLCO", "KCO", "VA")
PARAMS: tuple[str, ...] = SPIROMETRY_PARAMS + DIFFUSION_PARAMS
ETHNIC_GROUPS: dict[int, str] = {
    1: "Caucasian",
    2: "African American",
    3: "North East Asian",
    4: "South East Asian",
    5: "Other/mixed",
}

INPUT_COLUMNS: tuple[str, ...] = (
    "id",
    "sex",
    "eth",
    "age_lo",
    "age_hi",
    "ht_lo",
    "ht_hi",
    "alt",
    "si",
    *[c for p in PARAMS for c in (p, f"{p}_h")],
)
RANGE_COLUMNS: tuple[str, ...] = (
    "pred_min",
    "pred_max",
    "lln_min",
    "lln_max",
    "z_min",
    "z_max",
    "zgl_min",
    "zgl_max",
    *[f"zeth{e}_{m}" for e in range(1, 6) for m in ("min", "max")],
)


class RspiroError(RuntimeError):
    """Rscript or rspiro could not produce results."""


@dataclass(frozen=True, slots=True)
class GliSubject:
    """One subject-phase (or one candidate value set) to recalculate.

    ``values`` maps a parameter name (``FEV1``, ``FVC``, ``FEV1FVC`` as a
    fraction, ``TLCO``, ``KCO``, ``VA``) to the printed value and half of its
    last printed digit. ``alt`` asks for every GLI-2012 ethnic group and GLI
    global too (to identify a second z column). ``si`` says the diffusion
    values are in SI units.
    """

    id: str
    sex: int
    ethnicity: int
    age_lo: float
    age_hi: float
    height_lo_cm: float
    height_hi_cm: float
    values: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    alt: bool = False
    si: bool = False

    def row(self) -> dict[str, str]:
        r: dict[str, str] = {
            "id": self.id,
            "sex": str(self.sex),
            "eth": str(self.ethnicity),
            "age_lo": repr(self.age_lo),
            "age_hi": repr(self.age_hi),
            "ht_lo": repr(self.height_lo_cm),
            "ht_hi": repr(self.height_hi_cm),
            "alt": "1" if self.alt else "0",
            "si": "1" if self.si else "0",
        }
        for p in PARAMS:
            v = self.values.get(p)
            r[p] = "" if v is None else repr(v[0])
            r[f"{p}_h"] = "" if v is None else repr(v[1])
        return r


@dataclass(frozen=True, slots=True)
class GliRange:
    """Recalculated ranges for one subject-phase and parameter; None = not computed."""

    pred_min: float | None
    pred_max: float | None
    lln_min: float | None
    lln_max: float | None
    z_min: float | None
    z_max: float | None
    zgl_min: float | None = None
    zgl_max: float | None = None
    zeth: tuple[tuple[float, float] | None, ...] = (None,) * 5
    """GLI-2012 z range for each of the five ethnic groups (index 0 is group 1)."""

    @property
    def has_z(self) -> bool:
        return self.z_min is not None and self.z_max is not None

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> GliRange:
        def f(name: str) -> float | None:
            v = row.get(name, "")
            return None if v in ("", "NA", "NaN") else float(v)

        zeth = []
        for e in range(1, 6):
            lo, hi = f(f"zeth{e}_min"), f(f"zeth{e}_max")
            zeth.append((lo, hi) if lo is not None and hi is not None else None)
        return cls(
            f("pred_min"),
            f("pred_max"),
            f("lln_min"),
            f("lln_max"),
            f("z_min"),
            f("z_max"),
            f("zgl_min"),
            f("zgl_max"),
            tuple(zeth),
        )


GliResults = dict[tuple[str, str], GliRange]
"""(subject id, parameter) -> range."""


def script_path() -> Path:
    """The bundled R script."""
    return Path(str(resources.files("spirotrace").joinpath("rspiro_bridge.R")))


def find_rscript(configured: str) -> str | None:
    """The Rscript to run: the configured path if it exists, else Rscript on PATH."""
    if configured:
        p = Path(configured)
        return str(p) if p.is_file() else None
    return shutil.which("Rscript")


def write_input(subjects: Iterable[GliSubject], path: Path) -> int:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INPUT_COLUMNS)
        w.writeheader()
        n = 0
        for s in subjects:
            w.writerow(s.row())
            n += 1
    return n


def read_output(path: Path) -> GliResults:
    out: GliResults = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[(row["id"], row["param"])] = GliRange.from_row(row)
    return out


@dataclass(frozen=True, slots=True)
class RspiroBridge:
    """Runs the bundled R script with the configured Rscript."""

    rscript: str
    timeout: float = 1800.0

    @classmethod
    def from_settings_path(cls, configured: str) -> RspiroBridge | None:
        """A bridge for the configured Rscript, or None when there is none to run."""
        found = find_rscript(configured)
        return None if found is None else cls(found)

    def version(self) -> str:
        """Rscript's version line (never printed by the bridge itself)."""
        r = subprocess.run(
            [self.rscript, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        return (
            (r.stdout or r.stderr).strip().splitlines()[0]
            if (r.stdout or r.stderr)
            else ""
        )

    def compute(self, subjects: Iterable[GliSubject]) -> GliResults:
        """Recalculate ranges for ``subjects``; raises :class:`RspiroError` on failure."""
        subjects = list(subjects)
        if not subjects:
            return {}
        with tempfile.TemporaryDirectory(prefix="spirotrace-gli-") as tmp:
            fin, fout = Path(tmp) / "gli_input.csv", Path(tmp) / "gli_output.csv"
            write_input(subjects, fin)
            try:
                r = subprocess.run(
                    [self.rscript, str(script_path()), str(fin), str(fout)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RspiroError(f"could not run Rscript: {exc}") from exc
            if r.returncode != 0 or not fout.exists():
                msg = (r.stderr or "").strip().splitlines()
                raise RspiroError(
                    f"Rscript exit {r.returncode}: {msg[-1] if msg else 'no message'}"
                )
            return read_output(fout)
