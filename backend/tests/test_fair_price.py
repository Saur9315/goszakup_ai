from datetime import date

import pytest

from goszakup_ai.analytics.fair_price import (
    FairPriceParams,
    PriceAdjusters,
    PriceObs,
    Target,
    assess,
)
from goszakup_ai.analytics.stats import robust_z_log, weighted_quantile

ASTANA, ALMATY = "710000000", "750000000"


def obs(
    i: int,
    price: float,
    *,
    customer: str = "OTHER",
    region: str = ASTANA,
    locality: str | None = None,
    day: date = date(2025, 6, 15),
    quantity: float = 10,
) -> PriceObs:
    return PriceObs(
        unit_id=i,
        contract_id=1000 + i,
        chain_id=1000 + i,
        customer_bin=f"{customer}{i}" if customer == "OTHER" else customer,
        customer_name=None,
        sign_date=day,
        price=price,
        quantity=quantity,
        region_code=region,
        region_name=None,
        locality_code=locality or region,
        trd_buy_id=None,
    )


def target(price: float, **kwargs: object) -> Target:
    data: dict[str, object] = {
        "source": "contract_unit",
        "unit_id": 1,
        "chain_id": 1,
        "customer_bin": "ME",
        "enstru_code": "212021.200.000004",
        "unit_norm_code": "796",
        "price": price,
        "date": date(2025, 6, 15),
        "region_code": ASTANA,
        "locality_code": ASTANA,
    }
    data.update(kwargs)
    return Target.model_validate(data)


def test_weighted_quantile_and_robust_z() -> None:
    assert weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 0.5) == pytest.approx(2.5)
    assert weighted_quantile([1, 100], [9, 1], 0.5) == pytest.approx(1.0)
    assert robust_z_log(100, [100, 100, 100]) is None
    z = robust_z_log(300, [90, 100, 110, 95, 105])
    assert z is not None and z > 3


def test_excludes_own_purchases_and_prefers_locality() -> None:
    pool = [obs(i, 100) for i in range(5)]
    pool += [obs(10 + i, 500, region=ALMATY) for i in range(5)]
    pool += [obs(20, 1, customer="ME")]

    result = assess(target(100), pool, PriceAdjusters())

    assert result.level == "locality"
    assert result.n == 5
    assert result.fair_price == pytest.approx(100)
    assert result.verdict == "fair"
    assert all(c.customer_bin != "ME" for c in result.comparables)


def test_falls_back_to_national_with_regional_coefficient() -> None:
    pool = [obs(i, 120, region=ALMATY) for i in range(6)]
    adjusters = PriceAdjusters(region_k={ASTANA: 1.0, ALMATY: 1.2})

    result = assess(target(100), pool, adjusters)

    assert result.level == "national"
    assert result.fair_price == pytest.approx(100)
    assert any("всей РК" in note for note in result.limitations)


def test_inflation_brings_old_prices_to_target_month() -> None:
    pool = [obs(i, 100, day=date(2024, 1, 10)) for i in range(5)]
    adjusters = PriceAdjusters(cpi={date(2024, 1, 1): 100.0, date(2025, 6, 1): 120.0})

    result = assess(target(120), pool, adjusters)

    assert result.fair_price == pytest.approx(120)
    assert result.verdict == "fair"


@pytest.mark.parametrize(
    ("price", "verdict"),
    [(100, "fair"), (120, "elevated"), (140, "overpriced"), (60, "underpriced")],
)
def test_verdict_thresholds(price: float, verdict: str) -> None:
    pool = [obs(i, 100) for i in range(8)]

    assert assess(target(price), pool, PriceAdjusters()).verdict == verdict


def test_insufficient_data_has_low_confidence() -> None:
    result = assess(target(100), [obs(1, 100), obs(2, 110)], PriceAdjusters(), FairPriceParams())

    assert result.verdict == "insufficient_data"
    assert result.confidence_label == "low"
    assert result.n == 2
