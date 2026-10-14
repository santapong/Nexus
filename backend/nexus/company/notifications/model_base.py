"""Uninstalled notification metadata; importing declarations grants no effect authority."""

from sqlalchemy.orm import DeclarativeBase

from nexus.company.management.model_base import CompanyRow, RecordedRow, scoped_fk

__all__ = ["CompanyRow", "NotificationBase", "RecordedRow", "scoped_fk"]


class NotificationBase(DeclarativeBase):
    """Root normal014 owns registration, native keys, forced RLS and immutable guards."""
