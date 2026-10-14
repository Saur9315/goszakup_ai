from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

NBSP = " "


def fmt_number(value: float | int | Decimal | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    text = f"{float(value):,.{digits}f}".replace(",", NBSP)
    return text.replace(".", ",") if digits else text


def fmt_money(value: float | int | Decimal | None) -> str:
    if value is None:
        return "—"
    v = float(value)
    if abs(v) >= 1e9:
        return f"{fmt_number(v / 1e9, 2)}{NBSP}млрд{NBSP}₸"
    if abs(v) >= 1e6:
        return f"{fmt_number(v / 1e6, 1)}{NBSP}млн{NBSP}₸"
    return f"{fmt_number(v, 0 if abs(v) >= 100 else 2)}{NBSP}₸"


def fmt_pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    text = f"{value * 100:+.1f}" if signed else f"{value * 100:.1f}"
    return f"{text.replace('.', ',')}%"


def fmt_date(value: date | datetime | str | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%d.%m.%Y")


def fmt_value(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "да" if value else "—"
    if isinstance(value, (int, float, Decimal)):
        return fmt_number(value, 0 if float(value).is_integer() else 2)
    if isinstance(value, (date, datetime)):
        return fmt_date(value)
    return str(value)
