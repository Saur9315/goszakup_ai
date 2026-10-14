from goszakup_ai.agent.schemas import Fact
from goszakup_ai.agent.verify import drop_footnote_refs, substitute, verify


def test_drop_footnote_refs_keeps_inline_values() -> None:
    text = "Цена {f1}, выше Fair Price {f2} {f1}{f2}. Коридор от {f4} до {f5} {f4}{f5}."
    assert drop_footnote_refs(text) == "Цена {f1}, выше Fair Price {f2}. Коридор от {f4} до {f5}."


def test_drop_footnote_refs_does_not_glue_words() -> None:
    text = "Выборка {f7} от {f8} заказчиков {f7}{f8}тот же город."
    assert drop_footnote_refs(text) == "Выборка {f7} от {f8} заказчиков тот же город."


def test_drop_footnote_refs_dedupes_same_value_at_clause_end() -> None:
    displays = {"f1": "×0,94", "f2": "×0,94", "f3": "705"}
    text = "Проверено {f3} пар {f3}. У других рост {f1} {f2}, у заказчика выше."
    assert drop_footnote_refs(text, displays) == (
        "Проверено {f3} пар. У других рост {f1}, у заказчика выше."
    )


def test_verify_flags_numbers_outside_facts() -> None:
    result = verify(
        ["Цена {f1} при выборке 24 аналога и росте на 17%", "Ссылка {f9}"],
        fact_ids={"f1"},
        allowed={"24"},
        attempts=1,
    )
    assert result.numbers_total == 4
    assert result.numbers_grounded == 2
    assert result.unverified == ["17", "{f9}"]


def test_substitute_uses_fact_display() -> None:
    facts = {"f1": Fact(id="f1", label="Цена", value=3200.0, display="3 200 ₸")}
    assert substitute("Цена {f1}, {f2}", facts) == "Цена 3 200 ₸, —"
