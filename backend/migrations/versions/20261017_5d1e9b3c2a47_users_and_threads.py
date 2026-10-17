"""users and thread ownership

Revision ID: 5d1e9b3c2a47
Revises: 8c4f2a1e7b90
Create Date: 2026-10-17 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d1e9b3c2a47"
down_revision: str | None = "8c4f2a1e7b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_ROLE = "goszakup_api"


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("username", name=op.f("uq_app_user_username")),
        schema="meta",
    )
    op.create_table(
        "agent_thread",
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["meta.app_user.id"], name=op.f("fk_agent_thread_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("thread_id", name=op.f("pk_agent_thread")),
        schema="meta",
    )
    op.create_index(
        "ix_meta_agent_thread_user", "agent_thread", ["user_id", "updated_at"], schema="meta"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON meta.agent_thread TO {API_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_meta_agent_thread_user", table_name="agent_thread", schema="meta")
    op.drop_table("agent_thread", schema="meta")
    op.drop_table("app_user", schema="meta")
