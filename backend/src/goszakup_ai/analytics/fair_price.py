from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel

from goszakup_ai.analytics.links import announce_url, contract_url
from goszakup_ai.analytics.stats import robust_z_log, weighted_mean, weighted_quantile

Level = Literal["locality", "region", "national"]
Verdict = Literal["fair", "elevated", "overpriced", "underpriced", "insufficient_data"]

RELIABLE_LINKS = frozenset({"direct", "version", "lot"})
LINK_QUALITY = {"customer_code": 0.9, "enstru_modal_unit": 0.6, "lot_announced": 0.9}
LEVEL_QUALITY: dict[Level, float] = {"locality": 1.0, "region": 0.9, "national": 0.8}


@dataclass(frozen=True)
class FairPriceParams:
    min_n: int = 5
    elevated: float = 0.15
    overpriced: float = 0.30
    underpriced: float = -0.30
    top_k: int = 10


@dataclass(frozen=True)
class PriceObs:
    unit_id: int
    contract_id: int
    chain_id: int
    customer_bin: str | None
    customer_name: str | None
    sign_date: date | None
    price: float
    quantity: float
    region_code: str | None
    region_name: str | None
    locality_code: str | None
    trd_buy_id: int | None


@dataclass
class PriceAdjusters:
    cpi: dict[date, float] = field(default_factory=dict)
    region_k: dict[str, float] = field(default_factory=dict)
    season: dict[int, float] = field(default_factory=dict)

    def cpi_index(self, day: date) -> float | None:
        if not self.cpi:
            return None
        month = day.replace(day=1)
        months = sorted(self.cpi)
        month = min(max(month, months[0]), months[-1])
        return self.cpi.get(month) or self.cpi[max(m for m in months if m <= month)]

    def adjust(
        self, obs: PriceObs, target_date: date, target_region: str | None, *, national: bool
    ) -> float:
        price = obs.price
        if obs.sign_date is not None:
            to_idx, from_idx = self.cpi_index(target_date), self.cpi_index(obs.sign_date)
            if to_idx and from_idx:
                price *= to_idx / from_idx
            price *= self.season.get(target_date.month, 1.0) / self.season.get(
                obs.sign_date.month, 1.0
            )
        if national:
            k_target = self.region_k.get(target_region or "", 1.0)
            k_obs = self.region_k.get(obs.region_code or "", 1.0)
            price *= k_target / k_obs
        return price


class Target(BaseModel):
    source: Literal["contract_unit", "lot"]
    unit_id: int | None = None
    lot_id: int | None = None
    lot_number: str | None = None
    contract_id: int | None = None
    chain_id: int | None = None
    trd_buy_id: int | None = None
    customer_bin: str | None = None
    customer_name: str | None = None
    item_name: str | None = None
    enstru_code: str
    unit_norm_code: str
    unit_name: str | None = None
    unit_dimension: str = "unknown"
    plan_link: str = "direct"
    price: float
    quantity: float | None = None
    date: date
    region_code: str | None = None
    region_name: str | None = None
    locality_code: str | None = None
    locality_name: str | None = None


class Comparable(BaseModel):
    unit_id: int
    contract_id: int
    customer_bin: str | None
    customer_name: str | None
    sign_date: date | None
    region_name: str | None
    price: float
    adjusted_price: float
    quantity: float
    contract_url: str | None
    announce_url: str | None


class Adjustments(BaseModel):
    cpi_available: bool
    region_coefficient_target: float
    seasonal_factor_target: float


class FairPriceResult(BaseModel):
    target: Target
    level: Level | None
    n: int
    n_customers: int
    fair_price: float | None
    wavg_price: float | None
    p25: float | None
    p75: float | None
    deviation: float | None
    robust_z: float | None
    verdict: Verdict
    confidence: float
    confidence_label: Literal["high", "medium", "low"]
    adjustments: Adjustments
    comparables: list[Comparable]
    limitations: list[str]
    method: str


def _levels(target: Target) -> list[tuple[Level, Callable[[PriceObs], bool]]]:
    return [
        (
            "locality",
            lambda o: bool(target.locality_code) and o.locality_code == target.locality_code,
        ),
        ("region", lambda o: bool(target.region_code) and o.region_code == target.region_code),
        ("national", lambda o: True),
    ]


def _verdict(deviation: float | None, n: int, params: FairPriceParams) -> Verdict:
    if deviation is None or n < params.min_n:
        return "insufficient_data"
    if deviation > params.overpriced:
        return "overpriced"
    if deviation > params.elevated:
        return "elevated"
    if deviation < params.underpriced:
        return "underpriced"
    return "fair"


def confidence_score(n: int, iqr_ratio: float | None, level: Level | None, target: Target) -> float:
    if n == 0 or level is None:
        return 0.0
    f_n = 1 - math.exp(-n / 8)
    f_d = 1 / (1 + (iqr_ratio or 0.0))
    f_l = LEVEL_QUALITY[level]
    f_u = 1.0 if target.plan_link in RELIABLE_LINKS else LINK_QUALITY.get(target.plan_link, 0.6)
    f_dim = 0.8 if target.unit_dimension == "package" else 1.0
    return round(f_n * f_d * f_l * f_u * f_dim, 3)


