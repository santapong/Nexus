"""Shared strict wire types for the company-system boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
USD = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]


class Contract(BaseModel):
    """Reject undeclared fields and bind every domain contract to one company.

    Frozen fields do not recursively freeze JSON containers. Action boundaries
    therefore take canonical snapshots and recompute hashes before authorization.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    schema_version: Literal["nexus.company.v1"] = "nexus.company.v1"
    company_id: UUID
