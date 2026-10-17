from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goszakup_ai.agent.formatting import fmt_date, fmt_money, fmt_number, fmt_pct
from goszakup_ai.agent.schemas import Fact, Intent, ResolvedParams, ToolResult
from goszakup_ai.analytics.anomalies import price_anomalies, volume_anomalies
from goszakup_ai.analytics.links import contract_url
from goszakup_ai.analytics.repository import NotFoundError, fair_price_for_lot

MAX_LOTS = 3

VERDICTS_RU = {
    "fair": "цена в пределах рынка",
    "elevated": "цена выше рынка",
    "overpriced": "цена завышена",
    "underpriced": "цена аномально низкая",
    "insufficient_data": "недостаточно данных для вывода",
}
LEVELS_RU = {"locality": "тот же город", "region": "тот же регион", "national": "вся РК"}

money = fmt_money
num = fmt_number


def pct(value: Any, signed: bool = False) -> str:
    return fmt_pct(float(value) if value is not None else None, signed)


def times(value: float) -> str:
    return f"×{fmt_number(value, 2)}"


def fact(label: str, value: Any, display: str) -> Fact:
    return Fact(id="", label=label, value=value, display=display)


def _where(p: ResolvedParams, *, market: bool) -> tuple[str, dict[str, Any]]:
    clauses = [] if market else ["in_scope"]
    params: dict[str, Any] = {}
    if p.customer_bins:
        clauses.append("customer_bin = ANY(:bins)")
        params["bins"] = p.customer_bins
    if p.years:
        clauses.append("fin_year = ANY(:years)")
        params["years"] = p.years
    if p.enstru_codes:
        clauses.append("enstru_code = ANY(:codes)")
        params["codes"] = p.enstru_codes
    if p.region_code:
        clauses.append("region_code = :region")
        params["region"] = p.region_code
    return " AND ".join(clauses) or "true", params


SEARCH_SUMMARY_SQL = """
SELECT count(DISTINCT contract_id) AS contracts,
       count(*) AS units,
       coalesce(sum(amount_kzt), 0) AS amount,
       count(DISTINCT supplier_biin) AS suppliers,
       count(DISTINCT customer_bin) AS customers,
       min(sign_date) AS first,
       max(sign_date) AS last
FROM mart.price_observation
WHERE {where}
"""

SEARCH_ITEMS_SQL = """
SELECT * FROM mart.price_observation
WHERE {where}
ORDER BY amount_kzt DESC NULLS LAST
LIMIT :k
"""


async def search(session: AsyncSession, p: ResolvedParams) -> ToolResult:
    where, params = _where(p, market=False)
    s = (await session.execute(text(SEARCH_SUMMARY_SQL.format(where=where)), params)).one()
    rows = await session.execute(
        text(SEARCH_ITEMS_SQL.format(where=where)), params | {"k": p.top_k}
    )
    items = [
        {
            "date": fmt_date(r.sign_date),
            "customer": r.customer_name,
            "item": r.item_name or r.enstru_name,
            "quantity": f"{num(r.quantity_norm, 2)} {r.unit_norm_name or ''}".strip(),
            "price": money(r.price_norm),
            "amount": money(r.amount_kzt),
            "supplier": r.supplier_name,
            "link": contract_url(r.contract_id),
        }
        for r in rows
    ]
    facts = [
        fact("Договоров найдено", s.contracts, num(s.contracts)),
        fact("Позиций договоров", s.units, num(s.units)),
        fact("Общая сумма договоров", float(s.amount), money(s.amount)),
        fact("Поставщиков", s.suppliers, num(s.suppliers)),
        fact("Заказчиков", s.customers, num(s.customers)),
        fact("Первая дата подписания", s.first, fmt_date(s.first)),
        fact("Последняя дата подписания", s.last, fmt_date(s.last)),
    ]
    return ToolResult(
        tool="search",
        title="Поиск договоров",
        args={"where": where, **params},
        facts=facts,
        items=items,
        columns=[
            ("date", "Дата"),
            ("customer", "Заказчик"),
            ("item", "Предмет"),
            ("quantity", "Кол-во"),
            ("price", "Цена за ед. без НДС"),
            ("amount", "Сумма"),
            ("supplier", "Поставщик"),
            ("link", "Договор"),
        ],
        method=(
            "Выборка позиций актуальных версий договоров (без статусов «Изменен» и «Не заключен») "
            "по фильтрам; суммы без НДС в тенге; сортировка по сумме позиции."
        ),
        sample_size=s.units,
    )


