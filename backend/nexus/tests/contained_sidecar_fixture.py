"""Synthetic result descriptions plus real private sidecar files; no native authority proof."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_results import result_evidence_identity
from nexus.builder.engineering_contracts import EngineeringChangedFile, EngineeringSourceWitness
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.contained_observer_fixture import BOOT
from nexus.tests.unit.test_contained_evidence_types import sample
from nexus.tests.unit.test_contained_observer import IO
from nexus.tests.unit.test_contained_results import result


def legacy_result() -> BuilderRunResult:
    """Fixed metadata supports an exact pre-change protected-payload golden."""
    value = result()
    job = value.spec.job.model_copy(
        update={
            key: UUID(int=index)
            for index, key in enumerate(
                (
                    "company_id",
                    "task_id",
                    "trace_id",
                    "run_id",
                    "workspace_id",
                    "actor_id",
                    "action_id",
                ),
                1,
            )
        }
    )
    return BuilderRunResult.model_validate(
        value.model_copy(
            update={
                "spec": value.spec.model_copy(update={"job": job}),
                "recorded_at": datetime(2026, 10, 15, tzinfo=UTC),
            }
        ).model_dump()
    )


def publisher(
    *, containment_store: object = None, execution_method_sha256: object = None
) -> BuilderArtifactPublisher:
    """Use mocked DB/blob boundaries; sidecar I/O is exercised separately with owned files."""
    policy = SourcePolicy(
        source_symbol="fixture.builder",
        authority_profile="fixture.owner",
        data_classification="internal",
        origin_kind="derived",
        media_type="application/json",
        parser_version="fixture.parser.v1",
        chunker_version="fixture.chunker.v1",
        search_config="simple",
        freshness_seconds=60,
    )
    return BuilderArtifactPublisher(
        MagicMock(),
        MagicMock(spec=ProtectedBlobStore),
        ResourceRef(company_id=BOOT, resource_id=UUID(int=5)),
        policy,
        # Deliberately malformed values in constructor negatives retain their
        # real runtime types; casts satisfy static callers without coercing them.
        containment_store=cast(ContainmentEvidenceStore | None, containment_store),
        execution_method_sha256=cast(str | None, execution_method_sha256),
    )


async def contained_result(root: Path) -> tuple[BuilderRunResult, ContainmentEvidenceStore]:
    """Create a true hash-bound local sidecar, with only synthetic process observations."""
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256

    value = result()
    job = value.spec.job.model_copy(update={"company_id": BOOT, "action_id": BOOT})
    spec = value.spec.model_copy(update={"job": job, "runtime_recipe": RUNTIME_V2})
    value = value.model_copy(
        update={
            "spec": spec,
            "image_id": "a" * 64,
            "container_name": "nexus-builder-" + "c" * 32,
        }
    )
    identity = result_evidence_identity(value, CONTAINED_EXECUTION_METHOD_SHA256)
    observer = ContainmentObserver(IO([]), clock_us=lambda: 12_040_000)
    observation = await observer.finish(
        (sample(),),
        identity,
        spec_sha256=canonical_sha256(spec),
        proposal_sha256=value.proposal_sha256,
        selector_sha256=RUNTIME_V2_METHOD_SHA256,
        deadline=ObservationDeadline(end_us=13_000_000),
    )
    store = ContainmentEvidenceStore(root / "sidecars")
    reference = await store.save_once(observation)
    return BuilderRunResult.model_validate(
        value.model_copy(update={"containment": reference}).model_dump()
    ), store


def source_witness(value: BuilderRunResult) -> EngineeringSourceWitness:
    """Independent declared witness bytes remain separate from containment observations."""
    return EngineeringSourceWitness(
        spec_sha256=canonical_sha256(value.spec),
        source=value.spec.job.source,
        patch_sha256="a" * 64,
        baseline_inventory_sha256="b" * 64,
        post_inventory_sha256="c" * 64,
        changes=(
            EngineeringChangedFile(
                path="src/example.py", before_sha256="d" * 64, after_sha256="e" * 64
            ),
        ),
    )
