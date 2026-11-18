"""
Integration tests against a real PostgreSQL server.

They run only when TEST_DATABASE_URL points to a server where the user may
create databases, e.g.:

    docker run --rm -d --name budget-test-pg -p 55432:5432 \
        -e POSTGRES_PASSWORD=postgres postgres:18
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres uv run pytest

Each test gets a fresh, uniquely named database that is dropped afterwards.
"""
import os
import uuid
from collections.abc import Callable, Iterator

import psycopg
import pytest
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
