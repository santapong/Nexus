"""Fresh-interpreter pure replay from the same original bytes; no native worker or authority."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nexus.company.cycle_artifacts.common import CycleKind, digest
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case

PROGRAM = """
import json,sys
sys.path.insert(0,sys.argv[1])
from uuid import UUID
from nexus.company.cycle_artifacts.contracts import CycleArtifactBasis
from nexus.company.cycle_artifacts.production import prepare_presentation,prepare_support
from nexus.company.cycle_artifacts.common import digest
basis=CycleArtifactBasis.model_validate_json(sys.stdin.buffer.read())
prepare=prepare_presentation if basis.artifact_kind=='presentation' else prepare_support
prepared=prepare(basis,UUID(sys.argv[2]))
print(json.dumps({'json':digest(prepared.typed_json),'human':digest(prepared.human_export),
'manifest':prepared.output_manifest_sha256,'registration':basis.author_registration_sha256}))
"""


@pytest.mark.parametrize("kind", ["presentation", "support"])
def test_actual_prepare_replays_same_original_basis_across_fresh_hash_seeds(
    kind: CycleKind,
) -> None:
    case = deliverable_case(kind)
    backend = Path(__file__).parents[3]
    expected = {
        "json": digest(case.prepared.typed_json),
        "human": digest(case.prepared.human_export),
        "manifest": case.prepared.output_manifest_sha256,
        "registration": case.basis.author_registration_sha256,
    }
    for seed in ("0", "1", "2"):
        result = subprocess.run(
            [sys.executable, "-B", "-c", PROGRAM, str(backend), str(case.action_id)],
            input=case.basis.model_dump_json().encode(),
            capture_output=True,
            check=True,
            timeout=15,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONHASHSEED": seed,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        assert json.loads(result.stdout) == expected
