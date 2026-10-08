"""Command line entry point: spirotrace <command>."""
import argparse
import sys

from . import __version__

COMMANDS = {
    "init": "create a study project folder",
    "run": "extract and check all reports in a project",
    "review": "open the local review app",
    "export": "write the dataset, data dictionary and QC report",
    "template": "draft, test or survey a layout template",
    "eval": "evaluate against a manually coded reference sample",
}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spirotrace", description=__doc__)
    ap.add_argument("--version", action="version", version=f"spirotrace {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")
    for name, help_ in COMMANDS.items():
        sub.add_parser(name, help=help_)
    a = ap.parse_args(argv)
    if a.command is None:
        ap.print_help()
        return 0
    print(f"spirotrace {__version__}: '{a.command}' is not implemented yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
