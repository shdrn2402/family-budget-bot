"""Record which statement line was merged into a row

When an imported line is merged into an existing row instead of becoming a new
row, transactions.merged_external_id keeps that line's external_id:
- a Bit line enriching a card/bank row stores its own id;
- a card/bank line taking over a Bit row moves the Bit id here.
A row that already has one is no longer a match candidate (one merge per row),
and re-imports are detected exactly. Rows merged earlier stay NULL (#60).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adding a nullable column without a default is a metadata-only change (no table rewrite).
    op.execute("ALTER TABLE budget.transactions ADD COLUMN merged_external_id character varying(255)")
    op.execute(
        "CREATE UNIQUE INDEX transactions_merged_external_id_key "
        "ON budget.transactions (merged_external_id) WHERE merged_external_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX budget.transactions_merged_external_id_key")
    op.execute("ALTER TABLE budget.transactions DROP COLUMN merged_external_id")
