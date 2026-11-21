"""Tests for .github/scripts/needs_deploy.sh (decides whether CI deploys)."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "needs_deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, before: str, after: str) -> str:
    return subprocess.run(
        ["bash", str(SCRIPT), before, after], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def test_docs_only_change_skips_deploy(repo: Path) -> None:
    base = _commit(repo, {"bot/main.py": "x"})
    head = _commit(repo, {"docs/ROADMAP.md": "a", "README.md": "b", "docs/img/x.png": "c"})
    assert _run(repo, base, head) == "deploy=false"


def test_code_change_deploys(repo: Path) -> None:
    base = _commit(repo, {"bot/main.py": "x"})
    head = _commit(repo, {"docs/ROADMAP.md": "a", "bot/main.py": "y"})
    assert _run(repo, base, head) == "deploy=true"


def test_workflow_change_deploys(repo: Path) -> None:
    base = _commit(repo, {"bot/main.py": "x"})
    head = _commit(repo, {".github/workflows/deploy.yaml": "y"})
    assert _run(repo, base, head) == "deploy=true"


@pytest.mark.parametrize("before", ["", "0" * 40, "deadbeef" * 5])
def test_unknown_base_deploys(repo: Path, before: str) -> None:
    head = _commit(repo, {"docs/a.md": "a"})
    assert _run(repo, before, head) == "deploy=true"


def test_empty_diff_deploys(repo: Path) -> None:
    base = _commit(repo, {"bot/main.py": "x"})
    head = _commit(repo, {})
    assert _run(repo, base, head) == "deploy=true"
