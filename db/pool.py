"""The process-wide PostgreSQL connection pool.

Callers own the transaction:

    async with pool.connection() as conn:
        await transactions.delete(conn, tx_id)

The block commits when it exits normally and rolls back when it raises. Repositories never
commit on their own.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SEARCH_PATH = "budget,public"

# Connection settings shared by the pool and by tests that connect on their own.
CONNECTION_KWARGS: dict[str, Any] = {
    "row_factory": dict_row,
    "options": f"-c search_path={SEARCH_PATH}",
}

_pool: AsyncConnectionPool | None = None


async def open_pool(conninfo: str, *, min_size: int = 1, max_size: int = 4) -> AsyncConnectionPool:
    """Open the pool and wait until its first connection works. Fails loudly if it can't connect."""
    global _pool
    if _pool is not None:
        raise RuntimeError("the connection pool is already open")
    pool: AsyncConnectionPool = AsyncConnectionPool(
        conninfo,
        min_size=min_size,
        max_size=max_size,
        kwargs=CONNECTION_KWARGS,
        # A connection left broken by a database restart is replaced instead of handed out.
        check=AsyncConnectionPool.check_connection,
        open=False,
        name="budget",
    )
    await pool.open(wait=True)
    _pool = pool
    return pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        pool, _pool = _pool, None
        await pool.close()


@asynccontextmanager
async def connection() -> AsyncIterator[AsyncConnection]:
    """Borrow a connection for one unit of work (commit on success, rollback on error)."""
    if _pool is None:
        raise RuntimeError("the connection pool is not open")
    async with _pool.connection() as conn:
        yield conn
