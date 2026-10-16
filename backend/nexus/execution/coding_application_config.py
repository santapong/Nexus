"""Pinned full-company C server choices; decoding confers no current native allowance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_serializer, model_validator

from nexus.company.management.base import Name, ValueContract
from nexus.company.management.coding_repository import CodingRepositorySelection
from nexus.company.management.coding_sources import CodingSourceRef
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.planning_authority import PlanningRolePolicy
from nexus.execution.planning_application_config import (
    PlanningApplicationConfig,
    _nonfinite,
    _unique,
)
from nexus.harness.model_authorizer_contracts import ModelInputRecipe

MAX_CODING_CONFIG = 262_144


class CodingApplicationConfig(ValueContract):
    """One immutable full10 declaration; actor credentials, keys and new budgets are absent."""

    schema_version: Literal["nexus.coding.application.v1"] = "nexus.coding.application.v1"
    planning: PlanningApplicationConfig
    role_policy: PlanningRolePolicy
    recipe: ModelInputRecipe
    registry_id: Name
    max_output_tokens: int = Field(gt=0, le=128000, strict=True)
    worker_id: UUID
    code_sources: tuple[CodingSourceRef, ...] = Field(min_length=1, max_length=20)
    repository_selection: CodingRepositorySelection
    repository_path: Path
    prepared_root: Path
    prepared_storage_symbol: Name

    @field_serializer("repository_path", "prepared_root")
    def path_strings(self, value: Path) -> str:
        return str(value)

    @property
    def catalog(self) -> PlanAdmissionCatalog:
        return self.planning.catalog

    @property
    def admission(self) -> NexusCodingAdmission:
        value = self.catalog.nexus_coding_admission
        if value is None:
            raise ValueError("Coding requires complete separately versioned full10 admission")
        return value

    @property
    def goal(self) -> GoalRevisionRef:
        return self.admission.goal

    @model_validator(mode="after")
    def fixed_choices(self) -> Self:
        row = next(
            (row for row in self.catalog.models.models if row.registry_id == self.registry_id), None
        )
        roots = (
            *[
                self.planning.storage.brain_root,
                self.planning.storage.prepared_root,
                self.planning.storage.model_evidence_root,
            ],
            self.prepared_root,
        )
        if (
            self.admission.slots[1].tool.resource != "model:" + self.registry_id
            or row is None
            or self.role_policy.company_id != self.catalog.company_id
            or (
                self.role_policy.workflow_name,
                self.role_policy.workflow_version,
                self.role_policy.model_profile,
                self.recipe.profile,
            )
            != ("company.coding.v1", "v1", "engineering", "engineering")
            or self.max_output_tokens > row.max_output_tokens
            or self.role_policy.data_classification not in row.allowed_data
            or self.repository_selection.company_id != self.catalog.company_id
            or tuple(ref.git for ref in self.code_sources) != self.repository_selection.files
            or any(ref.source.company_id != self.catalog.company_id for ref in self.code_sources)
            or any(
                not p.is_absolute() or p == Path("/") or ".." in p.parts or len(str(p)) > 4096
                for p in (*roots, self.repository_path)
            )
            or len(set(roots)) != len(roots)
            or any(a in z.parents for a in roots for z in roots if a != z)
            or self.prepared_storage_symbol
            in {
                self.planning.storage.brain_storage_symbol,
                self.planning.storage.prepared_storage_symbol,
            }
        ):
            raise ValueError("Coding exact role/registry/source/private namespace differs")
        return self


def parse_coding_config(raw: bytes, expected_sha256: str) -> CodingApplicationConfig:
    """Strict hash-pinned configuration only; original operator file acquisition is separate."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= MAX_CODING_CONFIG
        or type(expected_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("Exact pinned coding configuration is unavailable")
    json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
    return CodingApplicationConfig.model_validate_json(raw)
