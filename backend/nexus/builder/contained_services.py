"""Exact process-local contained dependencies; no DTO, digest or replay lease grants authority."""

from nexus.builder.contained_cleanup import ContainedCleanup
from nexus.builder.contained_contracts import ParentObservation, ScopeExpectation
from nexus.builder.contained_diagnostics import ContainmentDiagnosticStore
from nexus.builder.contained_discovery import ContainedDiscovery
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_plan import describe_contained_selectors
from nexus.builder.contained_process import ContainedProcess, ProcessOwnershipUnresolvedError
from nexus.builder.contained_process_contracts import RuntimeCapture
from nexus.builder.contained_query import clock_us
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.systemd_scope_provider import SystemdScopeProvider


class ContainmentServices:
    """Trusted construction is per original scope/job; no caller callback or public enable flag."""

    def __init__(
        self,
        expectation: ScopeExpectation,
        store: ContainmentEvidenceStore,
        *,
        method_sha256: str = CONTAINED_EXECUTION_METHOD_SHA256,
    ) -> None:
        if (
            type(store) is not ContainmentEvidenceStore
            or method_sha256 != CONTAINED_EXECUTION_METHOD_SHA256
        ):
            raise ValueError("Contained method or concrete store is unavailable")
        self.expectation = ScopeExpectation.model_validate(expectation.model_dump())
        self.store, self.method_sha256 = store, method_sha256
        self.diagnostics = ContainmentDiagnosticStore(
            store.root.parent / (store.root.name + "-diagnostics")
        )
        self.parents = SystemdScopeProvider()
        self.process = ContainedProcess(self.parents, ContainedDiscovery())
        self.cleanup = ContainedCleanup()
        self.deadline: ObservationDeadline | None = None
        self.unresolved: ProcessOwnershipUnresolvedError | None = None

    def retain_unresolved(self, failure: ProcessOwnershipUnresolvedError) -> None:
        """Keep at most one original job's strong handle; this never schedules retry or cleanup."""
        if self.unresolved is not None and self.unresolved is not failure:
            raise ValueError("Contained unresolved ownership is already retained")
        self.unresolved = failure

    def unresolved_runtime(self) -> RuntimeCapture | None:
        """Current handle metadata never treats a terminal task as a reaped child."""
        if self.unresolved is None:
            return None
        process = self.unresolved.process
        pending = self.unresolved.pending
        if (
            process is None
            and pending is not None
            and pending.done()
            and not pending.cancelled()
            and pending.exception() is None
        ):
            process = pending.result()
        return (
            RuntimeCapture(
                pid=process.pid,
                start_ticks=None,
                cgroup_path=None,
                parent_membership="unavailable",
                reap="unresolved",
            )
            if process is not None
            else None
        )

    def require_policy(self, spec: BuilderExecutionSpec, policy: BuilderToolPolicy) -> None:
        """Qualify exact original policy/scope without requiring an old replay scope to be live."""
        describe_contained_selectors(spec, policy)
        if (
            policy.full_execution_method_sha256 != self.method_sha256
            or self.method_sha256 != CONTAINED_EXECUTION_METHOD_SHA256
        ):
            raise ValueError("Contained complete execution method differs")
        if (
            type(self.store) is not ContainmentEvidenceStore
            or type(self.diagnostics) is not ContainmentDiagnosticStore
            or self.diagnostics.root == self.store.root
            or type(self.parents) is not SystemdScopeProvider
            or type(self.process) is not ContainedProcess
            or self.process.parents is not self.parents
            or type(self.process.discovery) is not ContainedDiscovery
            or type(self.cleanup) is not ContainedCleanup
        ):
            raise ValueError("Contained concrete dependencies differ")
        job, expected = spec.job, self.expectation
        if (job.company_id, job.action_id, job.task_id, job.trace_id, job.run_id) != (
            expected.company_id,
            expected.action_id,
            expected.task_id,
            expected.trace_id,
            expected.run_id,
        ):
            raise ValueError("Contained original scope differs from the exact job")

    async def observe(self) -> ParentObservation:
        """Fresh boundaries obtain new facts; historical replay never invokes this method."""
        return await self.parents.observe(self.expectation)

    async def before_prepare(self, spec: BuilderExecutionSpec) -> None:
        """Set one finite job end before preparation; later observations cannot replenish it."""
        if self.deadline is not None:
            raise ValueError("Contained original job preparation cannot be repeated")
        observed = await self.observe()
        if clock_us() >= observed.deadline_us:
            raise ValueError("Contained parent expired before source preparation")
        self.deadline = ObservationDeadline(
            end_us=min(
                observed.deadline_us,
                clock_us() + spec.job.limits.job_seconds * 1_000_000,
            )
        )
