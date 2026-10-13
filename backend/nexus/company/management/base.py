"""Strict versioned declarations; decoding cannot issue company authority or acceptance."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from nexus.company.brain.base import (
    SHA256,
    Name,
    SourceTime,
    Symbol,
    ValueContract,
    require_company,
)

__all__ = ["SHA256", "Name", "SourceTime", "Symbol", "ValueContract", "require_company"]

ExactUSD = Annotated[
    Decimal, Field(ge=0, le=5, max_digits=18, decimal_places=6, allow_inf_nan=False)
]
Revision = Annotated[int, Field(ge=1, le=1_000_000_000, strict=True)]


class ManagementContract(ValueContract):
    schema_version: Literal["nexus.company.management.v1"] = "nexus.company.management.v1"
    company_id: UUID


class RevisionRef(ManagementContract):
    revision_id: UUID
    version: Symbol
    sha256: SHA256
