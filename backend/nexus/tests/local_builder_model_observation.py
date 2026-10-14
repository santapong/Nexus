"""Assemble observed receipt and dated eligibility; original catalog stays intact."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.core.llm.company_registry import EvaluationEvidence, ModelHealth
from nexus.tests.local_stockflow_packet import ROOT, write_private
from nexus.tests.stockflow_packet_contracts import PreparedState

EVIDENCE = Path("/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder")


async def build(
    destination: Path = ROOT,
    fixtures_path: Path = EVIDENCE / "model-requalification-existing-fixtures.log",
    expected_cases: int = 77,
) -> None:
    state = PreparedState.model_validate_json(
        await asyncio.to_thread((ROOT / "native-state.json").read_bytes)
    )
    sdk_raw = await asyncio.to_thread((destination / "model-requalification-sdk.json").read_bytes)
    sdk = json.loads(sdk_raw)
    fixtures_raw = await asyncio.to_thread(fixtures_path.read_bytes)
    observed_fixtures = re.search(rb"(\d+) passed in ([\d.]+)s", fixtures_raw)
    if (
        not sdk["criteria_passed"] == sdk["criteria_total"]
        or sdk["requests"] != 1
        or observed_fixtures is None
        or int(observed_fixtures[1]) != expected_cases
    ):
        raise ValueError("Actual complete mechanical fixture receipt unavailable")
    original = state.catalog.models.models[0]
    if sdk["registration_sha256"] != canonical_sha256(original):
        raise ValueError("Actual SDK receipt differs from exact original model identity")
    receipt = {
        **sdk,
        "sdk_receipt_sha256": hashlib.sha256(sdk_raw).hexdigest(),
        "existing_fixture_receipt": {
            "cases": int(observed_fixtures[1]),
            "seconds": float(observed_fixtures[2]),
            "log_sha256": hashlib.sha256(fixtures_raw).hexdigest(),
            "scope": "new registry/evidence/eligibility/profile mechanical fixture run",
        },
        "unsupported": [
            "native_structured_output",
            "live_provider_or_model_quality",
            "code_reasoning_quality",
        ],
        "prior_structured_failure_sha256": hashlib.sha256(
            (EVIDENCE / "model-requalification-sdk-first.log").read_bytes()
        ).hexdigest(),
    }
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode()
    await asyncio.to_thread(write_private, destination / "model-requalification-receipt.json", raw)
    sha = hashlib.sha256(raw).hexdigest()
    checked = datetime.fromisoformat(sdk["observed_at"])
    observation = ModelEligibilityObservation(
        company_id=state.spec.job.company_id,
        observation_id=uuid4(),
        registry_revision=state.catalog.models.revision,
        registry_id=original.registry_id,
        registration_sha256=canonical_sha256(original),
        receipt_sha256=sha,
        health=ModelHealth(
            status="healthy", checked_at=checked, expires_at=checked + timedelta(hours=1)
        ),
        evaluations=(
            EvaluationEvidence(
                profile="routine",
                suite_version="offline-mechanical-v1",
                artifact_reference="sha256:" + sha,
                score=Decimal("1"),
                conformance_passed=True,
                evaluated_at=checked,
                expires_at=checked + timedelta(hours=1),
            ),
        ),
    )
    catalog = PlanAdmissionCatalog.model_validate_json(
        state.catalog.model_copy(
            update={
                "model_observations": (observation,),
            }
        ).model_dump_json()
    )
    if catalog.models != state.catalog.models:
        raise AssertionError("Observation changed immutable model/price identity")
    # This validates profile admission only. It creates no work/permit/spend authority.
    await asyncio.to_thread(
        write_private,
        destination / "model-observation.json",
        observation.model_dump_json(indent=2).encode(),
    )
    await asyncio.to_thread(
        write_private,
        destination / "refreshed-catalog.json",
        catalog.model_dump_json(indent=2).encode(),
    )


if __name__ == "__main__":
    asyncio.run(build())
