from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

Row = dict[str, Any]

KZ_TZ = ZoneInfo("Asia/Almaty")


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.startswith("0000"):
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(KZ_TZ).replace(tzinfo=None)
    return dt


def as_dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return bool(int(value))


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def subject_row(s: Row) -> Row:
    return {
        "pid": int(s["pid"]),
        "bin": as_str(s.get("bin")),
        "iin": as_str(s.get("iin")),
        "name_ru": as_str(s.get("nameRu")),
        "name_kz": as_str(s.get("nameKz")),
        "full_name_ru": as_str(s.get("fullNameRu")),
        "is_customer": as_bool(s.get("customer")),
        "is_supplier": as_bool(s.get("supplier")),
        "is_organizer": as_bool(s.get("organizer")),
        "is_qvazi": as_bool(s.get("qvazi")),
        "is_national_company": as_bool(s.get("markNationalCompany")),
        "is_small_business": as_bool(s.get("markSmallEmployer")),
        "supplier_type": as_int(s.get("typeSupplier")),
        "kato_list": s.get("katoList") or None,
        "parent_bin": as_str(s.get("parentSubject")),
        "country_code": as_str(s.get("countryCode")),
        "last_update_date": parse_dt(s.get("lastUpdateDate")),
        "index_date": parse_dt(s.get("indexDate")),
    }


@dataclass
class PlanPointRows:
    plan_point: Row
    katos: list[Row] = field(default_factory=list)
    enstru: Row | None = None


def plan_point_rows(p: Row) -> PlanPointRows:
    pp_id = int(p["id"])
    plan_point = {
        "id": pp_id,
        "root_record_id": as_int(p.get("rootrecordId")),
        "year": as_int(p.get("plnPointYear")),
        "customer_pid": as_int(p.get("sysSubjectsId")),
        "customer_bin": as_str(p.get("subjectBiin")),
        "organizer_pid": as_int(p.get("sysOrganizatorId")),
        "name_ru": as_str(p.get("nameRu")),
        "name_kz": as_str(p.get("nameKz")),
        "desc_ru": as_str(p.get("descRu")),
        "desc_kz": as_str(p.get("descKz")),
        "extra_desc_ru": as_str(p.get("extraDescRu")),
        "extra_desc_kz": as_str(p.get("extraDescKz")),
        "enstru_id": as_int(p.get("refEnstruId")),
        "enstru_code": as_str(p.get("refEnstruCode")),
        "unit_code": as_str(p.get("refUnitsCode")),
        "quantity": as_dec(p.get("count")),
        "price": as_dec(p.get("price")),
        "amount": as_dec(p.get("amount")),
        "trade_method_id": as_int(p.get("refTradeMethodsId")),
        "subject_type_id": as_int(p.get("refSubjectTypeId")),
        "status_id": as_int(p.get("refPlnPointStatusId")),
        "month_id": as_int(p.get("refMonthsId")),
        "finsource_id": as_int(p.get("refFinsourceId")),
        "point_type_id": as_int(p.get("refPointTypeId")),
        "is_qvazi": as_bool(p.get("isQvazi")),
        "is_deleted": as_bool(p.get("isDeleted")),
        "is_active": as_bool(p.get("isActive")),
        "created_at": parse_dt(p.get("dateCreate")),
        "updated_at": parse_dt(p.get("timestamp")),
        "index_date": parse_dt(p.get("indexDate")),
    }
    katos = [
        {
            "id": int(k["id"]),
            "plan_point_id": pp_id,
            "kato_code": as_str(k.get("refKatoCode")),
            "country_code": as_str(k.get("refCountriesCode")),
            "delivery_place_ru": as_str(k.get("fullDeliveryPlaceNameRu")),
            "delivery_place_kz": as_str(k.get("fullDeliveryPlaceNameKz")),
            "quantity": as_dec(k.get("count")),
            "is_active": as_bool(k.get("isActive")),
            "is_deleted": as_bool(k.get("isDeleted")),
        }
        for k in p.get("PlansKato") or []
    ]
    e = p.get("RefEnstru")
    enstru = None
    if e and e.get("id") and e.get("code"):
        enstru = {
            "id": int(e["id"]),
            "code": e["code"],
            "parent_id": as_int(e.get("parentId")),
            "level": as_int(e.get("level")),
            "name_ru": as_str(e.get("nameRu")),
            "name_kz": as_str(e.get("nameKz")),
            "desc_ru": as_str(e.get("descRu")),
            "unit_name": as_str(e.get("edizm")),
            "unit_mkei": as_int(e.get("mkei")),
        }
    return PlanPointRows(plan_point, katos, enstru)


