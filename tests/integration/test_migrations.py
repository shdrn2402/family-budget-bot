from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from bot.db_migrate import BASELINE_REVISION, PartialSchemaError, run_migrations, upgrade_to
from tests.integration.conftest import connect
from tests.integration.schema_snapshot import schema_snapshot

PROD_SCHEMA_SQL: str = (
    Path(__file__).resolve().parent.parent / "fixtures" / "db" / "prod_schema_baseline.sql"
).read_text(encoding="utf-8")


def _load_prod_schema(url: URL) -> None:
    with connect(url) as conn:
        conn.execute(PROD_SCHEMA_SQL)
        conn.commit()


def _alembic_version(url: URL) -> str | None:
    with connect(url) as conn:
        row = conn.execute(
            "SELECT version_num FROM public.alembic_version"
        ).fetchone()
    return row[0] if row else None


def test_baseline_revision_matches_production_schema(create_database: Callable[[], URL]) -> None:
    """Revision 0001 on an empty database must equal the production schema exactly."""
    prod_url = create_database()
    _load_prod_schema(prod_url)

    baseline_url = create_database()
    upgrade_to(BASELINE_REVISION, baseline_url)

    with connect(prod_url) as prod, connect(baseline_url) as baseline:
        assert schema_snapshot(baseline) == schema_snapshot(prod)


def test_existing_unversioned_database_is_stamped_without_schema_changes(
    create_database: Callable[[], URL],
) -> None:
    """Production today: tables exist, no alembic_version. Adopting it must not run any DDL."""
    url = create_database()
    _load_prod_schema(url)
    with connect(url) as conn:
        conn.execute("INSERT INTO budget.users (id, name) VALUES (1, 'existing user')")
        conn.commit()
        before = schema_snapshot(conn)

    run_migrations(url, max_retries=1)

    assert _alembic_version(url) == BASELINE_REVISION
    with connect(url) as conn:
        assert schema_snapshot(conn) == before
        assert conn.execute("SELECT count(*) FROM budget.users").fetchone()[0] == 1


def test_empty_database_gets_schema_and_seed(create_database: Callable[[], URL]) -> None:
    url = create_database()

    run_migrations(url, max_retries=1)

    assert _alembic_version(url) == BASELINE_REVISION
    with connect(url) as conn:
        categories = conn.execute("SELECT count(*) FROM budget.categories").fetchone()[0]
        assert categories == 44


def test_bit_import_source_type_is_accepted(create_database: Callable[[], URL]) -> None:
    """Regression: the old schema.sql rejected 'import_bit', which production allows."""
    url = create_database()
    run_migrations(url, max_retries=1)

    with connect(url) as conn:
        conn.execute(
            "INSERT INTO budget.transactions (amount, date, source_type) VALUES (-10, now(), 'import_bit')"
        )
        conn.commit()


def test_running_migrations_twice_is_a_no_op(create_database: Callable[[], URL]) -> None:
    url = create_database()
    run_migrations(url, max_retries=1)
    with connect(url) as conn:
        conn.execute("INSERT INTO budget.users (id, name) VALUES (1, 'u')")
        conn.commit()
        before = schema_snapshot(conn)

    run_migrations(url, max_retries=1)

    with connect(url) as conn:
        assert schema_snapshot(conn) == before
        assert conn.execute("SELECT count(*) FROM budget.users").fetchone()[0] == 1


def test_partial_schema_is_refused_and_left_untouched(create_database: Callable[[], URL]) -> None:
    url = create_database()
    with connect(url) as conn:
        conn.execute("CREATE SCHEMA budget")
        conn.execute("CREATE TABLE budget.users (id bigint PRIMARY KEY)")
        conn.execute("INSERT INTO budget.users VALUES (7)")
        conn.commit()

    with pytest.raises(PartialSchemaError):
        run_migrations(url, max_retries=1)

    with connect(url) as conn:
        assert conn.execute("SELECT id FROM budget.users").fetchall() == [(7,)]
