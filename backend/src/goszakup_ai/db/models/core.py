from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from goszakup_ai.db.base import Base

SCHEMA = {"schema": "core"}
AMOUNT = Numeric(20, 4)


class Subject(Base):
    __tablename__ = "subject"
    __table_args__ = SCHEMA

    pid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    bin: Mapped[str | None] = mapped_column(String(12), index=True)
    iin: Mapped[str | None] = mapped_column(String(12), index=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    full_name_ru: Mapped[str | None] = mapped_column(Text)
    is_customer: Mapped[bool | None]
    is_supplier: Mapped[bool | None]
    is_organizer: Mapped[bool | None]
    is_qvazi: Mapped[bool | None]
    is_national_company: Mapped[bool | None]
    is_small_business: Mapped[bool | None]
    supplier_type: Mapped[int | None] = mapped_column(SmallInteger)
    kato_list: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    parent_bin: Mapped[str | None] = mapped_column(String(12))
    country_code: Mapped[str | None] = mapped_column(String(8))
    last_update_date: Mapped[datetime | None]
    index_date: Mapped[datetime | None]


class RefUnit(Base):
    __tablename__ = "ref_unit"
    __table_args__ = SCHEMA

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    code2: Mapped[str | None] = mapped_column(String(16))
    alpha_code: Mapped[str | None] = mapped_column(Text)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)


class RefUnitNorm(Base):
    __tablename__ = "ref_unit_norm"
    __table_args__ = SCHEMA

    unit_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    canonical_code: Mapped[str] = mapped_column(String(16))
    factor: Mapped[Decimal] = mapped_column(Numeric(20, 9))
    dimension: Mapped[str] = mapped_column(String(16))
    comparable: Mapped[bool]


class RefKato(Base):
    __tablename__ = "ref_kato"
    __table_args__ = SCHEMA

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(String(16), index=True)
    level: Mapped[int | None] = mapped_column(SmallInteger)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    full_name_ru: Mapped[str | None] = mapped_column(Text)
    full_name_kz: Mapped[str | None] = mapped_column(Text)


class RefEnstru(Base):
    __tablename__ = "ref_enstru"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(32), index=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    level: Mapped[int | None] = mapped_column(SmallInteger)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    desc_ru: Mapped[str | None] = mapped_column(Text)
    unit_name: Mapped[str | None] = mapped_column(Text)
    unit_mkei: Mapped[int | None] = mapped_column(Integer)


