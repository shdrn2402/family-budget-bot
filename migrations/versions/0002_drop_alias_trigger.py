"""Drop the trigger that created item aliases on category change

The trigger duplicated the alias learning done in Python (sync_category_by_alias):
one category change produced two aliases with different keys (description vs
description + comment), created generic aliases for Bit transfers, cascaded
through the bulk update, and failed for clients without search_path=budget.
After this revision, only the application code creates item aliases (#8).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exactly as created in 0001 (including the trailing space after "DO UPDATE"),
# so a downgrade restores the baseline byte for byte.
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


def upgrade() -> None:
    op.execute("DROP TRIGGER trg_update_item_alias ON budget.transactions")
    op.execute("DROP FUNCTION budget.update_item_alias_on_category_change()")


def downgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION budget.update_item_alias_on_category_change() RETURNS trigger
            LANGUAGE plpgsql
            AS $${_ALIAS_TRIGGER_FUNCTION_BODY}$$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_update_item_alias AFTER UPDATE OF category_id ON budget.transactions
            FOR EACH ROW EXECUTE FUNCTION budget.update_item_alias_on_category_change()
        """
    )