COMPARE_DIMENSIONS = {
    "customer": ("customer_bin", "max(customer_name)", "Заказчик"),
    "year": ("fin_year::text", "max(fin_year)::text", "Год"),
    "region": ("region_code", "max(region_name)", "Регион"),
    "supplier": ("supplier_biin", "max(supplier_name)", "Поставщик"),
    "trade_method": ("trade_method", "max(trade_method)", "Способ закупки"),
}

COMPARE_SQL = """
SELECT {key} AS key,
       {label} AS label,
       count(DISTINCT contract_id) AS contracts,
       count(*) AS units,
       coalesce(sum(amount_kzt), 0) AS amount,
       sum(amount_kzt) FILTER (WHERE is_single_source) / nullif(sum(amount_kzt), 0)
           AS single_source_share,
       sum(price_norm * quantity_norm) FILTER (WHERE unit_comparable)
           / nullif(sum(quantity_norm) FILTER (WHERE unit_comparable), 0) AS wavg_price,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price_norm) AS median_price
FROM mart.price_observation
WHERE {where}
GROUP BY 1
ORDER BY amount DESC
LIMIT :k
"""


async def compare(session: AsyncSession, p: ResolvedParams) -> ToolResult:
    market = bool(p.enstru_codes) and not p.customer_bins
    where, params = _where(p, market=market)
    key, label, header = COMPARE_DIMENSIONS[p.compare_by or "year"]
    single_code = len(p.enstru_codes) == 1
    sql = COMPARE_SQL.format(key=key, label=label, where=where)
    rows = (await session.execute(text(sql), params | {"k": p.top_k})).all()
    facts: list[Fact] = []
    items = []
    for r in rows:
        name = r.label or r.key
        share = float(r.single_source_share) if r.single_source_share is not None else None
        facts += [
            fact(f"Сумма договоров — {name}", float(r.amount), money(r.amount)),
            fact(f"Число договоров — {name}", r.contracts, num(r.contracts)),
            fact(f"Доля из одного источника — {name}", share, pct(share)),
        ]
        if single_code and r.wavg_price is not None:
            wavg, median = float(r.wavg_price), float(r.median_price)
            facts += [
                fact(f"Средневзвешенная цена — {name}", wavg, money(wavg)),
                fact(f"Медианная цена — {name}", median, money(median)),
            ]
        items.append(
            {
                "group": name,
                "contracts": num(r.contracts),
                "amount": money(r.amount),
                "single_source": pct(share),
                "wavg_price": money(r.wavg_price) if single_code else "—",
                "median_price": money(r.median_price) if single_code else "—",
            }
        )
    scope = "все заказчики РК" if market else "организации из выборки (27 БИН)"
    return ToolResult(
        tool="compare",
        title=f"Сравнение: {header.lower()}",
        args={"compare_by": p.compare_by, "where": where, **params},
        facts=facts,
        items=items,
        columns=[
            ("group", header),
            ("contracts", "Договоров"),
            ("amount", "Сумма"),
            ("single_source", "Из одного источника"),
            ("wavg_price", "Средневзв. цена"),
            ("median_price", "Медиана цены"),
        ],
        method=(
            f"Агрегаты по актуальным версиям договоров ({scope}): число договоров, сумма без НДС, "
            "доля суммы договоров из одного источника; для одного кода ЕНС ТРУ — "
            "средневзвешенная по количеству и медианная цена за нормализованную единицу."
        ),
        limitations=[] if single_code else ["Цены сравниваются только при одном коде ЕНС ТРУ"],
        sample_size=sum(r.units for r in rows),
    )


EFFICIENCY_SQL = """
SELECT e.*, sb.name_ru
FROM mart.procurement_efficiency e
JOIN meta.scope_bin sb ON sb.bin = e.customer_bin
WHERE {where}
ORDER BY contract_amount DESC NULLS LAST
LIMIT :k
"""