class RefDict(Base):
    __tablename__ = "ref_dict"
    __table_args__ = SCHEMA

    dict_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    code: Mapped[str | None] = mapped_column(String(64))
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class PlanPoint(Base):
    __tablename__ = "plan_point"
    __table_args__ = (
        Index("ix_core_plan_point_customer_enstru", "customer_bin", "enstru_code"),
        SCHEMA,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    root_record_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    year: Mapped[int | None] = mapped_column(SmallInteger, index=True)
    customer_pid: Mapped[int | None] = mapped_column(BigInteger)
    customer_bin: Mapped[str | None] = mapped_column(String(12), index=True)
    organizer_pid: Mapped[int | None] = mapped_column(BigInteger)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    name_clean: Mapped[str | None] = mapped_column(Text)
    desc_ru: Mapped[str | None] = mapped_column(Text)
    desc_kz: Mapped[str | None] = mapped_column(Text)
    extra_desc_ru: Mapped[str | None] = mapped_column(Text)
    extra_desc_kz: Mapped[str | None] = mapped_column(Text)
    enstru_id: Mapped[int | None] = mapped_column(BigInteger)
    enstru_code: Mapped[str | None] = mapped_column(String(32), index=True)
    unit_code: Mapped[str | None] = mapped_column(String(16))
    quantity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    trade_method_id: Mapped[int | None]
    subject_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    status_id: Mapped[int | None]
    month_id: Mapped[int | None] = mapped_column(SmallInteger)
    finsource_id: Mapped[int | None]
    point_type_id: Mapped[int | None]
    is_qvazi: Mapped[bool | None]
    is_deleted: Mapped[bool | None]
    is_active: Mapped[bool | None]
    created_at: Mapped[datetime | None]
    updated_at: Mapped[datetime | None]
    index_date: Mapped[datetime | None]


class PlanPointKato(Base):
    __tablename__ = "plan_point_kato"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    plan_point_id: Mapped[int] = mapped_column(
        ForeignKey("core.plan_point.id", ondelete="CASCADE"), index=True
    )
    kato_code: Mapped[str | None] = mapped_column(String(16), index=True)
    country_code: Mapped[str | None] = mapped_column(String(8))
    delivery_place_ru: Mapped[str | None] = mapped_column(Text)
    delivery_place_kz: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    is_active: Mapped[bool | None]
    is_deleted: Mapped[bool | None]


class TrdBuy(Base):
    __tablename__ = "trd_buy"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    number_anno: Mapped[str | None] = mapped_column(String(32), index=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    total_sum: Mapped[Decimal | None] = mapped_column(AMOUNT)
    count_lots: Mapped[int | None]
    trade_method_id: Mapped[int | None]
    subject_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    status_id: Mapped[int | None]
    type_trade_id: Mapped[int | None]
    org_pid: Mapped[int | None] = mapped_column(BigInteger)
    org_bin: Mapped[str | None] = mapped_column(String(12), index=True)
    single_supplier_biin: Mapped[str | None] = mapped_column(String(12))
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    publish_date: Mapped[datetime | None]
    start_date: Mapped[datetime | None]
    end_date: Mapped[datetime | None]
    itogi_date_public: Mapped[datetime | None]
    fin_years: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    kato_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    is_construction_work: Mapped[bool | None]
    last_update_date: Mapped[datetime | None]
    index_date: Mapped[datetime | None]


class Lot(Base):
    __tablename__ = "lot"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    lot_number: Mapped[str | None] = mapped_column(String(64), index=True)
    trd_buy_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    number_anno: Mapped[str | None] = mapped_column(String(32))
    customer_pid: Mapped[int | None] = mapped_column(BigInteger)
    customer_bin: Mapped[str | None] = mapped_column(String(12), index=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    name_clean: Mapped[str | None] = mapped_column(Text)
    description_ru: Mapped[str | None] = mapped_column(Text)
    description_kz: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    status_id: Mapped[int | None]
    plan_trade_method_id: Mapped[int | None]
    fact_trade_method_id: Mapped[int | None]
    is_union: Mapped[bool | None]
    is_dumping: Mapped[bool | None]
    is_construction_work: Mapped[bool | None]
    enstru_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    kato_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    is_deleted: Mapped[bool | None]
    last_update_date: Mapped[datetime | None]
    index_date: Mapped[datetime | None]


class LotPlanPoint(Base):
    __tablename__ = "lot_plan_point"
    __table_args__ = SCHEMA

    lot_id: Mapped[int] = mapped_column(
        ForeignKey("core.lot.id", ondelete="CASCADE"), primary_key=True
    )
    plan_point_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)


class Contract(Base):
    __tablename__ = "contract"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    root_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    contract_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    number: Mapped[str | None] = mapped_column(Text)
    number_sys: Mapped[str | None] = mapped_column(String(64))
    trd_buy_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    number_anno: Mapped[str | None] = mapped_column(String(32))
    customer_pid: Mapped[int | None] = mapped_column(BigInteger)
    customer_bin: Mapped[str | None] = mapped_column(String(12), index=True)
    supplier_pid: Mapped[int | None] = mapped_column(BigInteger)
    supplier_biin: Mapped[str | None] = mapped_column(String(12), index=True)
    status_id: Mapped[int | None]
    fakt_trade_method_id: Mapped[int | None]
    subject_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    fin_year: Mapped[int | None] = mapped_column(SmallInteger, index=True)
    year_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    finsource_id: Mapped[int | None]
    sign_date: Mapped[datetime | None]
    plan_exec_date: Mapped[datetime | None]
    fakt_exec_date: Mapped[datetime | None]
    end_date: Mapped[datetime | None]
    contract_sum: Mapped[Decimal | None] = mapped_column(AMOUNT)
    contract_sum_wnds: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fakt_sum: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fakt_sum_wnds: Mapped[Decimal | None] = mapped_column(AMOUNT)
    with_nds: Mapped[bool | None]
    currency_code: Mapped[str | None] = mapped_column(String(8))
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    cancel_id: Mapped[int | None]
    is_deleted: Mapped[bool | None]
    created_at: Mapped[datetime | None]
    last_update_date: Mapped[datetime | None]
    index_date: Mapped[datetime | None]


class ContractUnit(Base):
    __tablename__ = "contract_unit"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("core.contract.id", ondelete="CASCADE"), index=True
    )
    root_id: Mapped[int | None] = mapped_column(BigInteger)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    lot_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    plan_point_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    trd_buy_id: Mapped[int | None] = mapped_column(BigInteger)
    enstru_code: Mapped[str | None] = mapped_column(String(32), index=True)
    item_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    item_price_wnds: Mapped[Decimal | None] = mapped_column(AMOUNT)
    quantity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    total_sum: Mapped[Decimal | None] = mapped_column(AMOUNT)
    total_sum_wnds: Mapped[Decimal | None] = mapped_column(AMOUNT)
    contract_sum: Mapped[Decimal | None] = mapped_column(AMOUNT)
    contract_sum_wnds: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fact_sum: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fact_sum_wnds: Mapped[Decimal | None] = mapped_column(AMOUNT)
    status_id: Mapped[int | None]
    is_executed: Mapped[bool | None]
    is_deleted: Mapped[bool | None]
    exec_plan_date: Mapped[datetime | None]
    exec_fakt_date: Mapped[datetime | None]
    created_at: Mapped[datetime | None]
    index_date: Mapped[datetime | None]
