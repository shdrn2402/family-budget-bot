"""
Reconciliation checks that are not about the final ledger, so they don't fit the scenario
dataset. The ledger outcomes of save_transactions_bulk (bot/database.py) are described as
data in tests/fixtures/scenarios/ and replayed by tests/integration/test_scenarios.py.

Matching rule: same account, same amount, date within ±3 days, and the existing row is
either pending or from the "other" import source (Bit <-> card/bank statement). One exception
(#17): a pending entry on a transit account ("paid with Bit") may be confirmed by a Bit line on
any account. Among candidates: same account first, then the closest date, then the oldest row.
"""
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import pq

from bot.database import save_transactions_bulk
from bot.services.expense import save_expense_item
from tests.integration.conftest import CATEGORY_RESTAURANTS, Household
from tests.integration.test_core_import import statement_line

DAY = date(2026, 10, 10)


def _at(day: date, plus_days: int = 0) -> datetime:
    return datetime.combine(day + timedelta(days=plus_days), datetime.min.time())


async def _pending_manual_entry(
    db: psycopg.AsyncConnection, household: Household, *, account_id: int, amount: float = 50,
    comment: str | None = None, day: date = DAY,
) -> int:
    item = {"item_name": "lunch", "amount": amount, "account_id": account_id,
            "category_id": CATEGORY_RESTAURANTS, "comment": comment, "date": day.isoformat()}
    result = await save_expense_item(item, household.user_id, "en", db, "manual_text")
    await db.commit()
    assert result["status"] == "pending"
    return result["id"]


async def _rows(db: psycopg.AsyncConnection) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT id, user_id, account_id, category_id, amount, description, comment, date::date AS day, "
        "external_id, source_type, status FROM transactions ORDER BY id"
    )
    return await cur.fetchall()


async def _existing_card_line(db: psycopg.AsyncConnection, household: Household) -> None:
    assert await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -80, _at(DAY), "isracard_bit", description="BIT TRANSFER"),
    ], db) == 1


async def _existing_bit_line(db: psycopg.AsyncConnection, household: Household) -> None:
    assert await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -80, _at(DAY), "bit_existing", source_type="import_bit",
                       description="Transfer", comment="Alice"),
    ], db) == 1


async def _existing_pending_entry(db: psycopg.AsyncConnection, household: Household) -> None:
    await _pending_manual_entry(db, household, account_id=household.transit_account, amount=80)


def _bit_line(household: Household) -> dict[str, Any]:
    """A Bit payment made with the user's card (the parser puts it on that card's account)."""
    return statement_line(household.own_card_account, -80, _at(DAY, 1), "bit_new", source_type="import_bit",
                          description="Transfer", comment="Alice")


def _card_line(household: Household) -> dict[str, Any]:
    return statement_line(household.own_card_account, -80, _at(DAY), "isracard_new", description="BIT TRANSFER")


async def test_oldest_row_wins_among_equally_close_candidates(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    older = await _pending_manual_entry(db, household, account_id=household.own_card_account)
    await _pending_manual_entry(db, household, account_id=household.own_card_account)
    # Make the newer row come first in the heap, so an unordered scan would pick it.
    await db.execute("UPDATE transactions SET comment = 'touched' WHERE id = %s", (older,))
    await db.commit()

    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -50, _at(DAY), "isracard_oldest"),
    ], db)

    rows = await _rows(db)
    assert [(r["id"] == older, r["status"]) for r in rows] == [(True, "confirmed"), (False, "pending")]


@pytest.mark.parametrize(
    ("existing", "incoming"),
    [
        (_existing_card_line, _bit_line),       # Bit export after the card statement
        (_existing_bit_line, _card_line),       # card statement after the Bit export
        (_existing_pending_entry, _bit_line),   # Bit export matching a pending manual entry
    ],
    ids=["bit-after-card", "card-after-bit", "bit-after-pending"],
)
async def test_a_bit_match_merges_and_the_rest_of_the_batch_is_saved(
    db: psycopg.AsyncConnection, household: Household, existing: Any, incoming: Any
) -> None:
    """Regression for #12: a Bit match used to abort the whole batch (unescaped '%' in the SQL)."""
    await existing(db, household)
    unrelated = statement_line(household.bank_account, -999, _at(DAY, 20), "unrelated_line")

    assert await save_transactions_bulk(household.user_id, [incoming(household), unrelated], db) == 2

    assert db.info.transaction_status == pq.TransactionStatus.IDLE  # committed, no open transaction
    rows = await _rows(db)
    assert len(rows) == 2  # merged into the existing row, plus the unrelated line
    assert rows[1]["external_id"] == "unrelated_line"
