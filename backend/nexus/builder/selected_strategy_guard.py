"""Concrete current actor Strategy/source guard; no saved observation becomes a call permit."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contracts import BuilderLimits
from nexus.builder.selected_strategy_contracts import SelectedBuilderTemplate
from nexus.builder.selected_strategy_pins import require_selected_builder_spec
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.model_observations import effective_model_registration
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.actor_proof_contracts import SelectedStrategyProof
from nexus.company.strategy.actor_proof_reader import StrategyActorProofReader
from nexus.execution.engineering_worker_identity import EngineeringCredentialSourceGuard
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, execution_row, lease_scope
from nexus.harness.journal_models import CompanyControl, JournalAction


def checked_template(value: SelectedBuilderTemplate) -> SelectedBuilderTemplate:
    """Revalidate every original count before serialization of a copied configuration."""
    if type(value) is not SelectedBuilderTemplate:
        raise ValueError("Selected concrete template is unavailable")
    BuilderLimits.model_validate(
        {name: getattr(value.limits, name) for name in BuilderLimits.model_fields}
    )
    for ref in (value.source_metadata, value.protected_patch):
        if not isinstance(ref, ArtifactRevisionRef) or type(ref.byte_length) is not int:
            raise ValueError("Selected template reference count differs")
    return SelectedBuilderTemplate.model_validate(value.model_dump(warnings=False))


def selected_proof_deadlines(selected: SelectedStrategyProof) -> tuple[datetime, ...]:
    """Retain initially eligible ANY model families, not future witnesses or global minima."""
    observed = selected.profile_observed_at
    if observed.utcoffset() is None or observed > selected.proof.observed_at:
        raise ValueError("Selected profile observation clock differs")
    dates: list[datetime] = []
    for read in (selected.proof.initial, selected.proof.current):
        dates.append(read.sources.credential.expires_at)
        dates.extend(
            row.expires_at
            for row in (*read.grants, *read.sources.grants)
            if row.expires_at is not None
        )
        dates.extend(
            row.fresh_until for row in read.sources.freshness if row.fresh_until is not None
        )
        for child in (read.pair.author_child, read.pair.verifier_child):
            eligible = tuple(
                min(model.health.expires_at, evaluation.expires_at)
                for original in read.catalog.models.models
                for model in (
                    effective_model_registration(
                        read.catalog.models, read.catalog.model_observations, original
                    ),
                )
                for evaluation in model.evaluations
                if model.enabled
                and model.health.status == "healthy"
                and model.health.checked_at <= observed < model.health.expires_at
                and evaluation.profile == child.binding.model_profile
                and evaluation.conformance_passed
                and evaluation.evaluated_at <= observed < evaluation.expires_at
            )
            if not eligible:
                raise ValueError("No originally eligible selected Strategy model family")
            dates.append(max(eligible))
    return tuple(sorted(set(dates)))


def _fingerprint(value: SelectedStrategyProof) -> tuple[object, ...]:
    proof = value.proof
    return (
        value.binding,
        value.candidate,
        proof.selection,
        proof.original,
        proof.acceptance,
        proof.brief,
        proof.verifier,
        proof.check_result,
        proof.author_original_fence,
        proof.author_current_fence,
        proof.verifier_current_fence,
    )


class StrategySelectedBuilderGuard(EngineeringCredentialSourceGuard):
    """One actual job's final concrete wrapper; original and current windows remain separate."""

    def __init__(
        self,
        original: BuilderSourceGuard,
        credential: AuthenticatedWorkerIdentity,
        reader: StrategyActorProofReader,
        template: SelectedBuilderTemplate,
    ) -> None:
        if type(original) is not BuilderSourceGuard or type(reader) is not StrategyActorProofReader:
            raise ValueError("Selected source/actor reader composition differs")
        super().__init__(original, credential)
        self.reader, self.template = reader, checked_template(template)
        self._input_reader, self._factory = reader.reader, original.artifacts.factory
        self._catalog_sha256 = canonical_sha256(original.catalog)
        self._first: SelectedStrategyProof | None = None
        self._current: SelectedStrategyProof | None = None
        self._first_dates: tuple[datetime, ...] = ()
        self._current_dates: tuple[datetime, ...] = ()
        configured = validate_cycle_catalog(self.catalog.cycle_admission, self.catalog)
        if configured is None:
            raise ValueError("Selected builder requires the configured complete cycle")
        matches = tuple(
            slot.child.binding
            for slot in configured.slots[2:4]
            if slot.child.binding.task_id == self.lease.task_id
        )
        if len(matches) != 1:
            raise ValueError("Selected builder task is not an exact E/EV slot")
        self.binding = matches[0]
        self._require_composition()

    def _require_composition(self) -> None:
        actual = self.reader.reader
        if (
            actual is not self._input_reader
            or actual.artifacts is not self.artifacts
            or actual.freshness is not self.freshness
            or actual.artifacts.factory is not self._factory
            or actual.freshness._factory is not self._factory
            or self.freshness._factory is not self._factory
            or self.credential.identity != self.identity
            or actual.artifacts.factory is not self.artifacts.factory
            or canonical_sha256(actual.catalog) != self._catalog_sha256
            or canonical_sha256(self.catalog) != self._catalog_sha256
            or (
                self.lease.company_id,
                self.lease.task_id,
                self.lease.trace_id,
                self.lease.run_id,
                self.lease.actor_id,
                self.lease.workspace_id,
            )
            != (
                self.binding.company_id,
                self.binding.task_id,
                self.binding.trace_id,
                self.binding.run_id,
                self.binding.actor_id,
                self.binding.workspace_id,
            )
        ):
            raise ValueError("Selected builder configuration or exact lease binding differs")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        await super().validate(session, control, work, action, now)
        self.validate_time(await db_now(session))

    async def disclosure_windows(
        self, session: AsyncSession, control: CompanyControl
    ) -> tuple[datetime, ...]:
        self._require_composition()
        base = await super().disclosure_windows(session, control)
        work = await execution_row(session, lease_scope(self.lease))
        current = await self.reader.load_selected_locked(
            session, control, work, self.identity, credential=self.credential
        )
        if (
            type(current) is not SelectedStrategyProof
            or current.binding.child.binding != self.binding
        ):
            raise ValueError("Actual selected Strategy work differs")
        for read in (current.proof.initial, current.proof.current):
            if (
                read.sources.credential is not self.credential
                or canonical_sha256(read.catalog) != self._catalog_sha256
            ):
                raise ValueError("Selected proof credential or catalog differs")
        require_selected_builder_spec(
            current.proof.original.prepared.original.snapshot.policy,
            current.candidate,
            self.spec,
            self.policy,
            self.template,
            current.binding.child.binding,
            source_metadata=self.source.metadata,
        )
        dates = selected_proof_deadlines(current)
        if self._first is None:
            self._first, self._first_dates = current, dates
        elif _fingerprint(self._first) != _fingerprint(current):
            raise ValueError("Selected original proof changed during the actual builder job")
        self._current, self._current_dates = current, dates
        self._require_composition()
        final = await db_now(session)
        self._require_selected_time(final)
        values = (*base, *self._first_dates, *self._current_dates)
        if any(date <= final for date in values):
            raise ValueError("Selected source or initial profile window expired")
        return tuple(sorted(set(values)))

    def _require_selected_time(self, now: datetime) -> None:
        self._require_composition()
        if self._first is None or self._current is None:
            raise ValueError("No actual selected Strategy proof has been observed")
        self._first.require_time(now)
        self._current.require_time(now)
        if any(date <= now for date in (*self._first_dates, *self._current_dates)):
            raise ValueError("Originally selected Strategy witness window expired")

    def validate_time(self, now: datetime) -> None:
        super().validate_time(now)
        self._require_selected_time(now)
