"""Negative-only guard shapes. These bypass constructors and NEVER prove valid authority.

Each shape deliberately has a nominated structural/binding defect. No test may use
this helper as a positive selected-proof, source-READ, parent or permission fixture.
"""

from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import jwt
from pydantic import SecretStr

from nexus.builder.contained_intent_check import ContainedParentIntentCheck
from nexus.builder.contained_services import ContainmentServices
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.notifications.worker_identity import _verify
from nexus.company.strategy.actor_proof_reader import StrategyActorProofReader
from nexus.execution.intent_checks import BeforeIntentCheck, CompositeBeforeIntentCheck
from nexus.execution.selected_intent_gate import require_selected_intent_check
from nexus.tests.contained_observer_fixture import parent
from nexus.tests.unit.selected_intent_boundary_fixture import IntentBoundary, NoOpIntentCheck
from nexus.tests.unit.selected_strategy_pins_fixture import selected_case


def defective_check(case: IntentBoundary, defect: str) -> BeforeIntentCheck:
    """Construct only a nominated malformed shape; actual selected validate is never mocked."""
    # Keep the >50-line one-job descriptor and its defect together to avoid fake positive authority.
    from nexus.builder.selected_strategy_guard import StrategySelectedBuilderGuard

    selected = selected_case(case.work.workflow_name == "engineering.verify")
    job = selected.spec.job.model_copy(
        update={
            "company_id": case.work.company_id,
            "task_id": case.work.task_id,
            "trace_id": case.work.trace_id,
            "run_id": case.work.run_id,
            "actor_id": case.work.actor_id,
            "workspace_id": case.work.workspace_id,
            "action_id": case.action.id,
        }
    )
    guard = object.__new__(StrategySelectedBuilderGuard)
    guard.spec = selected.spec.model_copy(update={"job": job})
    guard.policy, guard.template = selected.policy, selected.template
    guard.lease, guard.identity, guard.catalog = case.lease, case.identity, case.catalog
    key = SecretStr("synthetic-selected-intent-signing-key-no-service")
    token = SecretStr(
        jwt.encode(
            {
                "sub": str(case.identity.principal_id),
                "workspace_id": str(case.identity.workspace_id),
                "iat": int((case.now - timedelta(seconds=1)).timestamp()),
                "exp": int((case.now + timedelta(seconds=60)).timestamp()),
            },
            key.get_secret_value(),
            algorithm="HS256",
        )
    )
    guard.credential = _verify(token, key)
    artifacts = SimpleNamespace(factory=MagicMock())
    guard.artifacts = cast(BoundedArtifactReader, artifacts)
    # Native reader/provider construction is intentionally absent; this helper only tests denial.
    guard.freshness = MagicMock()
    guard.reader = cast(
        StrategyActorProofReader,
        SimpleNamespace(
            reader=SimpleNamespace(
                artifacts=artifacts,
                freshness=guard.freshness,
                catalog=case.catalog,
            )
        ),
    )
    services = object.__new__(ContainmentServices)
    services.expectation = parent().expectation.model_copy(
        update={
            "company_id": job.company_id,
            "action_id": job.action_id,
            "task_id": job.task_id,
            "trace_id": job.trace_id,
            "run_id": job.run_id,
        }
    )
    guard.containment = services
    parent_check = ContainedParentIntentCheck(services)
    checks: tuple[BeforeIntentCheck, ...] = (guard, parent_check)
    # Check only the synchronous shape baseline, NEVER actual admission or proof authority.
    require_selected_intent_check(
        case.catalog,
        case.work,
        case.lease,
        case.identity,
        case.action,
        CompositeBeforeIntentCheck(checks),
    )
    if defect == "plain":
        return guard
    if defect == "missing_parent":
        checks = (guard,)
    elif defect == "noop_guard":
        checks = (NoOpIntentCheck(), parent_check)
    elif defect == "guard_subclass":
        guard_cls = type("UnqualifiedSelectedSubclass", (StrategySelectedBuilderGuard,), {})
        other = cast(StrategySelectedBuilderGuard, object.__new__(guard_cls))
        other.__dict__.update(guard.__dict__)
        checks = (other, parent_check)
    elif defect == "parent_subclass":
        parent_cls = type("UnqualifiedParentSubclass", (ContainedParentIntentCheck,), {})
        checks = (guard, parent_cls(services))
    elif defect == "extra":
        checks = (*checks, NoOpIntentCheck())
    elif defect == "reversed":
        checks = (parent_check, guard)
    elif defect == "lease":
        guard.lease = case.lease.model_copy(update={"fence": case.lease.fence + 1})
    elif defect == "action":
        guard.spec = guard.spec.model_copy(
            update={
                "job": job.model_copy(
                    update={"action_id": UUID(int=999)},
                )
            }
        )
    elif defect == "parent_scope":
        services.expectation = services.expectation.model_copy(update={"company_id": UUID(int=999)})
    elif defect == "parent_service":
        parent_check.services = object.__new__(ContainmentServices)
    elif defect == "composite_subclass":
        composite_cls = type("UnqualifiedCompositeSubclass", (CompositeBeforeIntentCheck,), {})
        return cast(BeforeIntentCheck, composite_cls(checks))
    return CompositeBeforeIntentCheck(checks)
