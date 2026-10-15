"""Credential/config ordering only; dispatch SQL/lease delivery is deliberately absent."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from pydantic import SecretStr

from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.worker_config import (
    FileNotificationWorkerRegistration,
    WorkerConfigurationError,
)
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistrationFile,
)
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_dispatch_read import read_notification_dispatch
from nexus.execution.notification_worker_context import prepare_notification_context
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.unit.mixed_notification_history_fixture import HistoryCase, history_case
from nexus.tests.unit.strategy_transition_observation_fixture import transition_case
from nexus.tests.unit.test_company_notification_worker_config import registration
from nexus.tests.unit.test_company_notification_worker_identity import (
    TEST_KEY,
    FixtureCredential,
    signed,
)


def dispatch_case(tmp_path: Path) -> tuple[HistoryCase, MagicMock, list[str]]:
    """Actual ORM predicates plus GUC/SDK-row delivery mocks; no database permission proof."""
    from sqlalchemy.sql.elements import TextClause

    item = history_case(tmp_path)
    services = MagicMock(spec=NotificationDispatchWorkerServices)
    services.reads, services.dispatcher = item.mixed.reads, item.mixed.original
    factory = cast(MagicMock, item.mixed.reads.factory)
    factory.return_value.__aenter__.return_value = item.session
    item.session.begin = MagicMock()
    queries: list[str] = []

    async def execute(statement: object, *args: object) -> MagicMock:
        sql = str(statement)
        queries.append(sql)
        result = MagicMock()
        if isinstance(statement, TextClause):
            assert "FROM dbos.workflow_status" in sql
            result.mappings.return_value.one_or_none.return_value = {
                "name": "internal.owner-notification",
                "queue_name": None,
                "application_version": "v1",
                "application_name": "nexus-owner-notifications",
                "serialization": "portable_json",
                "status": "SUCCESS",
                "inputs": json.dumps(
                    {"positionalArgs": [item.command.model_dump_json()], "namedArgs": {}}
                ),
            }
        else:
            assert "set_config" in sql
        return result

    item.session.execute = AsyncMock(side_effect=execute)
    return item, services, queries


async def test_actual_issued_mixed_metadata_uses_recorded_family_when_paused(
    tmp_path: Path,
) -> None:
    item, services, queries = dispatch_case(tmp_path)
    result = await read_notification_dispatch(
        services, item.command, item.command.workflow_id, operation_guard=item.mixed.guard
    )
    assert result.binding == item.mixed.guard.registration.sender
    assert result.draft_id == item.mixed.draft_id and item.work.fence == 3
    assert sum("FROM dbos.workflow_status" in sql for sql in queries) == 1


async def test_fresh_mixed_metadata_uses_active_partition_and_denies_pause(tmp_path: Path) -> None:
    from nexus.company.notifications.dispatch_models import NotificationDispatchRow
    from nexus.execution.runtime_models import EffectIntent

    item, services, queries = dispatch_case(tmp_path)
    item.stored.pop((EffectIntent, (item.work.company_id, item.command.action_id)))
    item.stored.pop((NotificationDispatchRow, (item.work.company_id, item.mixed.draft_id)))
    with pytest.raises(ExecutionDeniedError) as denied:
        await read_notification_dispatch(
            services, item.command, item.command.workflow_id, operation_guard=item.mixed.guard
        )
    trace = denied.value.__traceback__
    paths = []
    while trace is not None:
        paths.append(Path(trace.tb_frame.f_code.co_filename).name)
        trace = trace.tb_next
    assert "cycle_partition_checks.py" in paths
    assert not any("FROM dbos.workflow_status" in sql for sql in queries)


async def test_mixed_metadata_current_member_is_checked_before_action_read(tmp_path: Path) -> None:
    from nexus.company.directory_models import DirectoryMembership
    from nexus.harness.journal_models import JournalAction

    item, services, queries = dispatch_case(tmp_path)
    member = item.stored[(DirectoryMembership, (item.work.company_id, item.work.actor_id))]
    assert isinstance(member, DirectoryMembership)
    member.membership_active = False
    actual = item.session.get
    action_reads = 0

    async def get(model: type[object], key: object) -> object:
        nonlocal action_reads
        if model is JournalAction:
            action_reads += 1
        return await actual(model, key)

    item.session.get = AsyncMock(side_effect=get)
    with pytest.raises(ExecutionDeniedError):
        await read_notification_dispatch(
            services, item.command, item.command.workflow_id, operation_guard=item.mixed.guard
        )
    assert action_reads == 0
    assert not any("FROM dbos.workflow_status" in sql for sql in queries)


class DispatchBoundaryReachedError(ValueError):
    """Stop before mocked dispatch SQL; reaching this is not native permission proof."""


def case(tmp_path: Path) -> tuple[MagicMock, SegmentCommand, FixtureCredential, Path]:
    cycle = transition_case(2)
    admission = cycle.catalog.cycle_admission
    assert admission is not None
    sender = admission.slots[-1].child.binding
    original = registration()
    value = original.model_copy(
        update={
            "company_id": sender.company_id,
            "workspace_id": sender.workspace_id,
            "sender": sender,
            "plan": original.plan.model_copy(update={"company_id": sender.company_id}),
            "catalog_sha256": canonical_sha256(cycle.catalog),
            "subjects": (),
        }
    )
    path = tmp_path / "mixed-context-registration.json"
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=value, configuration=NotificationWorkerConfiguration(enabled=True)
        ).model_dump_json()
    )
    path.chmod(0o600)
    provider = FixtureCredential(
        SecretStr(signed({"sub": str(sender.actor_id), "workspace_id": str(sender.workspace_id)}))
    )
    services = MagicMock(spec=NotificationDispatchWorkerServices)
    services.reads = SimpleNamespace(
        facts=SimpleNamespace(catalog=cycle.catalog),
        registrations=FileNotificationWorkerRegistration(path),
        require_registration=MagicMock(),
        identities=NotificationWorkerIdentities(provider, SecretStr(TEST_KEY), enabled=True),
        factory=MagicMock(side_effect=AssertionError("No dispatch SQL is permitted by this test")),
    )
    command = SegmentCommand(
        company_id=sender.company_id,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
        actor_id=sender.actor_id,
        workspace_id=sender.workspace_id,
        run_id=sender.run_id,
        action_id=UUID(int=901),
        segment_id=UUID(int=902),
    )
    return services, command, provider, path


async def test_mixed_context_gets_one_genuine_witness_before_dispatch_metadata(
    tmp_path: Path,
) -> None:
    services, command, provider, _ = case(tmp_path)

    async def metadata(
        *args: object, operation_guard: NotificationOperationGuard | None = None
    ) -> None:
        assert provider.requests == 1
        assert type(operation_guard) is NotificationOperationGuard
        assert operation_guard.witness.identity.principal_id == command.actor_id
        operation_guard.require_identity(operation_guard.witness.identity)
        raise DispatchBoundaryReachedError

    with (
        patch("nexus.execution.notification_worker_context.read_notification_dispatch", metadata),
        pytest.raises(DispatchBoundaryReachedError),
    ):
        await prepare_notification_context(services, command, workflow_id=command.workflow_id)
    services.execution.assert_not_called()


async def test_configuration_change_during_credential_await_denies_before_dispatch(
    tmp_path: Path,
) -> None:
    services, command, provider, path = case(tmp_path)
    original = provider.credential

    async def changed() -> SecretStr:
        value = await original()
        path.write_text(path.read_text() + "\n")
        return value

    provider.credential = changed  # type: ignore[method-assign]
    metadata = AsyncMock(side_effect=AssertionError("Changed original configuration reached SQL"))
    with (
        patch("nexus.execution.notification_worker_context.read_notification_dispatch", metadata),
        pytest.raises(WorkerConfigurationError),
    ):
        await prepare_notification_context(services, command, workflow_id=command.workflow_id)
    assert provider.requests == 1
    metadata.assert_not_awaited()


async def test_direct_mixed_dispatch_without_sealed_guard_denies_before_sql(tmp_path: Path) -> None:
    services, command, provider, _ = case(tmp_path)
    with pytest.raises(ExecutionDeniedError, match="sealed operation"):
        await read_notification_dispatch(services, command, command.workflow_id)
    assert provider.requests == 0
    services.reads.factory.assert_not_called()


@pytest.mark.parametrize("state", [None, "intent", "outcome_unknown", "succeeded", "failed"])
async def test_effect_uses_final_mixed_dispatcher_only_for_actual_unissued_history(
    tmp_path: Path, state: str | None
) -> None:
    from nexus.company.notifications.mixed_worker_dispatch import MixedNotificationDispatcher
    from nexus.execution.notification_worker_context import NotificationContext
    from nexus.execution.notification_worker_effect import run_notification_effect

    item, services, _ = dispatch_case(tmp_path)
    context = MagicMock(spec=NotificationContext)
    context.command = item.command
    context.lease, context.credential = item.mixed.lease, item.mixed.guard.witness
    context.draft_id, context.guard = item.mixed.draft_id, item.mixed.guard
    original = AsyncMock()
    services.dispatcher.dispatch_with_credential = original
    mixed = AsyncMock()
    with (
        patch(
            "nexus.execution.notification_worker_effect.read_notification_history",
            AsyncMock(return_value=SimpleNamespace(intent_state=state)),
        ),
        patch.object(MixedNotificationDispatcher, "dispatch_with_credential", mixed),
    ):
        await run_notification_effect(services, context)
    original.assert_not_awaited()
    assert mixed.await_count == int(state is None)
