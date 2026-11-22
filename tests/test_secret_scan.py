"""Tests for .github/scripts/secret_scan.sh (gitleaks wrapper for pre-commit and CI).

They run the real gitleaks binary (GITLEAKS_BIN or `gitleaks` on PATH) and are
skipped when it isn't installed. CI installs it before running pytest.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "secret_scan.sh"
GITLEAKS = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")

pytestmark = pytest.mark.skipif(GITLEAKS is None, reason="gitleaks not installed")

# Built at runtime so the token never appears literally in the repo.
FAKE_AWS_KEY = "AKIA" + "QYLPMN5HHHFPZAM2"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, content in files.items():
        (repo / name).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


def _scan(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GITLEAKS_BIN": str(GITLEAKS)}
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=repo, env=env, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    shutil.copy(ROOT / ".gitleaks.toml", tmp_path / ".gitleaks.toml")
    _commit(tmp_path, {})
    return tmp_path


@pytest.fixture
def private_repo(repo: Path) -> Path:
    """The repo with the example private config in place (fake household values)."""
    shutil.copy(ROOT / ".gitleaks.private.example.toml", repo / ".gitleaks.private.toml")
    return repo


def _stage(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    _git(repo, "add", name)


def test_clean_staged_change_passes(repo: Path) -> None:
    _stage(repo, "a.txt", "nothing to see here\n")
    assert _scan(repo, "staged").returncode == 0


def test_staged_token_is_blocked_and_redacted(repo: Path) -> None:
    _stage(repo, "a.txt", f"aws_access_key_id = {FAKE_AWS_KEY}\n")
    result = _scan(repo, "staged")
    assert result.returncode == 1
    assert "aws-access-token" in result.stdout + result.stderr
    assert FAKE_AWS_KEY not in result.stdout + result.stderr


def test_without_private_config_household_values_are_not_checked(repo: Path) -> None:
    _stage(repo, "a.txt", "owner = Alice\n")
    result = _scan(repo, "staged")
    assert result.returncode == 0
    assert "household values are not checked" in result.stderr


def test_private_config_blocks_household_values_and_redacts_them(private_repo: Path) -> None:
    _stage(private_repo, "a.txt", "owner = Alice\n")
    result = _scan(private_repo, "staged")
    assert result.returncode == 1
    assert "household-name" in result.stdout + result.stderr
    assert "Alice" not in result.stdout + result.stderr


def test_private_config_still_applies_the_public_rules(private_repo: Path) -> None:
    _stage(private_repo, "a.txt", f"aws_access_key_id = {FAKE_AWS_KEY}\n")
    assert _scan(private_repo, "staged").returncode == 1


@pytest.mark.parametrize(
    ("content", "found"),
    [
        ("владелец Алиса\n", True),
        ("алисам\n", False),
    ],
)
def test_cyrillic_names_match_as_whole_words(private_repo: Path, content: str, found: bool) -> None:
    _stage(private_repo, "a.txt", content)
    assert _scan(private_repo, "staged").returncode == (1 if found else 0)


@pytest.mark.parametrize(
    ("content", "found"),
    [
        ("charged to card 1111\n", True),
        ("2222 credit\n", True),
        ("amount 1111 on 2026-11-11\n", False),
    ],
)
def test_card_digits_only_match_next_to_card_words(private_repo: Path, content: str, found: bool) -> None:
    _stage(private_repo, "a.txt", content)
    assert _scan(private_repo, "staged").returncode == (1 if found else 0)


def test_range_scans_only_commits_after_base(repo: Path) -> None:
    _commit(repo, {"old.txt": f"key = {FAKE_AWS_KEY}\n"})
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, {"new.txt": "clean\n"})
    assert _scan(repo, "range", base, head).returncode == 0


def test_range_finds_a_token_in_the_range(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, {"new.txt": f"key = {FAKE_AWS_KEY}\n"})
    result = _scan(repo, "range", base, head)
    assert result.returncode == 1
    assert FAKE_AWS_KEY not in result.stdout + result.stderr


@pytest.mark.parametrize("base", ["", "0" * 40, "deadbeef" * 5])
def test_unknown_base_scans_the_head_commit(repo: Path, base: str) -> None:
    _commit(repo, {"old.txt": f"key = {FAKE_AWS_KEY}\n"})
    head = _commit(repo, {"new.txt": "clean\n"})
    assert _scan(repo, "range", base, head).returncode == 0
    leaky_head = _commit(repo, {"newer.txt": f"key = {FAKE_AWS_KEY}\n"})
    assert _scan(repo, "range", base, leaky_head).returncode == 1


def test_missing_gitleaks_is_an_error_not_a_pass(repo: Path) -> None:
    env = {**os.environ, "GITLEAKS_BIN": "/nonexistent/gitleaks"}
    result = subprocess.run(["bash", str(SCRIPT), "staged"], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 2
