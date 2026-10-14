from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Intent = Literal["search", "compare", "analytics", "price_anomaly", "volume_anomaly", "fair_price"]
Language = Literal["ru", "kk"]
CompareBy = Literal["customer", "year", "region", "supplier", "trade_method"]


class QuestionAnalysis(BaseModel):
    language: Language = Field(description="Язык вопроса: ru — русский, kk — казахский")
    intent: Intent = Field(
        description=(
            "search — найти закупки, договоры, лоты или посчитать их количество и сумму; "
            "compare — сравнить заказчиков, годы, регионы, поставщиков; "
            "analytics — эффективность и общая картина закупок организации; "
            "price_anomaly — отклонения цен "
            "от средних; volume_anomaly — нетипичный рост количества по сравнению с прошлыми "
            "годами; fair_price — справедливость цены конкретного лота"
        )
    )
    bins: list[str] = Field(
        default_factory=list,
        description="БИН организаций: явно указанные или выбранные из списка по названию",
    )
    lot_numbers: list[str] = Field(
        default_factory=list, description="Номера лотов как в вопросе, например 54949500-ЗЦП4"
    )
    items: list[str] = Field(
        default_factory=list,
        description="Товары/работы/услуги из вопроса по-русски в именительном падеже",
    )
    years: list[int] = Field(default_factory=list, description="Годы 2024–2026, если указаны")
    region: str | None = Field(default=None, description="Регион или город, если указан")
    threshold_pct: float | None = Field(
        default=None, description="Порог отклонения в процентах, если указан (например 30)"
    )
    compare_by: CompareBy | None = Field(default=None, description="Разрез сравнения")
    top_k: int | None = Field(default=None, description="Сколько примеров показать, если указано")


class ResolvedParams(BaseModel):
    language: Language
    intent: Intent
    customer_bins: list[str] = Field(default_factory=list)
    customer_names: dict[str, str] = Field(default_factory=dict)
    enstru_codes: list[str] = Field(default_factory=list)
    enstru_names: dict[str, str] = Field(default_factory=dict)
    items: list[str] = Field(default_factory=list)
    lot_numbers: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    region_code: str | None = None
    region_name: str | None = None
    threshold: float = 0.3
    compare_by: CompareBy | None = None
    top_k: int = 10
    notes: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    id: str
    label: str
    value: Any
    display: str


class ToolResult(BaseModel):
    tool: str
    title: str
    args: dict[str, Any]
    facts: list[Fact] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[tuple[str, str]] = Field(default_factory=list)
    method: str = ""
    limitations: list[str] = Field(default_factory=list)
    sample_size: int | None = None
    confidence: float | None = None
    confidence_label: str | None = None


class AnswerDraft(BaseModel):
    verdict: str = Field(description="Краткий вывод: 1–3 предложения с цифрами через {fN}")
    analysis: list[str] = Field(
        description="2–5 пунктов: сравнение, средние значения, отклонения, все числа через {fN}"
    )


class Verification(BaseModel):
    numbers_total: int
    numbers_grounded: int
    unverified: list[str]
    attempts: int

    @property
    def accuracy(self) -> float:
        return self.numbers_grounded / self.numbers_total if self.numbers_total else 1.0


class AgentAnswer(BaseModel):
    run_id: str
    question: str
    params: ResolvedParams
    tool_results: list[ToolResult]
    verdict: str
    analysis: list[str]
    markdown: str
    verification: Verification
    data_as_of: datetime | None
    model: str
    latency_ms: int
