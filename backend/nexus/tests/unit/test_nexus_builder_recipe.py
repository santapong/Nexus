"""Exact recipe descriptions and real canonical assertions; no image/native qualification.

Cohesion exception: the real shared graph constructor, renderer, private metadata
and fixed wrapper cases remain in the approved paired test file rather than adding
another fixture/framework path. Supplied image facts never prove native admission.
"""

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from nexus.builder.contained_compiler import described_contained_script
from nexus.builder.contracts import (
    BuilderArtifact,
    BuilderJobSpec,
    BuilderLimits,
    RepositoryPin,
)
from nexus.builder.engineering_contracts import EngineeringBehaviorEvidence
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.nexus_public_inputs import describe_public_inputs
from nexus.builder.nexus_recipe import (
    REQUIRED_SOURCE_PATHS,
    NexusImageBinding,
    NexusToolchainManifest,
    command_references,
    make_nexus_policy,
    manifest_sha256,
    require_nexus_recipe,
)
from nexus.builder.nexus_recipe_assets import assets_sha256, canonical_assertions, wrapper_source
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.unit.test_nexus_public_inputs import (
    build_wheels,
    digest,
    selected_test_wheels,
    source_inputs,
)


def manifest_case(*, complete: bool = True) -> NexusToolchainManifest:
    raw = dict(zip(REQUIRED_SOURCE_PATHS[:4], source_inputs(), strict=True))
    rows = tuple(
        BuilderArtifact(
            path=path,
            sha256=digest(raw.get(path, path.encode())),
            byte_length=len(raw.get(path, path.encode())),
        )
        for path in REQUIRED_SOURCE_PATHS
    )
    return NexusToolchainManifest(
        source=RepositoryPin(
            repository_symbol="nexus", commit="1" * 40, tree="2" * 40, archive_sha256="3" * 64
        ),
        inputs=describe_public_inputs(
            *source_inputs(),
            platform="linux/amd64",
            build_wheels=build_wheels(),
            test_wheels=selected_test_wheels(),
        ),
        source_files=rows,
        assets_sha256=assets_sha256(),
        base_image="docker.io/library/python@sha256:" + "4" * 64 if complete else None,
        test_tree_sha256="5" * 64 if complete else None,
        node_tree_sha256="6" * 64 if complete else None,
        build_tree_sha256="7" * 64 if complete else None,
        cold_offline_receipt_sha256="8" * 64 if complete else None,
        test_requirements_sha256="9" * 64 if complete else None,
    )


def image_case(manifest: NexusToolchainManifest) -> NexusImageBinding:
    # Supplied image/qualification descriptors only; no actual platform readiness claim.
    return NexusImageBinding(
        reference="localhost/nexus-python-npm@sha256:" + "a" * 64,
        image_id="b" * 64,
        platform="linux/amd64",
        manifest_sha256=manifest_sha256(manifest),
        qualification_sha256="c" * 64,
    )


def recipe_case() -> tuple[NexusToolchainManifest, NexusImageBinding, BuilderExecutionSpec]:
    manifest = manifest_case()
    image = image_case(manifest)
    policy = make_nexus_policy(UUID(int=1), "builder.nexus", manifest, image)
    job = BuilderJobSpec(
        company_id=UUID(int=1),
        task_id=UUID(int=2),
        trace_id=UUID(int=3),
        run_id=UUID(int=4),
        workspace_id=UUID(int=5),
        actor_id=UUID(int=6),
        action_id=UUID(int=7),
        policy_symbol=policy.policy_symbol,
        resource_symbol=policy.resource_symbol,
        architecture="amd64",
        source=manifest.source,
        write_paths=policy.write_paths,
        artifact_paths=policy.artifact_paths,
        commands=command_references(),
        limits=BuilderLimits(),
    )
    return (
        manifest,
        image,
        BuilderExecutionSpec(
            job=job, policy_sha256=canonical_sha256(policy), runtime_recipe=policy.runtime_recipe
        ),
    )


