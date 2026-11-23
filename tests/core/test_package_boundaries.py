"""Layering between the packages: budget_core (pure) <- db (SQL) <- bot (Telegram adapter).

db/ is reused outside the bot later (ingestion, reporting), so it must not depend on it;
the bot reaches the database only through db/, so no SQL is written in bot/.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SQL = re.compile(r"^\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s", re.IGNORECASE)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_db_does_not_import_the_bot() -> None:
    files = sorted((ROOT / "db").rglob("*.py"))
    assert files, "db/ has no modules"
    offenders = {f.name: sorted(_imports(f) & {"bot", "telegram", "dotenv"}) for f in files}
    assert {f: m for f, m in offenders.items() if m} == {}


def test_bot_has_no_sql() -> None:
    """Queries live in db/. (bot/db_migrate.py only runs Alembic and the seed file.)"""
    offenders = []
    for f in sorted((ROOT / "bot").rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL.match(node.value):
                offenders.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_the_old_database_module_is_gone() -> None:
    assert not (ROOT / "bot" / "database.py").exists()
