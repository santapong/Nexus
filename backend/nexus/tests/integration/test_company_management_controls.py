"""Real owner control CAS/replay/audit and caps preserve existing spending and authority."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management import control_store as control_store_module
from nexus.company.management.base import RevisionRef
from nexus.company.management.control_models import ManagementControlEvent
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.harness.journal_models import CompanyControl, DailyBudget
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    control,
    prepare,
)
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_control_support import charter, mandate
from nexus.tests.management_control_support import management_factory as management_factory


async def test_actual_owner_mandate_cas_duplicate_history_and_caps_are_one_truthful_transaction(
    management_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare(management_factory)
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            DailyBudget(
                company_id=COMPANY,
                day=date(2026, 10, 14),
                held_usd=Decimal("0.4"),
                spent_usd=Decimal("1.2"),
            )
        )
    store = ManagementControlStore(management_factory)
    first = await store.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    assert (
        await store.publish_mandate(
            control(), identity(OWNER), mandate(), expected_revision_id=None
        )
        == first
    )
    with pytest.raises(ManagementConflictError):
        await store.publish_mandate(
            control(), identity(OWNER), mandate("v2"), expected_revision_id=None
        )
    second = await store.publish_mandate(
        control(),
        identity(OWNER),
        mandate("v2", daily="1", work="0.5"),
        expected_revision_id=first.revision_id,
    )
    assert second.revision_id != first.revision_id
    assert (
        await store.publish_mandate(
            control(), identity(OWNER), mandate(), expected_revision_id=None
        )
        == first
    )
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert (
            current is not None
            and current.daily_cap_usd == 1
            and current.work_cap_usd == Decimal("0.5")
        )
        assert (
            current.policy_version == "fixture-policy" and current.price_version == "fixture-prices"
        )
        day = await session.get(DailyBudget, (COMPANY, date(2026, 10, 14)))
        assert (
            day is not None and day.held_usd == Decimal("0.4") and day.spent_usd == Decimal("1.2")
        )
        head = await session.get(ManagementMandateHead, COMPANY)
        assert head is not None and head.current_revision_id == second.revision_id
        assert await session.scalar(select(func.count()).select_from(ManagementControlEvent)) == 2


@pytest.mark.parametrize("problem", ["member", "identity", "workspace", "board", "owner_splice"])
async def test_signed_current_owner_and_supervised_admission_cannot_be_bypassed(
    management_factory: async_sessionmaker[AsyncSession], problem: str
) -> None:
    await prepare(management_factory)
    data, scope, signed = mandate(), control(), identity(OWNER)
    if problem == "member":
        scope, signed = control(ACTOR), identity(ACTOR)
    elif problem == "identity":
        signed = identity(ACTOR)
    elif problem == "workspace":
        signed = VerifiedIdentity(principal_id=OWNER, workspace_id=UUID(int=999))
    elif problem == "board":
        data = data.model_copy(update={"oversight": "board"})
    else:
        data = data.model_copy(update={"owner_id": ACTOR})
    with pytest.raises(ValueError):
        await ManagementControlStore(management_factory).publish_mandate(
            scope, signed, data, expected_revision_id=None
        )
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.scalar(select(func.count()).select_from(ManagementMandateRevision)) == 0
        )


async def test_charter_requires_exact_active_mandate_and_current_verifier_membership(
    management_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare(management_factory)
    store = ManagementControlStore(management_factory)
    current = await store.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    ref = RevisionRef.model_validate_json(
        current.model_dump_json(include=set(RevisionRef.model_fields))
    )
    first = await store.publish_charter(
        control(), identity(OWNER), charter(), mandate=ref, expected_revision_id=None
    )
    assert first.mandate == ref
    assert (
        await store.publish_charter(
            control(), identity(OWNER), charter(), mandate=ref, expected_revision_id=None
        )
        == first
    )
    with pytest.raises(ValueError):
        await store.publish_charter(
            control(),
            identity(OWNER),
            charter("v2"),
            mandate=ref.model_copy(update={"sha256": "f" * 64}),
            expected_revision_id=first.revision_id,
        )
    await PersistentCompanyDirectory(management_factory).set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
        ),
        control(),
    )
    with pytest.raises(ValueError):
        await store.publish_charter(
            control(),
            identity(OWNER),
            charter("v2"),
            mandate=ref,
            expected_revision_id=first.revision_id,
        )
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.scalar(select(func.count()).select_from(ManagementCharterRevision)) == 1
        )


async def test_revoke_maintenance_and_old_reactivation_replay_never_restore_current_authority(
    management_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare(management_factory)
    store = ManagementControlStore(management_factory)
    current = await store.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    ref = RevisionRef.model_validate_json(
        current.model_dump_json(include=set(RevisionRef.model_fields))
    )
    revoked = await store.revoke_mandate(
        control().model_copy(update={"operation_id": UUID(int=5100)}), identity(OWNER), ref
    )
    restored_scope = control().model_copy(update={"operation_id": UUID(int=5101)})
    restored = await store.reactivate_mandate(restored_scope, identity(OWNER), ref)
    assert revoked.kind == "revoke" and restored.kind == "reactivate"
    await store.revoke_mandate(
        control().model_copy(update={"operation_id": UUID(int=5102)}), identity(OWNER), ref
    )
    assert await store.reactivate_mandate(restored_scope, identity(OWNER), ref) == restored
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(ManagementMandateHead, COMPANY)
        assert head is not None and not head.active
        current_control = await session.get(CompanyControl, COMPANY)
        assert current_control is not None
        current_control.paused = True
    await store.revoke_mandate(
        control().model_copy(update={"operation_id": UUID(int=5103)}), identity(OWNER), ref
    )
    with pytest.raises(ValueError):
        await store.reactivate_mandate(
            control().model_copy(update={"operation_id": UUID(int=5104)}), identity(OWNER), ref
        )
    with pytest.raises(ValueError):
        await store.publish_mandate(
            control(), identity(OWNER), mandate("v2"), expected_revision_id=ref.revision_id
        )


async def test_audit_failure_rolls_back_new_caps_history_and_head(
    management_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await prepare(management_factory)
    store = ManagementControlStore(management_factory)
    first = await store.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )

    async def broken_audit(*arguments: object, **keywords: object) -> None:
        raise RuntimeError("intentional audit failure before commit")

    monkeypatch.setattr(control_store_module, "append_control_event", broken_audit)
    with pytest.raises(RuntimeError):
        await store.publish_mandate(
            control(),
            identity(OWNER),
            mandate("v2", daily="1", work="0.5"),
            expected_revision_id=first.revision_id,
        )
    async with management_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(ManagementMandateHead, COMPANY)
        assert head is not None and head.current_revision_id == first.revision_id
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None and current.daily_cap_usd == 5 and current.work_cap_usd == 1
        assert (
            await session.scalar(select(func.count()).select_from(ManagementMandateRevision)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(ManagementControlEvent)) == 1


async def test_charter_activity_cannot_outlive_revoked_mandate_or_current_owner(
    management_factory: async_sessionmaker[AsyncSession],
) -> None:
    await prepare(management_factory)
    store = ManagementControlStore(management_factory)
    parent = await store.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    ref = RevisionRef.model_validate_json(
        parent.model_dump_json(include=set(RevisionRef.model_fields))
    )
    child = await store.publish_charter(
        control(), identity(OWNER), charter(), mandate=ref, expected_revision_id=None
    )
    from nexus.company.management.governance import CharterRevisionRef

    child_ref = CharterRevisionRef.model_validate_json(
        child.model_dump_json(include=set(CharterRevisionRef.model_fields))
    )
    await store.revoke_charter(
        control().model_copy(update={"operation_id": UUID(int=5200)}), identity(OWNER), child_ref
    )
    await store.revoke_mandate(
        control().model_copy(update={"operation_id": UUID(int=5201)}), identity(OWNER), ref
    )
    with pytest.raises(ValueError):
        await store.reactivate_charter(
            control().model_copy(update={"operation_id": UUID(int=5202)}),
            identity(OWNER),
            child_ref,
        )
    await PersistentCompanyDirectory(management_factory).set_membership(
        MembershipChange(
            company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
        ),
        control(),
    )
    with pytest.raises(ValueError):
        await store.publish_mandate(
            control(), identity(OWNER), mandate("v2"), expected_revision_id=ref.revision_id
        )


@pytest.mark.parametrize("subject", ["mandate", "charter"])
async def test_replacement_publication_preserves_revoked_activity_until_explicit_reactivation(
    management_factory: async_sessionmaker[AsyncSession], subject: str
) -> None:
    await prepare(management_factory)
    store = ManagementControlStore(management_factory)
    parent = await store.publish_mandate(
        control(), identity(OWNER), mandate(), expected_revision_id=None
    )
    parent_ref = RevisionRef.model_validate_json(
        parent.model_dump_json(include=set(RevisionRef.model_fields))
    )
    if subject == "mandate":
        await store.revoke_mandate(
            control().model_copy(update={"operation_id": UUID(int=5400)}),
            identity(OWNER),
            parent_ref,
        )
        second = await store.publish_mandate(
            control(),
            identity(OWNER),
            mandate("v2", daily="2", work="0.5"),
            expected_revision_id=parent_ref.revision_id,
        )
        async with management_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            head = await session.get(ManagementMandateHead, COMPANY)
            assert (
                head is not None
                and head.current_revision_id == second.revision_id
                and not head.active
            )
            current = await session.get(CompanyControl, COMPANY)
            assert current is not None and current.daily_cap_usd == 5 and current.work_cap_usd == 1
        second_ref = RevisionRef.model_validate_json(
            second.model_dump_json(include=set(RevisionRef.model_fields))
        )
        await store.reactivate_mandate(
            control().model_copy(update={"operation_id": UUID(int=5402)}),
            identity(OWNER),
            second_ref,
        )
        async with management_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            current = await session.get(CompanyControl, COMPANY)
            assert current is not None and current.daily_cap_usd == 2
            assert current.work_cap_usd == Decimal("0.5")
    else:
        child = await store.publish_charter(
            control(), identity(OWNER), charter(), mandate=parent_ref, expected_revision_id=None
        )
        from nexus.company.management.governance import CharterRevisionRef

        ref = CharterRevisionRef.model_validate_json(
            child.model_dump_json(include=set(CharterRevisionRef.model_fields))
        )
        await store.revoke_charter(
            control().model_copy(update={"operation_id": UUID(int=5401)}), identity(OWNER), ref
        )
        second_child = await store.publish_charter(
            control(),
            identity(OWNER),
            charter("v2"),
            mandate=parent_ref,
            expected_revision_id=ref.revision_id,
        )
        async with management_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            head_child = await session.get(ManagementCharterHead, (COMPANY, child.department_id))
            assert (
                head_child is not None
                and head_child.current_revision_id == second_child.revision_id
                and not head_child.active
            )
