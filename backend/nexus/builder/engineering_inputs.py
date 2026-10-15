"""Server-only exact native result lookup after current complete protected READ."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.engineering_bodies import (
    BODY_READ_SECONDS,
    CompleteEngineeringBody,
    load_complete_engineering_body,
    revalidate_complete_engineering_artifact_locked,
)
from nexus.builder.engineering_contracts import (
    EngineeringChangeDeclaration,
    EngineeringCheckInput,
    EngineeringSourceWitness,
)
from nexus.builder.engineering_metadata import EngineeringMetadata, actual_engineering_metadata
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.verification_support import (
    actual_result_reference,
    require_containment_configuration,
    require_result_containment,
    require_summary_containment,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourceFreshness,
)
from nexus.execution.runtime_support import db_now, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class PreparedEngineeringInput:
    command: EngineeringCheckInput
    metadata: EngineeringMetadata
    artifacts: tuple[ArtifactSlice, ...]
    freshness: tuple[QualifiedFreshness, ...]


def engineering_scope(
    scope: BrainReadScope, identity: VerifiedIdentity, target: VerificationSpec
) -> LedgerScope:
    require_acceptance(
        (scope.company_id, scope.principal_id, scope.task_id, scope.task_trace_id, scope.actor_id)
        == (
            target.company_id,
            target.verifier.actor_id,
            target.verifier.task_id,
            target.verifier.trace_id,
            target.verifier.actor_id,
        )
        and identity.principal_id == target.verifier.actor_id
        and identity.workspace_id == target.verifier.workspace_id
    )
    return LedgerScope(
        company_id=scope.company_id,
        principal_id=identity.principal_id,
        task_id=target.verifier.task_id,
        trace_id=target.verifier.trace_id,
    )


class RegisteredEngineeringInputs:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        reader: BoundedArtifactReader,
        results: BuilderResultStore,
        declarations: tuple[EngineeringChangeDeclaration, ...],
        freshness: RegisteredSourceFreshness,
        *,
        containment_store: ContainmentEvidenceStore | None = None,
        execution_method_sha256: str | None = None,
    ) -> None:
        require_containment_configuration(containment_store, execution_method_sha256)
        if not 0 < len(declarations) <= 32 or len({row.goal_id for row in declarations}) != len(
            declarations
        ):
            raise ValueError("Engineering declarations must be bounded and exact")
        self.factory, self.reader, self.results, self.freshness = (
            factory,
            reader,
            results,
            freshness,
        )
        self.declarations = {row.goal_id: row for row in declarations}
        self.containment_store, self.execution_method_sha256 = (
            containment_store,
            execution_method_sha256,
        )

    async def load(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        target: VerificationSpec,
        verifier_action_id: UUID,
    ) -> PreparedEngineeringInput:
        ledger = engineering_scope(scope, identity, target)
        async with runtime_transaction(self.factory, ledger, identity) as (session, _, _):
            metadata = await actual_engineering_metadata(session, target, verifier_action_id)
        declaration = self.declarations.get(metadata.author_registration.work.goal_id)
        require_acceptance(declaration is not None)
        assert declaration is not None
        require_acceptance(declaration.procedure_id == metadata.procedure_id)
        bodies = await self._artifacts(scope, identity, metadata)
        artifacts = tuple(body.first for body in bodies)
        original: dict[UUID, QualifiedFreshness] = {}
        for body in bodies:
            for row in body.freshness:
                require_acceptance(row.source_id not in original or original[row.source_id] == row)
                original.setdefault(row.source_id, row)
        freshness = tuple(original[key] for key in sorted(original))
        author, first = await self._result(metadata.author_spec, bodies[0])
        verifier, second = await self._result(metadata.verifier_spec, bodies[1])
        command = EngineeringCheckInput(
            company_id=target.company_id,
            target=target,
            declaration=declaration,
            author=author,
            verifier=verifier,
            author_receipt=metadata.author_receipt,
            verifier_receipt=metadata.verifier_receipt,
            author_registration=metadata.author_registration,
            verifier_registration=metadata.verifier_registration,
            author_output=metadata.author_output,
            verifier_output=metadata.verifier_output,
            author_witness=first,
            verifier_witness=second,
        )
        return PreparedEngineeringInput(command, metadata, artifacts, freshness)

    async def _artifacts(
        self, scope: BrainReadScope, identity: VerifiedIdentity, metadata: EngineeringMetadata
    ) -> tuple[CompleteEngineeringBody, ...]:
        refs = [metadata.author_output, metadata.verifier_output]
        require_acceptance(all(ref.byte_length <= 262144 for ref in refs))
        for spec in (metadata.author_spec, metadata.verifier_spec):
            require_acceptance(
                spec.protected_patch is not None and spec.protected_patch.byte_length > 0
            )
            assert spec.protected_patch is not None
            if spec.protected_patch not in refs:
                refs.append(spec.protected_patch)
        result = []
        async with asyncio.timeout(BODY_READ_SECONDS):
            for ref in refs:
                result.append(
                    await load_complete_engineering_body(
                        self.reader, self.freshness, scope, identity, ref
                    )
                )
        return tuple(result)

    async def _result(
        self, spec: BuilderExecutionSpec, protected: CompleteEngineeringBody
    ) -> tuple[BuilderRunResult, EngineeringSourceWitness]:
        protected.require_integrity()
        result = await self.results.load(spec)
        require_acceptance(result is not None and result.spec == spec)
        assert result is not None
        value = json.loads(protected.raw)
        require_acceptance(
            (
                value.get("result_sha256"),
                value.get("spec"),
                value.get("proposal_sha256"),
                value.get("intent_fence"),
            )
            == (
                BuilderResultStore.digest(result),
                spec.model_dump(mode="json"),
                result.proposal_sha256,
                result.intent_fence,
            )
        )
        require_summary_containment(result, protected.raw.decode())
        await require_result_containment(
            result, self.containment_store, self.execution_method_sha256
        )
        witness = EngineeringSourceWitness.model_validate_json(
            json.dumps(value.get("engineering_source_witness"))
        )
        return result, witness

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        prepared: PreparedEngineeringInput,
        now: datetime,
    ) -> None:
        engineering_scope(scope, identity, prepared.command.target)
        require_acceptance(
            self.declarations.get(prepared.metadata.author_registration.work.goal_id)
            == prepared.command.declaration
        )
        current = await actual_engineering_metadata(
            session, prepared.command.target, prepared.command.verifier.spec.job.action_id
        )
        require_acceptance(current == prepared.metadata)
        require_acceptance(
            await actual_result_reference(session, prepared.command.author) == current.author_output
            and await actual_result_reference(session, prepared.command.verifier)
            == current.verifier_output
        )
        for result in (prepared.command.author, prepared.command.verifier):
            await require_result_containment(
                result, self.containment_store, self.execution_method_sha256
            )
        for artifact in prepared.artifacts:
            await revalidate_complete_engineering_artifact_locked(
                self.reader, session, control, scope, identity, artifact, await db_now(session)
            )
        await self.freshness.revalidate(session, scope, prepared.freshness, await db_now(session))
