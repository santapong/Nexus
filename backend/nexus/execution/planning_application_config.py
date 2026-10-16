"""SHA-pinned server descriptions for one supervised Nexus goal; no activation or credentials."""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_serializer, model_validator

from nexus.company.brain.context import ContextSelection
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.base import Name, Symbol, ValueContract
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.nexus_cycle_admission import NexusCycleAdmission
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.planning_authority import PlanningRolePolicy
from nexus.harness.model_authorizer_contracts import ModelInputRecipe

MAX_PLANNING_CONFIG = 262_144


class PlanningSourcePolicies(ValueContract):
    """Closed immutable policy lookup shared with actual RegisteredSourceFreshness."""

    policies: tuple[SourcePolicy, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_symbols(self) -> Self:
        if len({row.source_symbol for row in self.policies}) != len(self.policies):
            raise ValueError("Planning source policies must have unique exact symbols")
        return self

    def policy(self, symbol: str) -> SourcePolicy:
        for row in self.policies:
            if row.source_symbol == symbol:
                return row
        raise KeyError("Planning source policy is not configured")


class PlanningStorage(ValueContract):
    """Private persistent namespaces, checked physically by the actual storage/application."""

    brain_root: Path
    prepared_root: Path
    model_evidence_root: Path
    brain_storage_symbol: Name
    prepared_storage_symbol: Name

    @field_serializer("brain_root", "prepared_root", "model_evidence_root")
    def path_strings(self, value: Path) -> str:
        """Keep this new configuration's Python/JSON hash inputs explicit and JSON safe."""
        return str(value)

    @model_validator(mode="after")
    def separate_namespaces(self) -> Self:
        roots = (self.brain_root, self.prepared_root, self.model_evidence_root)
        if (
            any(
                not p.is_absolute() or p == Path("/") or ".." in p.parts or len(str(p)) > 4096
                for p in roots
            )
            or len(set(roots)) != 3
            or any(a in b.parents for a in roots for b in roots if a != b)
            or self.brain_storage_symbol == self.prepared_storage_symbol
        ):
            raise ValueError("Planning storage needs separate exact absolute private namespaces")
        return self


class PlanningApplicationConfig(ValueContract):
    """A fixed catalog, root slices, mapping and role; decoding grants no native permission."""

    schema_version: Literal["nexus.planning.application.v1"] = "nexus.planning.application.v1"
    catalog: PlanAdmissionCatalog
    policy_version: Name
    role_policy: PlanningRolePolicy
    recipe: ModelInputRecipe
    selection: ContextSelection
    registry_id: Name
    max_output_tokens: int = Field(gt=0, le=128000, strict=True)
    worker_id: UUID
    mapping_revision: Symbol
    source_policies: tuple[SourcePolicy, ...] = Field(min_length=1, max_length=32)
    storage: PlanningStorage

    @property
    def admission(self) -> NexusCycleAdmission:
        value = self.catalog.nexus_cycle_admission
        if value is None:
            raise ValueError("Planning needs its configured Nexus admission")
        return value

    @property
    def goal(self) -> GoalRevisionRef:
        return self.admission.goal

    @model_validator(mode="after")
    def exact_server_choices(self) -> Self:
        admission = self.admission
        selected = next(
            (row for row in self.catalog.models.models if row.registry_id == self.registry_id), None
        )
        if (
            self.policy_version in {"nexus-preview-no-provider-v1", "uat-offline-v1"}
            or self.catalog.models.pricebook_version
            in {"nexus-preview-no-provider-v1", "uat-offline-v1"}
            or (self.role_policy.company_id, self.selection.company_id)
            != (admission.company_id, admission.company_id)
            or (
                self.role_policy.workflow_name,
                self.role_policy.workflow_version,
                self.role_policy.model_profile,
                self.recipe.profile,
            )
            != ("company.planning.v1", "v1", "reasoning", "reasoning")
            or selected is None
            or selected.price is None
            or admission.slots[0].tool.resource != f"model:{self.registry_id}"
            or selected.price.version != self.catalog.models.pricebook_version
            or self.max_output_tokens > selected.max_output_tokens
            or self.role_policy.data_classification not in selected.allowed_data
            or len({row.source_symbol for row in self.source_policies}) != len(self.source_policies)
        ):
            raise ValueError(
                "Planning configured goal/role/catalog/model/price or source policy differs"
            )
        return self


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Planning configuration has duplicate fields")
        values[key] = value
    return values


def _nonfinite(_: str) -> None:
    raise ValueError("Planning configuration has nonfinite data")


def parse_planning_config(raw: bytes, expected_sha256: str) -> PlanningApplicationConfig:
    """Decode bounded exact bytes only; Root's application owns safe file/FD acquisition."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= MAX_PLANNING_CONFIG
        or type(expected_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("Exact pinned planning configuration is unavailable")
    json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
    return PlanningApplicationConfig.model_validate_json(raw)
