from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from goszakup_ai.ingestion.mappers import Row

CPI_CSV = Path(__file__).resolve().parents[1] / "reference" / "cpi_kz_monthly.csv"

TALDAU_URL = "https://taldau.stat.gov.kz/ru/NewIndex/GetDynamics"
TALDAU_INDEX_ID = 703076
TALDAU_REGION_KZ = 741880
TALDAU_TO_PREVIOUS_PERIOD = 2695730
TALDAU_SERIES = {
    "cpi_mom_pct": 4772381,
    "food_mom_pct": 4772574,
    "nonfood_mom_pct": 4772568,
    "services_mom_pct": 4772555,
}
COLUMNS = ("cpi_mom_pct", "food_mom_pct", "nonfood_mom_pct", "services_mom_pct")


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


def read_cpi_csv(path: Path = CPI_CSV) -> list[Row]:
    with path.open(encoding="utf-8") as f:
        return [
            {
                "month": date.fromisoformat(f"{r['month']}-01"),
                **{c: _dec(r.get(c)) for c in COLUMNS},
                "source_url": r.get("source_url") or None,
            }
            for r in csv.DictReader(f)
        ]


def _parse_taldau(payload: Any) -> dict[date, Decimal]:
    series = payload[0] if isinstance(payload, list) else payload
    values: dict[date, Decimal] = {}
    for raw_date, raw_value in zip(series["dateList"], series["valueList"], strict=False):
        if raw_value in (None, ""):
            continue
        month = date(int(raw_date[2:6]), int(raw_date[:2]), 1)
        values[month] = (Decimal(str(raw_value)) - 100).quantize(Decimal("0.1"))
    return values


async def fetch_cpi_from_taldau(since: date, http_timeout: float = 60.0) -> list[Row]:
    by_month: dict[date, Row] = {}
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        for column, good_id in TALDAU_SERIES.items():
            response = await client.post(
                TALDAU_URL,
                data={
                    "dicIds": "67,848,2753",
                    "indexId": str(TALDAU_INDEX_ID),
                    "periodId": "4",
                    "terms": f"{TALDAU_REGION_KZ},{TALDAU_TO_PREVIOUS_PERIOD},{good_id}",
                    "filters_dates": ",",
                },
            )
            response.raise_for_status()
            for month, value in _parse_taldau(response.json()).items():
                if month >= since:
                    row = by_month.setdefault(
                        month,
                        {"month": month, **dict.fromkeys(COLUMNS), "source_url": TALDAU_URL},
                    )
                    row[column] = value
    return [by_month[m] for m in sorted(by_month)]
