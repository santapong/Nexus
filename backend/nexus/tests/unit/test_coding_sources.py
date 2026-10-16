"""Complete actual Brain rendering and fixed Git metadata; no Git/SQL/native calls."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from nexus.builder.contracts import BuilderArtifact, RepositoryPin
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.context import (
    AssembledContext,
    ContextAuthorityState,
    ContextLimits,
    ContextOmission,
)
from nexus.company.brain.context_render import render_context
from nexus.company.brain.git_source import GitSnapshotSpec
from nexus.company.brain.retrieval import MaterializedEvidence
from nexus.company.brain.sources import EvidenceRef, SourceHead
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import CodingBinding
from nexus.company.management.coding_sources import (
    CodingSourceRef,
    coding_selection,
    require_coding_archive,
    require_coding_sources,
)
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.tests.unit.test_company_brain_context_render import material
from nexus.tests.unit.test_company_brain_model_context_check import inputs
from nexus.tests.unit.test_company_planning_intent import prepared_inputs


def source_case(
    scope: BrainReadScope | None = None, authority: ContextAuthorityState | None = None
) -> tuple[CodingBinding, AssembledContext, tuple[CodingSourceRef, ...], BrainReadScope]:
    """Keep exact IDs, raw bytes and their actual renderer inputs adjacent (>50 lines)."""
    original_scope, original_context, lease = inputs()
    scope = scope or original_scope
    authority = authority or original_context.manifest.authority
    event = SourceTime(
        precision="instant", value=datetime.now(UTC).isoformat(), basis="supplied commit"
    )
    materials: list[MaterializedEvidence] = []
    refs = []
    for index, (path, text) in enumerate(
        (("src/app.py", "old\n"), ("tests/test_app.py", "fixed\n"))
    ):
        row = material(text, identifier=40 + index * 10)
        source = row.record.source.model_copy(
            update={"company_id": scope.company_id, "revision": "a" * 40}
        )
        artifact = row.record.artifact.model_copy(update={"company_id": scope.company_id})
        record = row.record.model_copy(
            update={
                "company_id": scope.company_id,
                "source": source,
                "artifact": artifact,
                "source_event": event,
            }
        )
        row = row.model_copy(
            update={
                "company_id": scope.company_id,
                "record": record,
                "external_key": path,
                "source_contributors": (source,),
                "contributors": tuple(
                    item.model_copy(update={"company_id": scope.company_id})
                    for item in row.contributors
                ),
            }
        )
        materials.append(row)
        refs.append(
            CodingSourceRef(
                file=BuilderArtifact(
                    path=path, sha256=artifact.sha256, byte_length=artifact.byte_length
                ),
                source=source,
                artifact=artifact,
                git=GitSnapshotSpec(
                    company_id=scope.company_id,
                    source_id=source.source_id,
                    source_symbol=row.source_symbol,
                    external_key=path,
                    path=path,
                    commit=source.revision,
                    git_blob="d" * 40,
                    sha256=artifact.sha256,
                    byte_length=artifact.byte_length,
                    source_event=event,
                ),
                evidence=(
                    EvidenceRef(company_id=scope.company_id, evidence_id=record.evidence_id),
                ),
            )
        )
    context = render_context(
        scope,
        authority,
        ContextLimits(policy_version="context-v1"),
        tuple(materials),
        tuple(
            SourceHead(
                company_id=scope.company_id,
                source_id=item.record.source.source_id,
                current=item.record.source,
                generation=1,
                observed_at=datetime.now(UTC),
                availability="available",
            )
            for item in materials
        ),
        question="Implement the cited change",
        purposes={item.record.evidence_id: "workspace" for item in materials},
    )
    goal = prepared_inputs()[2].goal.model_copy(update={"company_id": scope.company_id})
    assert (
        scope.task_id is not None and scope.task_trace_id is not None and scope.actor_id is not None
    )
    binding = CodingBinding(
        goal=goal,
        plan=PlanRevisionRef(
            company_id=scope.company_id,
            plan_id=UUID(int=22),
            plan_revision_id=UUID(int=23),
            revision=2,
            sha256="b" * 64,
        ),
        task_id=scope.task_id,
        trace_id=scope.task_trace_id,
        actor_id=scope.actor_id,
        workspace_id=scope.workspace_id,
        run_id=lease.run_id,
        source=RepositoryPin(
            repository_symbol="nexus", commit="a" * 40, tree="b" * 40, archive_sha256="c" * 64
        ),
        source_files=tuple(row.file for row in refs),
        allowed_write_paths=("src/app.py",),
        context_manifest_sha256=canonical_sha256(context.manifest),
    )
    return binding, context, tuple(refs), scope


def test_complete_source_bytes_are_real_workspace_data_not_schema_only() -> None:
    binding, context, sources, _ = source_case()
    assert coding_selection(sources).workspace_files == tuple(
        ref for row in sources for ref in row.evidence
    )
    assert require_coding_sources(binding, context, sources) == {
        "src/app.py": b"old\n",
        "tests/test_app.py": b"fixed\n",
    }
    assert "old\\n" in context.input_text and "fixed\\n" in context.input_text
    assert all(row.purpose == "workspace" for row in context.manifest.inclusions)


@pytest.mark.parametrize(
    "fault", ["commit", "path", "body-hash", "source", "artifact", "duplicate"]
)
def test_exact_git_source_and_artifact_file_mapping_cannot_be_crossed(fault: str) -> None:
    binding, context, sources, _ = source_case()
    first = sources[0]
    if fault == "duplicate":
        sources = (*sources, first)
    else:
        field, changed = {
            "commit": ("git", first.git.model_copy(update={"commit": "f" * 40})),
            "path": ("git", first.git.model_copy(update={"path": "other.py"})),
            "body-hash": ("file", first.file.model_copy(update={"sha256": "f" * 64})),
            "source": (
                "source",
                first.source.model_copy(update={"source_revision_id": UUID(int=999)}),
            ),
            "artifact": (
                "artifact",
                first.artifact.model_copy(update={"artifact_revision_id": UUID(int=999)}),
            ),
        }[fault]
        sources = (first.model_copy(update={field: changed}), *sources[1:])
    with pytest.raises(ValueError):
        require_coding_sources(binding, context, sources)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "purpose",
        "excerpt",
        "source-head",
        "body",
        "append",
        "omitted",
        "duplicate-head",
        "duplicate-inclusion",
        "declared-omission",
    ],
)
def test_required_source_must_be_complete_current_included_and_actually_rendered(
    fault: str,
) -> None:
    binding, context, sources, _ = source_case()
    manifest = context.manifest
    if fault == "missing":
        manifest = manifest.model_copy(update={"inclusions": manifest.inclusions[1:]})
    elif fault == "duplicate-head":
        manifest = manifest.model_copy(
            update={"source_heads": (*manifest.source_heads, manifest.source_heads[0])}
        )
    elif fault == "duplicate-inclusion":
        manifest = manifest.model_copy(
            update={"inclusions": (*manifest.inclusions, manifest.inclusions[0])}
        )
    elif fault == "declared-omission":
        manifest = manifest.model_copy(
            update={
                "omissions": (
                    ContextOmission(
                        company_id=manifest.company_id,
                        evidence=sources[0].evidence[0],
                        reason="span_limit",
                    ),
                )
            }
        )
    elif fault == "source-head":
        old = manifest.source_heads[0]
        manifest = manifest.model_copy(
            update={
                "source_heads": (
                    old.model_copy(update={"availability": "unavailable"}),
                    *manifest.source_heads[1:],
                )
            }
        )
    elif fault in {"purpose", "excerpt"}:
        first = manifest.inclusions[0].model_copy(
            update={"purpose": "attachment"} if fault == "purpose" else {"disposition": "excerpted"}
        )
        manifest = manifest.model_copy(update={"inclusions": (first, *manifest.inclusions[1:])})
    elif fault == "append":
        context = context.model_copy(update={"input_text": context.input_text + "APPENDED_CODE"})
    elif fault == "body":
        value = json.loads(context.input_text)
        value["untrusted_source_data"][0]["text"] = "bad\n"
        text = json.dumps(value, sort_keys=True, separators=(",", ":"))
        raw = (context.system_text + "\n" + text).encode()
        manifest = manifest.model_copy(
            update={"prompt_bytes": len(raw), "prompt_sha256": hashlib.sha256(raw).hexdigest()}
        )
        context = context.model_copy(update={"input_text": text})
    else:
        sources = (
            sources[0].model_copy(
                update={
                    "evidence": (
                        sources[0].evidence[0].model_copy(update={"evidence_id": UUID(int=999)}),
                    )
                }
            ),
            *sources[1:],
        )
    context = context.model_copy(update={"manifest": manifest})
    binding = binding.model_copy(update={"context_manifest_sha256": canonical_sha256(manifest)})
    with pytest.raises(ValueError):
        require_coding_sources(binding, context, sources)


def archive_for(originals: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path, raw in originals.items():
            info = tarfile.TarInfo(path)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def test_archive_byte_join_is_pure_not_commit_tree_attestation() -> None:
    binding, context, sources, _ = source_case()
    originals = dict(require_coding_sources(binding, context, sources))
    raw = archive_for(originals)
    binding = binding.model_copy(
        update={
            "source": binding.source.model_copy(
                update={"archive_sha256": hashlib.sha256(raw).hexdigest()}
            )
        }
    )
    require_coding_archive(raw, binding, originals)
    for bad in [raw + b"x", archive_for(originals | {"src/app.py": b"bad\n"})]:
        with pytest.raises(ValueError):
            require_coding_archive(bad, binding, originals)
    with pytest.raises(ValueError):
        require_coding_archive(cast(bytes, bytearray(raw)), binding, originals)
