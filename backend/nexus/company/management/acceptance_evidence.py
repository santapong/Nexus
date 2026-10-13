"""Configured actual report-input lookup and protected mechanical-result verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import AcceptanceDeniedError, require_acceptance
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourceFreshness,
)
from nexus.company.management.check_contracts import (
    REPORT_CHECK_RECIPE,
    ReportCheckInput,
    ReportCheckResult,
)
from nexus.company.management.report_checker import check_internal_report
from nexus.harness.journal_models import CompanyControl


class ActualReportInputLoader(Protocol):
    """Server-only actual author/source/ledger lookup; no caller dict or auth flag.

    The immutable observed-at snapshot is retained only while all actual inputs
    still match. Final lookup is DB-only under CompanyControl, with no blob/model
    I/O and no use of this interface to manufacture a signed identity.
    """

    async def load(
        self, scope: BrainReadScope, identity: VerifiedIdentity, target: VerificationSpec
    ) -> ReportCheckInput: ...

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: ReportCheckInput,
        now: datetime,
    ) -> ReportCheckInput: ...


class AcceptanceArtifactReader(Protocol):
    """Actual bounded authorized bytes and public same-session complete provenance gate."""

    async def bounded_artifact(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        artifact_revision_id: UUID,
        *,
        start_byte: int,
        max_bytes: int,
        include_history: bool,
    ) -> ArtifactSlice: ...

    async def revalidate_artifact(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        artifact: ArtifactSlice,
        now: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class PreparedReportCheck:
    command: ReportCheckInput
    result: ReportCheckResult
    protected: ArtifactSlice
    input_artifacts: tuple[ArtifactSlice, ...]
    freshness: tuple[QualifiedFreshness, ...]


def validate_report_result(
    command: ReportCheckInput, reference: ArtifactRevisionRef, raw: bytes
) -> ReportCheckResult:
    """Integrity plus actual deterministic recomputation, never acceptance authority."""
    if (
        reference.company_id != command.company_id
        or not 0 < len(raw) <= 16_384
        or len(raw) != reference.byte_length
        or hashlib.sha256(raw).hexdigest() != reference.sha256
        or command.target.check_recipe != REPORT_CHECK_RECIPE
    ):
        raise AcceptanceDeniedError("Protected mechanical result is unavailable")
    try:
        json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        result = ReportCheckResult.model_validate_json(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AcceptanceDeniedError("Protected mechanical result format is unavailable") from exc
    if result != check_internal_report(command):
        raise AcceptanceDeniedError("Protected mechanical result does not match actual inputs")
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate protected result key")
        values[key] = value
    return values


class ProtectedReportEvidenceResolver:
    """Mandatory configured protected reader + actual input loader, never caller-selected."""

    def __init__(
        self,
        reader: AcceptanceArtifactReader,
        inputs: ActualReportInputLoader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        self._reader, self._inputs, self._freshness = reader, inputs, freshness

    async def prepare(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        target: VerificationSpec,
        reference: ArtifactRevisionRef,
    ) -> PreparedReportCheck:
        if reference.company_id != scope.company_id or reference.byte_length > 16_384:
            raise AcceptanceDeniedError("Protected mechanical result is unavailable")
        protected = await self._reader.bounded_artifact(
            scope,
            identity,
            reference.artifact_revision_id,
            start_byte=0,
            max_bytes=16_384,
            include_history=False,
        )
        if protected.artifact != reference or protected.has_more or protected.span.start_byte != 0:
            raise AcceptanceDeniedError("Protected result must contain the actual complete bytes")
        command = await self._inputs.load(scope, identity, target)
        command = ReportCheckInput.model_validate_json(command.model_dump_json())
        if command.target != target or command.company_id != scope.company_id:
            raise AcceptanceDeniedError("Actual input lookup binds another target")
        result = validate_report_result(command, reference, protected.text.encode())
        inputs = await self._input_artifacts(scope, identity, command)
        freshness = await self._freshness.prepare(scope, identity, (protected, *inputs))
        return PreparedReportCheck(command, result, protected, inputs, freshness)

    async def _input_artifacts(
        self, scope: BrainReadScope, identity: VerifiedIdentity, command: ReportCheckInput
    ) -> tuple[ArtifactSlice, ...]:
        cited = (
            tuple(row.evidence.artifact for row in command.snapshot.citations)
            if command.snapshot
            else ()
        )
        references = {
            row.artifact_revision_id: row
            for row in (*command.target.artifacts, command.output, *cited)
        }
        require_acceptance(
            len(references) <= 33
            and sum(row.byte_length for row in references.values()) <= 8_650_752
        )
        result: list[ArtifactSlice] = []
        for reference in references.values():
            artifact = await self._reader.bounded_artifact(
                scope,
                identity,
                reference.artifact_revision_id,
                start_byte=0,
                max_bytes=min(reference.byte_length, 16_384),
                include_history=False,
            )
            require_acceptance(artifact.artifact == reference)
            result.append(artifact)
        return tuple(result)

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        prepared: PreparedReportCheck,
        now: datetime,
    ) -> None:
        current = await self._inputs.revalidate(
            session, control, scope, identity, prepared.command, now
        )
        current = ReportCheckInput.model_validate_json(current.model_dump_json())
        if current != prepared.command:
            raise AcceptanceDeniedError("Actual protected report inputs changed")
        await self._reader.revalidate_artifact(
            session, control, scope, identity, prepared.protected, now
        )
        for artifact in prepared.input_artifacts:
            await self._reader.revalidate_artifact(session, control, scope, identity, artifact, now)
        await self._freshness.revalidate(session, scope, prepared.freshness, now)
        validate_report_result(
            current, prepared.protected.artifact, prepared.protected.text.encode()
        )
