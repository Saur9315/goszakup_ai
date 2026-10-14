from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goszakup_ai.agent.schemas import QuestionAnalysis, ResolvedParams
from goszakup_ai.core.scope import TARGET_YEARS

BIN_RE = re.compile(r"\b\d{12}\b")
LOT_RE = re.compile(r"\b\d{5,10}-[A-ZА-ЯЁ]+(?:-[A-ZА-ЯЁ]+)*\d+\b")

ITEM_SQL = """
SELECT enstru_code, max(word_similarity(:q, name)) AS sim, sum(n_scope) AS n_scope,
       sum(n_obs) AS n_obs
FROM mart.item_catalog
WHERE :q <% name
GROUP BY enstru_code
ORDER BY sim DESC, n_scope DESC, n_obs DESC
LIMIT 20
"""

ENSTRU_NAME_SQL = """
SELECT DISTINCT ON (code) code, name_ru FROM core.ref_enstru
WHERE code = ANY(:codes) ORDER BY code, id DESC
"""

REGION_SQL = """
SELECT code, name_ru, similarity(lower(name_ru), lower(:q)) AS sim
FROM core.ref_kato WHERE level = 1
ORDER BY sim DESC LIMIT 1
"""

MAX_CODES_PER_ITEM = 5


async def scope_orgs(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(text("SELECT bin, name_ru FROM meta.scope_bin ORDER BY name_ru"))
    return [(r.bin, r.name_ru or "") for r in rows]


async def _known_bins(session: AsyncSession, bins: list[str]) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT DISTINCT ON (b) b, s.name_ru FROM unnest(CAST(:bins AS text[])) b "
            "JOIN core.subject s ON s.bin = b OR s.iin = b ORDER BY b, s.pid DESC"
        ),
        {"bins": bins},
    )
    return {r.b: r.name_ru or "" for r in rows}


async def _items_to_codes(session: AsyncSession, item: str) -> list[str]:
    rows = (await session.execute(text(ITEM_SQL), {"q": item.lower()})).all()
    if not rows:
        return []
    best = float(rows[0].sim)
    close = [r for r in rows if float(r.sim) >= best - 0.05]
    in_scope = [r for r in close if r.n_scope]
    chosen = in_scope or close
    return [r.enstru_code for r in chosen[:MAX_CODES_PER_ITEM]]


async def resolve(
    session: AsyncSession, analysis: QuestionAnalysis, question: str
) -> ResolvedParams:
    notes: list[str] = []

    bins = list(dict.fromkeys([*analysis.bins, *BIN_RE.findall(question)]))
    known = await _known_bins(session, bins) if bins else {}
    for b in bins:
        if b not in known:
            notes.append(f"БИН {b} не найден в загруженных данных")

    lots = list(dict.fromkeys([*LOT_RE.findall(question), *analysis.lot_numbers]))

    codes: list[str] = []
    for item in analysis.items:
        found = await _items_to_codes(session, item)
        if found:
            codes.extend(c for c in found if c not in codes)
        else:
            notes.append(f"Для «{item}» не найден код ЕНС ТРУ в данных")
    names: dict[str, str] = {}
    if codes:
        rows = await session.execute(text(ENSTRU_NAME_SQL), {"codes": codes})
        names = {r.code: r.name_ru for r in rows}

    region_code = region_name = None
    if analysis.region:
        row = (await session.execute(text(REGION_SQL), {"q": analysis.region})).first()
        if row is not None and float(row.sim) >= 0.3:
            region_code, region_name = row.code, row.name_ru
        else:
            notes.append(f"Регион «{analysis.region}» не распознан")

    years = [y for y in analysis.years if y in TARGET_YEARS] or list(TARGET_YEARS)
    if analysis.years and len(years) < len(analysis.years):
        notes.append("Данные загружены только за 2024–2026 годы")

    compare_by = analysis.compare_by or ("customer" if len(known) >= 2 else "year")
    threshold = (analysis.threshold_pct or 30) / 100
    return ResolvedParams(
        language=analysis.language,
        intent=analysis.intent,
        customer_bins=[b for b in bins if b in known],
        customer_names=known,
        enstru_codes=codes,
        enstru_names=names,
        items=analysis.items,
        lot_numbers=lots,
        years=years,
        region_code=region_code,
        region_name=region_name,
        threshold=threshold,
        compare_by=compare_by,
        top_k=min(analysis.top_k or 10, 50),
        notes=notes,
    )
