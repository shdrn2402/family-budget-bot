"""Alembic environment.

Uses the connection passed in by bot.db_migrate when present (so inspection,
migrations and seeding share one transaction); otherwise connects with the
bot's DB_* settings, e.g. when running the `alembic` CLI by hand.
"""
from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from bot.db_migrate import VERSION_TABLE, VERSION_TABLE_SCHEMA, build_database_url

config = context.config


def _run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=build_database_url().render_as_string(hide_password=True),
        literal_binds=True,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
        return

    engine = create_engine(build_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run_with_connection(connection)
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
