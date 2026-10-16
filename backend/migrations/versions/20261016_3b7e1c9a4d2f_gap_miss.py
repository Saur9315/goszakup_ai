"""gap miss

Revision ID: 3b7e1c9a4d2f
Revises: 655e7d666f2f
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b7e1c9a4d2f"
down_revision: str | None = "655e7d666f2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gap_miss",
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("entity", "id", name=op.f("pk_gap_miss")),
        schema="meta",
    )


def downgrade() -> None:
    op.drop_table("gap_miss", schema="meta")
