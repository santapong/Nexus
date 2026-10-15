"""Exact dormant P/C before-intent composition and retained final-clock observations."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.cycle_artifacts.action_parameters import (
    CycleAuthorSelector,
    PresentationCheckParameters,
    PresentationWriteParameters,
    SupportCheckParameters,
    SupportWriteParameters,
    decode_cycle_action,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.report_input_contracts import native_author
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction

if TYPE_CHECKING:
    from nexus.company.cycle_artifacts.input_reader import CycleInputReader
    from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
    from nexus.company.cycle_artifacts.publication_contracts import (
        CycleAuthorMaterial,
        CycleCheckMaterial,
        CycleReadProtection,
    )

DENIED = "Fresh cycle deliverable intent requires its exact native checks"


def _require(value: bool) -> None:
    if not value:
        raise ExecutionDeniedError(DENIED)


def require_material_pins(
    reader: "CycleInputReader | CycleOriginalReader",
    work: ExecutionWork,
    action: ActionProposal,
    material: "CycleAuthorMaterial | CycleCheckMaterial",
) -> None:
    """Recompute closed owner-approved byte selectors without granting native authority."""
    # This >50-line closed write/check pin comparison shares one exact native role selection.
    from nexus.company.cycle_artifacts.publication_contracts import (
        CycleAuthorMaterial,
        CycleCheckMaterial,
    )

    rule, binding = reader.rules.bind(work), native_author(work)[0]
    pins = decode_cycle_action(
        action,
        expected_kind=rule.kind,
        phase=rule.phase,
        binding=binding,
        permission=rule.permission,
    )
    if type(material) is CycleAuthorMaterial:
        _require(isinstance(pins, (PresentationWriteParameters, SupportWriteParameters)))
        assert isinstance(pins, (PresentationWriteParameters, SupportWriteParameters))
        basis = material.prepared.basis
        _require(
            rule.phase == "write"
            and action.action_id == material.prepared.action_id
            and pins.selector
            == CycleAuthorSelector(
                company_id=basis.company_id,
                goal=basis.goal,
                producing_plan=basis.producing_plan,
                procedure_id=basis.procedure_id,
                author=basis.author,
                registration_sha256=basis.author_registration_sha256,
            )
            and pins.output_manifest_sha256 == material.prepared.output_manifest_sha256
            and pins.input_snapshot_sha256 == canonical_sha256(basis)
            and pins.input_manifest_sha256 == canonical_sha256(basis.inputs)
        )
    else:
        _require(type(material) is CycleCheckMaterial)
        assert isinstance(material, CycleCheckMaterial)
        _require(isinstance(pins, (PresentationCheckParameters, SupportCheckParameters)))
        assert isinstance(pins, (PresentationCheckParameters, SupportCheckParameters))
        _require(
            rule.phase == "check"
            and action.action_id == material.prepared.action_id
            and pins.author_action_id == material.command.target.action_id
            and pins.verification_target_sha256 == canonical_sha256(material.command.target)
            and pins.author_output_manifest_sha256 == material.author.output_manifest_sha256
            and pins.output_sha256 == material.prepared.output_sha256
            and pins.input_snapshot_sha256 == material.prepared.input_snapshot_sha256
            and pins.input_manifest_sha256 == material.prepared.input_manifest_sha256
        )


class CycleArtifactIntentCheck:
    """Trusted concrete reader plus original material; no serialized check or permission flag."""

    def __init__(
        self,
        reader: "CycleInputReader | CycleOriginalReader",
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        material: "CycleAuthorMaterial | CycleCheckMaterial",
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> None:
        from nexus.company.cycle_artifacts.input_reader import CycleInputReader
        from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader
        from nexus.company.cycle_artifacts.publication_contracts import (
            CycleAuthorMaterial,
            CycleCheckMaterial,
        )

        _require(
            (type(material) is CycleAuthorMaterial and type(reader) is CycleInputReader)
            or (type(material) is CycleCheckMaterial and type(reader) is CycleOriginalReader)
        )
        self.reader, self.lease, self.identity = reader, lease, identity
        self.action_id, self.material, self.credential = action_id, material, credential
        self._reader, self._material = reader, material
        self._factory, self._catalog, self._rules = reader.factory, reader.catalog, reader.rules
        self._composition, self._catalog_sha = (
            reader.composition(),
            canonical_sha256(reader.catalog),
        )
        self._work: ExecutionWork | None = None
        self._action: JournalAction | None = None
        self._current: CycleReadProtection | None = None
        self._approval: ApprovalDecision | None = None
        self._approval_raw: str | None = None

    def require_composition(self) -> None:
        """Retain the original configured mode even if a public alias changes after awaits."""
        _require(
            self.reader is self._reader
            and self.material is self._material
            and self.reader.factory is self._factory
            and self.reader.catalog is self._catalog
            and self.reader.rules is self._rules
            and canonical_sha256(self._catalog) == self._catalog_sha
            and isinstance(self.credential, AuthenticatedWorkerIdentity)
            and self.credential.identity == self.identity
        )
        self.reader.require_composition(self._composition)

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Use the existing company transaction; retain exact approval and both read windows."""
        # Keep this >50-line same-session approval/read/final-clock operation adjacent.
        self.require_composition()
        require_cycle_artifact_intent_check(
            self._factory, self._catalog, work, self.lease, self.identity, action, self
        )
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        require_material_pins(self.reader, work, proposal, self.material)
        _require(action.approval_json is not None and action.consumed_at is not None)
        assert action.approval_json is not None
        approval = ApprovalDecision.model_validate_json(action.approval_json)
        _require(
            approval.company_id == work.company_id
            and approval.approver_id == control.owner_id
            and approval.decision == "approved"
            and approval.action_id == action.id
            and approval.action_revision == proposal.revision
            and approval.action_hash == action.proposal_hash == action_hash(proposal)
            and approval.issued_at <= now < approval.expires_at
        )
        self._work, self._action = work, action
        self._approval, self._approval_raw = approval, action.approval_json
        from nexus.company.cycle_artifacts.publication_contracts import CycleAuthorMaterial

        if isinstance(self.material, CycleAuthorMaterial):
            from nexus.company.cycle_artifacts.input_reader import CycleInputReader

            _require(type(self.reader) is CycleInputReader)
            assert isinstance(self.reader, CycleInputReader)
            self._current = await self.reader.revalidate_author_locked(
                session,
                control,
                work,
                self.lease,
                self.identity,
                self.material,
                credential=self.credential,
            )
        else:
            from nexus.company.cycle_artifacts.original_reader import CycleOriginalReader

            _require(type(self.reader) is CycleOriginalReader)
            assert isinstance(self.reader, CycleOriginalReader)
            self._current = await self.reader.revalidate_check_locked(
                session,
                control,
                work,
                self.lease,
                self.identity,
                self.material,
                credential=self.credential,
            )
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        """Close original/current approval, credential, lease and composition after final flush."""
        self.require_composition()
        _require(self._work is not None and self._action is not None)
        assert self._work is not None and self._action is not None
        require_cycle_artifact_intent_check(
            self._factory, self._catalog, self._work, self.lease, self.identity, self._action, self
        )
        _require(
            self._approval is not None
            and self._current is not None
            and self._action.approval_json == self._approval_raw
            and self.lease.expires_at > now
        )
        assert self._approval is not None and self._current is not None
        _require(self._approval.issued_at <= now < self._approval.expires_at)
        self.credential.require_time(now)
        self.material.protection.require_time(now)
        self._current.require_time(now)


