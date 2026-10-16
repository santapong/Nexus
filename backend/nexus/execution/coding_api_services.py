"""Sealed optional C API graph; runtime type names resolve actual concrete lifecycle classes."""

from dataclasses import dataclass, field

from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.coding_lifecycle import CodingLifecycle
from nexus.execution.coding_owner_reads import CodingOwnerReader


@dataclass(frozen=True, slots=True)
class CodingApiServices:
    directory: PersistentCompanyDirectory
    reads: CodingOwnerReader
    lifecycle: CodingLifecycle
    _bound: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.reads) is not CodingOwnerReader or type(self.lifecycle) is not CodingLifecycle:
            raise ValueError("Coding API requires its concrete reader and lifecycle")
        object.__setattr__(self, "_bound", (self.directory, self.reads, self.lifecycle))
        self.require_composition()

    def require_composition(self) -> None:
        if (
            any(
                a is not z
                for a, z in zip(
                    (self.directory, self.reads, self.lifecycle), self._bound, strict=True
                )
            )
            or self.lifecycle.reads is not self.reads
            or self.reads.services is not self.lifecycle.services
        ):
            raise ValueError("Original coding API graph changed")
        self.reads.require_composition()
        self.lifecycle.require_composition()
