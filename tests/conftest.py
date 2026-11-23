import os
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

os.environ["TELEGRAM_TOKEN"] = "test_token"


class FakeCursor:
    """Result of a query on an empty database: no rows, nothing changed."""

    rowcount = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def execute(self, query, params=None):
        return self

    async def fetchone(self):
        return None

    async def fetchall(self):
        return []


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    async def execute(self, query, params=None):
        return FakeCursor()

    @asynccontextmanager
    async def transaction(self):
        yield


@asynccontextmanager
async def fake_pool_connection():
    yield FakeConnection()


@pytest.fixture(autouse=True)
def mock_db_connection():
    """
    Replace the connection pool with an empty fake database, so unit tests never reach a
    real one. Integration tests pass their own connection to the repositories.
    """
    with patch("db.pool.connection", new=fake_pool_connection):
        yield
