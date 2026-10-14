from datetime import datetime
from decimal import Decimal
from typing import Any

from goszakup_ai.ingestion.mappers import (
    contract_rows,
    lot_rows,
    parse_dt,
    plan_point_rows,
    ref_dict_row,
)
from goszakup_ai.ingestion.pipeline import keep_units

CONTRACT = {
    "id": 24083849,
    "rootId": 22498878,
    "parentId": 23791478,
    "refContractTypeId": 2,
    "signDate": "2025-12-31 08:15:24",
    "finYear": 2025,
    "contractSum": 689200,
    "withNds": 0,
    "refCurrencyCode": "KZT",
    "supplierBiin": "990640001569",
    "deleted": 0,
    "indexDate": "2026-04-15T05:32:43.774",
    "ContractUnits": [
        {
            "id": 54559073,
            "lotId": 35565935,
            "plnPointId": 80866695,
            "itemPrice": 68920,
            "itemPriceWnds": 68920,
            "quantity": 10,
            "refEnstruCode": ["212021.200.000004"],
            "deleted": 0,
        }
    ],
    "Supplier": {"pid": 777, "bin": "990640001569", "nameRu": " ТОО Поставщик ", "supplier": 1},
    "Customer": None,
}

PLAN_POINT = {
    "id": 80866695,
    "subjectBiin": "990740002243",
    "plnPointYear": 2025,
    "nameRu": "Плазма",
    "refEnstruCode": "212021.200.000004",
    "refUnitsCode": "639",
    "count": 10,
    "price": 70920.5,
    "isDeleted": 0,
    "timestamp": "2025-03-01 10:00:00",
    "PlansKato": [{"id": 1, "refKatoCode": "711210000", "count": 10, "isDeleted": 0}],
    "RefEnstru": {"id": 5, "code": "212021.200.000004", "nameRu": "Плазма", "level": 4},
}


def test_parse_dt_handles_portal_formats() -> None:
    assert parse_dt("2025-12-31 08:15:24") == datetime(2025, 12, 31, 8, 15, 24)
    assert parse_dt("2026-04-15T05:32:43.774") == datetime(2026, 4, 15, 5, 32, 43, 774000)
    assert parse_dt("2026-04-15T05:32:43+00:00") == datetime(2026, 4, 15, 10, 32, 43)
    assert parse_dt("") is None
    assert parse_dt("0000-00-00 00:00:00") is None


def test_contract_rows_flatten_units_and_supplier() -> None:
    rows = contract_rows(CONTRACT)

    assert rows.contract["root_id"] == 22498878
    assert rows.contract["with_nds"] is False
    assert rows.contract["sign_date"] == datetime(2025, 12, 31, 8, 15, 24)
    [unit] = rows.units
    assert unit["contract_id"] == 24083849
    assert unit["plan_point_id"] == 80866695
    assert unit["enstru_code"] == "212021.200.000004"
    assert unit["item_price"] == Decimal("68920")
    [supplier] = rows.subjects
    assert supplier["pid"] == 777
    assert supplier["name_ru"] == "ТОО Поставщик"


def test_plan_point_rows_keep_kato_and_enstru() -> None:
    rows = plan_point_rows(PLAN_POINT)

    assert rows.plan_point["price"] == Decimal("70920.5")
    assert rows.plan_point["unit_code"] == "639"
    assert rows.katos == [
        {
            "id": 1,
            "plan_point_id": 80866695,
            "kato_code": "711210000",
            "country_code": None,
            "delivery_place_ru": None,
            "delivery_place_kz": None,
            "quantity": Decimal("10"),
            "is_active": None,
            "is_deleted": False,
        }
    ]
    assert rows.enstru is not None
    assert rows.enstru["code"] == "212021.200.000004"


def test_lot_rows_link_plan_points() -> None:
    rows = lot_rows({"id": 9, "pointList": [1, 2], "enstruList": [], "customerBin": "1"})

    assert rows.plan_points == [
        {"lot_id": 9, "plan_point_id": 1},
        {"lot_id": 9, "plan_point_id": 2},
    ]
    assert rows.lot["enstru_ids"] is None


def test_keep_units_drops_other_enstru_codes() -> None:
    contract: dict[str, Any] = {
        "id": 1,
        "ContractUnits": [
            {"id": 10, "refEnstruCode": ["111111.100.000001"]},
            {"id": 11, "refEnstruCode": ["222222.200.000002"]},
            {"id": 12, "refEnstruCode": None},
        ],
    }

    kept = keep_units(contract, "222222.200.000002")

    assert [u["id"] for u in kept["ContractUnits"]] == [11]
    assert len(contract["ContractUnits"]) == 3


def test_ref_dict_row_keeps_unknown_fields_in_extra() -> None:
    row = ref_dict_row("trade_method", {"id": 6, "code": "6", "name_ru": "ИОИ", "symbol_code": "X"})

    assert row["extra"] == {"symbol_code": "X"}
