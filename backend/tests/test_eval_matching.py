import pytest

from goszakup_ai.evals.matching import fact_present


@pytest.mark.parametrize(
    ("kind", "expected", "text", "found"),
    [
        ("money", 11_882_000_000, "на сумму 11,88 млрд ₸", True),
        ("money", 11_882_000_000, "на сумму 11,8 млрд ₸", False),
        ("money", 754_800, "на 754 800 ₸", True),
        ("money", 1_044_000, "1,0 млн ₸", True),
        ("count", 1915, "заключено 1 915 договоров", True),
        ("count", 1915, "заключено 1 916 договоров", False),
        ("pct", 0.259, "доля 25,9%", True),
        ("pct", 0.038, "отклонение +3,8% от Fair Price", True),
        ("pct", -0.12, "ниже на 12,0%", True),
        ("pct", 0.259, "доля 25,9 процента", False),
        ("number", 2.6237, "рост ×2,62", True),
        ("count", 24, "24 аналога, рост 24%", True),
        ("text", "990740002243", "(БИН 990740002243)", True),
        ("text", "31.12.2025", "по 31.12.2025", True),
    ],
)
def test_fact_present(kind: str, expected: float | str, text: str, found: bool) -> None:
    assert fact_present(kind, expected, text) is found  # type: ignore[arg-type]
