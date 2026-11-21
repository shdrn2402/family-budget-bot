"""
Pins the current behaviour of history reads and category learning against a real database:
get_recent_transactions, get_transactions_count, sync_category_by_alias (bot/database.py).
Part of issue #11.
"""
from datetime import datetime, timedelta

import psycopg

from bot.database import get_recent_transactions, get_transactions_count, sync_category_by_alias
from tests.integration.conftest import CATEGORY_INTERNAL_TRANSFER, CATEGORY_RESTAURANTS, CATEGORY_SALARY, Household

START = datetime(2026, 10, 1, 12, 0)


async def _insert(
    db: psycopg.AsyncConnection, household: Household, *, user_id: int, description: str,
    comment: str | None = None, category_id: int | None = None, days: int = 0,
) -> int:
    row = await (await db.execute(
        "INSERT INTO transactions (user_id, account_id, category_id, amount, description, comment, date, source_type) "
        "VALUES (%s, %s, %s, -10, %s, %s, %s, 'import_xls') RETURNING id",
        (user_id, household.bank_account, category_id, description, comment, START + timedelta(days=days)),
    )).fetchone()
    return row["id"]


async def _categories(db: psycopg.AsyncConnection) -> dict[int, int | None]:
    rows = await (await db.execute("SELECT id, category_id FROM transactions")).fetchall()
    return {r["id"]: r["category_id"] for r in rows}


async def _last_alias_id(db: psycopg.AsyncConnection) -> int:
    row = await (await db.execute("SELECT coalesce(max(id), 0) AS id FROM item_aliases")).fetchone()
    return row["id"]


async def _aliases_since(db: psycopg.AsyncConnection, last_id: int) -> dict[str, int]:
    """Aliases created after `last_id` (the seed and fixture aliases are ignored)."""
    rows = await (await db.execute(
        "SELECT name, category_id FROM item_aliases WHERE id > %s", (last_id,)
    )).fetchall()
    return {r["name"]: r["category_id"] for r in rows}


# --- History ---------------------------------------------------------------------------

async def test_history_is_newest_first_paged_and_per_user(db: psycopg.AsyncConnection, household: Household) -> None:
    ids = [await _insert(db, household, user_id=household.user_id, description=f"t{d}", days=d) for d in range(7)]
    await _insert(db, household, user_id=household.other_user_id, description="someone else", days=30)
    await db.commit()

    first_page = await get_recent_transactions(household.user_id, limit=5, offset=0, conn=db)
    second_page = await get_recent_transactions(household.user_id, limit=5, offset=5, conn=db)

    assert [t["id"] for t in first_page] == list(reversed(ids))[:5]
    assert [t["id"] for t in second_page] == list(reversed(ids))[5:]
    assert first_page[0]["account_name"] == {"en": "Test Bank", "ru": "Test Bank"}
    assert set(first_page[0]) == {"id", "description", "amount", "date", "account_name"}
    assert await get_transactions_count(household.user_id, conn=db) == 7
    assert await get_transactions_count(household.other_user_id, conn=db) == 1


# --- Category learning -----------------------------------------------------------------

async def test_learning_saves_the_alias_and_categorizes_matching_rows_of_that_user(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    mine = await _insert(db, household, user_id=household.user_id, description="Coffee")
    already_categorized = await _insert(db, household, user_id=household.user_id, description="Coffee",
                                        category_id=CATEGORY_SALARY)
    someone_elses = await _insert(db, household, user_id=household.other_user_id, description="Coffee")
    unrelated = await _insert(db, household, user_id=household.user_id, description="Taxi")
    await db.commit()
    last_alias = await _last_alias_id(db)

    updated = await sync_category_by_alias("Coffee", CATEGORY_RESTAURANTS, household.user_id, db)

    assert updated == 1
    assert await _categories(db) == {
        mine: CATEGORY_RESTAURANTS,
        already_categorized: CATEGORY_SALARY,   # existing categories are never overwritten
        someone_elses: None,                    # only the given user's rows
        unrelated: None,
    }
    assert await _aliases_since(db, last_alias) == {"coffee": CATEGORY_RESTAURANTS}  # stored lower-cased


async def test_learning_uses_the_description_plus_comment_key(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """Bit-style rows: the generic description plus the counterparty form the alias."""
    to_alice = await _insert(db, household, user_id=household.user_id, description="Transfer", comment="Alice")
    to_bob = await _insert(db, household, user_id=household.user_id, description="Transfer", comment="Bob")
    await db.commit()
    last_alias = await _last_alias_id(db)

    await sync_category_by_alias("Transfer Alice", CATEGORY_INTERNAL_TRANSFER, household.user_id, db)

    assert await _categories(db) == {to_alice: CATEGORY_INTERNAL_TRANSFER, to_bob: None}
    assert await _aliases_since(db, last_alias) == {"transfer alice": CATEGORY_INTERNAL_TRANSFER}


async def test_relearning_an_alias_moves_it_to_the_new_category(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    last_alias = await _last_alias_id(db)
    await sync_category_by_alias("Coffee", CATEGORY_RESTAURANTS, household.user_id, db)
    await sync_category_by_alias("Coffee", CATEGORY_SALARY, household.user_id, db)

    assert await _aliases_since(db, last_alias) == {"coffee": CATEGORY_SALARY}


async def test_current_behaviour_learning_matches_substrings(
    db: psycopg.AsyncConnection, household: Household
) -> None:
    """
    Known problem: matching is ILIKE '%alias%', so learning "Coffee" also categorizes any
    uncategorized row that merely contains it (e.g. "Coffee Machine Repair").
    """
    exact = await _insert(db, household, user_id=household.user_id, description="Coffee")
    containing = await _insert(db, household, user_id=household.user_id, description="Coffee Machine Repair")
    await db.commit()

    assert await sync_category_by_alias("Coffee", CATEGORY_RESTAURANTS, household.user_id, db) == 2

    assert await _categories(db) == {exact: CATEGORY_RESTAURANTS, containing: CATEGORY_RESTAURANTS}
