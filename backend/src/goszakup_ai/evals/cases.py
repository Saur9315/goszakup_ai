from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goszakup_ai.agent.schemas import AnswerKind, Intent, Language
from goszakup_ai.analytics.anomalies import volume_anomalies
from goszakup_ai.analytics.repository import fair_price_for_lot
from goszakup_ai.evals.matching import FactKind

HOSPITAL = "990740002243"
NATIONAL_HOSPITAL = "231040023028"
RESIDENCES = "971040001050"
ADMIN_BUILDINGS = "020440003656"
OK_ZHETPES = "051040005150"
OK_ZHETPES_ALMATY = "171041003124"
KINDERGARTEN = "100140011059"
MOTOR_DEPOT = "970940001378"
ENGINEERING = "210240033968"
BURABAY_PARK = "940740000911"
BERKUT = "000740001307"
PROSECUTORS = "981140001551"

ALIASES_RU = {
    HOSPITAL: "Больница МЦ УДП",
    NATIONAL_HOSPITAL: "Национальный госпиталь",
    RESIDENCES: "Дирекция государственных резиденций",
    ADMIN_BUILDINGS: "Дирекция административных зданий",
    OK_ZHETPES: "ЛОК Ок-Жетпес",
    OK_ZHETPES_ALMATY: "Ок-Жетпес Алматы",
    KINDERGARTEN: "детский сад Қарлығаш",
    MOTOR_DEPOT: "Автохозяйство УДП",
    ENGINEERING: "Инженерно-технический центр УДП",
    BURABAY_PARK: "нацпарк Бурабай",
    BERKUT: "авиакомпания Беркут",
    PROSECUTORS: "Управление материально-технического обеспечения Генпрокуратуры",
}
ALIASES_KK = {
    NATIONAL_HOSPITAL: "Ұлттық госпиталь",
    RESIDENCES: "Мемлекеттік резиденциялар дирекциясы",
    BURABAY_PARK: "«Бурабай» ұлттық паркі",
    MOTOR_DEPOT: "«Автохозяйство УДП»",
}


@dataclass(frozen=True)
class ExpectedFact:
    name: str
    kind: FactKind
    value: float | str


@dataclass
class EvalCase:
    id: str
    language: Language
    turns: list[str]
    intent: Intent | None
    kind: AnswerKind = "answer"
    bins: list[str] = field(default_factory=list)
    lots: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    facts: list[ExpectedFact] = field(default_factory=list)


async def _one(session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await session.execute(text(sql), params)).one()


async def _contracts(session: AsyncSession, bin_: str, year: int) -> list[ExpectedFact]:
    r = await _one(
        session,
        "SELECT count(DISTINCT contract_id) AS contracts, coalesce(sum(amount_kzt), 0) AS amount, "
        "to_char(max(sign_date), 'DD.MM.YYYY') AS last "
        "FROM mart.price_observation WHERE in_scope AND customer_bin = :b AND fin_year = :y",
        b=bin_,
        y=year,
    )
    return [
        ExpectedFact("договоров", "count", r.contracts),
        ExpectedFact("сумма", "money", float(r.amount)),
        ExpectedFact("последняя дата", "text", r.last),
        ExpectedFact("БИН", "text", bin_),
    ]


async def _efficiency(session: AsyncSession, bin_: str, year: int, column: str) -> ExpectedFact:
    r = await _one(
        session,
        f"SELECT {column} AS v FROM mart.procurement_efficiency "
        "WHERE customer_bin = :b AND year = :y",
        b=bin_,
        y=year,
    )
    return ExpectedFact(column, "pct", float(r.v))


async def _price_anomalies(
    session: AsyncSession, bin_: str | None, year: int
) -> list[ExpectedFact]:
    r = await _one(
        session,
        "SELECT count(*) AS checked, count(*) FILTER (WHERE deviation > 0.3) AS matched, "
        "count(*) FILTER (WHERE deviation > 0.3 AND abs(robust_z) > 2) AS confirmed "
        "FROM mart.price_anomaly WHERE peer_n >= 5 AND fin_year = :y "
        "AND (CAST(:b AS text) IS NULL OR customer_bin = :b)",
        b=bin_,
        y=year,
    )
    return [
        ExpectedFact("проверено", "count", r.checked),
        ExpectedFact("превышают порог", "count", r.matched),
        ExpectedFact("подтверждено", "count", r.confirmed),
    ]


async def _volume_anomalies(session: AsyncSession, bin_: str) -> list[ExpectedFact]:
    where = "customer_bin = :b AND year IN (2025, 2026)"
    r = await _one(
        session,
        f"SELECT count(*) AS checked, count(*) FILTER (WHERE ratio >= 1.5 "
        f"AND coalesce(extra_amount, 0) >= 0) AS matched FROM mart.volume_anomaly WHERE {where}",
        b=bin_,
    )
    report = await volume_anomalies(session, customer_bins=[bin_], years=[2025, 2026], limit=1)
    facts = [
        ExpectedFact("проверено пар", "count", r.checked),
        ExpectedFact("рост выше порога", "count", r.matched),
        ExpectedFact("подтверждено моделью", "count", report.confirmed),
    ]
    if report.items:
        facts.append(ExpectedFact("рост #1", "number", round(report.items[0].ratio, 2)))
    return facts