async def efficiency(session: AsyncSession, p: ResolvedParams) -> ToolResult:
    clauses = ["year = ANY(:years)"]
    params: dict[str, Any] = {"years": p.years}
    if p.customer_bins:
        clauses.append("customer_bin = ANY(:bins)")
        params["bins"] = p.customer_bins
    sql = EFFICIENCY_SQL.format(where=" AND ".join(clauses))
    rows = (await session.execute(text(sql), params | {"k": p.top_k})).all()
    facts: list[Fact] = []
    items = []
    for r in rows:
        name = f"{r.name_ru}, {r.year}" if len(rows) > 1 else str(r.year)
        values: list[tuple[str, Any, Callable[[Any], str]]] = [
            ("План закупок", r.plan_amount, money),
            ("Сумма договоров", r.contract_amount, money),
            ("Экономия к плановой цене", r.economy_share, pct),
            ("Доля из одного источника", r.single_source_share, pct),
            ("Доля несостоявшихся лотов", r.lots_failed_share, pct),
            ("Индекс концентрации поставщиков (HHI)", r.supplier_hhi, lambda v: num(v, 3)),
            ("Дней от объявления до договора", r.avg_days_publish_to_sign, num),
        ]
        facts += [
            fact(f"{label} — {name}", float(value), formatter(value))
            for label, value, formatter in values
            if value is not None
        ]
        items.append(
            {
                "org": r.name_ru,
                "year": str(r.year),
                "plan": money(r.plan_amount),
                "contracts": money(r.contract_amount),
                "economy": pct(r.economy_share),
                "single_source": pct(r.single_source_share),
                "failed": pct(r.lots_failed_share),
            }
        )
    return ToolResult(
        tool="efficiency",
        title="Эффективность закупок",
        args=params,
        facts=facts,
        items=items,
        columns=[
            ("org", "Заказчик"),
            ("year", "Год"),
            ("plan", "План"),
            ("contracts", "Договоры"),
            ("economy", "Экономия"),
            ("single_source", "Из одного источника"),
            ("failed", "Несостоявшиеся лоты"),
        ],
        method=(
            "Экономия = 1 − Σ(цена договора × кол-во) / Σ(плановая цена × кол-во) по позициям с "
            "прямой связью с пунктом плана; доля из одного источника — по сумме договоров; "
            "доля несостоявшихся лотов — лоты со статусом «Закупка не состоялась»; "
            "HHI — сумма квадратов долей поставщиков в сумме договоров заказчика за год."
        ),
        sample_size=len(rows),
    )


async def price_anomaly(session: AsyncSession, p: ResolvedParams) -> ToolResult:
    report = await price_anomalies(
        session,
        threshold=p.threshold,
        customer_bins=p.customer_bins,
        years=p.years,
        enstru_codes=p.enstru_codes,
        limit=p.top_k,
    )
    overpayment = report.confirmed_overpayment_kzt
    facts = [
        fact("Порог отклонения от средневзвешенной", p.threshold, pct(p.threshold)),
        fact("Проверено позиций договоров", report.checked, num(report.checked)),
        fact(
            "Из них сравнены с похожими по описанию (подкласс)",
            report.checked_by_subclass,
            num(report.checked_by_subclass),
        ),
        fact("Превышают порог (критерий ТЗ)", report.matched, num(report.matched)),
        fact("Подтверждено робастной статистикой (z > 2)", report.confirmed, num(report.confirmed)),
        fact("Оценка переплаты по подтверждённым", overpayment, money(overpayment)),
    ]
    for i, a in enumerate(report.items[:5], 1):
        name = a.item_name
        facts += [
            fact(f"#{i} отклонение — {name}", a.deviation, pct(a.deviation, True)),
            fact(f"#{i} цена — {name}", a.price, money(a.price)),
            fact(
                f"#{i} средневзвешенная аналогов — {name}",
                a.peer_wavg_price,
                money(a.peer_wavg_price),
            ),
        ]
    items = [
        {
            "lot": a.lot_number,
            "customer": a.customer_name,
            "item": a.item_name,
            "price": f"{money(a.price)} / {a.unit_name or 'ед.'}",
            "peer": money(a.peer_wavg_price),
            "deviation": pct(a.deviation, True),
            "z": num(a.robust_z, 2) if a.robust_z is not None else "—",
            "peers": num(a.peer_n),
            "group": f"подкласс «{a.subclass_label}»" if a.subclass_label else "весь код",
            "overpayment": money(a.overpayment_kzt),
            "link": a.contract_url,
        }
        for a in report.items
    ]
    limitations = [
        "Аналоги других заказчиков по РК в основном за 2026 год (ограничение поиска OWS)"
    ]
    if any(a.heterogeneous_group for a in report.items):
        limitations.append("Часть групп ЕНС ТРУ неоднородна: под одним кодом товары разного класса")
    return ToolResult(
        tool="price_anomalies",
        title="Отклонения цен от средневзвешенной по ЕНС ТРУ",
        args=report.params,
        facts=facts,
        items=items,
        columns=[
            ("lot", "Лот"),
            ("customer", "Заказчик"),
            ("item", "Предмет"),
            ("price", "Цена"),
            ("peer", "Средневзв. аналогов"),
            ("deviation", "Отклонение"),
            ("z", "z"),
            ("peers", "N аналогов"),
            ("group", "Группа сравнения"),
            ("overpayment", "Переплата"),
            ("link", "Договор"),
        ],
        method=report.method,
        limitations=limitations,
        sample_size=report.checked,
    )


