"""Separate Root-invoked restricted RR READ ONLY conservation audit; never auto-run by test."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.plan_models import ManagementProcedure, ManagementRevisionEvent
from nexus.execution.coding_application_config import CodingApplicationConfig
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_models import CostHold, DailyBudget, WorkBudget
from nexus.settings import settings
from nexus.tests.integration.nexus_coding_application_sources import (
    DATABASE,
    PORT,
    SOCKET,
    private_bytes,
)


async def audit(config: CodingApplicationConfig, output: Path) -> None:
    """ONE original30s transaction and rollback; no body/envelope/credential projection.

    Cohesion exception: expected invariants share one RR snapshot. A first
    mismatch retains the collected prefix as unconfirmed, never as a pass or a
    reason to repeat the querygroup. Root owns failure-specific interpretation.
    """
    if not settings.company_test_database_url:
        raise ValueError("Root must supply the released exact database")
    url = make_url(settings.company_test_database_url)
    assert url.database == DATABASE and url.password is None
    assert url.username in {"santapong", "nexus_company_app"}
    assert dict(url.query) == {"host": SOCKET, "port": str(PORT)}
    engine = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    company = config.catalog.company_id
    start, end = clock_us(), clock_us() + 30_000_000
    facts: dict[str, object] = {
        "database": DATABASE,
        "started_utc": datetime.now(UTC).isoformat(),
        "original_end_us": end,
    }
    try:
        async with (
            asyncio.timeout(max(0, end - clock_us()) / 1_000_000),
            engine.connect() as connection,
        ):
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                await connection.execute(text("SET LOCAL statement_timeout='25000ms'"))
                await connection.execute(
                    select(func.set_config("nexus.company_id", str(company), True))
                )
                facts["transaction_read_only"] = await connection.scalar(
                    text("SHOW transaction_read_only")
                )
                facts["transaction_isolation"] = await connection.scalar(
                    text("SHOW transaction_isolation")
                )
                assert (
                    facts["transaction_read_only"] == "on"
                    and facts["transaction_isolation"] == "repeatable read"
                )
                assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
                assert not await connection.scalar(
                    text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
                )
                facts["schema"] = await connection.scalar(
                    text("SELECT version_num FROM company_alembic_version")
                )
                assert facts["schema"] == "company_017"
                tables = (
                    await connection.execute(
                        text(
                            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity "
                            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname='public' AND c.relkind='r' "
                            "AND c.relname LIKE 'company_%' "
                            "AND c.relname<>'company_alembic_version' ORDER BY c.relname"
                        )
                    )
                ).all()
                assert len(tables) == 74 and all(row[1] and row[2] for row in tables)
                counts = {}
                for table, _, _ in tables:
                    assert re.fullmatch(r"company_[a-z_]+", table)
                    counts[table] = await connection.scalar(
                        text('SELECT count(*) FROM "' + table + '"')
                    )
                facts["table_counts"] = counts
                for name in ("fsync", "synchronous_commit", "full_page_writes"):
                    assert await connection.scalar(text("SHOW " + name)) == "on"
                expected = {
                    config.admission.procedure.binding.task_id,
                    *(slot.child.binding.task_id for slot in config.admission.slots),
                }
                native = (
                    (
                        await connection.execute(
                            select(
                                ExecutionWork.task_id,
                                ExecutionWork.run_id,
                                ExecutionWork.registration_hash,
                                ExecutionWork.model_requests_used,
                                ExecutionWork.tool_attempts_used,
                                ExecutionWork.plan_revisions_used,
                                ExecutionWork.model_requests_delegated,
                                ExecutionWork.tool_attempts_delegated,
                                ExecutionWork.worker_id,
                                ExecutionWork.lease_until,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert {row["task_id"] for row in native} == expected
                root = next(
                    row
                    for row in native
                    if row["task_id"] == config.admission.procedure.binding.task_id
                )
                assert (
                    root["model_requests_used"],
                    root["tool_attempts_used"],
                    root["plan_revisions_used"],
                ) == (0, 0, 1)
                assert (root["model_requests_delegated"], root["tool_attempts_delegated"]) == (5, 5)
                assert sum(row["model_requests_used"] for row in native) == 2
                assert sum(row["tool_attempts_used"] for row in native) == 0
                assert all(
                    row["worker_id"] is None and row["lease_until"] is None for row in native
                )
                registered = (
                    (
                        await connection.execute(
                            select(
                                RegisteredWork.task_id,
                                RegisteredWork.parent_task_id,
                                RegisteredWork.root_task_id,
                                RegisteredWork.allocation_usd,
                                RegisteredWork.delegated_usd,
                                RegisteredWork.active,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert {row["task_id"] for row in registered} == expected
                top = next(row for row in registered if row["task_id"] == root["task_id"])
                assert top["allocation_usd"] == top["delegated_usd"] == Decimal(1)
                assert all(
                    row["allocation_usd"] == Decimal(".1") for row in registered if row is not top
                )
                attempts = (
                    (
                        await connection.execute(
                            select(
                                ExecutionAttempt.task_id,
                                ExecutionAttempt.attempt_id,
                                ExecutionAttempt.kind,
                                ExecutionAttempt.fence,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(attempts) == 2 and all(
                    row["kind"] == "model_requests" for row in attempts
                )
                intents = (
                    (
                        await connection.execute(
                            select(
                                EffectIntent.action_id,
                                EffectIntent.task_id,
                                EffectIntent.run_id,
                                EffectIntent.proposal_hash,
                                EffectIntent.intent_fence,
                                EffectIntent.state,
                                EffectIntent.receipt_json.is_not(None).label("receipt_present"),
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(intents) == 2 and all(
                    row["state"] == "succeeded" and row["receipt_present"] for row in intents
                )
                dispatches = (
                    (
                        await connection.execute(
                            select(
                                SegmentDispatch.action_id,
                                SegmentDispatch.task_id,
                                SegmentDispatch.run_id,
                                SegmentDispatch.segment_id,
                                SegmentDispatch.workflow_id,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(dispatches) == 2
                assert {row["action_id"] for row in dispatches} == {
                    row["action_id"] for row in intents
                }
                holds = (
                    (
                        await connection.execute(
                            select(
                                CostHold.action_id,
                                CostHold.amount_usd,
                                CostHold.actual_usd,
                                CostHold.state,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                issued = {row["action_id"] for row in intents}
                model_holds = [row for row in holds if row["action_id"] in issued]
                assert len(model_holds) == 2 and all(
                    row["state"] == "reconciled" and row["actual_usd"] is not None
                    for row in model_holds
                )
                assert all(
                    row["amount_usd"] == 0 for row in holds if row["action_id"] not in issued
                )
                spend = sum((row["actual_usd"] for row in model_holds), Decimal(0))
                totals = (
                    await connection.execute(select(WorkBudget.held_usd, WorkBudget.spent_usd))
                ).all()
                days = (
                    await connection.execute(select(DailyBudget.held_usd, DailyBudget.spent_usd))
                ).all()
                assert sum((row[1] for row in totals), Decimal(0)) == spend
                assert sum((row[1] for row in days), Decimal(0)) == spend
                assert all(row[0] == 0 for row in (*totals, *days))
                assert (
                    await connection.scalar(select(func.count()).select_from(ManagementProcedure))
                    == 1
                )
                assert (
                    await connection.scalar(
                        select(func.count()).select_from(ManagementRevisionEvent)
                    )
                    == 1
                )
                facts.update(
                    native=[dict(row) for row in native],
                    registered=[dict(row) for row in registered],
                    attempts=[dict(row) for row in attempts],
                    intents=[dict(row) for row in intents],
                    holds=[dict(row) for row in holds],
                    actual_known_spent_usd=str(spend),
                    dispatches=[dict(row) for row in dispatches],
                )
                publications = (
                    (
                        await connection.execute(
                            text(
                                "SELECT s.source_symbol,s.source_id,h.current_revision_id,"
                                "a.sha256,a.byte_length,d.kind,p.parse_revision_id "
                                "FROM company_brain_sources s JOIN company_brain_source_heads h "
                                "ON h.company_id=s.company_id AND h.source_id=s.source_id "
                                "JOIN company_brain_source_revisions r "
                                "ON r.company_id=s.company_id "
                                "AND r.source_revision_id=h.current_revision_id "
                                "JOIN company_brain_artifact_revisions a "
                                "ON a.company_id=r.company_id "
                                "AND a.artifact_revision_id=r.artifact_revision_id "
                                "JOIN company_brain_derivations d ON d.company_id=r.company_id "
                                "AND d.derivation_id=r.derivation_id "
                                "JOIN company_brain_parse_revisions p ON p.company_id=r.company_id "
                                "AND p.source_revision_id=r.source_revision_id "
                                "WHERE s.source_symbol IN ('nexus.coding.model_origin.v1',"
                                "'nexus.coding.code_patch.v1') ORDER BY s.source_symbol"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(publications) == 2
                assert {row["kind"] for row in publications} == {"model_origin", "code_patch"}
                facts["publication_source_head_artifact_derivation_parse"] = [
                    dict(row) for row in publications
                ]
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() AND usename='nexus_company_app' "
                            "AND pid<>pg_backend_pid()"
                        )
                    )
                    == 0
                )
                assert clock_us() < end
            finally:
                await transaction.rollback()
            assert clock_us() < end
        facts["rollback"] = True
        facts["elapsed_us"] = clock_us() - start
        raw = json.dumps(facts, default=str, sort_keys=True, indent=2).encode() + b"\n"
        assert clock_us() < end
        with output.open("xb") as stream:
            stream.write(raw)
        output.chmod(0o600)
        assert clock_us() < end
    except BaseException as error:
        # Failure-only metadata may be retained after the read end. No additional
        # SQL or success adoption occurs, and an existing output is not replaced.
        facts.update(status="unconfirmed", first_error_type=type(error).__name__)
        if not output.exists():
            with output.open("xb") as stream:
                stream.write(json.dumps(facts, default=str, sort_keys=True).encode() + b"\n")
            output.chmod(0o600)
        raise
    finally:
        await engine.dispose()


def main() -> None:
    """Root-only explicit invocation after terminal; no test or fixture invokes this entry."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = private_bytes(args.config, 262144)
    assert hashlib.sha256(raw).hexdigest() == args.config_sha
    asyncio.run(audit(CodingApplicationConfig.model_validate_json(raw), args.output))


if __name__ == "__main__":
    main()