async def _fair_price(session: AsyncSession, lot: str) -> list[ExpectedFact]:
    result = (await fair_price_for_lot(session, lot))[0]
    facts = [
        ExpectedFact("номер лота", "text", lot),
        ExpectedFact("цена лота", "money", result.target.price),
        ExpectedFact("число аналогов", "count", result.n),
    ]
    if result.fair_price is not None:
        facts.append(ExpectedFact("Fair Price", "money", result.fair_price))
    if result.deviation is not None:
        facts.append(ExpectedFact("отклонение", "pct", result.deviation))
    return facts


async def _fair_price_lots(session: AsyncSession, count: int) -> list[str]:
    rows = await session.execute(
        text(
            "SELECT lot_number FROM mart.price_observation "
            "WHERE in_scope AND unit_comparable AND plan_link = 'direct' "
            "AND lot_number IS NOT NULL "
            "AND unit_dimension IN ('count', 'mass', 'volume') AND fin_year = 2025 "
            "GROUP BY lot_number HAVING count(*) = 1 ORDER BY max(amount_kzt) DESC LIMIT 60"
        )
    )
    chosen: list[str] = []
    seen_codes: set[str] = set()
    for (lot,) in rows:
        results = await fair_price_for_lot(session, lot)
        r = results[0]
        if r.n >= 5 and r.target.enstru_code not in seen_codes:
            chosen.append(lot)
            seen_codes.add(r.target.enstru_code)
        if len(chosen) == count:
            break
    return chosen


async def _beef_lot(session: AsyncSession, bin_: str) -> str | None:
    row = (
        await session.execute(
            text(
                "SELECT lot_number FROM mart.price_observation WHERE customer_bin = :b "
                "AND item_name ILIKE 'говядина%' AND lot_number IS NOT NULL "
                "ORDER BY amount_kzt DESC NULLS LAST LIMIT 1"
            ),
            {"b": bin_},
        )
    ).first()
    return row[0] if row else None


