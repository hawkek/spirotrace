"""Command line entry point: spirotrace <command>.

``init`` makes a study project folder; ``run`` reads and checks the reports;
``export`` resolves, derives and writes the outputs; ``review`` opens the
local review queue. Console output is counts only. Exit codes: 0, 1 when a
file failed or a stage was skipped for a missing tool, 2 for a settings error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import SCHEMA, SETTINGS_FILE, SettingsError, load_settings
from .ingest import find_tesseract
from .pipeline import (
    CACHE_DIR,
    OUTPUTS_DIR,
    REPORTS_DIR,
    REVIEW_DIR,
    PipelineError,
    export_project,
    pdf_files,
    run_project,
)
from .rspiro import find_rscript

SHARE_DIR = "share"
PROJECT_FOLDERS: tuple[str, ...] = (
    REPORTS_DIR,
    CACHE_DIR,
    REVIEW_DIR,
    OUTPUTS_DIR,
    SHARE_DIR,
)

COMMANDS = {
    "init": "create a study project folder",
    "run": "extract and check all reports in a project",
    "review": "open the local review app",
    "export": "write the dataset, data dictionary and QC report",
    "template": "draft, test or survey a layout template",
    "eval": "evaluate against a manually coded reference sample",
}


def default_settings_text() -> str:
    """A ``spiro.toml`` with every key at its default and its one-line doc."""
    lines = [
        "# spirotrace settings. Every key is optional; these are the defaults.",
        "",
    ]
    table = ""
    for f in SCHEMA:
        if f.table != table:
            table = f.table
            lines += ["", f"[{table}]"]
        lines.append(f"# {f.doc}")
        d = f.default
        if isinstance(d, bool):
            value = "true" if d else "false"
        elif isinstance(d, str):
            value = '"' + d.replace("\\", "\\\\").replace('"', '\\"') + '"'
        else:
            value = "[" + ", ".join(f'"{x}"' for x in d) + "]"
        lines.append(f"{f.name} = {value}")
    return "\n".join(lines) + "\n"


def init_project(folder: Path, say) -> int:
    """Flow 1: folders and a default settings file; never overwrites."""
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for name in PROJECT_FOLDERS:
        p = folder / name
        if not p.is_dir():
            p.mkdir()
            made.append(name)
    settings_path = folder / SETTINGS_FILE
    if settings_path.exists():
        say(f"{SETTINGS_FILE}: kept as it is")
    else:
        settings_path.write_text(default_settings_text(), encoding="utf-8")
        say(f"{SETTINGS_FILE}: written with the defaults")
    say(
        f"folders created: {len(made)}; already present: {len(PROJECT_FOLDERS) - len(made)}"
    )
    outside = len(pdf_files(folder))
    if outside:
        say(
            f"{outside} PDF(s) in the project folder itself: move them into {REPORTS_DIR}/"
        )
    say(f"PDFs in {REPORTS_DIR}/: {len(pdf_files(folder / REPORTS_DIR))}")
    say(
        "Rscript: " + ("found" if find_rscript("") else "not found (set tools.rscript)")
    )
    say(
        "tesseract: "
        + ("found" if find_tesseract("") else "not found (set tools.tesseract)")
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="spirotrace", description=__doc__)
    ap.add_argument("--version", action="version", version=f"spirotrace {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")
    parsers = {
        name: sub.add_parser(name, help=help_) for name, help_ in COMMANDS.items()
    }
    parsers["init"].add_argument("folder", type=Path, help="the study project folder")
    for name in ("run", "export", "review"):
        parsers[name].add_argument(
            "--project",
            type=Path,
            default=Path.cwd(),
            help="project folder (default: here)",
        )
    for name in ("run", "export"):
        parsers[name].add_argument(
            "--profile", default=None, help="ablation profile: profiles/<name>.toml"
        )
    a = ap.parse_args(argv)
    say = print
    if a.command is None:
        ap.print_help()
        return 0
    if a.command == "init":
        return init_project(a.folder, say)
    if a.command in ("run", "export"):
        try:
            settings = load_settings(a.project, a.profile)
        except SettingsError as exc:
            say(str(exc))
            return 2
        try:
            if a.command == "run":
                result = run_project(
                    a.project, settings, profile=a.profile, console=say
                )
                return 1 if result.failed_files or result.check.rules_not_run else 0
            export = export_project(a.project, settings, profile=a.profile, console=say)
            skipped = export.derived.gli_inputs and not export.derived.rspiro_version
            return 1 if skipped else 0
        except PipelineError as exc:
            say(str(exc))
            return 2
    say(f"spirotrace {__version__}: '{a.command}' is not implemented yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
