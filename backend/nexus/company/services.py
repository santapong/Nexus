"""Typed runtime dependencies for the isolated company profile, never checkpoint data."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.company.access import CompanyDirectory
from nexus.company.control_store import CompanyControls
from nexus.harness.journal import CompanyJournal


@dataclass(frozen=True, slots=True)
class CompanyServices:
    """Shared stateless service objects whose methods open fresh scoped transactions."""

    directory: CompanyDirectory
    journal: CompanyJournal
    controls: CompanyControls
