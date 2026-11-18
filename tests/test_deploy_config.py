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