async def build_cases(session: AsyncSession) -> list[EvalCase]:
    ru, kk = ALIASES_RU, ALIASES_KK
    cases: list[EvalCase] = []

    for i, (bin_, year) in enumerate(
        [
            (HOSPITAL, 2025),
            (NATIONAL_HOSPITAL, 2024),
            (OK_ZHETPES, 2025),
            (BERKUT, 2025),
            (PROSECUTORS, 2024),
        ],
        1,
    ):
        cases.append(
            EvalCase(
                f"search-{i}",
                "ru",
                [f"Сколько договоров заключил(а) {ru[bin_]} в {year} году и на какую сумму?"],
                "search",
                bins=[bin_],
                years=[year],
                facts=await _contracts(session, bin_, year),
            )
        )
    cases.append(
        EvalCase(
            "search-kk-1",
            "kk",
            [f"2025 жылы {kk[NATIONAL_HOSPITAL]} қанша шарт жасады және қандай сомаға?"],
            "search",
            bins=[NATIONAL_HOSPITAL],
            years=[2025],
            facts=await _contracts(session, NATIONAL_HOSPITAL, 2025),
        )
    )
    cases.append(
        EvalCase(
            "search-bin-1",
            "ru",
            [
                f"Покажи договоры заказчика с БИН {MOTOR_DEPOT} за 2024 год: "
                "сколько их и на какую сумму?"
            ],
            "search",
            bins=[MOTOR_DEPOT],
            years=[2024],
            facts=await _contracts(session, MOTOR_DEPOT, 2024),
        )
    )

    efficiency = [
        (
            MOTOR_DEPOT,
            2025,
            "single_source_share",
            "Какая доля закупок из одного источника у {org} в {y} году?",
        ),
        (
            NATIONAL_HOSPITAL,
            2025,
            "lots_failed_share",
            "Какая доля несостоявшихся лотов у {org} в {y} году?",
        ),
        (KINDERGARTEN, 2024, "economy_share", "Какая экономия к плановой цене у {org} в {y} году?"),
        (
            RESIDENCES,
            2025,
            "single_source_share",
            "Какую долю закупок {org} провела из одного источника в {y} году?",
        ),
    ]
    for i, (bin_, year, column, template) in enumerate(efficiency, 1):
        cases.append(
            EvalCase(
                f"efficiency-{i}",
                "ru",
                [template.format(org=ru[bin_], y=year)],
                "analytics",
                bins=[bin_],
                years=[year],
                facts=[await _efficiency(session, bin_, year, column)],
            )
        )
    cases.append(
        EvalCase(
            "efficiency-kk-1",
            "kk",
            [f"2025 жылы {kk[MOTOR_DEPOT]} бір көзден сатып алу үлесі қандай?"],
            "analytics",
            bins=[MOTOR_DEPOT],
            years=[2025],
            facts=[await _efficiency(session, MOTOR_DEPOT, 2025, "single_source_share")],
        )
    )

    for i, (a, b, year) in enumerate(
        [
            (HOSPITAL, NATIONAL_HOSPITAL, 2025),
            (OK_ZHETPES, OK_ZHETPES_ALMATY, 2024),
            (ADMIN_BUILDINGS, RESIDENCES, 2025),
        ],
        1,
    ):
        fa, fb = await _contracts(session, a, year), await _contracts(session, b, year)
        cases.append(
            EvalCase(
                f"compare-{i}",
                "ru",
                [f"Сравни {ru[a]} и {ru[b]} по сумме и количеству договоров за {year} год"],
                "compare",
                bins=[a, b],
                years=[year],
                facts=[*fa[:2], *fb[:2]],
            )
        )

    anomaly_targets: list[tuple[str | None, int]] = [
        (RESIDENCES, 2025),
        (HOSPITAL, 2024),
        (None, 2025),
    ]
    for i, (target, year) in enumerate(anomaly_targets, 1):
        org = f" у {ru[target]}" if target else ""
        cases.append(
            EvalCase(
                f"price-anomaly-{i}",
                "ru",
                [
                    f"Найди закупки{org} с отклонением цены > 30% "
                    "от средневзвешенной по данному ЕНСТРУ "
                    f"за {year} год"
                ],
                "price_anomaly",
                bins=[target] if target else [],
                years=[year],
                facts=await _price_anomalies(session, target, year),
            )
        )
    cases.append(
        EvalCase(
            "price-anomaly-kk-1",
            "kk",
            [
                f"2025 жылы {kk[RESIDENCES]} бағасы ЕНС ТРУ бойынша "
                "орташа өлшенген бағадан 30%-дан "
                "астам ауытқыған сатып алуларды тап"
            ],
            "price_anomaly",
            bins=[RESIDENCES],
            years=[2025],
            facts=await _price_anomalies(session, RESIDENCES, 2025),
        )
    )

    for i, bin_ in enumerate([RESIDENCES, HOSPITAL, BURABAY_PARK], 1):
        cases.append(
            EvalCase(
                f"volume-anomaly-{i}",
                "ru",
                [
                    f"Выяви нетипичное завышение количества ТРУ по сравнению с предыдущими годами "
                    f"у {ru[bin_]}"
                ],
                "volume_anomaly",
                bins=[bin_],
                facts=await _volume_anomalies(session, bin_),
            )
        )

    lots = await _fair_price_lots(session, 5)
    for i, lot in enumerate(lots[:4], 1):
        cases.append(
            EvalCase(
                f"fair-price-{i}",
                "ru",
                [
                    f"Оцени адекватность цены лота №{lot} относительно аналогичных "
                    "контрактов других ведомств в идентичном городе поставки"
                ],
                "fair_price",
                lots=[lot],
                facts=await _fair_price(session, lot),
            )
        )
    if len(lots) == 5:
        cases.append(
            EvalCase(
                "fair-price-kk-1",
                "kk",
                [
                    f"{lots[4]} лотының бағасы басқа ведомстволардың ұқсас келісімшарттарымен "
                    "салыстырғанда қаншалықты әділ?"
                ],
                "fair_price",
                lots=[lots[4]],
                facts=await _fair_price(session, lots[4]),
            )
        )

    cases.append(
        EvalCase(
            "dialog-followup-1",
            "ru",
            [
                f"Какая доля несостоявшихся лотов у {ru[NATIONAL_HOSPITAL]} в 2025 году?",
                "а в 2024?",
            ],
            "analytics",
            bins=[NATIONAL_HOSPITAL],
            years=[2024],
            facts=[await _efficiency(session, NATIONAL_HOSPITAL, 2024, "lots_failed_share")],
        )
    )
    cases.append(
        EvalCase(
            "dialog-followup-2",
            "ru",
            [f"Сколько договоров заключила {ru[HOSPITAL]} в 2025 году?", "а в 2024?"],
            "search",
            bins=[HOSPITAL],
            years=[2024],
            facts=(await _contracts(session, HOSPITAL, 2024))[:2],
        )
    )
    beef = await _beef_lot(session, ADMIN_BUILDINGS)
    if beef:
        cases.append(
            EvalCase(
                "dialog-clarify-lot",
                "ru",
                [f"Оцени справедливость цены говядины у {ru[ADMIN_BUILDINGS]}", beef],
                "fair_price",
                bins=[ADMIN_BUILDINGS],
                lots=[beef],
                facts=await _fair_price(session, beef),
            )
        )

    cases.append(
        EvalCase(
            "clarify-no-lot",
            "ru",
            ["Оцени справедливость цены лота"],
            "fair_price",
            kind="clarification",
        )
    )
    cases.append(
        EvalCase(
            "out-of-scope-1",
            "ru",
            ["Какая погода завтра в Астане?"],
            "out_of_scope",
            kind="clarification",
        )
    )
    cases.append(
        EvalCase(
            "out-of-scope-kk",
            "kk",
            ["Ертең Астанада ауа райы қандай болады?"],
            "out_of_scope",
            kind="clarification",
        )
    )
    return cases