async def volume_anomaly(session: AsyncSession, p: ResolvedParams) -> ToolResult:
    report = await volume_anomalies(
        session,
        min_ratio=1 + p.threshold if p.threshold > 0.3 else 1.5,
        customer_bins=p.customer_bins,
        years=[y for y in p.years if y > min(p.years)] or p.years,
        enstru_codes=p.enstru_codes,
        limit=p.top_k,
    )
    min_ratio = float(report.params["min_ratio"])
    facts = [
        fact("Минимальный рост к базе", min_ratio, times(min_ratio)),
        fact("Проверено пар заказчик × ЕНС ТРУ × год", report.checked, num(report.checked)),
        fact("Рост выше порога (критерий)", report.matched, num(report.matched)),
        fact("Подтверждено Isolation Forest", report.confirmed, num(report.confirmed)),
    ]
    for i, v in enumerate(report.items[:5], 1):
        name = v.enstru_name or v.enstru_code
        base = v.baseline_quantity
        facts += [
            fact(f"#{i} количество {v.year} — {name}", v.quantity, num(v.quantity, 2)),
            fact(f"#{i} среднее за прошлые годы — {name}", base, num(base, 2)),
            fact(f"#{i} рост — {name}", v.ratio, times(v.ratio)),
        ]
        if v.peer_ratio is not None:
            label = f"#{i} рост у других заказчиков — {name}"
            facts.append(fact(label, v.peer_ratio, times(v.peer_ratio)))
        if v.extra_amount is not None:
            label = f"#{i} сумма прироста — {name}"
            facts.append(fact(label, v.extra_amount, money(v.extra_amount)))
    items = [
        {
            "customer": v.customer_name,
            "item": v.enstru_name or v.enstru_code,
            "year": str(v.year),
            "quantity": f"{num(v.quantity, 2)} {v.unit_name or ''}".strip(),
            "baseline": num(v.baseline_quantity, 2),
            "ratio": times(v.ratio),
            "peers": f"{times(v.peer_ratio)} (n={v.peer_n})" if v.peer_ratio else "—",
            "extra": money(v.extra_amount),
            "model": f"{'да' if v.confirmed else 'нет'} ({num(v.isolation_score, 3)})",
        }
        for v in report.items
    ]
    limitations = [
        "Годы 2024–2026: база сравнения — 1–2 предыдущих года",
        "Коды ЕНС ТРУ могут меняться между годами; такие позиции без базы не сравниваются",
    ]
    if any(v.ratio > 100 for v in report.items):
        limitations.append(
            "Рост более чем в 100 раз обычно означает разные единицы измерения в разные годы "
            "или ошибку в плане"
        )
    return ToolResult(
        tool="volume_anomalies",
        title="Нетипичный рост количества ТРУ",
        args=report.params,
        facts=facts,
        items=items,
        columns=[
            ("customer", "Заказчик"),
            ("item", "ТРУ"),
            ("year", "Год"),
            ("quantity", "Количество"),
            ("baseline", "Среднее за прошлые годы"),
            ("ratio", "Рост"),
            ("peers", "Рост у других"),
            ("extra", "Сумма прироста"),
            ("model", "Нетипично по Isolation Forest"),
        ],
        method=report.method,
        limitations=limitations,
        sample_size=report.checked,
    )


