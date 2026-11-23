"""Golden tests: what the bot imports from fake statement files (tests/fixtures/statements/).

Each fixture has a `<name>.expected.json` next to it with the import adapter's output
(bot/services/importer.py on top of budget_core.parsers; the parsed statements
themselves are pinned in tests/core/test_core_parsers.py).
The test fails on any difference. To accept a change on purpose, rebuild the
goldens and review the diff:

    UPDATE_GOLDENS=1 uv run pytest tests/test_statement_fixtures.py
"""

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from budget_core.household import AccountRoles
from bot.services.importer import parse_bit_csv, parse_isracard, parse_leumi

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "statements"
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"

# Account IDs passed to the parsers. They're arbitrary; the card mapping by
# file name prefix is tested separately (tests/test_importer.py).
CARD_ACCOUNT_ID = 2
BIT_CARD_ACCOUNT_ID = 7
# The bank and transit accounts come from the household data; the goldens use ids 3 and 5.
ROLES = AccountRoles(by_role={"bank": 3, "transit": 5})

CASES: dict[str, Callable[[Path], list[dict[str, Any]]]] = {
    "isracard/1111_06_2026.xlsx": lambda p: parse_isracard(str(p), account_id=CARD_ACCOUNT_ID),
    "isracard/1111_07_2026_with_pending.xlsx": lambda p: parse_isracard(str(p), account_id=CARD_ACCOUNT_ID),
    "leumi/FibiSave0000_06.xls": lambda p: parse_leumi(str(p), ROLES),
    "bit/bit_transactions_2026.csv": lambda p: parse_bit_csv(str(p), account_id=BIT_CARD_ACCOUNT_ID, roles=ROLES),
}


def _jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def value(v: Any) -> Any:
        return v.isoformat() if isinstance(v, datetime) else v

    return [{k: value(v) for k, v in row.items()} for row in rows]


def _golden_path(fixture: Path) -> Path:
    return fixture.with_name(fixture.name + ".expected.json")


@pytest.mark.parametrize("name", sorted(CASES))
def test_parser_output_matches_golden(name: str) -> None:
    fixture = FIXTURES / name
    actual = _jsonable(CASES[name](fixture))
    golden = _golden_path(fixture)

    if UPDATE:
        golden.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    assert golden.exists(), f"missing {golden.name}; run with UPDATE_GOLDENS=1"
    expected = json.loads(golden.read_text(encoding="utf-8"))
    assert actual == expected


def test_every_fixture_file_has_a_case() -> None:
    files = {
        str(p.relative_to(FIXTURES))
        for p in FIXTURES.rglob("*")
        if p.suffix in {".xlsx", ".xls", ".csv"}
    }
    assert files == set(CASES)


def test_current_behaviour_identical_bit_transfers_share_an_external_id() -> None:
    """Two identical Bit transfers on one day get the same ID, so the import keeps only one.

    Known data loss, pinned on purpose; reconciliation moves to dbt in Stage 4.
    """
    rows = parse_bit_csv(str(FIXTURES / "bit/bit_transactions_2026.csv"), account_id=BIT_CARD_ACCOUNT_ID, roles=ROLES)
    same_day = [r for r in rows if r["date"] == datetime(2026, 6, 16)]
    assert len(same_day) == 2
    assert same_day[0]["external_id"] == same_day[1]["external_id"]