@dataclass
class ContractRows:
    contract: Row
    units: list[Row] = field(default_factory=list)
    subjects: list[Row] = field(default_factory=list)


def contract_rows(c: Row) -> ContractRows:
    contract_id = int(c["id"])
    contract = {
        "id": contract_id,
        "root_id": as_int(c.get("rootId")),
        "parent_id": as_int(c.get("parentId")),
        "contract_type_id": as_int(c.get("refContractTypeId")),
        "number": as_str(c.get("contractNumber")),
        "number_sys": as_str(c.get("contractNumberSys")),
        "trd_buy_id": as_int(c.get("trdBuyId")),
        "number_anno": as_str(c.get("trdBuyNumberAnno")),
        "customer_pid": as_int(c.get("customerId")),
        "customer_bin": as_str(c.get("customerBin")),
        "supplier_pid": as_int(c.get("supplierId")),
        "supplier_biin": as_str(c.get("supplierBiin")),
        "status_id": as_int(c.get("refContractStatusId")),
        "fakt_trade_method_id": as_int(c.get("faktTradeMethodsId")),
        "subject_type_id": as_int(c.get("refSubjectTypeId")),
        "fin_year": as_int(c.get("finYear")),
        "year_type_id": as_int(c.get("refContractYearTypeId")),
        "finsource_id": as_int(c.get("refFinsourceId")),
        "sign_date": parse_dt(c.get("signDate")),
        "plan_exec_date": parse_dt(c.get("planExecDate")),
        "fakt_exec_date": parse_dt(c.get("faktExecDate")),
        "end_date": parse_dt(c.get("contractEndDate")),
        "contract_sum": as_dec(c.get("contractSum")),
        "contract_sum_wnds": as_dec(c.get("contractSumWnds")),
        "fakt_sum": as_dec(c.get("faktSum")),
        "fakt_sum_wnds": as_dec(c.get("faktSumWnds")),
        "with_nds": as_bool(c.get("withNds")),
        "currency_code": as_str(c.get("refCurrencyCode")),
        "exchange_rate": as_dec(c.get("exchangeRate")),
        "cancel_id": as_int(c.get("refContractCancelId")),
        "is_deleted": as_bool(c.get("deleted")),
        "created_at": parse_dt(c.get("crdate")),
        "last_update_date": parse_dt(c.get("lastUpdateDate")),
        "index_date": parse_dt(c.get("indexDate")),
    }
    units = []
    for u in c.get("ContractUnits") or []:
        codes = u.get("refEnstruCode") or []
        units.append(
            {
                "id": int(u["id"]),
                "contract_id": contract_id,
                "root_id": as_int(u.get("rootId")),
                "parent_id": as_int(u.get("parentId")),
                "lot_id": as_int(u.get("lotId")),
                "plan_point_id": as_int(u.get("plnPointId")),
                "trd_buy_id": as_int(u.get("trdBuyId")),
                "enstru_code": as_str(codes[0]) if codes else None,
                "item_price": as_dec(u.get("itemPrice")),
                "item_price_wnds": as_dec(u.get("itemPriceWnds")),
                "quantity": as_dec(u.get("quantity")),
                "total_sum": as_dec(u.get("totalSum")),
                "total_sum_wnds": as_dec(u.get("totalSumWnds")),
                "contract_sum": as_dec(u.get("contractSum")),
                "contract_sum_wnds": as_dec(u.get("contractSumWnds")),
                "fact_sum": as_dec(u.get("factSum")),
                "fact_sum_wnds": as_dec(u.get("factSumWnds")),
                "status_id": as_int(u.get("refContractStatusId")),
                "is_executed": as_bool(u.get("executed")),
                "is_deleted": as_bool(u.get("deleted")),
                "exec_plan_date": parse_dt(u.get("execPlanDate")),
                "exec_fakt_date": parse_dt(u.get("execFaktDate")),
                "created_at": parse_dt(u.get("crdate")),
                "index_date": parse_dt(u.get("indexDate")),
            }
        )
    subjects = [
        subject_row(s) for s in (c.get("Supplier"), c.get("Customer")) if s and s.get("pid")
    ]
    return ContractRows(contract, units, subjects)


@dataclass
class LotRows:
    lot: Row
    plan_points: list[Row] = field(default_factory=list)


