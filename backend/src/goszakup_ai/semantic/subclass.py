from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from goszakup_ai.semantic.embedder import MODEL_ID, Embedder
from goszakup_ai.transform.text import desc_text_sql

log = logging.getLogger(__name__)

DISTANCE_THRESHOLD = 0.10
METHOD_ID = f"{MODEL_ID};average-cosine-{DISTANCE_THRESHOLD};medoid"
EMBED_CHUNK = 2048
CODE_BATCH = 300
LABEL_CHARS = 120

DESC = desc_text_sql("p.extra_desc_ru")

NEW_TEXTS_SQL = f"""
SELECT md5(t.txt) AS text_key, t.txt AS text
FROM (
    SELECT DISTINCT {DESC} AS txt FROM core.plan_point p WHERE p.extra_desc_ru IS NOT NULL
) t
LEFT JOIN core.item_text it ON it.text_key = md5(t.txt) AND it.model = :model
WHERE length(t.txt) > 3 AND it.text_key IS NULL
"""

UPSERT_TEXT_SQL = """
INSERT INTO core.item_text (text_key, text, model, embedding)
VALUES (:text_key, :text, :model, CAST(CAST(:embedding AS real[]) AS vector))
ON CONFLICT (text_key) DO UPDATE
SET text = excluded.text, model = excluded.model, embedding = excluded.embedding,
    created_at = now()
"""

CODE_TEXTS = f"""
SELECT p.enstru_code, md5({DESC}) AS text_key, count(*) AS n
FROM core.plan_point p
WHERE p.enstru_code IS NOT NULL AND p.extra_desc_ru IS NOT NULL
  AND length({DESC}) > 3 AND {DESC} <> lower(btrim(coalesce(p.name_ru, '')))
GROUP BY 1, 2
"""

DIRTY_CODES_SQL = f"""
WITH t AS ({CODE_TEXTS})
SELECT DISTINCT t.enstru_code
FROM t
JOIN core.item_text it ON it.text_key = t.text_key AND it.model = :model
LEFT JOIN core.item_subclass s
       ON s.enstru_code = t.enstru_code AND s.text_key = t.text_key AND s.method = :method
WHERE s.text_key IS NULL
UNION
SELECT DISTINCT s.enstru_code
FROM core.item_subclass s
LEFT JOIN t ON t.enstru_code = s.enstru_code AND t.text_key = s.text_key
WHERE t.text_key IS NULL OR s.method <> :method
"""

CLUSTER_INPUT_SQL = f"""
WITH t AS ({CODE_TEXTS})
SELECT t.enstru_code, t.text_key, t.n, it.text, CAST(it.embedding AS real[]) AS embedding
FROM t JOIN core.item_text it ON it.text_key = t.text_key AND it.model = :model
WHERE t.enstru_code = ANY(:codes)
ORDER BY t.enstru_code, t.text_key
"""

INSERT_SUBCLASS_SQL = """
INSERT INTO core.item_subclass (enstru_code, text_key, subclass, label, method)
VALUES (:enstru_code, :text_key, :subclass, :label, :method)
"""


@dataclass(frozen=True)
class SubclassStats:
    embedded: int
    codes: int
    seconds: float


def cluster_texts(vectors: np.ndarray, threshold: float = DISTANCE_THRESHOLD) -> np.ndarray:
    if len(vectors) < 2:
        return np.zeros(len(vectors), dtype=int)
    model = AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric="cosine", linkage="average"
    )
    raw = np.asarray(model.fit_predict(vectors))
    sizes = Counter(raw.tolist())
    order = {c: i for i, (c, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))}
    return np.array([order[c] for c in raw.tolist()], dtype=int)


def subclass_rows(code: str, rows: Sequence[Any]) -> list[dict[str, Any]]:
    vectors = np.array([r.embedding for r in rows], dtype=np.float32)
    labels = cluster_texts(vectors)
    names: dict[int, str] = {}
    for label in set(labels.tolist()):
        idx = np.flatnonzero(labels == label)
        centroid = vectors[idx].mean(axis=0)
        names[label] = rows[int(idx[np.argmax(vectors[idx] @ centroid)])].text[:LABEL_CHARS]
    return [
        {
            "enstru_code": code,
            "text_key": r.text_key,
            "subclass": label,
            "label": names[label],
            "method": METHOD_ID,
        }
        for r, label in zip(rows, labels.tolist(), strict=True)
    ]


async def embed_new_texts(engine: AsyncEngine, model_dir: Path) -> int:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(NEW_TEXTS_SQL), {"model": MODEL_ID})).all()
    if not rows:
        return 0
    log.info("embedding %d new descriptions", len(rows))
    embedder = Embedder(model_dir)
    for start in range(0, len(rows), EMBED_CHUNK):
        chunk = rows[start : start + EMBED_CHUNK]
        vectors = await asyncio.to_thread(embedder.embed, [r.text for r in chunk])
        async with engine.begin() as conn:
            await conn.execute(
                text(UPSERT_TEXT_SQL),
                [
                    {"text_key": r.text_key, "text": r.text, "model": MODEL_ID, "embedding": v}
                    for r, v in zip(chunk, vectors.tolist(), strict=True)
                ],
            )
        log.info("embedded %d / %d", min(start + EMBED_CHUNK, len(rows)), len(rows))
    return len(rows)


async def recluster(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        codes = list(
            (
                await conn.execute(text(DIRTY_CODES_SQL), {"model": MODEL_ID, "method": METHOD_ID})
            ).scalars()
        )
    for start in range(0, len(codes), CODE_BATCH):
        batch = codes[start : start + CODE_BATCH]
        async with engine.begin() as conn:
            rows = (
                await conn.execute(text(CLUSTER_INPUT_SQL), {"model": MODEL_ID, "codes": batch})
            ).all()
            by_code: dict[str, list[Any]] = {}
            for r in rows:
                by_code.setdefault(r.enstru_code, []).append(r)
            records = [rec for code, rs in by_code.items() for rec in subclass_rows(code, rs)]
            await conn.execute(
                text("DELETE FROM core.item_subclass WHERE enstru_code = ANY(:codes)"),
                {"codes": batch},
            )
            if records:
                await conn.execute(text(INSERT_SUBCLASS_SQL), records)
    return len(codes)


async def update_subclasses(engine: AsyncEngine, model_dir: Path) -> SubclassStats:
    started = time.monotonic()
    embedded = await embed_new_texts(engine, model_dir)
    codes = await recluster(engine)
    stats = SubclassStats(embedded, codes, round(time.monotonic() - started, 1))
    log.info(
        "subclasses: %d texts embedded, %d codes reclustered in %.1fs",
        stats.embedded,
        stats.codes,
        stats.seconds,
    )
    return stats