def test_fixed_four_commands_eight_phases_keep_actual_generic_noexec_renderer() -> None:
    manifest, image, spec = recipe_case()
    policy = make_nexus_policy(spec.job.company_id, "builder.nexus", manifest, image)
    require_nexus_recipe(spec, policy, manifest, image)
    assert policy.runtime_inputs is None and spec.runtime_inputs is None
    assert [row.command_key for row in policy.commands] == [
        "backend",
        "frontend-test",
        "frontend-build",
        "behavior",
    ]
    assert len(spec.job.commands) == 8
    script = described_contained_script(spec, policy)
    assert script.count("--manifest-sha256") == 8
    assert "cd /source/baseline" in script and "cd /source/post" in script
    assert "pnpm" not in script and "stockflow" not in script
    assert spec.job.limits == BuilderLimits()


@pytest.mark.parametrize(
    "field",
    [
        "base_image",
        "test_tree_sha256",
        "test_requirements_sha256",
        "build_tree_sha256",
        "node_tree_sha256",
        "cold_offline_receipt_sha256",
    ],
)
def test_host_receipts_cannot_substitute_missing_image_input_qualification(field: str) -> None:
    manifest = manifest_case().model_copy(update={field: None})
    with pytest.raises(ValueError, match="unqualified"):
        make_nexus_policy(UUID(int=1), "builder.nexus", manifest, image_case(manifest))


def test_source_command_asset_and_image_splices_deny() -> None:
    manifest, image, spec = recipe_case()
    policy = make_nexus_policy(spec.job.company_id, "builder.nexus", manifest, image)
    for changed in [
        spec.model_copy(
            update={"job": spec.job.model_copy(update={"commands": spec.job.commands[:4]})}
        ),
        spec.model_copy(
            update={
                "job": spec.job.model_copy(
                    update={"source": manifest.source.model_copy(update={"commit": "f" * 40})}
                )
            }
        ),
    ]:
        with pytest.raises(ValueError):
            require_nexus_recipe(changed, policy, manifest, image)
    with pytest.raises(ValueError):
        require_nexus_recipe(
            spec, policy, manifest.model_copy(update={"assets_sha256": "0" * 64}), image
        )
    with pytest.raises(ValueError):
        make_nexus_policy(
            UUID(int=1),
            "builder.nexus",
            manifest,
            image.model_copy(update={"platform": "linux/arm64"}),
        )


def test_actual_canonical_assertions_emit_existing_schema_and_detect_real_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import canonical

    evidence = EngineeringBehaviorEvidence.model_validate(canonical_assertions(canonical))
    assert len(evidence.cases) == 4 and all(row.status == "pass" for row in evidence.cases)
    monkeypatch.setattr(canonical, "canonical_sha256", lambda value: "0" * 64)
    failed = EngineeringBehaviorEvidence.model_validate(canonical_assertions(canonical))
    assert any(row.status == "fail" for row in failed.cases)
    assert "engineering.patch.v1" not in json.dumps(canonical_assertions(canonical))


def test_wrapper_is_fixed_readonly_source_offline_and_original_cleanup_asset() -> None:
    raw = wrapper_source()
    compile(raw, "fixed-nexus-recipe", "exec")
    assert "O_NOFOLLOW" in raw and "16_777_216" in raw and "4096" in raw
    assert "--offline" in raw and "--no-build-isolation" in raw
    assert "--behavior-child" in raw and "--ignore-scripts" in raw
    assert "remove_entries" in raw and "dir_fd" in raw
    assert hashlib.sha256(raw.encode()).hexdigest() != "0" * 64


