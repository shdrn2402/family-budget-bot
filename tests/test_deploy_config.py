from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def _load_yaml(relative_path: str) -> dict[str, Any]:
    with open(PROJECT_ROOT / relative_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _bot_environment() -> list[str]:
    compose = _load_yaml("compose.yaml")
    return compose["services"]["budget_bot"]["environment"]


def test_compose_passes_bot_timezone_to_bot_container() -> None:
    """BOT_TIMEZONE must reach the bot container, otherwise Config falls back to UTC."""
    env_names = [entry.split("=", 1)[0] for entry in _bot_environment()]
    assert "BOT_TIMEZONE" in env_names


def test_compose_bot_timezone_has_household_default() -> None:
    """If the .env value is missing, the container should still use the household timezone."""
    entry = next(e for e in _bot_environment() if e.startswith("BOT_TIMEZONE="))
    assert entry == "BOT_TIMEZONE=${BOT_TIMEZONE:-Asia/Jerusalem}"


def test_image_includes_every_first_party_package() -> None:
    """The Dockerfile copies packages one by one; an image missing one fails at startup, not in CI."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    packages = sorted(
        p.parent.name for p in PROJECT_ROOT.glob("*/__init__.py") if p.parent.name not in {"tests", "migrations"}
    )
    assert {"bot", "budget_core", "db"} <= set(packages)
    missing = [package for package in packages if f"{package}/ ./{package}/" not in dockerfile]
    assert missing == []


def test_restore_script_drops_every_schema_the_migrations_create() -> None:
    """A backup recreates every schema, so a restore must drop them all first (app since 0004, #62)."""
    import re

    migrations = "\n".join(p.read_text(encoding="utf-8") for p in (PROJECT_ROOT / "migrations" / "versions").glob("*.py"))
    created = set(re.findall(r"CREATE SCHEMA (?:IF NOT EXISTS )?(\w+)", migrations)) | {"budget"}
    script = (PROJECT_ROOT / "scripts" / "restore_db.sh").read_text(encoding="utf-8")
    drop_sql = re.search(r"^DROP_SQL='([^']*)'", script, re.M).group(1)
    dropped = set(re.findall(r"DROP SCHEMA IF EXISTS (\w+) CASCADE", drop_sql))
    assert "app" in created
    assert created - dropped == set()
