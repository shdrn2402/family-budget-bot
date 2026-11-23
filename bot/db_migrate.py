"""
Database schema management on startup.

Replaces the old init_db(), which silently dropped and restored the schema.
The startup flow only ever moves the schema forward:

- empty database        -> create the schema with Alembic, then load the seed data
- existing, unversioned -> production before Alembic: stamp the baseline (no DDL), then upgrade
- versioned             -> apply any new migrations
- partial schema        -> refuse to start; nothing is dropped automatically

Restoring a backup is a manual operation (scripts/restore_db.sh).
"""
import logging
import time
from enum import Enum
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, pool
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import OperationalError

from bot.config import Config

logger = logging.getLogger(__name__)

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
ALEMBIC_INI: Path = PROJECT_ROOT / "alembic.ini"
SEED_SQL: Path = PROJECT_ROOT / "scripts" / "seed_data.sql"

SCHEMA: str = "budget"
BASELINE_REVISION: str = "0001"
VERSION_TABLE: str = "alembic_version"
VERSION_TABLE_SCHEMA: str = "public"

# The pre-Alembic production schema (revision 0001); later revisions move or drop some of these.
LEGACY_TABLES: frozenset[str] = frozenset(
    {"users", "accounts", "account_aliases", "categories", "item_aliases", "transactions"}
)


class DatabaseState(Enum):
    EMPTY = "empty"
    UNVERSIONED = "unversioned"
    VERSIONED = "versioned"
    PARTIAL = "partial"


class MigrationAction(Enum):
    STAMP_BASELINE = "stamp_baseline"
    UPGRADE = "upgrade"
    SEED = "seed"


class PartialSchemaError(RuntimeError):
    """The schema exists but is incomplete and isn't managed by Alembic."""


def detect_state(table_names: set[str], has_version_table: bool) -> DatabaseState:
    if has_version_table:
        return DatabaseState.VERSIONED
    if not table_names:
        return DatabaseState.EMPTY
    if LEGACY_TABLES <= table_names:
        return DatabaseState.UNVERSIONED
    return DatabaseState.PARTIAL


def plan_actions(state: DatabaseState) -> list[MigrationAction]:
    if state is DatabaseState.EMPTY:
        return [MigrationAction.UPGRADE, MigrationAction.SEED]
    if state is DatabaseState.UNVERSIONED:
        return [MigrationAction.STAMP_BASELINE, MigrationAction.UPGRADE]
    if state is DatabaseState.VERSIONED:
        return [MigrationAction.UPGRADE]
    raise PartialSchemaError(
        f"Schema '{SCHEMA}' exists but is incomplete and not managed by Alembic. "
        "Refusing to start. Inspect the database, or restore a backup with scripts/restore_db.sh."
    )


def build_database_url() -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        port=int(Config.DB_PORT),
        database=Config.DB_NAME,
    )


def _alembic_config(connection: Connection) -> AlembicConfig:
    alembic_config = AlembicConfig(str(ALEMBIC_INI))
    alembic_config.attributes["connection"] = connection
    return alembic_config


def _inspect_state(connection: Connection) -> DatabaseState:
    inspector = inspect(connection)
    tables: set[str] = set()
    if SCHEMA in inspector.get_schema_names():
        tables = set(inspector.get_table_names(schema=SCHEMA))
    has_version_table = inspector.has_table(VERSION_TABLE, schema=VERSION_TABLE_SCHEMA)
    return detect_state(tables, has_version_table)


def _apply_seed(connection: Connection) -> None:
    # Use the driver cursor directly: the seed is a multi-statement script without parameters.
    sql = SEED_SQL.read_text(encoding="utf-8")
    with connection.connection.driver_connection.cursor() as cursor:
        cursor.execute(sql)


def _connect_with_retry(engine: Engine, max_retries: int, retry_delay: float) -> Connection:
    for attempt in range(1, max_retries + 1):
        try:
            return engine.connect()
        except OperationalError:
            if attempt == max_retries:
                raise
            logger.info("Waiting for database... (attempt %d/%d)", attempt, max_retries)
            time.sleep(retry_delay)
    raise RuntimeError("unreachable")


def head_revision() -> str:
    """The newest revision in migrations/versions."""
    head = ScriptDirectory.from_config(AlembicConfig(str(ALEMBIC_INI))).get_current_head()
    if head is None:
        raise RuntimeError("No Alembic revisions found.")
    return head


def upgrade_to(revision: str, database_url: URL | None = None) -> None:
    """Upgrade to a specific revision. Used by tests and for manual operations."""
    engine = create_engine(database_url or build_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            command.upgrade(_alembic_config(connection), revision)
            connection.commit()
    finally:
        engine.dispose()


def downgrade_to(revision: str, database_url: URL | None = None) -> None:
    """Downgrade to a specific revision. Used by tests and for manual operations."""
    engine = create_engine(database_url or build_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            command.downgrade(_alembic_config(connection), revision)
            connection.commit()
    finally:
        engine.dispose()


def run_migrations(
    database_url: URL | None = None, *, max_retries: int = 10, retry_delay: float = 2.0
) -> None:
    """Bring the database schema up to date. Everything runs in one transaction."""
    engine = create_engine(database_url or build_database_url(), poolclass=pool.NullPool)
    try:
        with _connect_with_retry(engine, max_retries, retry_delay) as connection:
            state = _inspect_state(connection)
            actions = plan_actions(state)
            logger.info("Database state: %s; actions: %s", state.value, [a.value for a in actions])

            alembic_config = _alembic_config(connection)
            for action in actions:
                if action is MigrationAction.STAMP_BASELINE:
                    command.stamp(alembic_config, BASELINE_REVISION)
                elif action is MigrationAction.UPGRADE:
                    command.upgrade(alembic_config, "head")
                elif action is MigrationAction.SEED:
                    _apply_seed(connection)
            connection.commit()
        logger.info("Database schema is up to date.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
