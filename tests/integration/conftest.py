"""
Integration tests against a real PostgreSQL server.

They run only when TEST_DATABASE_URL points to a server where the user may
create databases, e.g.:

    docker run --rm -d --name budget-test-pg -p 55432:5432 \
        -e POSTGRES_PASSWORD=postgres postgres:18
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres uv run pytest

Each test gets a fresh, uniquely named database that is dropped afterwards.
"""
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass

import psycopg
import pytest
from psycopg.rows import dict_row
from sqlalchemy.engine import URL, make_url

TEST_DATABASE_URL: str | None = os.getenv("TEST_DATABASE_URL")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(skip)


def _admin_conninfo() -> str:
    assert TEST_DATABASE_URL
    return TEST_DATABASE_URL


@pytest.fixture
def create_database() -> Iterator[Callable[[], URL]]:
    """Factory that creates empty databases and returns their SQLAlchemy URL."""
    created: list[str] = []

    def _create() -> URL:
        name = f"budget_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(_admin_conninfo(), autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return make_url(_admin_conninfo()).set(drivername="postgresql+psycopg", database=name)

    yield _create

    with psycopg.connect(_admin_conninfo(), autocommit=True) as admin:
        for name in created:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def connect(url: URL) -> psycopg.Connection:
    """Plain psycopg connection for a SQLAlchemy URL."""
    return psycopg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database
    )


# --- Core-path fixtures (issue #11) -------------------------------------------------

@pytest.fixture
def seeded_url(create_database: Callable[[], URL]) -> URL:
    """A database at the latest revision, with the reference seed loaded (as on a fresh install)."""
    from bot.db_migrate import run_migrations

    url = create_database()
    run_migrations(url, max_retries=1)
    return url


@pytest.fixture
async def db(seeded_url: URL) -> AsyncIterator[psycopg.AsyncConnection]:
    """An async connection configured like the bot's own (dict rows, search_path=budget,public)."""
    conn = await psycopg.AsyncConnection.connect(
        host=seeded_url.host,
        port=seeded_url.port,
        user=seeded_url.username,
        password=seeded_url.password,
        dbname=seeded_url.database,
        row_factory=dict_row,
        options="-c search_path=budget,public",
    )
    yield conn
    await conn.close()


@dataclass(frozen=True)
class Household:
    """Fake users and accounts created on top of the seed. IDs come from the sequences."""

    user_id: int
    other_user_id: int
    cash_account: int
    own_card_account: int
    other_card_account: int
    bank_account: int
    transit_account: int


# Reference categories from scripts/seed_data.sql (stable IDs; see the migration tests).
CATEGORY_SALARY = 11            # parent 1 (Income)
CATEGORY_OTHER_INCOME = 13      # parent 1 (Income)
CATEGORY_INTERNAL_TRANSFER = 15  # parent 2 (Transfer)
CATEGORY_RESTAURANTS = 19       # parent 3 (Food)
CATEGORY_CASH_WITHDRAWAL = 43   # parent 8 (Financial)


@pytest.fixture
async def household(db: psycopg.AsyncConnection) -> Household:
    async def account(name: str, account_type: str, owner_id: int | None) -> int:
        row = await (await db.execute(
            "INSERT INTO accounts (name, type, owner_id) VALUES (%s, %s, %s) RETURNING id",
            (json.dumps({"en": name, "ru": name}), account_type, owner_id),
        )).fetchone()
        return row["id"]

    await db.execute("INSERT INTO users (id, name) VALUES (1001, 'Test User'), (1002, 'Other User')")
    household = Household(
        user_id=1001,
        other_user_id=1002,
        cash_account=await account("Test Cash", "cash", None),
        own_card_account=await account("Test Card", "card", 1001),
        other_card_account=await account("Other Card", "card", 1002),
        bank_account=await account("Test Bank", "card", None),
        transit_account=await account("Test Transit", "transit", None),
    )
    await db.execute(
        "INSERT INTO account_aliases (name, account_id) VALUES "
        "('testcash', %s), ('testbank', %s), ('testtransit', %s)",
        (household.cash_account, household.bank_account, household.transit_account),
    )
    await db.execute(
        "INSERT INTO item_aliases (name, category_id) VALUES ('testcoffee', %s), ('TESTMERCHANT', %s)",
        (CATEGORY_RESTAURANTS, CATEGORY_RESTAURANTS),
    )
    await db.commit()
    return household

