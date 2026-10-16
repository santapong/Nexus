"""Real report services/publisher constructors, signed synthetic JWT and supplied native IO."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from unittest.mock import MagicMock

import jwt
from pydantic import SecretStr

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.management.acceptance_recovery import AcceptanceRecovery
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactRule
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.native_report_validator import NativeReportValidator
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.effect_store import EffectStore
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.unit.nexus_intent_fixture import Boundary


def credentials(
    binding: RunBinding, *, seconds: int = 120, foreign: bool = False
) -> NotificationWorkerIdentities:
    key = SecretStr("nexus-report-component-public-jwt-signing-key-32")
    now = datetime.now(UTC)
    raw = SecretStr(
        jwt.encode(
            {
                "sub": str(binding.actor_id if not foreign else binding.task_id),
                "workspace_id": str(binding.workspace_id),
                "iat": int((now - timedelta(seconds=10)).timestamp()),
                "exp": int((now + timedelta(seconds=seconds)).timestamp()),
            },
            key.get_secret_value(),
            algorithm="HS256",
        )
    )

    class Provider:
        async def credential(self) -> SecretStr:
            return raw

    return NotificationWorkerIdentities(Provider(), key, enabled=True)


def services(value: Boundary, effects: "EffectStore") -> NativeReportServices:
    from nexus.execution.effect_store import EffectStore

    assert isinstance(effects, EffectStore)
    factory = effects._factory
    catalog = value.catalog
    admission = catalog.nexus_cycle_admission
    assert admission is not None
    blobs = ProtectedBlobStore(
        Path("/var/tmp/nexus-component-unused-blobs"), storage_symbol="nexus.component.blobs"
    )
    artifacts = BoundedArtifactReader(factory, blobs)
    policies = SourceRegistry(
        tuple(
            SourcePolicy(
                source_symbol=symbol,
                authority_profile="nexus.component",
                data_classification="internal",
                origin_kind="derived",
                media_type="application/json",
                parser_version="v1",
                chunker_version="v1",
                search_config="simple",
                freshness_seconds=300,
            )
            for symbol in ("generated.report.v1", "generated.check.v1")
        ),
        MagicMock(),
    )
    reports = MagicMock(spec=OperatingReportStore)
    inputs = PersistentReportInputLoader(
        factory,
        ReportArtifactReader(
            PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits()), artifacts
        ),
        reports,
        source_policies=policies,
    )
    producer = NativeReportProducer(factory, reports, inputs)
    resources = {row.symbol: row.resource for row in catalog.resources}
    rules = tuple(
        GeneratedArtifactRule(
            company_id=admission.company_id,
            tool=cast(
                Literal["company.report.write.v1", "company.report.check.v1"], slot.tool.tool
            ),
            resource_symbol=slot.tool.resource,
            target=resources[slot.tool.resource],
            source_policy=symbol,
            recipe_version="native-report-profile-v1",
        )
        for slot, symbol in zip(
            admission.slots[3:5], ("generated.report.v1", "generated.check.v1"), strict=True
        )
    )
    publisher = GeneratedArtifactPublisher(
        factory,
        blobs,
        catalog,
        artifacts,
        policies,
        NativeReportValidator(producer),
        rules=rules,
    )
    identities = MagicMock()
    identities.actor.return_value = value.identity
    return NativeReportServices(
        factory,
        ExecutionStore(factory),
        effects,
        producer,
        publisher,
        MagicMock(spec=WorkAcceptanceStore),
        MagicMock(spec=AcceptanceRecovery),
        artifacts,
        identities,
        MagicMock(),
        WorkflowRegistration(
            workflow_name="internal.report",
            workflow_version="v1",
            queue_name="nexus.management.native",
            application_name="nexus-native-management",
        ),
        value.lease.worker_id,
        report_credentials=tuple(
            (slot.child.binding, credentials(slot.child.binding)) for slot in admission.slots[3:5]
        ),
    )
