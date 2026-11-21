"""
Pins the current behaviour of manual text entry (the fast parser; the LLM fallback was
removed in #20) against a real database: bot/services/expense.py. Part of issue #11.

Tests named test_current_behaviour_... record known problems on purpose. A fix should
update them deliberately.
"""
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from bot.services.expense import (
    get_local_date,
    parse_expense_message,
    process_expense_text,
    save_expense_item,
)
from tests.integration.conftest import (
    CATEGORY_INTERNAL_TRANSFER,
    CATEGORY_OTHER_INCOME,
    CATEGORY_RESTAURANTS,
    CATEGORY_SALARY,
    Household,
)


async def _transaction(db: psycopg.AsyncConnection, transaction_id: int) -> dict[str, Any]:
    row = await (await db.execute(
        "SELECT user_id, account_id, category_id, amount, description, comment, date::date AS day, "
        "source_type, status FROM transactions WHERE id = %s",
        (transaction_id,),
    )).fetchone()
    assert row is not None
    return row


# --- Parsing ---------------------------------------------------------------------------

async def test_item_account_amount_with_aliases(db: psycopg.AsyncConnection, household: Household) -> None:
    [item] = await process_expense_text("testcoffee testcash 25", household.user_id, db)

    assert item["item_name"] == "testcoffee"
    assert item["amount"] == 25.0
    assert item["account_id"] == household.cash_account
    assert item["category_id"] == CATEGORY_RESTAURANTS
    assert item["comment"] is None
    assert item["date"] is None