def test_actual_generic_argv_keeps_noexec_and_coherent_node_substitution_denies(
    tmp_path: Path,
) -> None:
    from nexus.builder.contained_compiler import described_contained_argv
    from nexus.builder.contracts import BuilderCapabilities
    from nexus.builder.node_recipe import command_policies as node_commands
    from nexus.builder.node_recipe import command_references as node_references
    from nexus.builder.runtime_plan import PreparedSources

    manifest, image, spec = recipe_case()
    policy = make_nexus_policy(spec.job.company_id, "builder.nexus", manifest, image)
    baseline, post = tmp_path / "baseline", tmp_path / "post"
    baseline.mkdir(mode=0o700)
    post.mkdir(mode=0o700)
    entry = tmp_path / "entrypoint.sh"
    entry.write_text(described_contained_script(spec, policy))
    (tmp_path / "resolv.conf").write_bytes(b"")
    capabilities = BuilderCapabilities(
        architecture="amd64",
        rootless=True,
        cgroup_v2=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        hard_workspace_quota=True,
        network_none_verified=True,
        image_present=True,
        qualified_image=image.reference,
    )
    argv = described_contained_argv(
        spec, policy, capabilities, PreparedSources(baseline, post), entry
    )
    assert "--network=none" in argv and "--pull=never" in argv and "--read-only" in argv
    assert len([value for value in argv if ":rw,nodev,nosuid,noexec," in value]) == 3
    assert f"{baseline}:/source/baseline:ro" in argv and f"{post}:/source/post:ro" in argv
    node = policy.model_copy(update={"commands": node_commands()})
    changed = spec.model_copy(
        update={
            "policy_sha256": canonical_sha256(node),
            "job": spec.job.model_copy(update={"commands": node_references()}),
        }
    )
    changed.require_descriptive_policy(
        node
    )  # A coherent ordinary descriptor still cannot be Nexus.
    with pytest.raises(ValueError, match="fixed recipe"):
        require_nexus_recipe(changed, node, manifest, image)


def test_fixed_asset_actual_read_rejects_source_config_links_and_oversize(tmp_path: Path) -> None:
    namespace: dict[str, object] = {"__name__": "nexus_asset_unit"}
    exec(compile(wrapper_source(), "fixed-nexus-asset", "exec"), namespace)
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    (source / "empty.py").write_bytes(b"")
    # Execute only fixed local metadata functions, never wrapper main/process commands.
    from collections.abc import Callable
    from typing import cast

    source_files = cast(Callable[[Path], list[tuple[str, bytes]]], namespace["source_files"])
    assert source_files(source) == [("empty.py", b"")]
    (source / "symlink.py").symlink_to(source / "empty.py")
    with pytest.raises(ValueError, match="link"):
        source_files(source)
    (source / "symlink.py").unlink()
    (source / ".npmrc").write_text("synthetic forbidden fixture")
    with pytest.raises(ValueError, match="configuration"):
        source_files(source)
    (source / ".npmrc").unlink()
    with (source / "large.py").open("wb") as stream:
        stream.truncate(16_777_217)
    with pytest.raises(ValueError, match="bound"):
        source_files(source)


def test_actual_metadata_cli_keeps_no_ready_and_original_inputs(tmp_path: Path) -> None:
    import runpy

    from nexus.builder.nexus_recipe import manifest_wire

    manifest = manifest_case(complete=False)
    source = tmp_path / "source"
    for path, raw in zip(REQUIRED_SOURCE_PATHS[:4], source_inputs(), strict=True):
        target = source / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(raw)
    for path in REQUIRED_SOURCE_PATHS[4:]:
        target = source / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(path.encode())
    selected = tmp_path / "manifest.json"
    selected.write_bytes(manifest_wire(manifest))
    script = Path(__file__).parents[3] / "scripts/nexus_toolchain_inputs.py"
    inspect_inputs = runpy.run_path(str(script), run_name="nexus_metadata_unit")["inspect_inputs"]
    output = tmp_path / "description.json"
    inspect_inputs(selected, digest(selected.read_bytes()), source, output)
    assert json.loads(output.read_bytes())["execution_permitted"] is False
    (source / "frontend/package-lock.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source"):
        inspect_inputs(selected, digest(selected.read_bytes()), source, tmp_path / "changed.json")


