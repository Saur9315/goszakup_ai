from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel
from sklearn.ensemble import IsolationForest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goszakup_ai.analytics.links import announce_url, contract_url
from goszakup_ai.analytics.stats import HETEROGENEOUS_MAD_LOG


class PriceAnomaly(BaseModel):
    unit_id: int
    contract_id: int
    lot_number: str | None
    customer_bin: str | None
    customer_name: str | None
    supplier_biin: str | None
    supplier_name: str | None
    sign_date: date | None
    enstru_code: str
    enstru_name: str | None
    item_name: str | None
    unit_name: str | None
    quantity: float
    price: float
    peer_wavg_price: float
    deviation: float
    robust_z: float | None
    confirmed: bool
    heterogeneous_group: bool
    peer_group: Literal["subclass", "code"]
    subclass_label: str | None
    peer_n: int
    n_customers: int
    overpayment_kzt: float
    region_name: str | None
    trade_method: str | None
    contract_url: str | None
    announce_url: str | None


class PriceAnomalyReport(BaseModel):
    params: dict[str, Any]
    checked: int
    checked_by_subclass: int
    matched: int
    confirmed: int
    confirmed_overpayment_kzt: float
    items: list[PriceAnomaly]
    method: str


class VolumeAnomaly(BaseModel):
    customer_bin: str
    customer_name: str | None
    enstru_code: str
    enstru_name: str | None
    unit_name: str | None
    year: int
    source: str
    quantity: float
    baseline_quantity: float
    baseline_years: int
    ratio: float
    peer_ratio: float | None
    peer_n: int
    excess_ratio: float | None
    amount: float | None
    extra_amount: float | None
    isolation_score: float
    confirmed: bool


class VolumeAnomalyReport(BaseModel):
    params: dict[str, Any]
    checked: int
    matched: int
    confirmed: int
    items: list[VolumeAnomaly]
    method: str


PRICE_METHOD = (
    "Для каждой позиции договора заказчиков из выборки цена без НДС за нормализованную единицу "
    "приведена к ценам базового месяца по ИПЦ и сравнена со средневзвешенной по количеству ценой "
    "всех остальных закупок того же кода ЕНС ТРУ и единицы (все заказчики РК, 2024–2026, без "
    "самой позиции). Если в подклассе позиции (близкие по смыслу описания внутри кода, "
    "эмбеддинги multilingual-e5-small) не меньше 5 других позиций и его медиана отличается от "
    "медианы кода больше чем в 2 раза либо цены по коду неоднородны (MAD логарифма > 0.7), а "
    "подкласс однороднее, сравнение идёт внутри подкласса. "
    "Отклонение = цена / средневзвешенная − 1. "
    "Формальный критерий ТЗ: отклонение больше порога. Подтверждённая аномалия: дополнительно "
    "robust z-score по логарифму цены "
    "(медиана и MAD группы) выше порога z. Группа неоднородна, если MAD логарифма цены > 0.7: "
    "под одним кодом ЕНС ТРУ разные по классу товары. "
    "Переплата = (цена − средневзвешенная) × количество."
)

ISOLATION_SHARE = 0.05

VOLUME_METHOD = (
    "Количество по заказчику × коду ЕНС ТРУ × году берётся из годового плана (план 2026 года "
    "полный), при его отсутствии — из договоров. База — среднее количество за предыдущие годы. "
    "Рост = количество / база. Сравнение с коллегами: медиана роста по тому же коду у других "
    "заказчиков выборки; превышение = рост / медиана коллег. Формальный критерий: рост не ниже "
    "порога. Подтверждённый рост: дополнительно Isolation Forest (scikit-learn, 200 деревьев, "
    "random_state=42) по признакам log роста, log превышения над коллегами и log суммы, "
    "обученный на всех парах заказчик × код × год, относит сочетание к 5% самых нетипичных."
)


