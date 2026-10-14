"""initial schema

Revision ID: 038d05591b0f
Revises:
Create Date: 2026-10-14 21:05:59.905818
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "038d05591b0f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMAS = ("raw", "core", "meta", "mart")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.create_table(
        "contract",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("root_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("contract_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("number_sys", sa.String(length=64), nullable=True),
        sa.Column("trd_buy_id", sa.BigInteger(), nullable=True),
        sa.Column("number_anno", sa.String(length=32), nullable=True),
        sa.Column("customer_pid", sa.BigInteger(), nullable=True),
        sa.Column("customer_bin", sa.String(length=12), nullable=True),
        sa.Column("supplier_pid", sa.BigInteger(), nullable=True),
        sa.Column("supplier_biin", sa.String(length=12), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("fakt_trade_method_id", sa.Integer(), nullable=True),
        sa.Column("subject_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("fin_year", sa.SmallInteger(), nullable=True),
        sa.Column("year_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("finsource_id", sa.Integer(), nullable=True),
        sa.Column("sign_date", sa.DateTime(), nullable=True),
        sa.Column("plan_exec_date", sa.DateTime(), nullable=True),
        sa.Column("fakt_exec_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("contract_sum", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("contract_sum_wnds", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("fakt_sum", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("fakt_sum_wnds", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("with_nds", sa.Boolean(), nullable=True),
        sa.Column("currency_code", sa.String(length=8), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("cancel_id", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_update_date", sa.DateTime(), nullable=True),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contract")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_customer_bin"),
        "contract",
        ["customer_bin"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_fin_year"), "contract", ["fin_year"], unique=False, schema="core"
    )
    op.create_index(
        op.f("ix_core_contract_root_id"), "contract", ["root_id"], unique=False, schema="core"
    )
    op.create_index(
        op.f("ix_core_contract_supplier_biin"),
        "contract",
        ["supplier_biin"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_trd_buy_id"), "contract", ["trd_buy_id"], unique=False, schema="core"
    )
    op.create_table(
        "lot",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("lot_number", sa.String(length=64), nullable=True),
        sa.Column("trd_buy_id", sa.BigInteger(), nullable=True),
        sa.Column("number_anno", sa.String(length=32), nullable=True),
        sa.Column("customer_pid", sa.BigInteger(), nullable=True),
        sa.Column("customer_bin", sa.String(length=12), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("description_ru", sa.Text(), nullable=True),
        sa.Column("description_kz", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("plan_trade_method_id", sa.Integer(), nullable=True),
        sa.Column("fact_trade_method_id", sa.Integer(), nullable=True),
        sa.Column("is_union", sa.Boolean(), nullable=True),
        sa.Column("is_dumping", sa.Boolean(), nullable=True),
        sa.Column("is_construction_work", sa.Boolean(), nullable=True),
        sa.Column("enstru_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("kato_codes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("last_update_date", sa.DateTime(), nullable=True),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lot")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_lot_customer_bin"), "lot", ["customer_bin"], unique=False, schema="core"
    )
    op.create_index(
        op.f("ix_core_lot_lot_number"), "lot", ["lot_number"], unique=False, schema="core"
    )
    op.create_index(
        op.f("ix_core_lot_trd_buy_id"), "lot", ["trd_buy_id"], unique=False, schema="core"
    )
    op.create_table(
        "plan_point",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("root_record_id", sa.BigInteger(), nullable=True),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("customer_pid", sa.BigInteger(), nullable=True),
        sa.Column("customer_bin", sa.String(length=12), nullable=True),
        sa.Column("organizer_pid", sa.BigInteger(), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("desc_ru", sa.Text(), nullable=True),
        sa.Column("desc_kz", sa.Text(), nullable=True),
        sa.Column("extra_desc_ru", sa.Text(), nullable=True),
        sa.Column("extra_desc_kz", sa.Text(), nullable=True),
        sa.Column("enstru_id", sa.BigInteger(), nullable=True),
        sa.Column("enstru_code", sa.String(length=32), nullable=True),
        sa.Column("unit_code", sa.String(length=16), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("price", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("trade_method_id", sa.Integer(), nullable=True),
        sa.Column("subject_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("month_id", sa.SmallInteger(), nullable=True),
        sa.Column("finsource_id", sa.Integer(), nullable=True),
        sa.Column("point_type_id", sa.Integer(), nullable=True),
        sa.Column("is_qvazi", sa.Boolean(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_point")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_plan_point_customer_bin"),
        "plan_point",
        ["customer_bin"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_plan_point_enstru_code"),
        "plan_point",
        ["enstru_code"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_plan_point_year"), "plan_point", ["year"], unique=False, schema="core"
    )
    op.create_table(
        "ref_dict",
        sa.Column("dict_name", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("dict_name", "id", name=op.f("pk_ref_dict")),
        schema="core",
    )
    op.create_table(
        "ref_enstru",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("desc_ru", sa.Text(), nullable=True),
        sa.Column("unit_name", sa.Text(), nullable=True),
        sa.Column("unit_mkei", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ref_enstru")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_ref_enstru_code"), "ref_enstru", ["code"], unique=False, schema="core"
    )
    op.create_table(
        "ref_kato",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("parent_code", sa.String(length=16), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("full_name_ru", sa.Text(), nullable=True),
        sa.Column("full_name_kz", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_kato")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_ref_kato_parent_code"),
        "ref_kato",
        ["parent_code"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "ref_unit",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("code2", sa.String(length=16), nullable=True),
        sa.Column("alpha_code", sa.Text(), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_ref_unit")),
        schema="core",
    )
    op.create_table(
        "subject",
        sa.Column("pid", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("bin", sa.String(length=12), nullable=True),
        sa.Column("iin", sa.String(length=12), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("full_name_ru", sa.Text(), nullable=True),
        sa.Column("is_customer", sa.Boolean(), nullable=True),
        sa.Column("is_supplier", sa.Boolean(), nullable=True),
        sa.Column("is_organizer", sa.Boolean(), nullable=True),
        sa.Column("is_qvazi", sa.Boolean(), nullable=True),
        sa.Column("is_national_company", sa.Boolean(), nullable=True),
        sa.Column("is_small_business", sa.Boolean(), nullable=True),
        sa.Column("supplier_type", sa.SmallInteger(), nullable=True),
        sa.Column("kato_list", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("parent_bin", sa.String(length=12), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("last_update_date", sa.DateTime(), nullable=True),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("pid", name=op.f("pk_subject")),
        schema="core",
    )
    op.create_index(op.f("ix_core_subject_bin"), "subject", ["bin"], unique=False, schema="core")
    op.create_index(op.f("ix_core_subject_iin"), "subject", ["iin"], unique=False, schema="core")
    op.create_table(
        "trd_buy",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("number_anno", sa.String(length=32), nullable=True),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("name_kz", sa.Text(), nullable=True),
        sa.Column("total_sum", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("count_lots", sa.Integer(), nullable=True),
        sa.Column("trade_method_id", sa.Integer(), nullable=True),
        sa.Column("subject_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("type_trade_id", sa.Integer(), nullable=True),
        sa.Column("org_pid", sa.BigInteger(), nullable=True),
        sa.Column("org_bin", sa.String(length=12), nullable=True),
        sa.Column("single_supplier_biin", sa.String(length=12), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("publish_date", sa.DateTime(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("itogi_date_public", sa.DateTime(), nullable=True),
        sa.Column("fin_years", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("kato_codes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("is_construction_work", sa.Boolean(), nullable=True),
        sa.Column("last_update_date", sa.DateTime(), nullable=True),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trd_buy")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_trd_buy_number_anno"), "trd_buy", ["number_anno"], unique=False, schema="core"
    )
    op.create_index(
        op.f("ix_core_trd_buy_org_bin"), "trd_buy", ["org_bin"], unique=False, schema="core"
    )
    op.create_table(
        "dq_check_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("check_name", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("failed_count", sa.BigInteger(), nullable=False),
        sa.Column("total_count", sa.BigInteger(), nullable=False),
        sa.Column("sample", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("checked_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dq_check_result")),
        schema="meta",
    )
    op.create_table(
        "scope_bin",
        sa.Column("bin", sa.String(length=12), nullable=False),
        sa.Column("name_ru", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("bin", name=op.f("pk_scope_bin")),
        schema="meta",
    )
    op.create_table(
        "sync_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("command", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_run")),
        schema="meta",
    )
    op.create_table(
        "sync_state",
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("last_index_date", sa.DateTime(), nullable=True),
        sa.Column(
            "last_success_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("rows_loaded", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("entity", "scope_key", name=op.f("pk_sync_state")),
        schema="meta",
    )
    op.create_table(
        "ows_object",
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("entity", "source_key", name=op.f("pk_ows_object")),
        schema="raw",
    )
    op.create_table(
        "contract_unit",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("root_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("lot_id", sa.BigInteger(), nullable=True),
        sa.Column("plan_point_id", sa.BigInteger(), nullable=True),
        sa.Column("trd_buy_id", sa.BigInteger(), nullable=True),
        sa.Column("enstru_code", sa.String(length=32), nullable=True),
        sa.Column("item_price", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("item_price_wnds", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("total_sum", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("total_sum_wnds", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("contract_sum", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("contract_sum_wnds", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("fact_sum", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("fact_sum_wnds", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("is_executed", sa.Boolean(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("exec_plan_date", sa.DateTime(), nullable=True),
        sa.Column("exec_fakt_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("index_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["core.contract.id"],
            name=op.f("fk_contract_unit_contract_id_contract"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contract_unit")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_unit_contract_id"),
        "contract_unit",
        ["contract_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_unit_enstru_code"),
        "contract_unit",
        ["enstru_code"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_unit_lot_id"),
        "contract_unit",
        ["lot_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_contract_unit_plan_point_id"),
        "contract_unit",
        ["plan_point_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "lot_plan_point",
        sa.Column("lot_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_point_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["core.lot.id"],
            name=op.f("fk_lot_plan_point_lot_id_lot"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("lot_id", "plan_point_id", name=op.f("pk_lot_plan_point")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_lot_plan_point_plan_point_id"),
        "lot_plan_point",
        ["plan_point_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "plan_point_kato",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("plan_point_id", sa.BigInteger(), nullable=False),
        sa.Column("kato_code", sa.String(length=16), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("delivery_place_ru", sa.Text(), nullable=True),
        sa.Column("delivery_place_kz", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_point_id"],
            ["core.plan_point.id"],
            name=op.f("fk_plan_point_kato_plan_point_id_plan_point"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_point_kato")),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_plan_point_kato_kato_code"),
        "plan_point_kato",
        ["kato_code"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_plan_point_kato_plan_point_id"),
        "plan_point_kato",
        ["plan_point_id"],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_core_plan_point_kato_plan_point_id"), table_name="plan_point_kato", schema="core"
    )
    op.drop_index(
        op.f("ix_core_plan_point_kato_kato_code"), table_name="plan_point_kato", schema="core"
    )
    op.drop_table("plan_point_kato", schema="core")
    op.drop_index(
        op.f("ix_core_lot_plan_point_plan_point_id"), table_name="lot_plan_point", schema="core"
    )
    op.drop_table("lot_plan_point", schema="core")
    op.drop_index(
        op.f("ix_core_contract_unit_plan_point_id"), table_name="contract_unit", schema="core"
    )
    op.drop_index(op.f("ix_core_contract_unit_lot_id"), table_name="contract_unit", schema="core")
    op.drop_index(
        op.f("ix_core_contract_unit_enstru_code"), table_name="contract_unit", schema="core"
    )
    op.drop_index(
        op.f("ix_core_contract_unit_contract_id"), table_name="contract_unit", schema="core"
    )
    op.drop_table("contract_unit", schema="core")
    op.drop_table("ows_object", schema="raw")
    op.drop_table("sync_state", schema="meta")
    op.drop_table("sync_run", schema="meta")
    op.drop_table("scope_bin", schema="meta")
    op.drop_table("dq_check_result", schema="meta")
    op.drop_index(op.f("ix_core_trd_buy_org_bin"), table_name="trd_buy", schema="core")
    op.drop_index(op.f("ix_core_trd_buy_number_anno"), table_name="trd_buy", schema="core")
    op.drop_table("trd_buy", schema="core")
    op.drop_index(op.f("ix_core_subject_iin"), table_name="subject", schema="core")
    op.drop_index(op.f("ix_core_subject_bin"), table_name="subject", schema="core")
    op.drop_table("subject", schema="core")
    op.drop_table("ref_unit", schema="core")
    op.drop_index(op.f("ix_core_ref_kato_parent_code"), table_name="ref_kato", schema="core")
    op.drop_table("ref_kato", schema="core")
    op.drop_index(op.f("ix_core_ref_enstru_code"), table_name="ref_enstru", schema="core")
    op.drop_table("ref_enstru", schema="core")
    op.drop_table("ref_dict", schema="core")
    op.drop_index(op.f("ix_core_plan_point_year"), table_name="plan_point", schema="core")
    op.drop_index(op.f("ix_core_plan_point_enstru_code"), table_name="plan_point", schema="core")
    op.drop_index(op.f("ix_core_plan_point_customer_bin"), table_name="plan_point", schema="core")
    op.drop_table("plan_point", schema="core")
    op.drop_index(op.f("ix_core_lot_trd_buy_id"), table_name="lot", schema="core")
    op.drop_index(op.f("ix_core_lot_lot_number"), table_name="lot", schema="core")
    op.drop_index(op.f("ix_core_lot_customer_bin"), table_name="lot", schema="core")
    op.drop_table("lot", schema="core")
    op.drop_index(op.f("ix_core_contract_trd_buy_id"), table_name="contract", schema="core")
    op.drop_index(op.f("ix_core_contract_supplier_biin"), table_name="contract", schema="core")
    op.drop_index(op.f("ix_core_contract_root_id"), table_name="contract", schema="core")
    op.drop_index(op.f("ix_core_contract_fin_year"), table_name="contract", schema="core")
    op.drop_index(op.f("ix_core_contract_customer_bin"), table_name="contract", schema="core")
    op.drop_table("contract", schema="core")
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
