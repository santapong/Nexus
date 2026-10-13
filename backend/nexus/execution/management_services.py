"""Trusted process-local management composition; dependencies never enter work checkpoints."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management.plan_support import PlanAdmissionCatalog, PlanSourceFreshness
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore


@dataclass(frozen=True, slots=True)
class ManagementExecutionServices:
    """Configured readers/catalog narrow native guards, without granting any call permission."""

    catalog: PlanAdmissionCatalog
    artifacts: BoundedArtifactReader
    freshness: PlanSourceFreshness

    def execution_store(self, factory: async_sessionmaker[AsyncSession]) -> ExecutionStore:
        return ExecutionStore(
            factory,
            management_catalog=self.catalog,
            management_artifacts=self.artifacts,
            management_freshness=self.freshness,
        )

    def effect_store(self, factory: async_sessionmaker[AsyncSession]) -> EffectStore:
        return EffectStore(
            factory,
            management_catalog=self.catalog,
            management_artifacts=self.artifacts,
            management_freshness=self.freshness,
        )
