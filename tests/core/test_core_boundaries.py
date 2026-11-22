"""budget_core is the pure domain layer: no Telegram, no database, no bot code.

Stage 3 reuses it inside a Lambda, so it must not pull in the adapters.
"""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent.parent / "budget_core"
FORBIDDEN = ("bot", "db", "telegram", "psycopg", "psycopg_pool", "alembic", "dotenv")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def test_budget_core_does_not_import_adapters() -> None:
    files = sorted(CORE.rglob("*.py"))
    assert files, "budget_core/ has no modules"
    offenders = {
        str(f.relative_to(CORE)): sorted(m for m in _imported_modules(f) if m.split(".")[0] in FORBIDDEN)
        for f in files
    }
    assert {f: m for f, m in offenders.items() if m} == {}


def test_parsers_take_bytes_not_paths() -> None:
    """Pure functions: the caller does the I/O, so S3 objects and Telegram files work alike."""
    for f in (CORE / "parsers").glob("[!_]*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        parse = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "parse")
        assert [a.arg for a in parse.args.args] == ["data"], f.name
        assert ast.unparse(parse.args.args[0].annotation) == "bytes", f.name
