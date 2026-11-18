"""Baseline: schema as it exists in production (2026-11-18)

Reproduces the production schema exactly, including the `import_bit` source
type and the alias trigger that were added to production by hand. Existing
production is not migrated by this revision, only stamped with it
(see bot/db_migrate.py).

tests/integration/test_migrations.py compares the result with a snapshot of
the production schema, so this revision must not be edited. Change the schema
in new revisions instead.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Function body copied verbatim from production (including the trailing space
# after "DO UPDATE"), so the catalog comparison matches byte for byte.
_ALIAS_TRIGGER_FUNCTION_BODY = (
    "\n"
    "BEGIN\n"
    "    IF NEW.category_id IS DISTINCT FROM OLD.category_id AND NEW.category_id IS NOT NULL THEN\n"
    "        INSERT INTO item_aliases (name, category_id)\n"
    "        VALUES (trim(lower(NEW.description)), NEW.category_id)\n"
    "        ON CONFLICT (name) DO UPDATE \n"
    "        SET category_id = EXCLUDED.category_id;\n"
    "    END IF;\n"
    "    RETURN NEW;\n"
    "END;\n"
)

_STATEMENTS: list[str] = [
    "CREATE SCHEMA budget",
    f"""
    CREATE FUNCTION budget.update_item_alias_on_category_change() RETURNS trigger
        LANGUAGE plpgsql
        AS $${_ALIAS_TRIGGER_FUNCTION_BODY}$$
    """,
    """
    CREATE TABLE budget.users (
        id BIGINT PRIMARY KEY,
        name VARCHAR(255),
        is_admin BOOLEAN DEFAULT FALSE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE budget.accounts (
        id SERIAL PRIMARY KEY,
        owner_id BIGINT REFERENCES budget.users(id),
        name JSONB NOT NULL,
        type VARCHAR(50) NOT NULL
    )
    """,
    """
    CREATE TABLE budget.account_aliases (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) UNIQUE NOT NULL,
        account_id INT REFERENCES budget.accounts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE budget.categories (
        id SERIAL PRIMARY KEY,
        name JSONB NOT NULL,
        parent_id INT REFERENCES budget.categories(id)
    )
    """,
    """
    CREATE TABLE budget.item_aliases (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) UNIQUE NOT NULL,
        category_id INT REFERENCES budget.categories(id) ON DELETE CASCADE
    )
    """,
    # CHECK expressions are written exactly as production stores them.
    """
    CREATE TABLE budget.transactions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES budget.users(id),
        account_id INT REFERENCES budget.accounts(id),
        category_id INT REFERENCES budget.categories(id),
        amount NUMERIC(12, 2) NOT NULL,
        description TEXT,
        comment TEXT,
        date TIMESTAMP WITH TIME ZONE NOT NULL,
        external_id VARCHAR(255) UNIQUE,
        source_type VARCHAR(20),
        status VARCHAR(20) DEFAULT 'confirmed',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT transactions_source_type_check CHECK (((source_type)::text = ANY ((ARRAY['manual'::character varying, 'import_xls'::character varying, 'import_bit'::character varying, 'manual_text'::character varying, 'manual_voice'::character varying])::text[]))),
        CONSTRAINT transactions_status_check CHECK (((status)::text = ANY (ARRAY[('draft'::character varying)::text, ('pending'::character varying)::text, ('confirmed'::character varying)::text, ('adjustment'::character varying)::text])))
    )
    """,
    """
    CREATE TRIGGER trg_update_item_alias AFTER UPDATE OF category_id ON budget.transactions
        FOR EACH ROW EXECUTE FUNCTION budget.update_item_alias_on_category_change()
    """,
]


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError(
        "The baseline can't be downgraded: it would drop the whole schema and all data. "
        "Restore from a backup instead (scripts/restore_db.sh)."
    )
