"""
Issue #8: the hand-made alias trigger duplicated the alias learning done in Python.
Revision 0002 drops it, so only the application code creates item aliases.
"""
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import URL

from db import merchant_rules
from bot.db_migrate import BASELINE_REVISION, downgrade_to, upgrade_to
from tests.integration.conftest import connect
from tests.integration.schema_snapshot import schema_snapshot

PROD_SCHEMA_SQL: str = (
    Path(__file__).resolve().parent.parent / "fixtures" / "db" / "prod_schema_baseline.sql"
).read_text(encoding="utf-8")

# A Bit transfer: generic description, counterparty in the comment.
DESCRIPTION = "העברה בBIT"
COMMENT = "Alice"
CATEGORY_ID = 16
USER_ID = 1


def _insert_uncategorized_transaction(url: URL) -> int:
    with connect(url) as conn:
        conn.execute(
            "INSERT INTO budget.categories (id, name) VALUES (%s, '{\"en\": \"Transfers\"}')",
            (CATEGORY_ID,),
        )
        conn.execute("INSERT INTO budget.users (id, name) VALUES (%s, 'u')", (USER_ID,))
        row = conn.execute(
            "INSERT INTO budget.transactions (user_id, amount, description, comment, date, source_type) "
            "VALUES (%s, -50, %s, %s, now(), 'import_bit') RETURNING id",
            (USER_ID, DESCRIPTION, COMMENT),
        ).fetchone()
        conn.commit()
    return row[0]


BOT_SEARCH_PATH = "-c search_path=budget,public"


def _set_category(url: URL, transaction_id: int, *, bot_search_path: bool) -> None:
    """Update a category like the bot (search_path=budget,public) or like a SQL client (default)."""
    with psycopg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password,
        dbname=url.database, options=BOT_SEARCH_PATH if bot_search_path else "",
    ) as conn:
        conn.execute(
            "UPDATE budget.transactions SET category_id = %s WHERE id = %s", (CATEGORY_ID, transaction_id)
        )
        conn.commit()


async def _inline_menu_category_change(url: URL, transaction_id: int) -> None:
    """What the inline menu's save_cat branch does: update the row, then sync the alias."""
    _set_category(url, transaction_id, bot_search_path=True)
    async with await psycopg.AsyncConnection.connect(
        host=url.host, port=url.port, user=url.username, password=url.password,
        dbname=url.database, options=BOT_SEARCH_PATH,
    ) as conn:
        alias_name = f"{DESCRIPTION} {COMMENT}".strip()
        if _has_merchant_rules(url):
            await merchant_rules.learn(conn, alias_name, CATEGORY_ID, USER_ID)
        else:  # before 0004: the alias upsert the code did then
            await conn.execute(
                "INSERT INTO item_aliases (name, category_id) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET category_id = EXCLUDED.category_id",
                (alias_name.lower(), CATEGORY_ID),
            )
            await conn.commit()


def _has_merchant_rules(url: URL) -> bool:
    """app.merchant_rules replaced budget.item_aliases in revision 0004 (#62)."""
    with connect(url) as conn:
        return conn.execute("SELECT to_regclass('app.merchant_rules')").fetchone() != (None,)


def _aliases(url: URL) -> list[str]:
    query = (
        "SELECT pattern FROM app.merchant_rules ORDER BY pattern" if _has_merchant_rules(url)
        else "SELECT name FROM budget.item_aliases ORDER BY name"
    )
    with connect(url) as conn:
        return [row[0] for row in conn.execute(query)]


def test_head_has_no_alias_trigger_or_function(create_database: Callable[[], URL]) -> None:
    url = create_database()
    upgrade_to("head", url)

    with connect(url) as conn:
        snapshot = schema_snapshot(conn)
    assert snapshot["triggers"] == []
    assert snapshot["functions"] == []


async def test_baseline_trigger_creates_a_duplicate_alias(create_database: Callable[[], URL]) -> None:
    """Documents the bug being fixed: at 0001 one category change yields two aliases."""
    url = create_database()
    upgrade_to(BASELINE_REVISION, url)
    transaction_id = _insert_uncategorized_transaction(url)

    await _inline_menu_category_change(url, transaction_id)

    assert _aliases(url) == sorted([DESCRIPTION.lower(), f"{DESCRIPTION} {COMMENT}".lower()])


def test_baseline_trigger_breaks_category_updates_from_sql_clients(
    create_database: Callable[[], URL],
) -> None:
    """Documents the bug being fixed: the trigger needs search_path=budget to find item_aliases."""
    url = create_database()
    upgrade_to(BASELINE_REVISION, url)
    transaction_id = _insert_uncategorized_transaction(url)

    with pytest.raises(psycopg.errors.UndefinedTable):
        _set_category(url, transaction_id, bot_search_path=False)


@pytest.mark.parametrize("bot_search_path", [True, False], ids=["bot", "sql-client"])
def test_category_change_alone_creates_no_alias(
    create_database: Callable[[], URL], bot_search_path: bool
) -> None:
    url = create_database()
    upgrade_to("head", url)
    transaction_id = _insert_uncategorized_transaction(url)

    _set_category(url, transaction_id, bot_search_path=bot_search_path)

    assert _aliases(url) == []


async def test_inline_menu_flow_creates_exactly_one_composite_alias(
    create_database: Callable[[], URL],
) -> None:
    url = create_database()
    upgrade_to("head", url)
    transaction_id = _insert_uncategorized_transaction(url)

    await _inline_menu_category_change(url, transaction_id)

    assert _aliases(url) == [f"{DESCRIPTION} {COMMENT}".lower()]


def test_downgrade_restores_the_baseline_schema(create_database: Callable[[], URL]) -> None:
    prod_url = create_database()
    with connect(prod_url) as conn:
        conn.execute(PROD_SCHEMA_SQL)
        conn.commit()

    url = create_database()
    upgrade_to("head", url)
    downgrade_to(BASELINE_REVISION, url)

    with connect(url) as downgraded, connect(prod_url) as prod:
        assert schema_snapshot(downgraded) == schema_snapshot(prod)
