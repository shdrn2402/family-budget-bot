"""
Pins the current behaviour of saving imported statement rows against a real database:
db.transactions.save_statement_rows (no-match path) and latest_date.
Matching against existing rows is covered in test_core_reconciliation.py. Part of issue #11.
"""
from datetime import datetime
from typing import Any

import psycopg
import pytest
from psycopg import pq

from db import accounts, transactions
from tests.integration.conftest import CATEGORY_CASH_WITHDRAWAL, CATEGORY_RESTAURANTS, Household


def statement_line(account_id: int, amount: float, day: datetime, external_id: str, **extra: Any) -> dict[str, Any]:
    """A row as produced by the statement parsers in bot/services/importer.py."""
    line: dict[str, Any] = {
        "account_id": account_id,
        "amount": amount,
        "date": day,
        "external_id": external_id,
        "description": "TEST SHOP",
        "source_type": "import_xls",
    }
    line.update(extra)
    return line


async def _rows(db: psycopg.AsyncConnection) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT user_id, account_id, category_id, amount, description, comment, external_id, "
        "source_type, status FROM transactions ORDER BY id"
    )
    return await cur.fetchall()


async def test_new_rows_are_inserted_as_confirmed(db: psycopg.AsyncConnection, household: Household) -> None:
    lines = [
        statement_line(household.own_card_account, -42.5, datetime(2026, 10, 3), "isracard_1",
                       category_id=CATEGORY_RESTAURANTS),
        statement_line(household.bank_account, 1200.0, datetime(2026, 10, 4), "leumi_1",
                       description="SALARY", comment="october"),
    ]

    inserted = await transactions.save_statement_rows(db, household.other_user_id, lines)

    assert inserted == 2
    assert await _rows(db) == [
        # The card has an owner, so the row belongs to the owner, not to whoever uploaded it.
        {"user_id": household.user_id, "account_id": household.own_card_account,
         "category_id": CATEGORY_RESTAURANTS, "amount": -42.5, "description": "TEST SHOP",
         "comment": None, "external_id": "isracard_1", "source_type": "import_xls", "status": "confirmed"},
        # A shared account has no owner: the uploader is used.
        {"user_id": household.other_user_id, "account_id": household.bank_account,
         "category_id": None, "amount": 1200, "description": "SALARY",
         "comment": "october", "external_id": "leumi_1", "source_type": "import_xls", "status": "confirmed"},
    ]


async def test_status_from_the_parser_is_ignored(db: psycopg.AsyncConnection, household: Household) -> None:
    """Bit parser rows carry status='confirmed'; any value is ignored and 'confirmed' is stored."""
    line = statement_line(household.transit_account, -15, datetime(2026, 10, 3), "bit_1",
                          source_type="import_bit", status="draft")

    await transactions.save_statement_rows(db, household.user_id, [line])

    assert [r["status"] for r in await _rows(db)] == ["confirmed"]


async def test_duplicate_external_ids_are_skipped(db: psycopg.AsyncConnection, household: Household) -> None:
    lines = [
        statement_line(household.own_card_account, -10, datetime(2026, 10, 3), "isracard_1"),
        statement_line(household.own_card_account, -20, datetime(2026, 10, 4), "isracard_2"),
    ]
    assert await transactions.save_statement_rows(db, household.user_id, lines) == 2

    again = lines + [statement_line(household.own_card_account, -30, datetime(2026, 10, 5), "isracard_3")]
    assert await transactions.save_statement_rows(db, household.user_id, again) == 1

    assert [r["external_id"] for r in await _rows(db)] == ["isracard_1", "isracard_2", "isracard_3"]


async def test_transfer_offset_rows_are_kept(db: psycopg.AsyncConnection, household: Household) -> None:
    """
    For a cash withdrawal the document handler appends an offsetting row on the cash account
    with external_id '<id>_offset'. Both rows must be stored.
    """
    withdrawal = statement_line(household.bank_account, -200, datetime(2026, 10, 3), "leumi_7",
                                description="ATM", category_id=CATEGORY_CASH_WITHDRAWAL)
    offset = {**withdrawal, "amount": 200, "account_id": household.cash_account, "external_id": "leumi_7_offset"}

    assert await transactions.save_statement_rows(db, household.user_id, [withdrawal, offset]) == 2

    rows = await _rows(db)
    assert [(r["account_id"], r["amount"], r["external_id"]) for r in rows] == [
        (household.bank_account, -200, "leumi_7"),
        (household.cash_account, 200, "leumi_7_offset"),
    ]


async def test_latest_import_date_per_source(db: psycopg.AsyncConnection, household: Household) -> None:
    assert await transactions.latest_date(db, "import_bit") is None

    await transactions.save_statement_rows(db, household.user_id, [
        statement_line(household.transit_account, -5, datetime(2026, 9, 1), "bit_a", source_type="import_bit"),
        statement_line(household.transit_account, -6, datetime(2026, 9, 20), "bit_b", source_type="import_bit"),
        statement_line(household.own_card_account, -7, datetime(2026, 10, 30), "isracard_c"),
    ])

    latest = await transactions.latest_date(db, "import_bit")
    assert latest is not None and latest.date().isoformat() == "2026-09-20"


async def test_database_errors_are_raised_and_rolled_back(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """
    Fixed in #12: errors used to be returned as "0 inserted", so the import report said
    "duplicates". They now propagate, after rolling back, so nothing from the batch is saved.
    """
    lines = [
        statement_line(household.own_card_account, -10, datetime(2026, 10, 3), "isracard_ok"),
        statement_line(household.own_card_account, -20, datetime(2026, 10, 4), "bad_1", source_type="not_a_source"),
    ]

    with pytest.raises(psycopg.errors.CheckViolation):
        await transactions.save_statement_rows(db, household.user_id, lines)

    assert db.info.transaction_status == pq.TransactionStatus.IDLE
    assert await _rows(db) == []


async def test_uploaders_own_card_account(db: psycopg.AsyncConnection, household: Household) -> None:
    """Used for card-paid lines in Bit exports (#12), instead of a hard-coded account."""
    assert (await accounts.find_owned_card(db, household.user_id))["id"] == household.own_card_account
    assert (await accounts.find_owned_card(db, household.other_user_id))["id"] == household.other_card_account
    assert await accounts.find_owned_card(db, 424242) is None
