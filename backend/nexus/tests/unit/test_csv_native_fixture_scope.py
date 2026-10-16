"""Fixture scope tests issue no database calls, registrations, hooks or native jobs."""

from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from nexus.tests.csv_native_scope import DATABASE, ROOT, require_database, require_root
from nexus.tests.csv_native_source import reviewed_sources


def test_exact_unused_ordinary_root_is_eligible() -> None:
    assert Path("/tmp/nexus-csv-native-pg-20261015-2") == ROOT
    require_root(ROOT, existing=ROOT.exists())


@pytest.mark.parametrize("root", [Path("/tmp/other"), Path("/home/santapong"), ROOT / ".."])
def test_other_root_or_namespace_denies(root: Path) -> None:
    with pytest.raises(ValueError, match="CSV native"):
        require_root(root, existing=False)


def test_exact_socket_and_assigned_database_only() -> None:
    assert DATABASE == "nexus_company_test_native_csv_engineering_v2"
    value = make_url(
        f"postgresql+asyncpg://santapong@/{DATABASE}"
        "?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438"
    )
    require_database(value, application=False)
    require_database(value.set(username="nexus_company_app"), application=True)
    for changed in (
        value.set(database="nexus_company_test_builder_engineering"),
        value.set(host="localhost"),
        value.set(password="unexpected"),
        value.set(username="other"),
        value.update_query_dict({"port": "5432"}),
    ):
        with pytest.raises(ValueError, match="CSV native"):
            require_database(changed, application=False)


def test_reviewed_sources_are_wholly_generated_exact_two_file_delta() -> None:
    before, after = reviewed_sources()
    assert len(before) == len(after) == 39
    assert sorted(name for name in before if before[name] != after[name]) == [
        "packages/shared/src/csv/csv.test.ts",
        "packages/shared/src/csv/index.ts",
    ]
    assert len([name for name in before if name.endswith(".test.ts")]) == 27


def test_direct_empty_catalog_has_only_two_zero_model_native_profiles() -> None:
    from uuid import uuid4

    from nexus.company.brain.access_contracts import ResourceRef
    from nexus.tests.csv_native_plan import empty_catalog, quotas
    from nexus.tests.integration.test_company_directory import COMPANY

    catalog = empty_catalog(ResourceRef(company_id=COMPANY, resource_id=uuid4()))
    assert catalog.models.models == () and catalog.admitted_profiles == frozenset()
    assert tuple(row.execution_profile for row in catalog.native_profiles) == (
        "engineering.native.v1",
        "verification.native.v1",
    )
    parent, child = quotas()
    assert parent.model_dump() == {
        "model_requests": 0,
        "tool_attempts": 2,
        "rework_rounds": 0,
        "plan_revisions": 0,
    }
    assert child.model_dump() == {
        "model_requests": 0,
        "tool_attempts": 1,
        "rework_rounds": 0,
        "plan_revisions": 0,
    }


def test_public_caps_and_pin_constants_match_exact_reviewed_limits() -> None:
    from nexus.tests.csv_native_runtime import CACHE_SHA, LOCK_SHA, MANIFEST_SHA, TOOL_SHA, limits

    assert all(len(row) == 64 for row in (CACHE_SHA, LOCK_SHA, MANIFEST_SHA, TOOL_SHA))
    value = limits()
    assert (
        value.cpu_millis,
        value.memory_bytes,
        value.workspace_bytes,
        value.output_bytes,
        value.log_bytes,
        value.command_seconds,
        value.job_seconds,
        value.pids,
    ) == (2000, 4294967296, 2147483648, 67108864, 1048576, 300, 1200, 256)


@pytest.mark.parametrize("case", ["hash", "bound", "symlink", "hardlink"])
def test_public_bytes_cannot_substitute_identity_or_escape_bounds(
    tmp_path: Path, case: str
) -> None:
    import hashlib
    import os

    from nexus.tests.csv_native_source import ordinary_bytes

    path = tmp_path / "ordinary"
    path.write_bytes(b"public")
    digest = hashlib.sha256(b"public").hexdigest()
    maximum = 10
    if case == "hash":
        digest = "a" * 64
    if case == "bound":
        maximum = 3
    if case == "symlink":
        link = tmp_path / "substitute"
        link.symlink_to(path)
        path = link
    if case == "hardlink":
        os.link(path, tmp_path / "duplicate")
    with pytest.raises(ValueError, match="CSV native"):
        ordinary_bytes(path, maximum, digest)


def test_unscoped_process_cannot_assert_delegated_kernel_qualification() -> None:
    from nexus.tests.csv_native_runtime import _kernel_scope

    with pytest.raises(ValueError, match="outside the exact owned delegated scope"):
        _kernel_scope(ROOT)


def test_expected_database_revision_matches_actual_pinned_company_lineage() -> None:
    """Historical CSV016 stays pinned while normal017 is its exact known successor."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from nexus.tests.csv_native_scope import COMPANY_REVISION

    backend = Path(__file__).resolve().parents[3]
    config = Config(str(backend / "alembic_company.ini"))
    config.set_main_option("script_location", str(backend / "company_alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert COMPANY_REVISION == "company_016"
    assert scripts.get_current_head() == "company_017"
    head = scripts.get_revision("company_017")
    assert head is not None and head.down_revision == COMPANY_REVISION
    pinned = scripts.get_revision(COMPANY_REVISION)
    assert pinned is not None and pinned.down_revision == "company_015"


def test_current_job_scope_gate_cannot_use_unscoped_historical_capability() -> None:
    from nexus.tests.csv_native_runtime import _kernel_scope

    with pytest.raises(ValueError, match="outside the exact owned delegated scope"):
        _kernel_scope(ROOT, job=True)


def test_audit_runner_preserves_real_prepare_run_and_reconcile_composition() -> None:
    from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
    from nexus.builder.runner import NativeBuilderRunner
    from nexus.tests.csv_native_audit import CsvObservedNodeRunner

    assert CsvObservedNodeRunner.run is NativeBuilderRunner.run
    assert CsvObservedNodeRunner.prepare is EngineeringNativeBuilderRunner.prepare
    assert CsvObservedNodeRunner.reconcile is EngineeringNativeBuilderRunner.reconcile


def test_historical_exact_root_cannot_be_reused_by_current_fixture() -> None:
    with pytest.raises(ValueError, match="CSV native"):
        require_root(Path("/tmp/nexus-csv-native-pg-20261015-1"), existing=True)


@pytest.mark.parametrize("application", [False, True])
def test_historical_exact_database_cannot_be_reused_by_current_fixture(application: bool) -> None:
    username = "nexus_company_app" if application else "santapong"
    original = make_url(
        f"postgresql+asyncpg://{username}@/nexus_company_test_native_csv_engineering"
        "?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438"
    )
    with pytest.raises(ValueError, match="CSV native"):
        require_database(original, application=application)
