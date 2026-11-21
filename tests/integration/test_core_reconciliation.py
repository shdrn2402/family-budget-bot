"""
Pins the current reconciliation behaviour of save_transactions_bulk (bot/database.py):
how imported statement rows are matched with existing rows (pending manual entries,
Bit rows, card rows). Part of issue #11.

Matching rule: same account, same amount, date within ±3 days, and the existing row is
either pending or from the "other" import source (Bit <-> card/bank statement). One exception
(#17): a pending entry on a transit account ("paid with Bit") may be confirmed by a Bit line on
any account. Among candidates: same account first, then the closest date, then the oldest row.

Tests named test_current_behaviour_... record known problems on purpose.
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


# --- Pending manual entry + statement line --------------------------------------------

async def test_statement_line_confirms_a_pending_manual_entry(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    pending_id = await _pending_manual_entry(db, household, account_id=household.own_card_account)
    line = statement_line(household.own_card_account, -50, _at(DAY, 1), "isracard_77", description="RESTAURANT XYZ")

    assert await save_transactions_bulk(household.user_id, [line], db) == 1

    [row] = await _rows(db)
    assert row == {
        "id": pending_id,
        "user_id": household.user_id,
        "account_id": household.own_card_account,
        "category_id": CATEGORY_RESTAURANTS,      # the manual category is kept
        "amount": -50,
        "description": "RESTAURANT XYZ",          # the statement text replaces the description
        "comment": "lunch",                       # the original text moves to the comment
        "day": DAY + timedelta(days=1),           # the statement date wins
        "external_id": "isracard_77",
        "source_type": "import_xls",
        "status": "confirmed",
    }


async def test_manual_comment_is_kept_after_the_original_text(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    await _pending_manual_entry(db, household, account_id=household.own_card_account, comment="with friends")
    line = statement_line(household.own_card_account, -50, _at(DAY), "isracard_78")

    await save_transactions_bulk(household.user_id, [line], db)

    [row] = await _rows(db)
    assert row["comment"] == "lunch, with friends"


async def test_match_window_is_three_days(db: psycopg.AsyncConnection, household: Household) -> None:
    await _pending_manual_entry(db, household, account_id=household.own_card_account)

    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -50, _at(DAY, 3), "isracard_in_window"),
    ], db)

    [row] = await _rows(db)
    assert (row["external_id"], row["status"]) == ("isracard_in_window", "confirmed")


async def test_no_match_outside_the_window(db: psycopg.AsyncConnection, household: Household) -> None:
    await _pending_manual_entry(db, household, account_id=household.own_card_account)

    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -50, _at(DAY, 4), "isracard_too_late"),
        statement_line(household.own_card_account, -50, _at(DAY, -4), "isracard_too_early"),
    ], db)

    rows = await _rows(db)
    assert [(r["external_id"], r["status"]) for r in rows] == [
        (None, "pending"),
        ("isracard_too_late", "confirmed"),
        ("isracard_too_early", "confirmed"),
    ]


async def test_no_match_for_a_different_amount(db: psycopg.AsyncConnection, household: Household) -> None:
    await _pending_manual_entry(db, household, account_id=household.own_card_account, amount=50)

    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -50.01, _at(DAY), "isracard_other_amount"),
    ], db)

    assert len(await _rows(db)) == 2


async def test_statement_line_on_another_card_does_not_confirm_a_pending_entry(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """#17: the account is part of the match, so another family member's card line is its own row."""
    pending_id = await _pending_manual_entry(db, household, account_id=household.own_card_account)

    await save_transactions_bulk(household.other_user_id, [
        statement_line(household.other_card_account, -50, _at(DAY), "isracard_other_card"),
    ], db)

    rows = await _rows(db)
    assert [(r["id"] == pending_id, r["account_id"], r["user_id"], r["status"]) for r in rows] == [
        (True, household.own_card_account, household.user_id, "pending"),
        (False, household.other_card_account, household.other_user_id, "confirmed"),
    ]


async def test_card_statement_line_does_not_confirm_a_pending_transit_entry(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """Only a Bit line may confirm a pending "paid with Bit" entry from another account."""
    await _pending_manual_entry(db, household, account_id=household.transit_account, amount=80)

    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -80, _at(DAY), "isracard_card_line"),
    ], db)

    rows = await _rows(db)
    assert [(r["account_id"], r["status"]) for r in rows] == [
        (household.transit_account, "pending"),
        (household.own_card_account, "confirmed"),
    ]


async def test_closest_date_wins_among_candidates(db: psycopg.AsyncConnection, household: Household) -> None:
    await _pending_manual_entry(db, household, account_id=household.own_card_account, day=DAY)
    closer = await _pending_manual_entry(db, household, account_id=household.own_card_account,
                                         day=DAY + timedelta(days=2))

    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -50, _at(DAY, 3), "isracard_closest"),
    ], db)

    rows = await _rows(db)
    assert [(r["id"] == closer, r["status"]) for r in rows] == [(False, "pending"), (True, "confirmed")]


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


