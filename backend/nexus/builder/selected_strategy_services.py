"""Concrete complete server template factory; construction performs no read or native action."""

from dataclasses import dataclass, field

from nexus.builder.selected_strategy_contracts import SelectedBuilderTemplate
from nexus.builder.selected_strategy_guard import StrategySelectedBuilderGuard, checked_template
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.actor_proof_reader import StrategyActorProofReader


@dataclass(frozen=True)
class SelectedBuilderEntry:
    binding: RunBinding
    template: SelectedBuilderTemplate


@dataclass(frozen=True)
class SelectedBuilderServices:
    """One immutable exact E/EV tuple; metadata/configuration is never current proof."""

    reader: StrategyActorProofReader
    entries: tuple[SelectedBuilderEntry, ...]
    _catalog_sha256: str = field(init=False, repr=False)
    _input_reader: object = field(init=False, repr=False)
    _factory: object = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.reader) is not StrategyActorProofReader:
            raise ValueError("Selected concrete actor reader is unavailable")
        object.__setattr__(self, "_catalog_sha256", canonical_sha256(self.reader.reader.catalog))
        object.__setattr__(self, "_input_reader", self.reader.reader)
        object.__setattr__(self, "_factory", self.reader.reader.artifacts.factory)
        self._require_configuration()

    def _require_configuration(self) -> None:
        catalog = self.reader.reader.catalog
        admission = validate_cycle_catalog(catalog.cycle_admission, catalog)
        if (
            self.reader.reader is not self._input_reader
            or self.reader.reader.artifacts.factory is not self._factory
            or self.reader.reader.freshness._factory is not self._factory
            or admission is None
            or type(self.entries) is not tuple
            or len(self.entries) != 2
            or canonical_sha256(catalog) != self._catalog_sha256
        ):
            raise ValueError("Selected complete catalog/template tuple is unavailable")
        resources = {row.symbol: row.resource for row in catalog.resources}
        for entry, slot in zip(self.entries, admission.slots[2:4], strict=True):
            if type(entry) is not SelectedBuilderEntry:
                raise ValueError("Selected concrete entry is unavailable")
            binding = RunBinding.model_validate(entry.binding.model_dump(warnings=False))
            template = checked_template(entry.template)
            if (
                binding != slot.child.binding
                or template.company_id != admission.company_id
                or template.goal_id != admission.goal.goal_id
                or template.tool != slot.tool
                or template.output_resource != resources.get(slot.tool.resource)
            ):
                raise ValueError("Selected template or configured E/EV binding differs")
        first, last = (entry.template for entry in self.entries)
        if (
            first.candidate_policy_sha256,
            first.candidate_scope_sha256,
            first.repository,
            first.protected_patch,
        ) != (
            last.candidate_policy_sha256,
            last.candidate_scope_sha256,
            last.repository,
            last.protected_patch,
        ):
            raise ValueError("Configured E/EV selected choice differs")

    def resolve_guard(
        self, original: BuilderSourceGuard, credential: AuthenticatedWorkerIdentity
    ) -> StrategySelectedBuilderGuard:
        """Select trusted configuration only; actual same-session proof stays inside the guard."""
        self._require_configuration()
        matches = tuple(
            entry
            for entry in self.entries
            if (
                entry.binding.company_id,
                entry.binding.task_id,
                entry.binding.trace_id,
                entry.binding.run_id,
                entry.binding.actor_id,
                entry.binding.workspace_id,
            )
            == (
                original.lease.company_id,
                original.lease.task_id,
                original.lease.trace_id,
                original.lease.run_id,
                original.lease.actor_id,
                original.lease.workspace_id,
            )
        )
        if len(matches) != 1:
            raise ValueError("Exact selected builder guard configuration is unavailable")
        return StrategySelectedBuilderGuard(original, credential, self.reader, matches[0].template)