async def price_anomalies(
    session: AsyncSession,
    *,
    threshold: float = 0.3,
    direction: Literal["above", "below", "both"] = "above",
    customer_bins: Sequence[str] | None = None,
    years: Sequence[int] | None = None,
    enstru_codes: Sequence[str] | None = None,
    min_peers: int = 5,
    confirm_z: float = 2.0,
    only_confirmed: bool = True,
    limit: int = 20,
) -> PriceAnomalyReport:
    deviation = {
        "above": "deviation > :threshold",
        "below": "deviation < -:threshold",
        "both": "abs(deviation) > :threshold",
    }[direction]
    filters = ["peer_n >= :min_peers"]
    if customer_bins:
        filters.append("customer_bin = ANY(:customer_bins)")
    if years:
        filters.append("fin_year = ANY(:years)")
    if enstru_codes:
        filters.append("enstru_code = ANY(:enstru_codes)")
    where = " AND ".join(filters)
    confirmed = f"({deviation}) AND abs(robust_z) > :confirm_z"
    params: dict[str, Any] = {
        "confirm_z": confirm_z,
        "threshold": threshold,
        "min_peers": min_peers,
        "customer_bins": list(customer_bins) if customer_bins else None,
        "years": list(years) if years else None,
        "enstru_codes": list(enstru_codes) if enstru_codes else None,
        "limit": limit,
    }
    summary = (
        await session.execute(
            text(
                f"SELECT count(*) AS checked, "
                f"count(*) FILTER (WHERE peer_group = 'subclass') AS checked_by_subclass, "
                f"count(*) FILTER (WHERE {deviation}) AS matched, "
                f"count(*) FILTER (WHERE {confirmed}) AS confirmed, "
                f"coalesce(sum(overpayment_kzt) "
                f"FILTER (WHERE {confirmed} AND overpayment_kzt > 0), 0) AS overpayment "
                f"FROM mart.price_anomaly WHERE {where}"
            ),
            params,
        )
    ).one()
    rows = await session.execute(
        text(
            f"SELECT *, {confirmed} AS is_confirmed FROM mart.price_anomaly "
            f"WHERE {where} AND {confirmed if only_confirmed else deviation} "
            "ORDER BY abs(overpayment_kzt) DESC NULLS LAST LIMIT :limit"
        ),
        params,
    )
    items = [
        PriceAnomaly(
            unit_id=r.unit_id,
            contract_id=r.contract_id,
            lot_number=r.lot_number,
            customer_bin=r.customer_bin,
            customer_name=r.customer_name,
            supplier_biin=r.supplier_biin,
            supplier_name=r.supplier_name,
            sign_date=r.sign_date.date() if r.sign_date else None,
            enstru_code=r.enstru_code,
            enstru_name=r.enstru_name,
            item_name=r.item_name,
            unit_name=r.unit_name,
            quantity=float(r.quantity_norm),
            price=round(float(r.price_norm), 2),
            peer_wavg_price=round(
                float(r.peer_wavg_real) * float(r.price_norm) / float(r.real_price), 2
            ),
            deviation=round(float(r.deviation), 4),
            robust_z=round(float(r.robust_z), 2) if r.robust_z is not None else None,
            confirmed=bool(r.is_confirmed),
            heterogeneous_group=(r.group_mad_log or 0) > HETEROGENEOUS_MAD_LOG,
            peer_group=r.peer_group,
            subclass_label=r.subclass_label if r.peer_group == "subclass" else None,
            peer_n=r.peer_n,
            n_customers=r.n_customers,
            overpayment_kzt=round(float(r.overpayment_kzt), 2),
            region_name=r.region_name,
            trade_method=r.trade_method,
            contract_url=contract_url(r.contract_id),
            announce_url=announce_url(r.trd_buy_id),
        )
        for r in rows
    ]
    return PriceAnomalyReport(
        params={k: v for k, v in params.items() if v is not None and k != "limit"}
        | {"direction": direction, "only_confirmed": only_confirmed},
        checked=summary.checked,
        checked_by_subclass=summary.checked_by_subclass,
        matched=summary.matched,
        confirmed=summary.confirmed,
        confirmed_overpayment_kzt=round(float(summary.overpayment), 2),
        items=items,
        method=PRICE_METHOD,
    )