# --- Bit rows <-> card/bank statement rows --------------------------------------------

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


async def test_bit_line_enriches_an_existing_card_line(db: psycopg.AsyncConnection, household: Household) -> None:
    """Card statement first, Bit export second: the card row keeps its id and gains the counterparty."""
    await _existing_card_line(db, household)

    assert await save_transactions_bulk(household.user_id, [_bit_line(household)], db) == 1

    [row] = await _rows(db)
    assert (row["external_id"], row["source_type"], row["account_id"], row["comment"]) == (
        "isracard_bit", "import_xls", household.own_card_account, "Alice"
    )


async def test_card_line_takes_over_an_existing_bit_line(db: psycopg.AsyncConnection, household: Household) -> None:
    """Bit export first, card statement second: the card statement's id becomes authoritative."""
    await _existing_bit_line(db, household)

    assert await save_transactions_bulk(household.user_id, [_card_line(household)], db) == 1

    [row] = await _rows(db)
    assert (row["external_id"], row["source_type"], row["description"], row["comment"]) == (
        "isracard_new", "import_xls", "Transfer", "Alice, BIT TRANSFER"
    )


async def test_bit_line_confirms_a_pending_manual_entry(db: psycopg.AsyncConnection, household: Household) -> None:
    """
    Decided in #12: a Bit row confirms a matching pending manual entry, like statement lines do,
    and the counterparty is kept in the comment next to the original text. #17: a "paid with Bit"
    entry on the transit account moves to the account that actually paid.
    """
    pending_id = await _pending_manual_entry(db, household, account_id=household.transit_account, amount=80)

    assert await save_transactions_bulk(household.user_id, [_bit_line(household)], db) == 1

    [row] = await _rows(db)
    assert {k: row[k] for k in ("id", "account_id", "status", "external_id", "source_type", "description",
                                "comment")} == {
        "id": pending_id,
        "account_id": household.own_card_account,
        "status": "confirmed",
        "external_id": "bit_new",
        "source_type": "import_bit",
        "description": "Transfer",
        "comment": "lunch, Alice",
    }


