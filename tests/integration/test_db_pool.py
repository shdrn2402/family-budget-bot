"""The bot's connection pool (db/pool.py) against a real database.

Pins the unit-of-work contract the repositories rely on: dict rows, the budget search
path, commit when the block exits normally and rollback when it raises.
"""
from collections.abc import AsyncIterator

import psycopg
import pytest
from sqlalchemy.engine import URL

from db import pool, users
from tests.integration.conftest import connect


def _conninfo(url: URL) -> str:
    return psycopg.conninfo.make_conninfo(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database
    )


@pytest.fixture
async def open_pool(seeded_url: URL) -> AsyncIterator[URL]:
    await pool.open_pool(_conninfo(seeded_url), min_size=1, max_size=2)
    yield seeded_url
    await pool.close_pool()


def _user_ids(url: URL) -> list[int]:
    with connect(url) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM budget.users ORDER BY id").fetchall()]


async def test_connections_return_dict_rows_on_the_budget_schema(open_pool: URL) -> None:
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT current_schema() AS schema")).fetchone()
    assert row == {"schema": "budget"}


async def test_a_block_that_exits_normally_is_committed(open_pool: URL) -> None:
    async with pool.connection() as conn:
        await users.register(conn, 3001, "Committed")

    assert _user_ids(open_pool) == [3001]  # seen from another connection


async def test_a_block_that_raises_is_rolled_back(open_pool: URL) -> None:
    with pytest.raises(RuntimeError):
        async with pool.connection() as conn:
            await users.register(conn, 3002, "Rolled back")
            raise RuntimeError("handler failed")

    assert _user_ids(open_pool) == []


async def test_the_pool_must_be_opened_once_before_use(open_pool: URL) -> None:
    with pytest.raises(RuntimeError, match="already open"):
        await pool.open_pool(_conninfo(open_pool))

    await pool.close_pool()
    with pytest.raises(RuntimeError, match="not open"):
        async with pool.connection():
            pass
