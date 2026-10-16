"""Original genuine planner witness around actual planning/context checks; no permission DTO."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.model_context_check import BrainModelContextCheck
from nexus.company.management.planning_intent import PlanningIntentCheck
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NexusPlanningIntentCheck(PlanningIntentCheck):
    def __init__(
        self, original: PlanningIntentCheck, credential: AuthenticatedWorkerIdentity
    ) -> None:
        if type(original) is not PlanningIntentCheck or not isinstance(
            credential, AuthenticatedWorkerIdentity
        ):
            raise ValueError("Nexus planning needs its actual check and authenticated actor")
        super().__init__(original._context_check, original._prepared, registry=original.registry)
        self.credential = credential
        self._original = original
        self._objects = (
            original,
            original._prepared,
            self._context_check,
            self._prepared,
            credential,
            self._context_check._revalidator,
        )
        self._pins = self.fingerprint()
        self.require_composition()

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        checker = self._context_check
        if type(checker._revalidator) is not PersistentContextAssembler:
            raise ValueError("Nexus planning requires the real context assembler")
        return checker._revalidator._factory

    def fingerprint(self) -> tuple[object, ...]:
        check = self._context_check
        return (
            self._prepared.model_dump_json(by_alias=True),
            check._lease,
            check._identity,
            check._scope,
            check._request,
            check._recipe,
            check._classification,
            self.credential.identity,
            self.credential.issued_at,
            self.credential.expires_at,
            self.factory,
            self.registry,
        )

    def require_composition(self) -> None:
        check = self._context_check
        if (
            type(check) is not BrainModelContextCheck
            or any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (
                        self._original,
                        self._original._prepared,
                        check,
                        self._prepared,
                        self.credential,
                        check._revalidator,
                    ),
                    strict=True,
                )
            )
            or self.fingerprint() != self._pins
        ):
            raise ValueError("Nexus planning original composition changed")
        if (
            self._original._context_check is not check
            or self._original._prepared != self._prepared
            or check._identity != self.credential.identity
            or check._lease.expires_at > self.credential.expires_at
        ):
            raise ValueError("Nexus planning credential does not cover its own original lease")
        if (
            self.registry is None
            or self._prepared.input_estimate is None
            or self._prepared.input_estimate.whole_request is None
        ):
            raise ValueError("Fresh Nexus planning requires its real whole-input proof")
        check._require_snapshot_binding()

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.validate_time(now)
        await super().validate(session, control, work, action, now)
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.credential.require_time(now)
        manifest = self._prepared.context.manifest
        deadlines = (
            self._context_check._lease.expires_at,
            *(grant.expires_at for grant in manifest.contributors),
            *(head.fresh_until for head in manifest.source_heads),
        )
        if any(end is not None and now >= end for end in deadlines):
            raise ValueError("Nexus planning original source/grant/lease window expired")
