"""Same-actor genuine credential around the existing native report compiler/intent checks."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.native_report_intent import NativeReportIntent
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NexusReportIntent(NativeReportIntent):
    def __init__(
        self, original: NativeReportIntent, credential: AuthenticatedWorkerIdentity
    ) -> None:
        if type(original) is not NativeReportIntent or not isinstance(
            credential, AuthenticatedWorkerIdentity
        ):
            raise ValueError("Nexus report requires its actual intent and authenticated actor")
        super().__init__(original.context, original.prepared, original.resources)
        self.credential = credential
        self._original = original
        self._objects = (
            original,
            self.context,
            self.prepared,
            self.resources,
            credential,
            self.context.services,
            self.context.services.publisher.catalog,
        )
        self._pins = self.fingerprint()
        self.require_composition()

    def fingerprint(self) -> tuple[object, ...]:
        context = self.context
        services = context.services
        reader = services.producer.inputs.reader
        if type(reader) is not ReportArtifactReader:
            raise ValueError("Nexus report requires its concrete protected reader")
        return (
            context.lease,
            context.identity,
            context.command,
            context.action,
            context.credential_provider,
            context.original_end_us,
            context.services.report_credentials,
            self.prepared,
            self.resources,
            self.credential.identity,
            self.credential.issued_at,
            self.credential.expires_at,
            canonical_sha256(services.publisher.catalog),
            services.factory,
            services.execution,
            services.effects,
            services.producer,
            services.publisher,
            services.artifacts,
            services.publisher.validator,
            services.publisher.freshness,
            tuple(
                sorted(
                    (key, canonical_sha256(value))
                    for key, value in services.publisher.rules.items()
                )
            ),
            tuple(
                sorted(
                    (key, canonical_sha256(value))
                    for key, value in services.publisher.policies.items()
                )
            ),
            services.producer.inputs,
            reader,
            reader.artifacts,
            reader.retriever,
            reader.retriever.factory,
            reader.retriever.blobs,
            services.publisher.blobs,
            services.artifacts.blobs,
            services.execution._factory,
            services.effects._factory,
            services.producer.factory,
            services.publisher.factory,
            services.artifacts.factory,
        )

    def require_composition(self) -> None:
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self._original,
                        self.context,
                        self.prepared,
                        self.resources,
                        self.credential,
                        self.context.services,
                        self.context.services.publisher.catalog,
                    ),
                    strict=True,
                )
            )
            or self.fingerprint() != self._pins
        ):
            raise ValueError("Nexus report original composition changed")
        context = self.context
        if (
            context.credential is not self.credential
            or context.credential_provider is None
            or context.original_end_us is None
            or clock_us() >= context.original_end_us
            or not any(
                binding.task_id == context.lease.task_id and provider is context.credential_provider
                for binding, provider in context.services.report_credentials
            )
        ):
            raise ValueError("Nexus report original credential provider/window changed")
        if (
            self.credential.identity != self.context.identity
            or self.context.lease.expires_at > self.credential.expires_at
        ):
            raise ValueError("Nexus report credential does not cover its original lease")
        if (
            self._original.context is not self.context
            or self._original.prepared is not self.prepared
            or self._original.resources is not self.resources
        ):
            raise ValueError("Nexus report original intent changed")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.require_composition()
        self.credential.require_time(now)
        await super().validate(session, control, work, action, now)
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.credential.require_time(now)
        super().validate_time(now)
