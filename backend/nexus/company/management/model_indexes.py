"""Static reviewed FK index declarations only; application runtime emits no DDL."""

from sqlalchemy import Index

from nexus.company.management.model_base import ManagementBase

_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ix_m3_fk_01cafd13c84c",
        "company_management_charter_revisions",
        ("company_id", "mandate_revision_id"),
    ),
    (
        "ix_m3_fk_0f405bfd9d62",
        "company_management_verification_bindings",
        ("company_id", "plan_revision_id", "author_task_id"),
    ),
    (
        "ix_m3_fk_12b320a7ce36",
        "company_management_plan_tasks",
        ("company_id", "department_id", "charter_revision_id"),
    ),
    ("ix_m3_fk_2b59a56a047f", "company_management_plan_revisions", ("company_id", "proposed_by")),
    (
        "ix_m3_fk_2fab3db19790",
        "company_management_commitment_revisions",
        ("company_id", "recorded_by"),
    ),
    (
        "ix_m3_fk_308580d68217",
        "company_management_procedures",
        ("company_id", "parent_task_id", "parent_run_id"),
    ),
    (
        "ix_m3_fk_36e45c5aeb58",
        "company_management_plan_tasks",
        ("company_id", "goal_id", "procedure_id"),
    ),
    (
        "ix_m3_fk_3bb7b2f1b632",
        "company_management_control_events",
        ("company_id", "previous_mandate_revision_id"),
    ),
    (
        "ix_m3_fk_3cd9a0fc008f",
        "company_management_revision_events",
        ("company_id", "previous_plan_revision_id"),
    ),
    ("ix_m3_fk_40e4c1ff93e6", "company_management_control_events", ("company_id", "owner_id")),
    (
        "ix_m3_fk_44a5e2a53abf",
        "company_management_acceptance_invalidations",
        ("company_id", "recorded_by"),
    ),
    (
        "ix_m3_fk_45156fee24e0",
        "company_management_revision_events",
        ("company_id", "parent_task_id", "parent_run_id"),
    ),
    ("ix_m3_fk_4c7c1ca7b045", "company_management_mandate_revisions", ("company_id", "owner_id")),
    (
        "ix_m3_fk_50e8f455c493",
        "company_management_plan_heads",
        ("company_id", "current_revision_id", "decision_id"),
    ),
    (
        "ix_m3_fk_574bc0c38a48",
        "company_management_goal_revisions",
        ("company_id", "responsible_id"),
    ),
    (
        "ix_m3_fk_58de7b92109c",
        "company_management_goal_heads",
        ("company_id", "goal_id", "current_revision_id"),
    ),
    (
        "ix_m3_fk_5c564153be36",
        "company_management_commitment_revisions",
        ("company_id", "responsible_id"),
    ),
    (
        "ix_m3_fk_5dd7dec63e17",
        "company_management_plan_revisions",
        ("company_id", "mandate_revision_id"),
    ),
    (
        "ix_m3_fk_5e566ab98b62",
        "company_management_plan_dependencies",
        ("company_id", "plan_revision_id", "dependency_task_id"),
    ),
    (
        "ix_m3_fk_6bf62bddd95a",
        "company_management_plan_heads",
        ("company_id", "goal_id", "procedure_id"),
    ),
    (
        "ix_m3_fk_6e541bfd669d",
        "company_management_control_events",
        ("company_id", "department_id", "previous_charter_revision_id"),
    ),
    (
        "ix_m3_fk_6ebbd84e04ca",
        "company_management_acceptance_proofs",
        ("company_id", "artifact_revision_id"),
    ),
    (
        "ix_m3_fk_730ae74d6570",
        "company_management_commitment_revisions",
        ("company_id", "goal_id", "goal_revision_id"),
    ),
    ("ix_m3_fk_751c01d56e21", "company_management_goal_revisions", ("company_id", "recorded_by")),
    (
        "ix_m3_fk_781d7b36aab9",
        "company_management_revision_events",
        ("company_id", "next_plan_revision_id"),
    ),
    (
        "ix_m3_fk_7ddbd147a172",
        "company_management_commitment_revisions",
        ("company_id", "plan_revision_id"),
    ),
    ("ix_m3_fk_7f14d7e26a8e", "company_management_goal_evidence", ("company_id", "evidence_id")),
    (
        "ix_m3_fk_86f6e10d6002",
        "company_management_plan_heads",
        ("company_id", "plan_id", "current_revision_id", "goal_id"),
    ),
    (
        "ix_m3_fk_8fdcf6cff560",
        "company_management_revision_events",
        ("company_id", "owner_decision_id"),
    ),
    (
        "ix_m3_fk_8ff0d9adb48e",
        "company_management_mandate_heads",
        ("company_id", "current_revision_id"),
    ),
    (
        "ix_m3_fk_989c3ee4ef9e",
        "company_management_plan_revisions",
        ("company_id", "goal_id", "goal_revision_id"),
    ),
    ("ix_m3_fk_9fa6fd365a3a", "company_management_work_acceptances", ("company_id", "verifier_id")),
    (
        "ix_m3_fk_a1d3a7c26442",
        "company_management_charter_revisions",
        ("company_id", "recorded_by"),
    ),
    ("ix_m3_fk_b264e030a515", "company_management_revision_events", ("company_id", "owner_id")),
    (
        "ix_m3_fk_b338915a7f28",
        "company_management_control_events",
        ("company_id", "mandate_revision_id"),
    ),
    (
        "ix_m3_fk_b34c0f167eb7",
        "company_management_control_events",
        ("company_id", "department_id", "charter_revision_id"),
    ),
    (
        "ix_m3_fk_bdf878e5cf5d",
        "company_management_commitment_heads",
        ("company_id", "commitment_id", "current_revision_id"),
    ),
    ("ix_m3_fk_c987a75d2bf6", "company_management_plan_tasks", ("company_id", "task_id", "run_id")),
    (
        "ix_m3_fk_d05e7cbafb73",
        "company_management_work_acceptances",
        ("company_id", "verifier_task_id", "verifier_run_id"),
    ),
    (
        "ix_m3_fk_d154136bf408",
        "company_management_charter_heads",
        ("company_id", "department_id", "current_revision_id"),
    ),
    (
        "ix_m3_fk_d20ecb139965",
        "company_management_revision_events",
        ("company_id", "procedure_id", "parent_task_id", "parent_run_id"),
    ),
    ("ix_m3_fk_d2b2d466360b", "company_management_work_acceptances", ("company_id", "author_id")),
    (
        "ix_m3_fk_ed77ac27f257",
        "company_management_plan_tasks",
        ("company_id", "plan_revision_id", "goal_id"),
    ),
    ("ix_m3_fk_ef400092f95a", "company_management_owner_decisions", ("company_id", "owner_id")),
    ("ix_m3_fk_f226a65daacf", "company_management_report_snapshots", ("company_id", "created_by")),
    (
        "ix_m3_fk_f535590964f4",
        "company_management_goal_revisions",
        ("company_id", "mandate_revision_id"),
    ),
    (
        "ix_m3_fk_fe50ae941ca7",
        "company_management_control_events",
        ("company_id", "goal_id", "goal_revision_id"),
    ),
    (
        "ix_m3_fk_ff42f5c42352",
        "company_management_control_events",
        ("company_id", "goal_id", "previous_goal_revision_id"),
    ),
)


def register_indexes() -> None:
    """Attach frozen indexes to complete metadata before normal migration comparison."""
    for name, table_name, columns in _INDEXES:
        table = ManagementBase.metadata.tables[table_name]
        if not any(index.name == name for index in table.indexes):
            Index(name, *(table.c[column] for column in columns))
