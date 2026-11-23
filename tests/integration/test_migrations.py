from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from bot.db_migrate import BASELINE_REVISION, PartialSchemaError, head_revision, run_migrations, upgrade_to
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


def test_existing_unversioned_database_is_adopted_as_baseline(
    create_database: Callable[[], URL],
) -> None:
    """
    A pre-Alembic production database is stamped as the baseline (no DDL for 0001),
    then only the newer revisions run. It must end up identical to a fresh database
    at head, with its data kept.
    """
    url = create_database()
    _load_prod_schema(url)
    with connect(url) as conn:
        conn.execute("INSERT INTO budget.users (id, name) VALUES (1, 'existing user')")
        conn.commit()

    run_migrations(url, max_retries=1)

    fresh_url = create_database()
    upgrade_to("head", fresh_url)

    assert _alembic_version(url) == head_revision()
    with connect(url) as adopted, connect(fresh_url) as fresh:
        assert schema_snapshot(adopted) == schema_snapshot(fresh)
        assert adopted.execute("SELECT count(*) FROM budget.users").fetchone()[0] == 1


def test_empty_database_gets_schema_and_seed(create_database: Callable[[], URL]) -> None:
    url = create_database()

    run_migrations(url, max_retries=1)

    assert _alembic_version(url) == head_revision()
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


def test_merged_external_id_is_unique_and_its_migration_reverses_cleanly(
    create_database: Callable[[], URL],
) -> None:
    """0003 adds transactions.merged_external_id (#60); downgrading restores 0002 exactly."""
    import psycopg

    from bot.db_migrate import downgrade_to

    before_url = create_database()
    upgrade_to("0002", before_url)

    url = create_database()
    upgrade_to("0003", url)
    with connect(url) as conn:
        conn.execute("INSERT INTO budget.users (id, name) VALUES (1, 'u')")
        insert = (
            "INSERT INTO budget.transactions (user_id, amount, description, date, merged_external_id) "
            "VALUES (1, -1, 'x', now(), %s)"
        )
        conn.execute(insert, (None,))
        conn.execute(insert, (None,))  # many rows without a merge
        conn.execute(insert, ("bit_1",))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, ("bit_1",))  # but each line merges into one row only
        conn.rollback()

    downgrade_to("0002", url)
    with connect(url) as downgraded, connect(before_url) as before:
        assert schema_snapshot(downgraded) == schema_snapshot(before)


def test_item_aliases_move_to_app_merchant_rules_and_back(create_database: Callable[[], URL]) -> None:
    """0004 moves the rules into app.merchant_rules, keeping ids (#62); downgrading restores 0003."""
    from bot.db_migrate import downgrade_to

    before_url = create_database()
    upgrade_to("0003", before_url)

    url = create_database()
    upgrade_to("0003", url)
    with connect(url) as conn:
        conn.execute(
            "INSERT INTO budget.categories (id, name) VALUES (19, '{\"en\": \"a\"}'), (26, '{\"en\": \"b\"}')"
        )
        conn.execute(
            "INSERT INTO budget.item_aliases (id, name, category_id) VALUES "
            "(7, 'testcoffee', 19), (9, 'TESTMERCHANT', 26), (12, 'no category', NULL)"
        )
        conn.commit()

    upgrade_to("0004", url)
    with connect(url) as conn:
        rules = conn.execute("SELECT id, pattern, category_id FROM app.merchant_rules ORDER BY id").fetchall()
        assert rules == [(7, "testcoffee", 19), (9, "TESTMERCHANT", 26)]  # a rule without a category is dropped
        assert conn.execute("SELECT to_regclass('budget.item_aliases')").fetchone() == (None,)
        # New rules continue after the copied ids.
        new_id = conn.execute(
            "INSERT INTO app.merchant_rules (pattern, category_id) VALUES ('new', 19) RETURNING id"
        ).fetchone()[0]
        assert new_id > 12
        conn.rollback()

    downgrade_to("0003", url)
    with connect(url) as downgraded, connect(before_url) as before:
        assert schema_snapshot(downgraded) == schema_snapshot(before)
        assert downgraded.execute("SELECT to_regnamespace('app')").fetchone() == (None,)
        assert downgraded.execute("SELECT id, name, category_id FROM budget.item_aliases ORDER BY id").fetchall() == [
            (7, "testcoffee", 19), (9, "TESTMERCHANT", 26)
        ]
