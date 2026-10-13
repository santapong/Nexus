"""Strict Brain wire primitives; decoding identifiers never grants company authority."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def exact_flag(value: object) -> bool:
    """Remain literal even when an HTTP framework requests non-strict decoding."""
    if type(value) is not bool:
        raise ValueError("A literal boolean is required")
    return value


def exact_count(value: object) -> int:
    """Reject booleans, strings and floats before numerical constraint processing."""
    if type(value) is not int:
        raise ValueError("An exact integer is required")
    return value


Flag = Annotated[bool, BeforeValidator(exact_flag)]
Count = Annotated[int, BeforeValidator(exact_count), Field(ge=1, le=1_000_000_000)]
Ordinal = Annotated[int, BeforeValidator(exact_count), Field(ge=0, le=1_000_000_000)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Symbol = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ValueContract(BaseModel):
    """Bounded immutable nested value; no permissions or executable commands."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class BrainContract(ValueContract):
    """Versioned company-bound interchange, independent of legacy v1 wire semantics."""

    schema_version: Literal["nexus.company.brain.v1"] = "nexus.company.brain.v1"
    company_id: UUID


class CompanyRef(Protocol):
    """Nested references expose their actual company for structural checks."""

    @property
    def company_id(self) -> UUID: ...


def require_company(company_id: UUID, *records: CompanyRef | None) -> None:
    """Foreign nested IDs must fail before service lookup, not confer scope."""
    if any(record is not None and record.company_id != company_id for record in records):
        raise ValueError("Nested Brain reference belongs to another company")


class BrainReadScope(BrainContract):
    """Server-derived audit/work identifiers; current locked access remains mandatory."""

    workspace_id: UUID
    principal_id: UUID
    operation_id: UUID
    trace_id: UUID
    task_id: UUID | None = None
    task_trace_id: UUID | None = None
    actor_id: UUID | None = None

    @model_validator(mode="after")
    def distinct_registered_binding(self) -> Self:
        """Keep control audit IDs separate from optional immutable registered work."""
        binding = (self.task_id, self.task_trace_id, self.actor_id)
        if any(item is not None for item in binding) and any(item is None for item in binding):
            raise ValueError("Registered work binding must include task, trace and actor")
        if self.task_id is not None and self.task_id == self.operation_id:
            raise ValueError("An operation audit identity cannot be a work identity")
        return self


class SourceTime(ValueContract):
    """Exact source precision; unknown or date-only values never become invented instants."""

    precision: Literal["unknown", "year", "month", "day", "instant"]
    value: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None
    basis: Annotated[str, StringConstraints(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def exact_precision(self) -> Self:
        """Validate shape and calendar without filling missing date/time components."""
        if self.precision == "unknown":
            if self.value is not None:
                raise ValueError("Unknown source time cannot assert a value")
            return self
        if self.value is None:
            raise ValueError("Declared source precision requires its exact value")
        patterns = {
            "year": r"\d{4}",
            "month": r"\d{4}-\d{2}",
            "day": r"\d{4}-\d{2}-\d{2}",
            "instant": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
        }
        if re.fullmatch(patterns[self.precision], self.value) is None:
            raise ValueError("Source time does not match its declared precision")
        if self.precision == "instant":
            stamp = datetime.fromisoformat(self.value)
            if stamp.utcoffset() is None:
                raise ValueError("Source instant requires an explicit timezone")
        else:
            suffix = (
                "-01-01" if self.precision == "year" else "-01" if self.precision == "month" else ""
            )
            date.fromisoformat(self.value + suffix)
        return self


class ValidityInterval(ValueContract):
    """Optional meaningful validity instants, distinct from source-event precision."""

    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("Validity interval must be positive")
        return self