def lot_rows(item: Row) -> LotRows:
    lot_id = int(item["id"])
    lot = {
        "id": lot_id,
        "lot_number": as_str(item.get("lotNumber")),
        "trd_buy_id": as_int(item.get("trdBuyId")),
        "number_anno": as_str(item.get("trdBuyNumberAnno")),
        "customer_pid": as_int(item.get("customerId")),
        "customer_bin": as_str(item.get("customerBin")),
        "name_ru": as_str(item.get("nameRu")),
        "name_kz": as_str(item.get("nameKz")),
        "description_ru": as_str(item.get("descriptionRu")),
        "description_kz": as_str(item.get("descriptionKz")),
        "quantity": as_dec(item.get("count")),
        "amount": as_dec(item.get("amount")),
        "status_id": as_int(item.get("refLotStatusId")),
        "plan_trade_method_id": as_int(item.get("refTradeMethodsId")),
        "fact_trade_method_id": as_int(item.get("refBuyTradeMethodsId")),
        "is_union": as_bool(item.get("unionLots")),
        "is_dumping": as_bool(item.get("dumping")),
        "is_construction_work": as_bool(item.get("isConstructionWork")),
        "enstru_ids": [int(x) for x in item.get("enstruList") or []] or None,
        "kato_codes": [str(x) for x in item.get("plnPointKatoList") or []] or None,
        "is_deleted": as_bool(item.get("isDeleted")),
        "last_update_date": parse_dt(item.get("lastUpdateDate")),
        "index_date": parse_dt(item.get("indexDate")),
    }
    points = [{"lot_id": lot_id, "plan_point_id": int(pid)} for pid in item.get("pointList") or []]
    return LotRows(lot, points)


def trd_buy_row(t: Row) -> Row:
    return {
        "id": int(t["id"]),
        "number_anno": as_str(t.get("numberAnno")),
        "name_ru": as_str(t.get("nameRu")),
        "name_kz": as_str(t.get("nameKz")),
        "total_sum": as_dec(t.get("totalSum")),
        "count_lots": as_int(t.get("countLots")),
        "trade_method_id": as_int(t.get("refTradeMethodsId")),
        "subject_type_id": as_int(t.get("refSubjectTypeId")),
        "status_id": as_int(t.get("refBuyStatusId")),
        "type_trade_id": as_int(t.get("refTypeTradeId")),
        "org_pid": as_int(t.get("orgPid")),
        "org_bin": as_str(t.get("orgBin")),
        "single_supplier_biin": as_str(t.get("biinSupplier")),
        "parent_id": as_int(t.get("parentId")),
        "publish_date": parse_dt(t.get("publishDate")),
        "start_date": parse_dt(t.get("startDate")),
        "end_date": parse_dt(t.get("endDate")),
        "itogi_date_public": parse_dt(t.get("itogiDatePublic")),
        "fin_years": [int(y) for y in t.get("finYear") or []] or None,
        "kato_codes": [str(k) for k in t.get("kato") or []] or None,
        "is_construction_work": as_bool(t.get("isConstructionWork")),
        "last_update_date": parse_dt(t.get("lastUpdateDate")),
        "index_date": parse_dt(t.get("indexDate")),
    }


def ref_unit_row(r: Row) -> Row:
    return {
        "code": str(r["code"]),
        "code2": as_str(r.get("code2")),
        "alpha_code": as_str(r.get("alpha_code")),
        "name_ru": as_str(r.get("name_ru")),
        "name_kz": as_str(r.get("name_kz")),
    }


def ref_kato_row(r: Row) -> Row:
    return {
        "code": str(r["code"]),
        "parent_code": as_str(r.get("parent_code")),
        "level": as_int(r.get("level_")),
        "name_ru": as_str(r.get("name_ru")),
        "name_kz": as_str(r.get("name_kz")),
        "full_name_ru": as_str(r.get("full_name_ru")),
        "full_name_kz": as_str(r.get("full_name_kz")),
    }


def ref_dict_row(dict_name: str, r: Row) -> Row:
    known = {"id", "code", "name_ru", "name_kz"}
    extra = {k: v for k, v in r.items() if k not in known}
    return {
        "dict_name": dict_name,
        "id": int(r["id"]),
        "code": as_str(r.get("code")),
        "name_ru": as_str(r.get("name_ru")),
        "name_kz": as_str(r.get("name_kz")),
        "extra": extra or None,
    }
