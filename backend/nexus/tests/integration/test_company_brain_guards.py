"""Deployed company008 policies and adversarial direct-write guards, not DDL compilation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from nexus.company.brain.claim_models import BrainClaimRevision
from nexus.company.brain.evidence_models import BrainEvidence, BrainParseFailure, BrainParseRevision
from nexus.company.brain.model_base import BrainBase
from nexus.company.brain.scope_support import brain_transaction
from nexus.tests.integration.test_company_brain_access import AccessDatabase, identity, scope
from nexus.tests.integration.test_company_brain_access import database as database
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import COMPANY, OWNER


async def test_all_brain_tables_force_company_row_security(database: AccessDatabase) -> None:
    async with database.admin() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,p.polname "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "LEFT JOIN pg_policy p ON p.polrelid=c.oid "
                    "WHERE n.nspname='public' AND c.relkind='r' "
                    "AND c.relname LIKE 'company_brain_%'"
                )
            )
        ).all()
    assert len(rows) == 26
    assert {row.relname for row in rows} == set(BrainBase.metadata.tables)
    assert all(
        row.relrowsecurity and row.relforcerowsecurity and row.polname == "company_scope"
        for row in rows
    )


@pytest.mark.parametrize("kind,receipt", [("verified_outcome", None), ("plan", UUID(int=3000))])
async def test_raw_verification_or_receipt_uuid_cannot_publish_outcome(
    database: AccessDatabase, kind: str, receipt: UUID | None
) -> None:
    with pytest.raises(DBAPIError, match=r"verified_outcome_disabled|no_uuid_promotion"):
        async with brain_transaction(database.app, scope(OWNER), identity(OWNER), owner=True) as (
            session,
            _,
            now,
        ):
            session.add(
                BrainClaimRevision(
                    company_id=COMPANY,
                    claim_revision_id=UUID(int=3001),
                    claim_id=UUID(int=3002),
                    resource_id=UUID(int=1200),
                    revision="1",
                    kind=kind,
                    text="An unsupported outcome",
                    source_event_json='{"precision":"unknown","value":null,"basis":"fixture"}',
                    ingested_at=now,
                    origin="operator",
                    status="proposed",
                    receipt_id=receipt,
                )
            )
            await session.flush()


@pytest.mark.parametrize("failed_first", [False, True])
async def test_one_parse_recipe_cannot_hold_both_success_and_failure(
    database: AccessDatabase, tmp_path: Path, failed_first: bool
) -> None:
    raw = b'{"stable":true}' if not failed_first else b"{broken"
    store = await configured(database.app, tmp_path, Reader({"r1": raw}), media="application/json")
    result = await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    assert result.source is not None
    assert result.status == ("quarantined" if failed_first else "accepted")
    with pytest.raises(DBAPIError, match="already has"):
        async with brain_transaction(database.app, scope(OWNER), identity(OWNER), owner=True) as (
            session,
            _,
            now,
        ):
            if failed_first:
                session.add(
                    BrainParseRevision(
                        company_id=COMPANY,
                        parse_revision_id=UUID(int=3010),
                        source_revision_id=result.source.source_revision_id,
                        parser_version="utf8-identity-v1",
                        chunker_version="utf8-sections-v1",
                        canonical_text=raw.decode(),
                        canonical_sha256=hashlib.sha256(raw).hexdigest(),
                        recorded_at=now,
                    )
                )
            else:
                session.add(
                    BrainParseFailure(
                        company_id=COMPANY,
                        failure_id=UUID(int=3010),
                        source_id=result.source.source_id,
                        source_revision_id=result.source.source_revision_id,
                        parser_version="utf8-identity-v1",
                        chunker_version="utf8-sections-v1",
                        reason_code="parse_failed",
                        recorded_at=now,
                    )
                )
            await session.flush()
    async with database.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainParseRevision)) == int(
            not failed_first
        )
        assert await session.scalar(select(func.count()).select_from(BrainParseFailure)) == int(
            failed_first
        )


async def test_parse_reference_cannot_persist_missing_parsed_offset_pair(
    database: AccessDatabase, tmp_path: Path
) -> None:
    raw = b"Exact source and parse offsets require both coordinates"
    store = await configured(database.app, tmp_path, Reader({"r1": raw}))
    await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    with pytest.raises(DBAPIError, match="ck_brain_evidence_parsed_span"):
        async with brain_transaction(database.app, scope(OWNER), identity(OWNER)) as (
            session,
            _,
            _,
        ):
            original = await session.scalar(select(BrainEvidence))
            assert original is not None and original.parse_revision_id is not None
            fields = {
                column.name: getattr(original, column.name)
                for column in BrainEvidence.__table__.columns
            }
            fields.update(evidence_id=UUID(int=3099), parsed_start_byte=None, parsed_end_byte=None)
            session.add(BrainEvidence(**fields))
            await session.flush()
