"""Pure final-clock qualification over trusted loaded facts; no cached grant authority."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.access import Capability, PrincipalAccess, VerifiedIdentity, require_capability
from nexus.company.management.base import SHA256, require_company
from nexus.company.notifications.contracts import NotificationContract, NotificationDraft


class NotificationDeniedError(ValueError):
    """Constant safe denial: no provider, mailbox, source text or lookup existence detail."""


class NotificationQualification(NotificationContract):
    """Server-loaded projection; its JSON cannot replace fresh native lookup under CC."""

    principal: PrincipalAccess
    recipient_policy_sha256: SHA256
    current_resource_ids: tuple[UUID, ...] = Field(max_length=6400)
    protection_deadlines: tuple[AwareDatetime, ...] = Field(max_length=12_800)
    checked_at: AwareDatetime

    @model_validator(mode="after")
    def exact_principal(self) -> Self:
        require_company(self.company_id, self.principal)
        if len(set(self.current_resource_ids)) != len(self.current_resource_ids):
            raise ValueError("Current resource qualification must be unique")
        return self


def require_current_qualification(
    qualification: NotificationQualification,
    draft: NotificationDraft,
    identity: VerifiedIdentity,
    now: datetime,
) -> None:
    """Final pure temporal gate, after the resolver's actual awaited current DB reads."""
    principal = qualification.principal
    exact = (
        qualification.company_id == draft.company_id
        and principal.principal_id == draft.recipient_policy.owner_id
        and principal.owner_id == draft.recipient_policy.owner_id
        and principal.principal_id == identity.principal_id
        and principal.workspace_id == identity.workspace_id
        and qualification.recipient_policy_sha256 == draft.recipient_policy.sha256
        and set(qualification.current_resource_ids) == set(draft.provenance.required_resource_ids)
        and now.utcoffset() is not None
        and qualification.checked_at <= now
        and draft.recipient_policy.registered_at <= now < draft.recipient_policy.expires_at
        and all(
            now < deadline
            for deadline in (
                *draft.provenance.protection_deadlines,
                *qualification.protection_deadlines,
            )
        )
    )
    if not exact:
        raise NotificationDeniedError("Owner notification qualification is unavailable")
    try:
        require_capability(principal, Capability.GRANT)
    except ValueError as exc:
        raise NotificationDeniedError("Owner notification qualification is unavailable") from exc