def isolation_outliers(
    features: np.ndarray, share: float = ISOLATION_SHARE
) -> tuple[np.ndarray, np.ndarray]:
    if len(features) < 10:
        return np.zeros(len(features)), np.zeros(len(features), dtype=bool)
    model = IsolationForest(n_estimators=200, random_state=42, contamination=share)
    model.fit(features)
    scores = np.asarray(-model.score_samples(features), dtype=float)
    return scores, np.asarray(model.predict(features) == -1)


async def volume_anomalies(
    session: AsyncSession,
    *,
    min_ratio: float = 1.5,
    customer_bins: Sequence[str] | None = None,
    years: Sequence[int] | None = None,
    enstru_codes: Sequence[str] | None = None,
    min_extra_amount: float = 0.0,
    only_confirmed: bool = False,
    limit: int = 20,
) -> VolumeAnomalyReport:
    rows = (await session.execute(text("SELECT * FROM mart.volume_anomaly"))).mappings().all()
    features = np.array(
        [
            [
                np.log(float(r["ratio"])),
                np.log(float(r["excess_ratio"] or r["ratio"])),
                np.log1p(max(float(r["amount"] or 0), 0)),
            ]
            for r in rows
        ]
    ).reshape(-1, 3)
    scores, outliers = isolation_outliers(features)

    def in_filter(r: Any) -> bool:
        return (
            (not customer_bins or r["customer_bin"] in customer_bins)
            and (not years or r["year"] in years)
            and (not enstru_codes or r["enstru_code"] in enstru_codes)
        )

    def selected(r: Any) -> bool:
        return (
            in_filter(r)
            and float(r["ratio"]) >= min_ratio
            and float(r["extra_amount"] or 0) >= min_extra_amount
        )

    matched = [
        (r, float(s), bool(o))
        for r, s, o in zip(rows, scores, outliers, strict=True)
        if selected(r)
    ]
    checked = sum(1 for r in rows if in_filter(r))
    confirmed = sum(1 for _, _, o in matched if o)
    shown = [m for m in matched if m[2]] if only_confirmed else matched
    shown.sort(key=lambda m: (not m[2], -float(m[0]["extra_amount"] or 0)))
    items = [
        VolumeAnomaly(
            customer_bin=r["customer_bin"],
            customer_name=r["customer_name"],
            enstru_code=r["enstru_code"],
            enstru_name=r["enstru_name"],
            unit_name=r["unit_name"],
            year=r["year"],
            source=r["source"],
            quantity=float(r["quantity"]),
            baseline_quantity=round(float(r["baseline_quantity"]), 3),
            baseline_years=r["baseline_years"],
            ratio=round(float(r["ratio"]), 3),
            peer_ratio=round(float(r["peer_ratio"]), 3) if r["peer_n"] > 0 else None,
            peer_n=r["peer_n"],
            excess_ratio=round(float(r["excess_ratio"]), 3) if r["excess_ratio"] else None,
            amount=round(float(r["amount"]), 2) if r["amount"] is not None else None,
            extra_amount=round(float(r["extra_amount"]), 2) if r["extra_amount"] else None,
            isolation_score=round(s, 3),
            confirmed=o,
        )
        for r, s, o in shown[:limit]
    ]
    return VolumeAnomalyReport(
        params={
            "min_ratio": min_ratio,
            "customer_bins": list(customer_bins) if customer_bins else None,
            "years": list(years) if years else None,
            "enstru_codes": list(enstru_codes) if enstru_codes else None,
            "min_extra_amount": min_extra_amount,
            "only_confirmed": only_confirmed,
        },
        checked=checked,
        matched=len(matched),
        confirmed=confirmed,
        items=items,
        method=VOLUME_METHOD,
    )