async def test_factory_reuses_actual_engine_and_concrete_coding_graph_without_io(
    tmp_path: Path,
) -> None:
    # Cohesive constructor proof only: actual graph, supplied image/tree facts; no native permit.
    from nexus.builder.coding_templates import (
        CodingBuilderEntry,
        CodingBuilderServices,
        CodingBuilderTemplate,
    )
    from nexus.builder.contained_evidence_store import ContainmentEvidenceStore
    from nexus.builder.contained_services import ContainmentServices
    from nexus.builder.contracts import BuilderCapabilities
    from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
    from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
    from nexus.builder.nexus_recipe import compose_nexus_runner
    from nexus.builder.result_store import BuilderResultStore
    from nexus.company.brain.sources import ArtifactRevisionRef
    from nexus.company.management.coding_publication_origin import CodingPublicationOriginReader
    from nexus.execution.effect_store import EffectStore
    from nexus.execution.runtime_store import ExecutionStore
    from nexus.tests.unit.coding_publication_fixture import graph
    from nexus.tests.unit.test_contained_scope import expectation

    value = await graph(tmp_path)  # Default real_repository=False; no Git or SQL delivery.
    reader = CodingPublicationOriginReader(
        value.private.factory,
        value.catalog,
        value.private.sources.artifacts,
        value.private.sources.freshness,
        rules=value.rules,
        recipe=value.prepared.input_recipe,
    )
    manifest = manifest_case().model_copy(update={"source": value.prepared.binding.source})
    image = image_case(manifest)
    admission = reader.admission
    policy = make_nexus_policy(
        reader.catalog.company_id, admission.slots[5].tool.resource, manifest, image
    )
    reference = ArtifactRevisionRef(
        company_id=reader.catalog.company_id,
        artifact_id=UUID(int=911),
        artifact_revision_id=UUID(int=912),
        revision="unit",
        sha256="e" * 64,
        byte_length=1,
    )
    entries = []
    for slot in admission.slots[5:7]:
        target = next(
            r.resource for r in reader.catalog.resources if r.symbol == slot.tool.resource
        )
        template = CodingBuilderTemplate(
            company_id=reader.catalog.company_id,
            goal_id=admission.goal.goal_id,
            admission_sha256=canonical_sha256(admission),
            c_action_id=reader.rules.action_id,
            origin=reference,
            protected_patch=reference,
            source_metadata=reference,
            repository=manifest.source,
            policy=policy,
            architecture="amd64",
            commands=command_references(),
            write_paths=policy.write_paths,
            artifact_paths=policy.artifact_paths,
            limits=BuilderLimits(),
            output_resource=target,
        )
        entries.append(CodingBuilderEntry(slot.child.binding, template))
    coding = CodingBuilderServices(reader, tuple(entries))
    contained = ContainmentServices(expectation(), ContainmentEvidenceStore(tmp_path / "contained"))
    jobs = tmp_path / "jobs"
    jobs.mkdir(mode=0o700)
    publisher = EngineeringArtifactPublisher(
        reader.factory,
        reader.blobs,
        entries[0].template.output_resource,
        reader.rules.origin_policy,
        jobs,
        containment_store=contained.store,
        execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )
    execution = ExecutionStore(
        reader.factory,
        management_catalog=reader.catalog,
        management_artifacts=reader.artifacts,
        management_freshness=reader.freshness,
    )
    effects = EffectStore(
        reader.factory,
        management_catalog=reader.catalog,
        management_artifacts=reader.artifacts,
        management_freshness=reader.freshness,
    )
    capabilities = BuilderCapabilities(
        architecture="amd64",
        rootless=True,
        cgroup_v2=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        hard_workspace_quota=True,
        network_none_verified=True,
        image_present=True,
        qualified_image=image.reference,
    )
    results = BuilderResultStore(tmp_path / "results")

    def compose() -> EngineeringNativeBuilderRunner:
        return compose_nexus_runner(
            reader.factory,
            execution,
            effects,
            policy=policy,
            capabilities=capabilities,
            image_id=image.image_id,
            results=results,
            jobs_root=jobs,
            publisher=publisher,
            containment=contained,
            coding=coding,
            manifest=manifest,
            image=image,
        )

    runner = compose()
    assert type(runner) is EngineeringNativeBuilderRunner
    assert (
        runner.execution is execution
        and runner.effects is effects
        and runner.containment is contained
    )
    assert contained.deadline is None
    execution._management_artifacts = None
    with pytest.raises(ValueError, match="graph"):
        compose()


