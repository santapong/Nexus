"""Complete private bodies/results outside the caller mutex, under one fixed aggregate cap."""

import asyncio
import json
from typing import TYPE_CHECKING

from nexus.builder.engineering_bodies import (
    BODY_READ_SECONDS,
    CompleteEngineeringBody,
    load_complete_engineering_body,
)
from nexus.builder.engineering_checker import check_engineering_change
from nexus.builder.engineering_contracts import EngineeringCheckInput, EngineeringSourceWitness
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.verification_support import (
    require_result_containment,
    require_summary_containment,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.cycle_artifacts.common import bounded_json
from nexus.company.cycle_artifacts.engineering import (
    EngineeringEvidence,
    compare_engineering_evidence,
)
from nexus.company.cycle_artifacts.native_contracts import (
    CycleEngineeringMaterial,
    EngineeringPrerequisiteFacts,
)
from nexus.company.management.acceptance_errors import require_acceptance

if TYPE_CHECKING:
    from nexus.company.cycle_artifacts.engineering_prerequisite_reader import CycleEngineeringReader


async def _result(
    reader: "CycleEngineeringReader",
    spec: BuilderExecutionSpec,
    body: CompleteEngineeringBody,
) -> tuple[BuilderRunResult, EngineeringSourceWitness]:
    body.require_integrity()
    result = await reader.results.load(spec)
    require_acceptance(result is not None and result.spec == spec)
    assert result is not None
    witness = require_result_body(result, body)
    await require_result_containment(
        result, reader.containment_store, reader.execution_method_sha256
    )
    return result, witness


def require_result_body(
    result: BuilderRunResult,
    body: CompleteEngineeringBody,
) -> EngineeringSourceWitness:
    body.require_integrity()
    value = bounded_json(body.raw)
    require_acceptance(isinstance(value, dict))
    assert isinstance(value, dict)
    require_acceptance(
        (
            value.get("result_sha256"),
            value.get("spec"),
            value.get("proposal_sha256"),
            value.get("intent_fence"),
        )
        == (
            BuilderResultStore.digest(result),
            result.spec.model_dump(mode="json"),
            result.proposal_sha256,
            result.intent_fence,
        )
    )
    require_summary_containment(result, body.raw.decode())
    witness = EngineeringSourceWitness.model_validate_json(
        json.dumps(value.get("engineering_source_witness"), allow_nan=False)
    )
    return witness


async def load_engineering_material(
    reader: "CycleEngineeringReader",
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    facts: EngineeringPrerequisiteFacts,
) -> CycleEngineeringMaterial:
    # Keep the bounded collection, private sidecars and exact recomputation in one >50-line phase.
    composition = reader.composition()
    metadata = facts.metadata
    patch = metadata.author_spec.protected_patch
    require_acceptance(patch is not None and patch == metadata.verifier_spec.protected_patch)
    assert patch is not None
    references = (
        metadata.author_output,
        metadata.verifier_output,
        facts.check,
        patch,
        reader.source.metadata,
    )
    bodies = []
    async with asyncio.timeout(BODY_READ_SECONDS):
        for reference in references:
            bodies.append(
                await load_complete_engineering_body(
                    reader.artifacts, reader.freshness, scope, identity, reference
                )
            )
            reader.require_composition(composition)
        author, first = await _result(reader, metadata.author_spec, bodies[0])
        reader.require_composition(composition)
        verifier, second = await _result(reader, metadata.verifier_spec, bodies[1])
        reader.require_composition(composition)
        require_acceptance(
            bounded_json(bodies[4].raw, maximum=16384)
            == {"source": author.spec.job.source.model_dump(mode="json")}
        )
        declaration = reader.declarations.get(metadata.author_registration.work.goal_id)
        require_acceptance(
            declaration is not None and declaration.procedure_id == metadata.procedure_id
        )
        assert declaration is not None
        command = EngineeringCheckInput(
            company_id=scope.company_id,
            target=facts.acceptance.target,
            declaration=declaration,
            author=author,
            verifier=verifier,
            author_receipt=metadata.author_receipt,
            verifier_receipt=metadata.verifier_receipt,
            author_registration=metadata.author_registration,
            verifier_registration=metadata.verifier_registration,
            author_output=metadata.author_output,
            verifier_output=metadata.verifier_output,
            author_witness=first,
            verifier_witness=second,
        )
        checked = check_engineering_change(command)
        require_acceptance(
            checked.verdict == "pass"
            and reader.proof.reference(checked) == facts.check
            and checked.model_dump_json().encode() == bodies[2].raw
        )
        evidence = EngineeringEvidence(
            company_id=scope.company_id,
            acceptance=facts.acceptance,
            procedure_id=metadata.procedure_id,
            author_registration=metadata.author_registration,
            verifier_registration=metadata.verifier_registration,
            author_receipt=metadata.author_receipt,
            verifier_receipt=metadata.verifier_receipt,
            author_summary=metadata.author_output,
            verifier_summary=metadata.verifier_output,
            check=facts.check,
            author_utf8=bodies[0].raw,
            verifier_utf8=bodies[1].raw,
            check_utf8=bodies[2].raw,
        )
        material = CycleEngineeringMaterial(
            facts, command, compare_engineering_evidence(evidence), tuple(bodies)
        )
        require_engineering_material(reader, material)
        return material


def require_engineering_material(
    reader: "CycleEngineeringReader", material: CycleEngineeringMaterial
) -> None:
    """A supplied process-local value still has to recompute every protected byte binding."""
    facts, command, bodies = material.facts, material.command, material.bodies
    metadata = facts.metadata
    require_acceptance(len(bodies) == 5 and metadata.author_spec.protected_patch is not None)
    refs = (
        metadata.author_output,
        metadata.verifier_output,
        facts.check,
        metadata.author_spec.protected_patch,
        reader.source.metadata,
    )
    require_acceptance(tuple(body.first.artifact for body in bodies) == refs)
    for body in bodies:
        body.require_integrity()
    first = require_result_body(command.author, bodies[0])
    second = require_result_body(command.verifier, bodies[1])
    declaration = reader.declarations.get(metadata.author_registration.work.goal_id)
    require_acceptance(declaration is not None)
    assert declaration is not None
    expected = EngineeringCheckInput(
        company_id=facts.acceptance.company_id,
        target=facts.acceptance.target,
        declaration=declaration,
        author=command.author,
        verifier=command.verifier,
        author_receipt=metadata.author_receipt,
        verifier_receipt=metadata.verifier_receipt,
        author_registration=metadata.author_registration,
        verifier_registration=metadata.verifier_registration,
        author_output=metadata.author_output,
        verifier_output=metadata.verifier_output,
        author_witness=first,
        verifier_witness=second,
    )
    require_acceptance(
        command == expected
        and command.author.spec == metadata.author_spec
        and command.verifier.spec == metadata.verifier_spec
        and bounded_json(bodies[4].raw, maximum=16384)
        == {"source": command.author.spec.job.source.model_dump(mode="json")}
    )
    checked = check_engineering_change(expected)
    require_acceptance(
        checked.verdict == "pass"
        and reader.proof.reference(checked) == facts.check
        and checked.model_dump_json().encode() == bodies[2].raw
    )
    evidence = EngineeringEvidence(
        company_id=facts.acceptance.company_id,
        acceptance=facts.acceptance,
        procedure_id=metadata.procedure_id,
        author_registration=metadata.author_registration,
        verifier_registration=metadata.verifier_registration,
        author_receipt=metadata.author_receipt,
        verifier_receipt=metadata.verifier_receipt,
        author_summary=metadata.author_output,
        verifier_summary=metadata.verifier_output,
        check=facts.check,
        author_utf8=bodies[0].raw,
        verifier_utf8=bodies[1].raw,
        check_utf8=bodies[2].raw,
    )
    require_acceptance(compare_engineering_evidence(evidence) == material.basis)
