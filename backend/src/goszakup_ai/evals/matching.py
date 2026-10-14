from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

FactKind = Literal["count", "money", "pct", "number", "text"]

MULTIPLIERS = {"млрд": 1e9, "млн": 1e6, "тыс": 1e3}
NUMBER_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?"
    r"(?:\s*(млрд|млн|тыс)\.?)?(\s*%)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Quantity:
    value: float
    tolerance: float
    percent: bool


def quantities(text: str) -> Iterator[Quantity]:
    for m in NUMBER_RE.finditer(text):
        whole = re.sub(r"\D", "", m.group(1))
        fraction = m.group(2) or ""
        value = float(f"{whole}.{fraction}") if fraction else float(whole)
        step = 10.0 ** -len(fraction) if fraction else 1.0
        multiplier = MULTIPLIERS.get((m.group(3) or "").lower(), 1.0)
        percent = bool(m.group(4))
        value, step = value * multiplier, step * multiplier
        if percent:
            value, step = value / 100, step / 100
        yield Quantity(value, step / 2 + 1e-9, percent)


def fact_present(kind: FactKind, expected: float | str, text: str) -> bool:
    plain = text.replace(" ", " ").replace(" ", " ")
    if kind == "text":
        return str(expected).lower() in plain.lower()
    target = abs(float(expected))
    for q in quantities(plain):
        if (kind == "pct") != q.percent:
            continue
        tolerance = 0.5 if kind == "count" else q.tolerance
        if kind == "money":
            tolerance = max(tolerance, target * 0.005)
        if abs(q.value - target) <= tolerance:
            return True
    return False
