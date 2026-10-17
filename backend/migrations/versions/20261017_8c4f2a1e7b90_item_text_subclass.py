"""item text embeddings and subclasses

Revision ID: 8c4f2a1e7b90
Revises: 3b7e1c9a4d2f
Create Date: 2026-10-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from goszakup_ai.db.models.core import Vector

revision: str = "8c4f2a1e7b90"
down_revision: str | None = "3b7e1c9a4d2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item_text",
        sa.Column("text_key", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("text_key", name=op.f("pk_item_text")),
        schema="core",
    )
    op.create_table(
        "item_subclass",
        sa.Column("enstru_code", sa.String(length=32), nullable=False),
        sa.Column("text_key", sa.String(length=32), nullable=False),
        sa.Column("subclass", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("enstru_code", "text_key", name=op.f("pk_item_subclass")),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("item_subclass", schema="core")
    op.drop_table("item_text", schema="core")
