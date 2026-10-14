"""normalization: unit map, clean names, tz audit times

Revision ID: fc782075050c
Revises: 038d05591b0f
Create Date: 2026-10-14 21:32:52.820264
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fc782075050c"
down_revision: str | None = "038d05591b0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UNIT_NORM = [
    # unit_code, canonical_code, factor, dimension, comparable
    ("166", "166", "1", "mass", True),
    ("168", "166", "1000", "mass", True),
    ("163", "166", "0.001", "mass", True),
    ("112", "112", "1", "volume", True),
    ("111", "112", "0.001", "volume", True),
    ("113", "112", "1000", "volume", True),
    ("116", "112", "10", "volume", True),
    ("122", "112", "100", "volume", True),
    ("006", "006", "1", "length", True),
    ("018", "006", "1", "length", True),
    ("5156", "006", "1", "length", True),
    ("001", "006", "0.000000001", "length", True),
    ("055", "055", "1", "area", True),
    ("081", "055", "1", "area", True),
    ("796", "796", "1", "count", True),
    ("797", "796", "100", "count", True),
    ("642", "796", "1", "count", True),
    ("715", "715", "1", "count", True),
    ("245", "245", "1", "energy", True),
    ("214", "214", "1", "power", True),
    ("5114", "5114", "1", "service", False),
    ("980", "980", "1", "service", False),
    ("365", "365", "1", "time", False),
    *[
        (code, code, "1", "package", True)
        for code in (
            "778",
            "5111",
            "704",
            "839",
            "872",
            "868",
            "736",
            "881",
            "870",
            "625",
            "5108",
            "639",
            "616",
            "889",
            "879",
            "179",
            "062",
            "876",
            "972",
            "547",
            "316",
        )
    ],
]


def upgrade() -> None:
    op.create_table(
        "ref_unit_norm",
        sa.Column("unit_code", sa.String(length=16), nullable=False),
        sa.Column("canonical_code", sa.String(length=16), nullable=False),
        sa.Column("factor", sa.Numeric(precision=20, scale=9), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("comparable", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("unit_code", name=op.f("pk_ref_unit_norm")),
        schema="core",
    )
    op.add_column("lot", sa.Column("name_clean", sa.Text(), nullable=True), schema="core")
    op.add_column("plan_point", sa.Column("name_clean", sa.Text(), nullable=True), schema="core")
    op.create_index(
        "ix_core_plan_point_customer_enstru",
        "plan_point",
        ["customer_bin", "enstru_code"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_plan_point_root_record_id"),
        "plan_point",
        ["root_record_id"],
        unique=False,
        schema="core",
    )
    op.alter_column(
        "dq_check_result",
        "checked_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "scope_bin",
        "added_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "sync_run",
        "started_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "sync_run",
        "finished_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        schema="meta",
    )
    op.alter_column(
        "sync_state",
        "last_success_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "ows_object",
        "fetched_at",
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="raw",
    )
    unit_norm = sa.table(
        "ref_unit_norm",
        sa.column("unit_code", sa.String),
        sa.column("canonical_code", sa.String),
        sa.column("factor", sa.Numeric),
        sa.column("dimension", sa.String),
        sa.column("comparable", sa.Boolean),
        schema="core",
    )
    op.bulk_insert(
        unit_norm,
        [
            dict(
                zip(
                    ("unit_code", "canonical_code", "factor", "dimension", "comparable"),
                    row,
                    strict=True,
                )
            )
            for row in UNIT_NORM
        ],
    )


def downgrade() -> None:
    op.alter_column(
        "ows_object",
        "fetched_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="raw",
    )
    op.alter_column(
        "sync_state",
        "last_success_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "sync_run",
        "finished_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
        schema="meta",
    )
    op.alter_column(
        "sync_run",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "scope_bin",
        "added_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.alter_column(
        "dq_check_result",
        "checked_at",
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        schema="meta",
    )
    op.drop_index(op.f("ix_core_plan_point_root_record_id"), table_name="plan_point", schema="core")
    op.drop_index("ix_core_plan_point_customer_enstru", table_name="plan_point", schema="core")
    op.drop_column("plan_point", "name_clean", schema="core")
    op.drop_column("lot", "name_clean", schema="core")
    op.drop_table("ref_unit_norm", schema="core")
