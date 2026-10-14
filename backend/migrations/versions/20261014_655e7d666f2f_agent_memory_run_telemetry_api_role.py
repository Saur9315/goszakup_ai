"""agent memory, run telemetry, api role

Revision ID: 655e7d666f2f
Revises: 624c24e31366
Create Date: 2026-10-14 22:59:16.955758
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "655e7d666f2f"
down_revision: str | None = "624c24e31366"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


API_ROLE = "goszakup_api"


def upgrade() -> None:
    op.add_column("analysis_run", sa.Column("thread_id", sa.Uuid(), nullable=True), schema="meta")
    op.add_column(
        "analysis_run", sa.Column("kind", sa.String(length=16), nullable=True), schema="meta"
    )
    op.add_column(
        "analysis_run", sa.Column("llm_fallback", sa.Boolean(), nullable=True), schema="meta"
    )
    op.add_column(
        "analysis_run",
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="meta",
    )
    op.add_column(
        "analysis_run",
        sa.Column("timings_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="meta",
    )
    op.add_column(
        "analysis_run",
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        schema="meta",
    )
    op.create_index(
        op.f("ix_meta_analysis_run_thread_id"),
        "analysis_run",
        ["thread_id"],
        unique=False,
        schema="meta",
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{API_ROLE}') "
        f"THEN CREATE ROLE {API_ROLE} NOLOGIN; END IF; END $$"
    )
    for schema in ("core", "mart", "meta"):
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {API_ROLE}")
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {API_ROLE}")
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {API_ROLE}"
        )
    op.execute(f"GRANT INSERT ON meta.analysis_run TO {API_ROLE}")
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA agent TO {API_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT ALL ON TABLES TO {API_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT ALL ON SEQUENCES TO {API_ROLE}")


def downgrade() -> None:
    for schema in ("core", "mart", "meta", "agent"):
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {API_ROLE}"
        )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA agent REVOKE ALL ON SEQUENCES FROM {API_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA core, mart, meta FROM {API_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA core, mart, meta, agent FROM {API_ROLE}")
    op.execute("DROP SCHEMA IF EXISTS agent CASCADE")
    op.drop_index(op.f("ix_meta_analysis_run_thread_id"), table_name="analysis_run", schema="meta")
    op.drop_column("analysis_run", "prompt_version", schema="meta")
    op.drop_column("analysis_run", "timings_ms", schema="meta")
    op.drop_column("analysis_run", "usage", schema="meta")
    op.drop_column("analysis_run", "llm_fallback", schema="meta")
    op.drop_column("analysis_run", "kind", schema="meta")
    op.drop_column("analysis_run", "thread_id", schema="meta")