def _label(score: float) -> Literal["high", "medium", "low"]:
    return "high" if score >= 0.6 else "medium" if score >= 0.35 else "low"


def method_text(params: FairPriceParams) -> str:
    return (
        "Fair Price = взвешенная медиана цен аналогов (вес = √количества), цены без НДС "
        "за нормализованную единицу. Аналоги: тот же код ЕНС ТРУ и единица, другие заказчики. "
        f"Уровень выборки: город → регион → РК, первый уровень с N ≥ {params.min_n}. "
        "Поправки: инфляция по ИПЦ к месяцу оцениваемой закупки, сезонный коэффициент месяца, "
        "для уровня РК — региональный коэффициент цен. "
        f"Вердикт: отклонение > +{params.overpriced:.0%} — завышена, "
        f"+{params.elevated:.0%}…+{params.overpriced:.0%} — выше рынка, "
        f"< {params.underpriced:.0%} — аномально низкая."
    )


def assess(
    target: Target,
    pool: Sequence[PriceObs],
    adjusters: PriceAdjusters,
    params: FairPriceParams | None = None,
) -> FairPriceResult:
    params = params or FairPriceParams()
    candidates = [
        o
        for o in pool
        if o.price > 0
        and o.quantity > 0
        and o.customer_bin != target.customer_bin
        and (target.chain_id is None or o.chain_id != target.chain_id)
    ]
    level: Level | None = None
    chosen: list[PriceObs] = []
    for name, matches in _levels(target):
        chosen = [o for o in candidates if matches(o)]
        level = name
        if len(chosen) >= params.min_n:
            break

    national = level == "national"
    adjusted = [
        adjusters.adjust(o, target.date, target.region_code, national=national) for o in chosen
    ]
    n = len(chosen)
    fair = wavg = p25 = p75 = deviation = rz = None
    if n:
        weights = [math.sqrt(o.quantity) for o in chosen]
        fair = weighted_quantile(adjusted, weights, 0.5)
        p25 = weighted_quantile(adjusted, weights, 0.25)
        p75 = weighted_quantile(adjusted, weights, 0.75)
        wavg = weighted_mean(adjusted, [o.quantity for o in chosen])
        deviation = target.price / fair - 1 if fair else None
        rz = robust_z_log(target.price, adjusted) if n >= 3 else None
    iqr_ratio = (p75 - p25) / fair if fair and p25 is not None and p75 is not None else None
    score = confidence_score(n, iqr_ratio, level if n else None, target)

    order = sorted(
        range(n),
        key=lambda i: (
            chosen[i].locality_code != target.locality_code,
            -(chosen[i].sign_date or date.min).toordinal(),
        ),
    )
    comparables = [
        Comparable(
            unit_id=chosen[i].unit_id,
            contract_id=chosen[i].contract_id,
            customer_bin=chosen[i].customer_bin,
            customer_name=chosen[i].customer_name,
            sign_date=chosen[i].sign_date,
            region_name=chosen[i].region_name,
            price=round(chosen[i].price, 2),
            adjusted_price=round(adjusted[i], 2),
            quantity=chosen[i].quantity,
            contract_url=contract_url(chosen[i].contract_id),
            announce_url=announce_url(chosen[i].trd_buy_id),
        )
        for i in order[: params.top_k]
    ]

    limitations = []
    if n < params.min_n:
        limitations.append(f"Мало сопоставимых закупок других заказчиков: N = {n} < {params.min_n}")
    if national and n:
        limitations.append("Аналоги взяты по всей РК с поправкой на региональный коэффициент цен")
    if target.source == "lot":
        limitations.append("Оценивается объявленная цена лота: договор по лоту не заключён")
    if target.plan_link not in RELIABLE_LINKS:
        limitations.append("Единица измерения или место поставки восстановлены косвенно")
    if target.unit_dimension == "package":
        limitations.append(
            "Единица — упаковка или набор: размер упаковки у аналогов может отличаться"
        )
    if not adjusters.cpi:
        limitations.append("Инфляционная поправка не применена: нет ряда ИПЦ")
    if iqr_ratio is not None and iqr_ratio > 1:
        limitations.append(f"Большой разброс цен аналогов: (P75 − P25) / медиана = {iqr_ratio:.2f}")

    return FairPriceResult(
        target=target,
        level=level if n else None,
        n=n,
        n_customers=len({o.customer_bin for o in chosen}),
        fair_price=_round(fair),
        wavg_price=_round(wavg),
        p25=_round(p25),
        p75=_round(p75),
        deviation=_round(deviation, 4),
        robust_z=_round(rz, 2),
        verdict=_verdict(deviation, n, params),
        confidence=score,
        confidence_label=_label(score),
        adjustments=Adjustments(
            cpi_available=bool(adjusters.cpi),
            region_coefficient_target=adjusters.region_k.get(target.region_code or "", 1.0),
            seasonal_factor_target=adjusters.season.get(target.date.month, 1.0),
        ),
        comparables=comparables,
        limitations=limitations,
        method=method_text(params),
    )


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)