def require_cycle_artifact_intent_check(
    factory: async_sessionmaker[AsyncSession],
    catalog: PlanAdmissionCatalog | None,
    work: ExecutionWork,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: JournalAction,
    before_intent: BeforeIntentCheck | None,
) -> None:
    """Mandatory shape check after prior return, before any fresh hold/attempt mutation."""
    # Keep this >50-line exact class/config/action/own-slot shape comparison in one boundary.
    if catalog is None or catalog.cycle_admission is None:
        return
    slots = catalog.cycle_admission.slots[4:8]
    if work.task_id not in {slot.child.binding.task_id for slot in slots}:
        return
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    if proposal.tool == "model.request.v1" and type(before_intent) is not CycleArtifactIntentCheck:
        return  # The separate real management/model gate owns this reserved model slot.
    _require(type(before_intent) is CycleArtifactIntentCheck)
    assert isinstance(before_intent, CycleArtifactIntentCheck)
    try:
        before_intent.require_composition()
        rule, bound = before_intent.reader.rules.bind(work), native_author(work)[0]
        _require(
            before_intent._factory is factory
            and before_intent._catalog is catalog
            and before_intent.lease == lease
            and before_intent.identity == identity
            and before_intent.action_id == action.id
            and work.fence == lease.fence
            and (
                lease.company_id,
                lease.task_id,
                lease.trace_id,
                lease.run_id,
                lease.actor_id,
                lease.workspace_id,
            )
            == (
                bound.company_id,
                bound.task_id,
                bound.trace_id,
                bound.run_id,
                bound.actor_id,
                bound.workspace_id,
            )
            and (identity.principal_id, identity.workspace_id)
            == (bound.actor_id, bound.workspace_id)
            and action.company_id == work.company_id
            and action.task_id == work.task_id
            and action.trace_id == work.trace_id
            and rule.phase in {"write", "check"}
        )
        require_material_pins(
            before_intent.reader,
            work,
            ActionProposal.model_validate_json(action.proposal_json),
            before_intent.material,
        )
    except (ValueError, AttributeError, TypeError) as exc:
        raise ExecutionDeniedError(DENIED) from exc
