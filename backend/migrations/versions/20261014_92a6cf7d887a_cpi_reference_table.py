"""cpi reference table

Revision ID: 92a6cf7d887a
Revises: fc782075050c
Create Date: 2026-10-14 21:58:50.814874
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "92a6cf7d887a"
down_revision: str | None = "fc782075050c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ref_cpi",
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("cpi_mom_pct", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("food_mom_pct", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("nonfood_mom_pct", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("services_mom_pct", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("month", name=op.f("pk_ref_cpi")),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("ref_cpi", schema="core")
