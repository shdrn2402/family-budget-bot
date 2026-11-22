"""
Replays every scenario in tests/fixtures/scenarios/ on a fresh database through the bot's
own functions, then compares the ledger with the scenario's expected rows.

- manual_entry      -> bot.services.expense.save_expense_item (as the bot does for typed entries)
- statement_import  -> prepare_statement_batch + save_transactions_bulk (as the import handler does
                       after parsing; file parsing itself is covered by test_statement_fixtures.py)
- stored_row        -> a plain INSERT, for rows left by older code

Rows are compared as a multiset on the fields listed in tests/scenario_loader.py (ROW_FIELDS),
so row order and database ids don't matter.
"""
from collections import Counter
from datetime import datetime, time
from typing import Any

import psycopg
import pytest
import yaml

from bot.database import get_all_item_aliases, save_transactions_bulk
from bot.services.expense import save_expense_item
from bot.services.statement_batch import prepare_statement_batch
from tests.scenario_loader import Household, Scenario, load_household, load_scenario, normalize_row, scenario_paths

HOUSEHOLD = load_household()


async def _apply_household(db: psycopg.AsyncConnection, household: Household) -> None:
    """Replace the seed's household data with the fake household (accounts keep their fixed ids)."""
    for key, user_id in household.users.items():
        await db.execute("INSERT INTO users (id, name) VALUES (%s, %s)", (user_id, key.title()))
    for account in household.accounts.values():
        owner = household.users.get(account.get("owner")) if account.get("owner") else None
        await db.execute(
            "INSERT INTO accounts (id, name, type, owner_id) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, type = EXCLUDED.type, owner_id = EXCLUDED.owner_id",
            (account["id"], psycopg.types.json.Jsonb({"en": account["name"], "ru": account["name"]}),
             account["type"], owner),
        )
    await db.execute("SELECT setval('accounts_id_seq', (SELECT max(id) FROM accounts))")
    await db.execute("DELETE FROM account_aliases")
    await db.execute("DELETE FROM item_aliases")
    for alias, category in household.merchant_rules.items():
        await db.execute("INSERT INTO item_aliases (name, category_id) VALUES (%s, %s)",
                         (alias, household.categories[category]))
    await db.commit()


def _statement_line(household: Household, line: dict[str, Any]) -> dict[str, Any]:
    """A line in the shape the parsers return."""
    tx = {
        "account_id": household.accounts[line["account"]]["id"],
        "amount": line["amount"],
        "date": datetime.combine(line["date"], time()),
        "external_id": line["external_id"],
        "description": line["description"],
        "source_type": line.get("source_type", "import_xls"),
    }
    if "comment" in line:
        tx["comment"] = line["comment"]
    return tx


async def _run_step(db: psycopg.AsyncConnection, household: Household, kind: str, step: dict[str, Any]) -> None:
    user_id = household.users[step["user"]]

    if kind == "manual_entry":
        item = {
            "item_name": step["item"],
            "amount": step["amount"],
            "account_id": household.accounts[step["account"]]["id"],
            "category_id": household.categories[step["category"]],
            "comment": step.get("comment"),
            "date": step["date"].isoformat(),
        }
        result = await save_expense_item(item, user_id, "en", db, "manual_text")
        await db.commit()
        expect = step.get("expect")
        if expect and expect.startswith("error:"):
            assert result.get("error") == expect.removeprefix("error:"), result
        elif expect:
            assert result.get("status") == expect, result

    elif kind == "statement_import":
        lines = [_statement_line(household, line) for line in step["lines"]]
        batch = prepare_statement_batch(lines, await get_all_item_aliases(db))
        saved = await save_transactions_bulk(user_id, batch, db)
        if "expect_saved" in step:
            assert saved == step["expect_saved"], f"saved {saved} rows"

    elif kind == "stored_row":
        await db.execute(
            "INSERT INTO transactions (user_id, account_id, category_id, amount, description, comment, date, "
            "external_id, source_type, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, household.accounts[step["account"]]["id"],
             household.categories[step["category"]] if step.get("category") else None,
             step["amount"], step["description"], step.get("comment"), step["date"], step["external_id"],
             step.get("source_type", "import_xls"), step.get("status", "confirmed")),
        )
        await db.commit()


async def _ledger(db: psycopg.AsyncConnection, household: Household) -> list[dict[str, Any]]:
    rows = await (await db.execute(
        "SELECT user_id, account_id, category_id, amount, description, comment, date::date AS day, "
        "external_id, source_type, status FROM transactions ORDER BY id"
    )).fetchall()
    return [
        {
            "user": household.user_key(r["user_id"]),
            "account": household.account_key(r["account_id"]),
            "amount": float(r["amount"]),
            "date": r["day"],
            "status": r["status"],
            "source_type": r["source_type"],
            "external_id": r["external_id"],
            "description": r["description"],
            "comment": r["comment"],
            "category": household.category_key(r["category_id"]),
        }
        for r in rows
    ]


def _as_yaml(rows: list[dict[str, Any]]) -> str:
    """The actual rows in the scenario file format, to make a failing diff easy to read."""
    trimmed = [{k: v for k, v in row.items() if v is not None} for row in rows]
    return yaml.safe_dump(trimmed, allow_unicode=True, sort_keys=False, default_flow_style=None, width=200)


@pytest.mark.parametrize("path", scenario_paths(), ids=lambda p: p.stem)
async def test_scenario(db: psycopg.AsyncConnection, path: Any) -> None:
    scenario: Scenario = load_scenario(path, HOUSEHOLD)
    await _apply_household(db, HOUSEHOLD)

    for step in scenario.steps:
        kind, body = next(iter(step.items()))
        await _run_step(db, HOUSEHOLD, kind, body)

    actual = await _ledger(db, HOUSEHOLD)
    assert Counter(map(normalize_row, actual)) == Counter(map(normalize_row, scenario.expected)), (
        f"{scenario.id}: ledger differs from 'expected'. Actual rows:\n{_as_yaml(actual)}"
    )
