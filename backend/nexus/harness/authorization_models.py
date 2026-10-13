"""Immutable authority-source links, supplied by additive company revision c004."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.harness.journal_models import JournalAction
from nexus.harness.standing_models import StandingAuthorityGrant


class AuthorityBase(DeclarativeBase):
    """Owned source-link metadata referencing the actual company action/grant columns."""


class ActionAuthority(AuthorityBase):
    """One standing authorization provenance link per consumed exact action."""

    __tablename__ = "company_action_authority"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(Uuid)
    grant_hash: Mapped[str] = mapped_column(String(64))
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "action_id"],
            [JournalAction.__table__.c.company_id, JournalAction.__table__.c.id],
            name="fk_company_authority_action",
        ),
        ForeignKeyConstraint(
            ["company_id", "grant_id"],
            [
                StandingAuthorityGrant.__table__.c.company_id,
                StandingAuthorityGrant.__table__.c.grant_id,
            ],
            name="fk_company_authority_grant",
        ),
    )
