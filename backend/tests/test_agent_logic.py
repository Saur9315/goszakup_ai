from goszakup_ai.agent.graph import Agent, AgentState, template_draft
from goszakup_ai.agent.prompts import history_block
from goszakup_ai.agent.schemas import Fact, Turn, Verification


def facts(n: int) -> list[Fact]:
    return [
        Fact(id=f"f{i}", label=f"Показатель {i}", value=i, display=str(i)) for i in range(1, n + 1)
    ]


def test_template_draft_uses_only_fact_references() -> None:
    draft = template_draft(facts(5))

    assert draft.verdict == "Показатель 1: {f1}; Показатель 2: {f2}; Показатель 3: {f3}."
    assert draft.analysis == ["Показатель 4: {f4}", "Показатель 5: {f5}"]


def test_history_block_keeps_last_turns_with_parameters() -> None:
    turns = [
        Turn(question=f"вопрос {i}", intent="search", customer_bins=["990740002243"], years=[2025])
        for i in range(5)
    ]

    block = history_block(turns)

    assert "вопрос 0" not in block and "вопрос 4" in block
    assert "БИН=990740002243" in block and "годы=2025" in block


def _verification(unverified: list[str]) -> Verification:
    return Verification(
        numbers_total=3, numbers_grounded=3 - len(unverified), unverified=unverified, attempts=1
    )


def test_after_verify_retries_once_on_unverified_numbers() -> None:
    after = Agent._after_verify
    state: AgentState = {"verification": _verification(["17"]), "attempts": 1}
    assert after(object(), state) == "compose"  # type: ignore[arg-type]
    assert after(object(), {**state, "attempts": 2}) == "remember"  # type: ignore[arg-type]
    assert after(object(), {**state, "llm_fallback": True}) == "remember"  # type: ignore[arg-type]
    clean: AgentState = {"verification": _verification([]), "attempts": 1}
    assert after(object(), clean) == "remember"  # type: ignore[arg-type]