async def test_card_line_later_takes_over_a_bit_confirmed_entry(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """Manual entry, then the Bit export, then the card statement: still one row, card id wins."""
    await _pending_manual_entry(db, household, account_id=household.transit_account, amount=80)
    await save_transactions_bulk(household.user_id, [_bit_line(household)], db)

    assert await save_transactions_bulk(household.user_id, [_card_line(household)], db) == 1

    [row] = await _rows(db)
    assert (row["status"], row["external_id"], row["source_type"]) == ("confirmed", "isracard_new", "import_xls")


async def test_reimporting_a_merged_bit_line_counts_as_a_duplicate(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    await _existing_card_line(db, household)
    assert await save_transactions_bulk(household.user_id, [_bit_line(household)], db) == 1

    assert await save_transactions_bulk(household.user_id, [_bit_line(household)], db) == 0

    [row] = await _rows(db)
    assert row["comment"] == "Alice"


async def test_names_with_wildcard_characters_are_compared_literally(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """'A_ice' is a different name from 'Alice', although LIKE '%A_ice%' would match it."""
    await save_transactions_bulk(household.user_id, [
        statement_line(household.own_card_account, -80, _at(DAY), "isracard_wild", comment="Alice"),
    ], db)
    bit_line = {**_bit_line(household), "comment": "A_ice"}

    assert await save_transactions_bulk(household.user_id, [bit_line], db) == 1

    [row] = await _rows(db)
    assert row["comment"] == "Alice, A_ice"


# --- Re-uploads over rows left unmerged by the old code (#15) --------------------------

async def _store_directly(db: psycopg.AsyncConnection, household: Household, line: dict[str, Any]) -> None:
    """Insert a row as-is, without reconciliation, like the old code left Bit/statement pairs."""
    await db.execute(
        "INSERT INTO transactions (user_id, account_id, amount, description, comment, date, external_id, "
        "source_type, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')",
        (household.user_id, line["account_id"], line["amount"], line["description"], line.get("comment"),
         line["date"], line["external_id"], line["source_type"]),
    )
    await db.commit()


def _bank_line(household: Household) -> dict[str, Any]:
    return statement_line(household.bank_account, 310, _at(DAY), "leumi_310", description="INCOMING TRANSFER")


def _unrelated_bit_credit(household: Household) -> dict[str, Any]:
    """A Bit balance credit with the same amount and date, on another account (transit)."""
    return statement_line(household.transit_account, 310, _at(DAY), "bit_credit_310", source_type="import_bit",
                          description="Transfer", comment="Bob")


def _stored_card_line(household: Household) -> dict[str, Any]:
    return statement_line(household.own_card_account, -300, _at(DAY), "isracard_300", description="BIT TRANSFER")


def _stored_bit_card_line(household: Household) -> dict[str, Any]:
    return statement_line(household.own_card_account, -300, _at(DAY), "bit_card_300", source_type="import_bit",
                          description="Transfer", comment="Alice")


@pytest.mark.parametrize(
    ("stored", "reuploaded"),
    [
        # Production case: a bank line plus an unrelated Bit credit; the bank statement is re-uploaded.
        ((_bank_line, _unrelated_bit_credit), _bank_line),
        # A card line plus its Bit twin, both stored; the card statement is re-uploaded.
        ((_stored_card_line, _stored_bit_card_line), _stored_card_line),
        # The same pair; the Bit export is re-uploaded.
        ((_stored_card_line, _stored_bit_card_line), _stored_bit_card_line),
    ],
    ids=["bank-statement-again", "card-statement-again", "bit-export-again"],
)
async def test_reuploading_an_already_stored_line_is_a_duplicate(
    db: psycopg.AsyncConnection, household: Household, stored: Any, reuploaded: Any
) -> None:
    """
    #15: a line whose external_id is already stored must be skipped before any matching.
    It used to match the other stored row and try to take over its id (unique violation),
    which failed the whole batch.
    """
    for make_line in stored:
        await _store_directly(db, household, make_line(household))
    before = await _rows(db)
    unrelated = statement_line(household.bank_account, -999, _at(DAY, 20), "unrelated_line")

    assert await save_transactions_bulk(household.user_id, [reuploaded(household), unrelated], db) == 1

    rows = await _rows(db)
    assert rows[:-1] == before                     # the stored rows are untouched
    assert rows[-1]["external_id"] == "unrelated_line"


# --- Lines on different accounts are never merged (#17) -------------------------------

async def test_same_account_pending_entry_is_preferred_over_a_transit_one(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    await _pending_manual_entry(db, household, account_id=household.transit_account, amount=80)
    on_card = await _pending_manual_entry(db, household, account_id=household.own_card_account, amount=80)

    await save_transactions_bulk(household.user_id, [_bit_line(household)], db)

    rows = await _rows(db)
    assert [(r["id"] == on_card, r["account_id"], r["status"]) for r in rows] == [
        (False, household.transit_account, "pending"),
        (True, household.own_card_account, "confirmed"),
    ]


async def test_bit_balance_line_does_not_confirm_a_pending_card_entry(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    await _pending_manual_entry(db, household, account_id=household.own_card_account, amount=80)
    from_balance = {**_bit_line(household), "account_id": household.transit_account}

    await save_transactions_bulk(household.user_id, [from_balance], db)

    rows = await _rows(db)
    assert [(r["account_id"], r["status"], r["source_type"]) for r in rows] == [
        (household.own_card_account, "pending", "manual_text"),
        (household.transit_account, "confirmed", "import_bit"),
    ]


async def test_bank_line_does_not_take_over_a_bit_balance_row(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """A Bit balance credit and a bank credit of the same amount are two events: both are kept."""
    await save_transactions_bulk(household.user_id, [
        statement_line(household.transit_account, 310, _at(DAY), "bit_balance_credit", source_type="import_bit",
                       description="Transfer", comment="Alice"),
    ], db)

    await save_transactions_bulk(household.user_id, [
        statement_line(household.bank_account, 310, _at(DAY, 1), "leumi_credit"),
    ], db)

    rows = await _rows(db)
    assert [(r["account_id"], r["external_id"], r["source_type"]) for r in rows] == [
        (household.transit_account, "bit_balance_credit", "import_bit"),
        (household.bank_account, "leumi_credit", "import_xls"),
    ]


async def test_bit_card_line_does_not_enrich_a_bank_row(db: psycopg.AsyncConnection, household: Household) -> None:
    await save_transactions_bulk(household.user_id, [
        statement_line(household.bank_account, -80, _at(DAY), "leumi_debit"),
    ], db)

    assert await save_transactions_bulk(household.user_id, [_bit_line(household)], db) == 1

    rows = await _rows(db)
    assert [(r["account_id"], r["external_id"], r["comment"]) for r in rows] == [
        (household.bank_account, "leumi_debit", None),
        (household.own_card_account, "bit_new", "Alice"),
    ]


async def test_cash_offset_is_not_taken_over_by_a_transit_bit_row(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    await save_transactions_bulk(household.user_id, [
        statement_line(household.transit_account, 200, _at(DAY), "bit_balance_200", source_type="import_bit"),
    ], db)

    await save_transactions_bulk(household.user_id, [
        statement_line(household.cash_account, 200, _at(DAY), "leumi_atm_offset"),
    ], db)

    rows = await _rows(db)
    assert [(r["account_id"], r["external_id"]) for r in rows] == [
        (household.transit_account, "bit_balance_200"),
        (household.cash_account, "leumi_atm_offset"),
    ]
