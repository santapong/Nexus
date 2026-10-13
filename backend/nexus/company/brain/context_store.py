"""Shared context assembly and explicit same-session claim/publication revalidation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.context import (
    AssembledContext,
    ContextLimits,
    ContextManifest,
    ContextSelection,
)
from nexus.company.brain.context_render import Purpose, render_context
from nexus.company.brain.interfaces import ContextAuthorityProvider
from nexus.company.brain.models import BrainEvidence
from nexus.company.brain.retrieval import CitationHandle, SearchRequest
from nexus.company.brain.retrieval_records import heads
from nexus.company.brain.retrieval_sql import evidence_ids
from nexus.company.brain.retrieval_store import PersistentBrainRetriever, _clock
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
    revalidate_brain_scope,
)
from nexus.company.brain.sources import SourceHead
from nexus.company.contracts.actions import ResourceRevision
from nexus.harness.journal_models import CompanyControl


class PersistentContextAssembler:
    """Mandatory trusted limits/provider; no model calls or token-ledger invention."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        retriever: PersistentBrainRetriever,
        authority: ContextAuthorityProvider,
        *,
        limits: ContextLimits,
    ) -> None:
        self._factory, self._retriever, self._authority = factory, retriever, authority
        self._limits = ContextLimits.model_validate_json(limits.model_dump_json())

    async def assemble(
        self, scope: BrainReadScope, identity: VerifiedIdentity, selection: ContextSelection
    ) -> AssembledContext:
        selection = ContextSelection.model_validate_json(selection.model_dump_json())
        if selection.company_id != scope.company_id:
            raise BrainDeniedError("Brain context is unavailable")
        async with brain_transaction(self._factory, scope, identity) as (session, _, _):
            authority = await self._authority.current(session, scope, identity)
            section_ids = await self._sections(session, scope, selection)
        handles, purposes = await self._select(
            scope,
            identity,
            selection,
            section_ids,
            tuple(row.evidence_id for row in authority.feedback),
        )
        materials = await self._retriever.materialize(scope, identity, handles)
        source_heads = _combine_heads(handles)
        rendered = render_context(
            scope,
            authority,
            self._limits,
            materials,
            source_heads,
            question=selection.search.query
            if selection.search
            else "Review the selected authorized evidence",
            purposes=purposes,
            sections={
                row.artifact_revision_id: row.sections for row in selection.explicit_sections
            },
        )
        async with brain_transaction(self._factory, scope, identity) as (session, control, _):
            await self.revalidate_context(
                session, control, scope, identity, rendered.manifest, await _clock(session)
            )
            # Omissions still expose permitted reference metadata and must be rechecked too.
            await self._retriever._prepare(session, scope, handles, await _clock(session))
        return rendered

    async def _select(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        selection: ContextSelection,
        section_ids: tuple[UUID, ...],
        feedback_ids: tuple[UUID, ...],
    ) -> tuple[tuple[CitationHandle, ...], dict[UUID, Purpose]]:
        purposes: dict[UUID, Purpose] = dict.fromkeys(feedback_ids, "feedback")
        purposes.update({row.evidence_id: "workspace" for row in selection.workspace_files})
        purposes.update({row.evidence_id: "attachment" for row in selection.attachments})
        direct = tuple(
            dict.fromkeys(
                (*feedback_ids, *selection.explicit_evidence_ids, *purposes, *section_ids)
            )
        )
        selected = list(
            await self._retriever.citation_handles(scope, identity, direct, include_history=True)
        )
        if selection.search is not None:
            found = await self._retriever.search(scope, identity, selection.search)
            known = {row.evidence_id for row in selected}
            selected.extend(
                row.handle for row in found.handles if row.handle.evidence_id not in known
            )
        if len(selected) > self._limits.max_inclusions:
            raise BrainDeniedError("Context selection exceeds its inclusion boundary")
        return tuple(selected), purposes

    async def _sections(
        self, session: AsyncSession, scope: BrainReadScope, selection: ContextSelection
    ) -> tuple[UUID, ...]:
        if not selection.explicit_sections:
            return ()
        request = SearchRequest(
            company_id=scope.company_id, query="exact section selection", include_history=True
        )
        rows = (
            await session.execute(
                select(
                    BrainEvidence.evidence_id,
                    BrainEvidence.artifact_revision_id,
                    BrainEvidence.raw_section,
                )
                .where(
                    BrainEvidence.company_id == scope.company_id,
                    BrainEvidence.artifact_revision_id.in_(
                        tuple(row.artifact_revision_id for row in selection.explicit_sections)
                    ),
                    BrainEvidence.evidence_id.in_(
                        evidence_ids(scope, await _clock(session), request)
                    ),
                )
                .order_by(BrainEvidence.artifact_revision_id, BrainEvidence.raw_start_byte)
                .limit(self._limits.max_inclusions + 1)
            )
        ).all()
        if len(rows) > self._limits.max_inclusions:
            raise BrainDeniedError("Context section metadata exceeds its boundary")
        available = {(artifact, section) for _, artifact, section in rows}
        if any(
            (selection.artifact_revision_id, section) not in available
            for selection in selection.explicit_sections
            for section in selection.sections
        ):
            raise BrainDeniedError("Selected Brain sections are unavailable")
        return tuple(key for key, _, _ in rows)

    # The 60-line final claim gate keeps identity, current runtime authority, resources,
    # heads and handles adjacent; no new transaction or external work is hidden here.
    async def revalidate_context(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        manifest: ContextManifest,
        now: datetime,
    ) -> tuple[ResourceRevision, ...]:
        """Caller holds CompanyControl; no transaction/commit or external I/O is opened."""
        manifest = ContextManifest.model_validate_json(manifest.model_dump_json())
        if not session.in_transaction() or control.company_id != scope.company_id:
            raise BrainDeniedError("Context revalidation needs its locked company transaction")
        if (
            manifest.company_id,
            manifest.principal_id,
            manifest.operation_id,
            manifest.trace_id,
            manifest.task_id,
            manifest.task_trace_id,
            manifest.actor_id,
        ) != (
            scope.company_id,
            scope.principal_id,
            scope.operation_id,
            scope.trace_id,
            scope.task_id,
            scope.task_trace_id,
            scope.actor_id,
        ):
            raise BrainDeniedError("Context audit/work scope was spliced")
        await revalidate_brain_scope(session, control, scope, identity)
        current = await self._authority.current(session, scope, identity)
        if current != manifest.authority or manifest.policy_version != self._limits.policy_version:
            raise BrainConflictError("Context runtime policy changed; reassemble")
        resources = await require_resources(
            session,
            scope,
            tuple(row.resource_id for row in manifest.contributors),
            await _clock(session),
        )
        if resources != manifest.contributors:
            raise BrainConflictError("Context source access changed; reassemble")
        refs = tuple(head.current for head in manifest.source_heads)
        if await heads(session, scope, refs) != manifest.source_heads:
            raise BrainConflictError("Context source heads changed; reassemble")
        handles = tuple(row.handle for row in manifest.inclusions)
        await self._retriever._prepare(session, scope, handles, await _clock(session))
        return tuple(
            ResourceRevision(
                resource=f"brain.resource:{row.resource_id}", revision=f"acl:{row.generation}"
            )
            for row in resources
        ) + tuple(
            ResourceRevision(
                resource=f"brain.source:{row.source_id}",
                revision=f"head:{row.generation}:{row.current.source_revision_id}",
            )
            for row in manifest.source_heads
        )


def _combine_heads(handles: tuple[CitationHandle, ...]) -> tuple[SourceHead, ...]:
    found: dict[UUID, SourceHead] = {}
    for handle in handles:
        for head in handle.source_heads:
            if head.source_id in found and head != found[head.source_id]:
                raise BrainConflictError("Selected context source snapshots differ")
            found[head.source_id] = head
    return tuple(found[key] for key in sorted(found))