async def fair_price(session: AsyncSession, p: ResolvedParams) -> list[ToolResult]:
    if not p.lot_numbers:
        raise NotFoundError(
            "Для оценки справедливости цены укажите номер лота, например 54949500-ЗЦП4"
        )
    results = []
    for lot in p.lot_numbers[:MAX_LOTS]:
        for r in await fair_price_for_lot(session, lot):
            t, adj = r.target, r.adjustments
            unit = t.unit_name or "ед."
            facts = [
                fact("Заказчик лота", t.customer_bin, t.customer_name or t.customer_bin or "—"),
                fact("Место поставки", t.locality_name, t.locality_name or t.region_name or "—"),
                fact(f"Цена лота {t.lot_number} за {unit}", t.price, money(t.price)),
                fact("Fair Price (взвешенная медиана аналогов)", r.fair_price, money(r.fair_price)),
                fact("Средневзвешенная цена аналогов", r.wavg_price, money(r.wavg_price)),
                fact("Нижняя граница коридора (P25)", r.p25, money(r.p25)),
                fact("Верхняя граница коридора (P75)", r.p75, money(r.p75)),
                fact("Отклонение от Fair Price", r.deviation, pct(r.deviation, True)),
                fact("Число аналогов", r.n, num(r.n)),
                fact("Число заказчиков-аналогов", r.n_customers, num(r.n_customers)),
                fact(
                    "Группа аналогов",
                    r.peer_group,
                    f"подкласс «{t.subclass_label}» (похожие описания)"
                    if r.peer_group == "subclass"
                    else "все позиции кода ЕНС ТРУ",
                ),
                fact("Уровень выборки", r.level, LEVELS_RU.get(r.level or "", "—")),
                fact("Вердикт", r.verdict, VERDICTS_RU[r.verdict]),
                fact("Уверенность", r.confidence, f"{num(r.confidence, 2)} ({r.confidence_label})"),
                fact(
                    "Региональный коэффициент места поставки",
                    adj.region_coefficient_target,
                    num(adj.region_coefficient_target, 3),
                ),
                fact(
                    "Сезонный коэффициент месяца",
                    adj.seasonal_factor_target,
                    num(adj.seasonal_factor_target, 3),
                ),
            ]
            if r.robust_z is not None:
                facts.append(fact("Robust z-score цены", r.robust_z, num(r.robust_z, 2)))
            items = [
                {
                    "date": fmt_date(c.sign_date),
                    "customer": c.customer_name,
                    "similarity": num(c.similarity, 2) if c.similarity is not None else "—",
                    "region": c.region_name,
                    "price": money(c.price),
                    "adjusted": money(c.adjusted_price),
                    "quantity": num(c.quantity, 2),
                    "link": c.contract_url or c.announce_url,
                }
                for c in r.comparables
            ]
            results.append(
                ToolResult(
                    tool="fair_price",
                    title=f"Fair Price: лот {t.lot_number} — {t.item_name}",
                    args={"lot": lot, "unit_id": t.unit_id, "enstru_code": t.enstru_code},
                    facts=facts,
                    items=items,
                    columns=[
                        ("date", "Дата"),
                        ("customer", "Заказчик-аналог"),
                        ("similarity", "Сходство описания"),
                        ("region", "Регион"),
                        ("price", "Цена"),
                        ("adjusted", "Цена с поправками"),
                        ("quantity", "Кол-во"),
                        ("link", "Договор"),
                    ],
                    method=r.method,
                    limitations=r.limitations,
                    sample_size=r.n,
                    confidence=r.confidence,
                    confidence_label=r.confidence_label,
                )
            )
    return results


SUGGEST_LOTS_SQL = """
SELECT lot_number, max(item_name) AS item, max(customer_name) AS customer,
       max(price_norm) AS price, max(unit_norm_name) AS unit, sum(amount_kzt) AS amount
FROM mart.price_observation
WHERE {where} AND lot_number IS NOT NULL
GROUP BY lot_number
ORDER BY amount DESC NULLS LAST
LIMIT 5
"""


async def suggest_lots(session: AsyncSession, p: ResolvedParams) -> list[str]:
    if not (p.customer_bins or p.enstru_codes):
        return []
    where, params = _where(p, market=False)
    rows = await session.execute(text(SUGGEST_LOTS_SQL.format(where=where)), params)
    return [
        f"{r.lot_number} — {r.item}, {r.customer}, {money(r.price)} / {r.unit or 'ед.'}"
        for r in rows
    ]


ToolFn = Callable[[AsyncSession, ResolvedParams], Awaitable[ToolResult | list[ToolResult]]]

ROUTES: dict[Intent, list[ToolFn]] = {
    "search": [search],
    "compare": [compare],
    "analytics": [efficiency, compare],
    "price_anomaly": [price_anomaly],
    "volume_anomaly": [volume_anomaly],
    "fair_price": [fair_price],
    "out_of_scope": [],
}


async def run_tools(session: AsyncSession, p: ResolvedParams) -> list[ToolResult]:
    results: list[ToolResult] = []
    tools = [compare] if p.intent == "analytics" and p.enstru_codes else ROUTES[p.intent]
    for tool in tools:
        out = await tool(session, p)
        results.extend(out if isinstance(out, list) else [out])
    return results