def embedded_reader() -> Callable[[Path, int], bytes]:
    """Compile only the fixed inert asset namespace; no main, image, or package command runs."""
    namespace: dict[str, object] = {"__name__": "nexus_wrapper_read_unit"}
    exec(compile(wrapper_source(), "exact-nexus-wrapper", "exec"), namespace)
    return cast(Callable[[Path, int], bytes], namespace["read"])


def test_copied_scratch_first_read_accepts_actual_atime_advance(tmp_path: Path) -> None:
    original = tmp_path / "readonly-input.py"
    raw = b"# synthetic canonical source copy\n"
    original.write_bytes(raw)
    work = tmp_path / "work" / "post"
    work.mkdir(mode=0o700, parents=True)
    copied = work / "canonical.py"
    shutil.copyfile(original, copied)
    now = time.time_ns()
    os.utime(copied, ns=(now - 172_800_000_000_000, now))
    first = copied.stat()  # No byte pre-read that would warm atime before the actual helper.
    try:
        assert embedded_reader()(copied, 65536) == raw
    finally:
        after = copied.stat()
        (tmp_path / "scratch-first-read-observation.json").write_text(
            json.dumps(
                {
                    "before_atime_ns": first.st_atime_ns,
                    "after_atime_ns": after.st_atime_ns,
                    "atime_advanced": after.st_atime_ns > first.st_atime_ns,
                    "before_mtime_ns": first.st_mtime_ns,
                    "after_mtime_ns": after.st_mtime_ns,
                    "before_ctime_ns": first.st_ctime_ns,
                    "after_ctime_ns": after.st_ctime_ns,
                    "before_inode": first.st_ino,
                    "after_inode": after.st_ino,
                    "expected_sha256": digest(raw),
                    "actual_sha256": digest(copied.read_bytes()),
                },
                sort_keys=True,
            )
        )
    assert after.st_ino == first.st_ino and after.st_mtime_ns == first.st_mtime_ns
    assert after.st_ctime_ns == first.st_ctime_ns and after.st_atime_ns >= first.st_atime_ns


@pytest.mark.parametrize(
    "failure", ["symlink", "hardlink", "oversize", "tamper", "replace", "mtime-ns"]
)
def test_embedded_reader_keeps_actual_tamper_and_object_denials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    path = tmp_path / "copied-source.py"
    path.write_bytes(b"original public source")
    limit = 1024
    read = embedded_reader()
    if failure == "symlink":
        link = tmp_path / "link.py"
        link.symlink_to(path)
        path = link
    elif failure == "hardlink":
        os.link(path, tmp_path / "second.py")
    elif failure == "oversize":
        limit = 3
    else:
        original_read = os.read
        inode = path.stat().st_ino

        def change(fd: int, length: int) -> bytes:
            raw = original_read(fd, length)
            if os.fstat(fd).st_ino == inode:
                if failure == "tamper":
                    path.write_bytes(b"modified public source")
                elif failure == "mtime-ns":
                    stamp = path.stat()
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
                else:
                    replacement = tmp_path / "replacement.py"
                    replacement.write_bytes(b"original public source")
                    replacement.replace(path)
            return raw

        monkeypatch.setattr(os, "read", change)
    with pytest.raises(ValueError):
        read(path, limit)
