from unittest.mock import MagicMock, patch

import pytest

from bot.db_migrate import (
    LEGACY_TABLES,
    DatabaseState,
    MigrationAction,
    PartialSchemaError,
    detect_state,
    plan_actions,
)


def test_detect_state_empty_database() -> None:
    assert detect_state(table_names=set(), has_version_table=False) is DatabaseState.EMPTY


def test_detect_state_legacy_database_without_alembic() -> None:
    """Production before this change: all tables exist, no alembic_version table."""
    assert detect_state(table_names=set(LEGACY_TABLES), has_version_table=False) is DatabaseState.UNVERSIONED


def test_detect_state_versioned_database() -> None:
    assert detect_state(table_names=set(LEGACY_TABLES), has_version_table=True) is DatabaseState.VERSIONED


def test_detect_state_versioned_wins_even_if_tables_change_later() -> None:
    """Once Alembic manages the database, table names no longer decide anything."""
    assert detect_state(table_names={"users"}, has_version_table=True) is DatabaseState.VERSIONED


def test_detect_state_partial_schema() -> None:
    assert detect_state(table_names={"users", "accounts"}, has_version_table=False) is DatabaseState.PARTIAL


def test_plan_for_empty_database_creates_schema_then_seeds() -> None:
    assert plan_actions(DatabaseState.EMPTY) == [MigrationAction.UPGRADE, MigrationAction.SEED]


def test_plan_for_legacy_database_stamps_baseline_without_ddl() -> None:
    assert plan_actions(DatabaseState.UNVERSIONED) == [MigrationAction.STAMP_BASELINE, MigrationAction.UPGRADE]


def test_plan_for_versioned_database_only_upgrades() -> None:
    assert plan_actions(DatabaseState.VERSIONED) == [MigrationAction.UPGRADE]


def test_plan_for_partial_schema_refuses_and_never_drops() -> None:
    with pytest.raises(PartialSchemaError):
        plan_actions(DatabaseState.PARTIAL)


def test_main_runs_migrations_before_polling() -> None:
    """Startup must run migrations (no more automatic restore/DROP SCHEMA in init_db)."""
    import bot.main

    calls: list[str] = []
    app = MagicMock()
    app.run_polling.side_effect = lambda: calls.append("polling")

    with patch.object(bot.main.Config, "TELEGRAM_TOKEN", "test_token"), \
         patch("bot.main.run_migrations", side_effect=lambda: calls.append("migrations")), \
         patch("bot.main.ApplicationBuilder") as builder:
        builder.return_value.token.return_value.build.return_value = app
        bot.main.main()

    assert calls == ["migrations", "polling"]


def test_init_db_is_removed() -> None:
    import bot.database

    assert not hasattr(bot.database, "init_db")
