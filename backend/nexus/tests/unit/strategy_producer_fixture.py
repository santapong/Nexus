"""Synthetic explicit server policy; no reader, protected bundle or native authority."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy.contracts import StrategyCheckSnapshot
from nexus.company.strategy.producer import prepare_strategy_artifact, strategy_input_bundle_bytes
from nexus.company.strategy.producer_contracts import (
    StrategyFindingRule,
    StrategyOriginalInputBundle,
    StrategyOriginalInputBundleRef,
    StrategyProductionPolicy,
)
from nexus.execution.runtime_support import registration_digest
from nexus.tests.unit.strategy_brief_fixture import strategy_case


def producer_case() -> tuple[StrategyCheckSnapshot, StrategyProductionPolicy]:
    case = strategy_case()
    snapshot = case.command.snapshot
    assert snapshot is not None
    policy = StrategyProductionPolicy(
        company_id=snapshot.company_id,
        scope_sha256=canonical_sha256(snapshot.scope),
        candidate_policy_sha256=canonical_sha256(snapshot.policy),
        data_classification="internal",
        finding_rules=tuple(
            StrategyFindingRule(
                finding_id=row.finding_id, evidence_id=row.evidence_id, hypothesis=row.hypothesis
            )
            for row in case.brief.findings
        ),
        candidates=case.brief.candidates,
        recommendation=case.brief.recommendation,
        unknowns=case.brief.unknowns,
        decision_request=case.brief.decision_request,
    )
    return snapshot, policy


def bundle_ref(
    snapshot: StrategyCheckSnapshot, policy: StrategyProductionPolicy
) -> StrategyOriginalInputBundleRef:
    raw = strategy_input_bundle_bytes(snapshot, policy)
    return StrategyOriginalInputBundleRef(
        company_id=snapshot.company_id,
        artifact=ArtifactRevisionRef(
            company_id=snapshot.company_id,
            artifact_id=UUID(int=100),
            artifact_revision_id=UUID(int=101),
            revision="synthetic-bundle-v1",
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        ),
        resource=ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=102)),
        input_snapshot_sha256=canonical_sha256(snapshot),
        producer_policy_sha256=canonical_sha256(policy),
    )


def large_strategy_output_case() -> tuple[StrategyCheckSnapshot, StrategyProductionPolicy]:
    """One exact source/manifest layout that exceeds the supported Brief UTF8 byte bound."""
    # This >50-line fixture keeps source/manifest/hash identity exact at the byte boundary.
    snapshot, policy = producer_case()
    template = snapshot.sources[0]
    raw = ("x" * 16384).encode()
    sources, artifacts, contributors, evidence_refs, rules = [], [], [], [], []
    for index in range(16):
        source_ref = template.evidence.source.model_copy(
            update={
                "source_id": UUID(int=3000 + index),
                "source_revision_id": UUID(int=3100 + index),
            }
        )
        artifact = template.evidence.artifact.model_copy(
            update={
                "artifact_id": UUID(int=3200 + index),
                "artifact_revision_id": UUID(int=3300 + index),
                "byte_length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        span = template.evidence.raw_span.model_copy(update={"start_byte": 0, "end_byte": len(raw)})
        evidence = template.evidence.model_copy(
            update={
                "evidence_id": UUID(int=3400 + index),
                "source": source_ref,
                "artifact": artifact,
                "raw_span": span,
                "span_sha256": artifact.sha256,
            }
        )
        sources.append(
            template.model_copy(
                update={
                    "evidence": evidence,
                    "raw_text": raw.decode(),
                    "head": template.head.model_copy(
                        update={"source_id": source_ref.source_id, "current": source_ref}
                    ),
                }
            )
        )
        artifacts.append(artifact)
        contributors.append(source_ref)
        evidence_refs.append(
            snapshot.inputs.evidence[0].model_copy(update={"evidence_id": evidence.evidence_id})
        )
        rules.append(
            policy.finding_rules[0].model_copy(
                update={
                    "finding_id": "quantity-parse" if index == 0 else f"extra-{index}",
                    "evidence_id": evidence.evidence_id,
                    "hypothesis": None,
                }
            )
        )
    inputs = snapshot.inputs.model_copy(
        update={
            "artifacts": (*snapshot.inputs.artifacts, *artifacts),
            "contributors": (*snapshot.inputs.contributors, *contributors),
            "evidence": (*snapshot.inputs.evidence, *evidence_refs),
        }
    )
    snapshot = snapshot.model_copy(
        update={"sources": (*snapshot.sources, *sources), "inputs": inputs}
    )
    policy = policy.model_copy(update={"finding_rules": tuple(rules)})
    return snapshot, policy


def _bundle_probe(root: Path, phase: str) -> None:
    # This >50-line test probe retains one exact wire/ref across genuinely fresh interpreters.
    if phase == "write":
        snapshot, policy = producer_case()
        source = snapshot.sources[0]
        source_policy = source.source_policy.model_copy(
            update={
                "allowed_external_keys": frozenset({"csv-source", "readme-source", "method-source"})
            }
        )
        snapshot = snapshot.model_copy(
            update={"sources": (source.model_copy(update={"source_policy": source_policy}),)}
        )
        raw = strategy_input_bundle_bytes(snapshot, policy)
        reference = StrategyOriginalInputBundleRef(
            company_id=snapshot.company_id,
            artifact=ArtifactRevisionRef(
                company_id=snapshot.company_id,
                artifact_id=UUID(int=900),
                artifact_revision_id=UUID(int=901),
                revision="probe-v2",
                sha256=hashlib.sha256(raw).hexdigest(),
                byte_length=len(raw),
            ),
            resource=ResourceRef(company_id=snapshot.company_id, resource_id=UUID(int=902)),
            input_snapshot_sha256=canonical_sha256(snapshot),
            producer_policy_sha256=canonical_sha256(policy),
        )
        (root / "wire.json").write_bytes(raw)
        (root / "ref.json").write_text(reference.model_dump_json())
    else:
        bundle = StrategyOriginalInputBundle.model_validate_json((root / "wire.json").read_bytes())
        snapshot, policy = bundle.snapshot, bundle.policy
        reference = StrategyOriginalInputBundleRef.model_validate_json(
            (root / "ref.json").read_text()
        )
        raw = strategy_input_bundle_bytes(snapshot, policy)
    compiled = prepare_strategy_artifact(snapshot, policy, original_bundle=reference)
    sys.stdout.write(
        json.dumps(
            {
                "bundle_sha256": hashlib.sha256(raw).hexdigest(),
                "registration_sha256": registration_digest(snapshot.author_registration),
                "output_sha256": compiled.prepared.output_sha256,
            }
        )
    )


def bundle_replay_process(root: Path, phase: str, seed: str) -> subprocess.CompletedProcess[str]:
    """Fresh bounded interpreter proves actual hash-seed-independent bundle/prepare behavior."""
    script = (
        "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
        "from nexus.tests.unit.strategy_producer_fixture import _bundle_probe;"
        "_bundle_probe(Path(sys.argv[2]),sys.argv[3])"
    )
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(Path(__file__).resolve().parents[3]),
            str(root),
            phase,
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": seed,
            "PYTHONDONTWRITEBYTECODE": "1",
            "COMPANY_TEST_DATABASE_URL": "",
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
