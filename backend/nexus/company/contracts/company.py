"""Owner mandates and scoped departmental responsibilities."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from nexus.company.contracts.base import USD, Contract, Name


class CompanyMandate(Contract):
    """Owner-authored company direction; decoding is not proof of authority."""

    owner_id: UUID
    version: Name
    purpose: Name
    goals: tuple[UUID, ...] = ()
    oversight: Literal["supervised", "delegated", "board"] = "supervised"
    daily_cap_usd: Annotated[USD, Field(le=5)] = Decimal("5.00")
    work_cap_usd: USD = Decimal("1.00")
    self_improvement_enabled: Literal[False] = False


class DepartmentCharter(Contract):
    """Versioned responsibilities and explicit tool eligibility for one role."""

    department_id: UUID
    name: Name
    version: Name
    responsibilities: tuple[Name, ...] = Field(min_length=1)
    allowed_tools: tuple[Name, ...] = ()
    resource_scopes: tuple[Name, ...] = ()
    deliverables: tuple[Name, ...] = Field(min_length=1)
    verifier_id: UUID
