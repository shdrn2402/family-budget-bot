import pytest
import os
from unittest.mock import AsyncMock, patch

os.environ["TELEGRAM_TOKEN"] = "test_token"

class FakeCursor:
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc, tb):
        pass
        
    async def execute(self, query, params=None):
        pass
        
    async def fetchone(self):
        return {"id": 999999}

class FakeConnection:
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc, tb):
        pass

    def cursor(self):
        return FakeCursor()
        
    async def commit(self):
        pass
        
    async def close(self):
        pass

@pytest.fixture(autouse=True)
def mock_db_connection():
    """
    Replace the real database connection with FakeConnection, so unit tests
    never reach a real database. Integration tests pass their own connection.
    """
    with patch("bot.database.get_db_connection", new=AsyncMock(return_value=FakeConnection())):
        yield