async def test_generic_card_word_resolves_to_the_users_own_card(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    [mine] = await process_expense_text("testcoffee card 10", household.user_id, db)
    [theirs] = await process_expense_text("testcoffee карта 10", household.other_user_id, db)

    assert mine["account_id"] == household.own_card_account
    assert theirs["account_id"] == household.other_card_account


async def test_multi_word_item_trailing_comment_and_currency_words(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    [item] = await process_expense_text("big lunch testcash 120 with friends шекелей", household.user_id, db)

    assert item["item_name"] == "big lunch"
    assert item["amount"] == 120.0
    assert item["account_id"] == household.cash_account
    assert item["comment"] == "with friends"


async def test_currency_word_alone_leaves_no_comment(db: psycopg.AsyncConnection, household: Household) -> None:
    [item] = await process_expense_text("testcoffee testcash 25 nis", household.user_id, db)
    assert item["comment"] is None


@pytest.mark.parametrize(
    ("word", "days_ago"),
    [("вчера", 1), ("yesterday", 1), ("позавчера", 2), ("сегодня", 0), ("today", 0)],
)
async def test_relative_date_words(
    db: psycopg.AsyncConnection, household: Household, word: str, days_ago: int
) -> None:
    [item] = await process_expense_text(f"testcoffee testcash 25 {word}", household.user_id, db)

    assert item["date"] == (get_local_date() - timedelta(days=days_ago)).isoformat()
    assert item["comment"] is None


async def test_several_items_separated_by_commas(db: psycopg.AsyncConnection, household: Household) -> None:
    items = await process_expense_text("testcoffee testcash 25, taxi testbank 40", household.user_id, db)

    assert [(i["item_name"], i["amount"], i["account_id"]) for i in items] == [
        ("testcoffee", 25.0, household.cash_account),
        ("taxi", 40.0, household.bank_account),
    ]


async def test_item_and_amount_without_account(db: psycopg.AsyncConnection, household: Household) -> None:
    """Two words parse fine but leave the account empty; saving then refuses it (see below)."""
    [item] = await process_expense_text("testcoffee 25", household.user_id, db)
    assert item["account_id"] is None
    assert "error" not in item


async def test_unknown_account_word_is_an_error(db: psycopg.AsyncConnection, household: Household) -> None:
    [item] = await parse_expense_message("testcoffee nosuchaccount 25", household.user_id, db)
    assert item == {"original": "testcoffee nosuchaccount 25", "error": "unknown_account",
                    "account_alias": "nosuchaccount"}


async def test_any_parse_error_returns_only_the_errors(db: psycopg.AsyncConnection, household: Household) -> None:
    """All or nothing: if one part can't be read, no part is returned for saving (#20)."""
    items = await process_expense_text("testcoffee testcash 25, testcoffee nosuchaccount 5", household.user_id, db)

    assert items == [{"original": "testcoffee nosuchaccount 5", "error": "unknown_account",
                      "account_alias": "nosuchaccount"}]


async def test_unparseable_parts_are_marked(db: psycopg.AsyncConnection, household: Household) -> None:
    items = await parse_expense_message("lonely, testcoffee testcash many", household.user_id, db)
    assert [i["error"] for i in items] == ["not_enough_words", "invalid_amount"]


async def test_current_behaviour_decimal_comma_splits_the_message(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """
    Known problem: the message is split on commas before amounts are parsed, so "150,5"
    becomes two parts. The trailing "5" fails to parse, so the whole message is refused even
    though it was in the fast-parser format.
    """
    items = await parse_expense_message("testcoffee testcash 150,5", household.user_id, db)

    assert items[0]["amount"] == 150.0
    assert items[1] == {"original": "5", "error": "not_enough_words"}


async def test_current_behaviour_category_lookup_is_case_sensitive(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """
    Known problem: manual entry looks up the lower-cased item name, but aliases learned from
    statements are stored upper-case (e.g. 'TESTMERCHANT'), so they never match here.
    """
    [item] = await process_expense_text("testmerchant testcash 10", household.user_id, db)
    assert item["category_id"] is None


# --- Saving ----------------------------------------------------------------------------

def _item(household: Household, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "item_name": "testcoffee",
        "amount": 25.0,
        "account_id": household.cash_account,
        "category_id": CATEGORY_RESTAURANTS,
        "comment": None,
        "date": None,
    }
    item.update(overrides)
    return item


async def test_cash_expense_is_confirmed_and_negative(db: psycopg.AsyncConnection, household: Household) -> None:
    result = await save_expense_item(_item(household), household.user_id, "en", db, "manual_text")
    await db.commit()

    assert result["status"] == "confirmed"
    assert result["db_amount"] == -25.0
    row = await _transaction(db, result["id"])
    assert row == {
        "user_id": household.user_id,
        "account_id": household.cash_account,
        "category_id": CATEGORY_RESTAURANTS,
        "amount": -25,
        "description": "testcoffee",
        "comment": None,
        "day": get_local_date(),
        "source_type": "manual_text",
        "status": "confirmed",
    }


@pytest.mark.parametrize("account_field", ["own_card_account", "bank_account", "transit_account"])
async def test_non_cash_entries_are_pending(
    db: psycopg.AsyncConnection, household: Household, account_field: str
) -> None:
    """Anything that isn't a cash account waits for a statement to confirm it."""
    item = _item(household, account_id=getattr(household, account_field))
    result = await save_expense_item(item, household.user_id, "en", db, "manual_text")
    assert result["status"] == "pending"


async def test_card_entries_over_150_are_refused(db: psycopg.AsyncConnection, household: Household) -> None:
    item = _item(household, account_id=household.own_card_account, amount=150.01)
    assert await save_expense_item(item, household.user_id, "en", db, "manual_text") == {
        "error": "card_limit_exceeded"
    }

    at_limit = _item(household, account_id=household.own_card_account, amount=150)
    assert "id" in await save_expense_item(at_limit, household.user_id, "en", db, "manual_text")


async def test_current_behaviour_card_limit_only_applies_to_card_accounts(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """The 150 limit checks account type 'card' only; a transit account accepts any amount."""
    item = _item(household, account_id=household.transit_account, amount=5000)
    result = await save_expense_item(item, household.user_id, "en", db, "manual_text")
    assert result["status"] == "pending"


@pytest.mark.parametrize(
    ("category_id", "amount", "expected"),
    [
        (CATEGORY_SALARY, -1000.0, 1000.0),          # income: always positive
        (CATEGORY_INTERNAL_TRANSFER, -70.0, -70.0),  # transfer: sign kept
        (CATEGORY_INTERNAL_TRANSFER, 70.0, 70.0),
        (CATEGORY_RESTAURANTS, 25.0, -25.0),         # everything else: always negative
        (None, 25.0, -25.0),                         # no category: expense
    ],
)
async def test_amount_sign_follows_the_category_group(
    db: psycopg.AsyncConnection, household: Household, category_id: int | None, amount: float, expected: float
) -> None:
    item = _item(household, item_name="something", category_id=category_id, amount=amount)
    result = await save_expense_item(item, household.user_id, "en", db, "manual_text")
    assert result["db_amount"] == expected


async def test_income_keyword_without_category_becomes_other_income(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    item = _item(household, item_name="зарплата march", category_id=None, amount=5000)
    result = await save_expense_item(item, household.user_id, "en", db, "manual_text")
    await db.commit()

    assert result["db_amount"] == 5000.0
    assert (await _transaction(db, result["id"]))["category_id"] == CATEGORY_OTHER_INCOME


async def test_explicit_date_and_comment_are_stored(db: psycopg.AsyncConnection, household: Household) -> None:
    day = get_local_date() - timedelta(days=2)
    item = _item(household, date=day.isoformat(), comment="with friends")
    result = await save_expense_item(item, household.user_id, "en", db, "manual_voice")
    await db.commit()

    row = await _transaction(db, result["id"])
    assert (row["day"], row["comment"], row["source_type"]) == (day, "with friends", "manual_voice")


async def test_missing_account_is_refused(db: psycopg.AsyncConnection, household: Household) -> None:
    item = _item(household, account_id=None)
    assert await save_expense_item(item, household.user_id, "en", db, "manual_text") == {
        "error": "account_not_found"
    }
