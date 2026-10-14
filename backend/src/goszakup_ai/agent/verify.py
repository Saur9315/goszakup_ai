from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from goszakup_ai.agent.schemas import Fact, ResolvedParams, ToolResult, Verification

PLACEHOLDER_RE = re.compile(r"\{(f\d+)\}")
NUMBER_RE = re.compile(r"\d+(?:[\s .,]\d+)*")


def _normalize(token: str) -> str:
    return re.sub(r"[\s ]", "", token).replace(",", ".").rstrip(".")


def _spaces(text: str) -> str:
    return text.replace("\u00a0", " ")


def _numbers(text: str) -> list[str]:
    return [_normalize(m.group()) for m in NUMBER_RE.finditer(text)]


def _harvest(values: Iterable[Any]) -> set[str]:
    allowed: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        allowed.update(_numbers(text))
        if isinstance(value, float):
            allowed.update({f"{value:.0f}", f"{value:.1f}", f"{value:.2f}"})
    return allowed


def allowed_numbers(p: ResolvedParams, results: list[ToolResult], facts: list[Fact]) -> set[str]:
    values: list[Any] = [
        *p.customer_bins,
        *p.customer_names.values(),
        *p.enstru_codes,
        *p.enstru_names.values(),
        *p.lot_numbers,
        *p.years,
        *p.items,
        p.top_k,
        round(p.threshold * 100),
    ]
    for f in facts:
        values.extend([f.label, f.display, f.value])
    for r in results:
        values.append(r.title)
        for item in r.items:
            values.extend(item.values())
    return _harvest(values)


def verify(texts: list[str], fact_ids: set[str], allowed: set[str], attempts: int) -> Verification:
    total = grounded = 0
    unverified: list[str] = []
    for text in texts:
        for ref in PLACEHOLDER_RE.findall(text):
            total += 1
            if ref in fact_ids:
                grounded += 1
            else:
                unverified.append("{" + ref + "}")
        for number in _numbers(PLACEHOLDER_RE.sub(" ", text)):
            total += 1
            if number in allowed:
                grounded += 1
            else:
                unverified.append(number)
    return Verification(
        numbers_total=total, numbers_grounded=grounded, unverified=unverified, attempts=attempts
    )


def substitute(text: str, facts: dict[str, Fact]) -> str:
    return PLACEHOLDER_RE.sub(
        lambda m: facts[m.group(1)].display if m.group(1) in facts else "—", text
    )


def drop_footnote_refs(text: str, displays: dict[str, str] | None = None) -> str:
    displays = displays or {}
    matches = list(PLACEHOLDER_RE.finditer(text))
    plain = _spaces(PLACEHOLDER_RE.sub(" ", text))
    seen: set[str] = {_spaces(d) for d in displays.values() if _spaces(d) in plain}
    out = ""
    pos = 0
    dropped = False
    for i, m in enumerate(matches):
        gap_before = text[matches[i - 1].end() : m.start()] if i else None
        gap_after = text[m.end() : matches[i + 1].start()] if i + 1 < len(matches) else None
        adjacent = (gap_before is not None and not gap_before.strip()) or (
            gap_after is not None and not gap_after.strip()
        )
        after_sentence = text[: m.start()].rstrip().endswith((".", "!", "?"))
        clause_end = re.match(r"\s*([.,;:!?)]|$)", text[m.end() :]) is not None
        segment = text[pos : m.start()]
        if dropped and out and out[-1].isalnum() and segment[:1].isalpha():
            segment = " " + segment
        key = displays.get(m.group(1), m.group(1))
        key = _spaces(key) if key in displays.values() else key
        dropped = (adjacent or after_sentence or clause_end) and key in seen
        out += segment.rstrip() if dropped else segment + m.group()
        seen.add(key)
        pos = m.end()
    tail = text[pos:]
    if dropped and out and out[-1].isalnum() and tail[:1].isalpha():
        tail = " " + tail
    return re.sub(r"\s+([.,;:])", r"\1", out + tail).strip()
