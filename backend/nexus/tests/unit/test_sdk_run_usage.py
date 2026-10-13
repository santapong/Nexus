"""SDK migration cannot silently replace observed or unavailable usage with zero."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from nexus.agents.analyst import AnalystAgent
from nexus.agents.ceo import CEOAgent
from nexus.agents.director import DirectorAgent
from nexus.agents.engineer import EngineerAgent
from nexus.agents.qa import QAAgent
from nexus.agents.writer import WriterAgent
from nexus.core.kafka.schemas import AgentCommand
from nexus.core.llm.benchmarking import run_model_benchmark
from nexus.core.llm.run_usage import UsageUnavailableError, extract_run_tokens
from nexus.db.models import AgentRole


async def test_real_sdk_result_uses_its_actual_input_and_output_counts() -> None:
    result = await Agent(TestModel(custom_output_text="synthetic"), name="usage_fixture").run(
        "Test"
    )
    tokens = extract_run_tokens(result)
    assert tokens.input_tokens > 0 and tokens.output_tokens > 0
    assert tokens.total_tokens == tokens.input_tokens + tokens.output_tokens


def test_old_callable_usage_is_explicitly_validated() -> None:
    result = SimpleNamespace(usage=lambda: SimpleNamespace(request_tokens=31, response_tokens=9))
    tokens = extract_run_tokens(result)
    assert tokens.input_tokens == 31 and tokens.output_tokens == 9


def test_observed_zero_usage_is_distinct_from_missing_usage() -> None:
    result = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    assert extract_run_tokens(result).total_tokens == 0


@pytest.mark.parametrize("value", [None, True, "10", -1, 1.5, MagicMock()])
def test_invalid_new_usage_never_becomes_a_successful_zero_bill(value: object) -> None:
    result = SimpleNamespace(usage=SimpleNamespace(input_tokens=value, output_tokens=1))
    with pytest.raises(UsageUnavailableError):
        extract_run_tokens(result)


@pytest.mark.parametrize("result", [None, object(), SimpleNamespace(usage=None)])
def test_absent_usage_is_unknown_instead_of_free(result: object) -> None:
    with pytest.raises(UsageUnavailableError):
        extract_run_tokens(result)


def test_invalid_new_fields_cannot_fall_back_to_old_fields_on_property() -> None:
    result = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=None,
            output_tokens=1,
            request_tokens=100,
            response_tokens=20,
        )
    )
    with pytest.raises(UsageUnavailableError):
        extract_run_tokens(result)


@pytest.mark.parametrize(
    "agent_class, role, module",
    [
        (EngineerAgent, AgentRole.ENGINEER, "engineer"),
        (AnalystAgent, AgentRole.ANALYST, "analyst"),
        (WriterAgent, AgentRole.WRITER, "writer"),
        (QAAgent, AgentRole.QA, "qa"),
    ],
)
async def test_agents_record_real_sdk_usage_without_zero_fallback(
    agent_class: type[EngineerAgent] | type[AnalystAgent] | type[WriterAgent] | type[QAAgent],
    role: AgentRole,
    module: str,
) -> None:
    result = await Agent(TestModel(custom_output_text="synthetic"), name="usage_fixture").run(
        "Test"
    )
    expected = extract_run_tokens(result)
    llm_agent = MagicMock()
    llm_agent.model.model_name = "test:fixture"
    agent = agent_class(
        role=role,
        agent_id="fixture-agent",
        subscribe_topics=[],
        group_id="fixture",
        llm_agent=llm_agent,
        db_session_factory=MagicMock(),
    )
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="fixture-manager",
        payload={},
        target_role=role.value,
        instruction="Synthetic fixture",
    )
    with (
        patch.object(agent, "_run_with_retry", new=AsyncMock(return_value=result)),
        patch(f"nexus.agents.{module}.record_usage", new_callable=AsyncMock) as record,
        patch("nexus.agents.qa.publish", new_callable=AsyncMock),
    ):
        response = await agent.handle_task(command, AsyncMock())
    assert response.tokens_used == expected.total_tokens
    assert record.call_args.kwargs["input_tokens"] == expected.input_tokens
    assert record.call_args.kwargs["output_tokens"] == expected.output_tokens


async def test_engineer_cannot_report_success_when_usage_is_unavailable() -> None:
    llm_agent = MagicMock()
    agent = EngineerAgent(
        role=AgentRole.ENGINEER,
        agent_id="fixture-agent",
        subscribe_topics=[],
        group_id="fixture",
        llm_agent=llm_agent,
        db_session_factory=MagicMock(),
    )
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="fixture-manager",
        payload={},
        target_role="engineer",
        instruction="Synthetic fixture",
    )
    with (
        patch.object(
            agent,
            "_run_with_retry",
            new=AsyncMock(return_value=SimpleNamespace(output="generated draft")),
        ),
        patch("nexus.agents.engineer.record_usage", new_callable=AsyncMock) as record,
        pytest.raises(UsageUnavailableError),
    ):
        await agent.handle_task(command, AsyncMock())
    record.assert_not_called()


@pytest.mark.parametrize("method", ["_extract_requirements", "_create_plan", "_decompose_task"])
async def test_ceo_fallbacks_cannot_swallow_unknown_usage(method: str) -> None:
    agent = CEOAgent(
        role=AgentRole.CEO,
        agent_id="fixture-ceo",
        subscribe_topics=[],
        group_id="fixture",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(),
    )
    command = AgentCommand(
        task_id=uuid4(),
        trace_id=uuid4(),
        agent_id="fixture-manager",
        payload={},
        target_role="ceo",
        instruction="Synthetic fixture",
    )
    with (
        patch.object(
            agent, "_run_with_retry", new=AsyncMock(return_value=SimpleNamespace(output="{}"))
        ),
        patch("nexus.agents.ceo.record_usage", new_callable=AsyncMock) as record,
        pytest.raises(UsageUnavailableError),
    ):
        await getattr(agent, method)(command, AsyncMock())
    record.assert_not_called()


async def test_director_aggregation_fallback_cannot_swallow_unknown_usage() -> None:
    agent = DirectorAgent(
        role=AgentRole.DIRECTOR,
        agent_id="fixture-director",
        subscribe_topics=[],
        group_id="fixture",
        llm_agent=MagicMock(),
        db_session_factory=MagicMock(),
    )
    with (
        patch.object(
            agent, "_run_with_retry", new=AsyncMock(return_value=SimpleNamespace(output="draft"))
        ),
        patch("nexus.agents.director.record_usage", new_callable=AsyncMock) as record,
        pytest.raises(UsageUnavailableError),
    ):
        await agent._synthesize_result(
            task_id=str(uuid4()),
            original_instruction="Synthetic",
            aggregated_output="draft",
            convergence_context="",
            session=AsyncMock(),
        )
    record.assert_not_called()


async def test_benchmark_cannot_save_zero_billing_when_usage_is_missing() -> None:
    session = AsyncMock()
    row = MagicMock()
    row.scalar_one_or_none.return_value = SimpleNamespace(input="Synthetic benchmark")
    session.execute.return_value = row
    fake_agent = MagicMock()
    fake_agent.run = AsyncMock(return_value=SimpleNamespace(output="draft"))
    with (
        patch("nexus.core.llm.benchmarking.resolve_model", return_value=TestModel()),
        patch("nexus.core.llm.benchmarking.PydanticAgent", return_value=fake_agent),
        pytest.raises(UsageUnavailableError),
    ):
        await run_model_benchmark(session, "test:fixture", str(uuid4()), "engineer")
    session.flush.assert_not_called()
