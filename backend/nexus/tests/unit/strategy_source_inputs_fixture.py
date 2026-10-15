"""Mocked DB boundary descriptions with an actually verified synthetic credential."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.source_models import BrainSource
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity, _verify
from nexus.company.strategy.contracts import StrategyCheckSnapshot
from nexus.company.strategy.source_inputs import StrategySourceInputs
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.strategy_brief_fixture import strategy_case


@dataclass
class SourceCase:
    service: StrategySourceInputs
    session: MagicMock
    control: CompanyControl
    scope: BrainReadScope
    original: StrategyCheckSnapshot
    credential: AuthenticatedWorkerIdentity
    native: BrainSource
    clock: dict[str, datetime]
    grant: ResourceGeneration


def source_case(monkeypatch: pytest.MonkeyPatch) -> SourceCase:
    # This coherent >50-line fixture binds source metadata, native mocks and actual signed time.
    from nexus.company.strategy import source_inputs as module

    original = strategy_case().command.snapshot
    assert original is not None
    now = datetime.now(UTC)
    source = original.sources[0]
    policy = source.source_policy.model_copy(
        update={"allowed_external_keys": frozenset({"fixture"})}
    )
    head = source.head.model_copy(
        update={"observed_at": now, "fresh_until": now + timedelta(hours=1)}
    )
    source = source.model_copy(update={"head": head, "source_policy": policy})
    original = original.model_copy(update={"observed_at": now, "sources": (source,)})
    author = original.scope.author
    key = SecretStr("strategy-source-public-synthetic-test-key-at-least-64-characters-long")
    claims = {
        "sub": str(author.actor_id),
        "workspace_id": str(author.workspace_id),
        "iat": int(now.timestamp()) - 1,
        "exp": int(now.timestamp()) + 300,
    }
    credential = _verify(
        SecretStr(jwt.encode(claims, key.get_secret_value(), algorithm="HS256")), key
    )
    scope = BrainReadScope(
        company_id=original.company_id,
        workspace_id=author.workspace_id,
        principal_id=author.actor_id,
        operation_id=UUID(int=200),
        trace_id=author.trace_id,
    )
    native = BrainSource(
        company_id=original.company_id,
        source_id=head.source_id,
        source_symbol=policy.source_symbol,
        authority_profile=policy.authority_profile,
        data_classification=policy.data_classification,
        external_key="fixture",
    )
    bundle = SimpleNamespace(
        source=native,
        artifact=SimpleNamespace(
            media_type=policy.media_type,
            byte_length=len(source.raw_text.encode()),
            raw_text=source.raw_text,
        ),
        record=lambda: source.evidence,
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    session.get = AsyncMock(return_value=native)
    control = CompanyControl(company_id=original.company_id, owner_id=UUID(int=3))
    clock = {"now": now}

    async def current(_: AsyncSession) -> datetime:
        return clock["now"]

    grant = ResourceGeneration(
        company_id=original.company_id,
        resource_id=original.inputs.required_resource_ids[0],
        generation=1,
        expires_at=now + timedelta(seconds=60),
    )
    reader = MagicMock(spec=BoundedArtifactReader)
    reader.revalidate_artifact_reference = AsyncMock()
    service = StrategySourceInputs(reader, SimpleNamespace(policy=lambda _: policy))
    monkeypatch.setattr(module, "db_now", current)
    monkeypatch.setattr(module, "require_brain_scope", AsyncMock())
    monkeypatch.setattr(
        module, "bundles", AsyncMock(return_value={source.evidence.evidence_id: bundle})
    )
    monkeypatch.setattr(module, "heads", AsyncMock(return_value=(head,)))
    monkeypatch.setattr(
        module, "native_manifest", AsyncMock(return_value=(original.inputs, "internal"))
    )
    monkeypatch.setattr(module, "require_resources", AsyncMock(return_value=(grant,)))
    return SourceCase(service, session, control, scope, original, credential, native, clock, grant)
