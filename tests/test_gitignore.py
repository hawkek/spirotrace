"""The committed .gitignore keeps study data out and leaves source tracked."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

MUST_IGNORE = [
    "reports/a.pdf",
    "cache/x",
    "review/events_KH.csv",
    "outputs/values_long.csv",
    "runs/r/x",
    "share/s.csv",
    "spiro.toml",
    "x_CONTAINS_DATA.csv",
    "CLAUDE.local.md",
    "docs_local/x.md",
    "private/t.yaml",
]

MUST_NOT_IGNORE = [
    "src/spirotrace/cli.py",
    "tests/test_skeleton.py",
    "tests/fixtures/synthetic/a.pdf",
    "docs/analysis-plan.md",
]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


@pytest.fixture
def planted_repo(tmp_path: Path) -> Path:
    """Return a fresh git repo holding our .gitignore and every planted file."""
    shutil.copyfile(REPO_ROOT / ".gitignore", tmp_path / ".gitignore")
    for rel in MUST_IGNORE + MUST_NOT_IGNORE:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def ignore_match(repo: Path, rel: str) -> tuple[str, str] | None:
    """Return the ``(source, pattern)`` that ignores ``rel``, or None if not ignored.

    ``git check-ignore -v`` also reports paths matched by a "!" re-include
    and exits 0 for them, so a negated pattern counts as not ignored.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-v", rel],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    if result.returncode == 1:
        return None
    # -v output is "<source>:<line>:<pattern>\t<path>".
    info = result.stdout.split("\t", 1)[0]
    source, _, pattern = info.split(":", 2)
    if pattern.startswith("!"):
        return None
    return source, pattern


@pytest.mark.parametrize("rel", MUST_IGNORE)
def test_data_path_is_ignored(planted_repo: Path, rel: str) -> None:
    match = ignore_match(planted_repo, rel)
    assert match is not None, f"{rel} is not ignored"
    assert match[0] == ".gitignore", f"{rel} matched by {match[0]}, not .gitignore"


@pytest.mark.parametrize("rel", MUST_NOT_IGNORE)
def test_source_path_is_not_ignored(planted_repo: Path, rel: str) -> None:
    match = ignore_match(planted_repo, rel)
    assert match is None, f"{rel} is ignored by {match}"
