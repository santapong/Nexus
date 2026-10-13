"""Protected actual-byte references, immutable records and path/symlink denials."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from nexus.core.llm.company_adapter_contracts import CompanyModelResult, request_hash
from nexus.core.llm.company_pricing import TokenUsage
from nexus.harness.model_authorizer_contracts import InputEstimate
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.unit.test_company_model_authorizer import recipe
from nexus.tests.unit.test_company_provider_conformance import catalog, request


def envelope() -> ModelEvidence:
    call = request()
    return ModelEvidence(
        request=call,
        request_hash=request_hash(call),
        action_hash="a" * 64,
        model=catalog("openai").models[0],
        registry_revision=call.registry_revision,
        price_version=call.price_version,
        recipe=recipe(),
        input_estimate=InputEstimate(
            request_hash=request_hash(call),
            registry_id=call.registry_id,
            registry_revision=call.registry_revision,
            recipe_id=recipe().recipe_id,
            recipe_revision=recipe().revision,
            input_text_tokens=20,
            system_text_tokens=0,
            tool_schema_tokens=0,
            output_schema_tokens=50,
            sdk_overhead_tokens=256,
        ),
        result=CompanyModelResult(
            request_id=call.request_id,
            status="response",
            billing="known",
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            text="actual-result",
        ),
        source_event_at=datetime.now(UTC),
        checked_at=datetime.now(UTC),
        owner_id=UUID(int=8),
    )


async def test_actual_saved_bytes_hash_acl_and_immutable_result(tmp_path: Path) -> None:
    store, evidence = FileModelEvidenceStore(tmp_path), envelope()
    reference = await store.save(evidence)
    assert await store.load(reference) == evidence
    assert Path(reference.reference).stat().st_mode & 0o777 == 0o400
    assert set(reference.allowed_principals) == {evidence.request.actor_id, evidence.owner_id}
    assert await store.save(evidence) == reference
    changed = evidence.model_copy(
        update={"result": evidence.result.model_copy(update={"text": "replacement"})}
    )
    with pytest.raises(ValueError, match="immutable"):
        await store.save(changed)
    assert not list(Path(reference.reference).parent.glob("*.pending"))


@pytest.mark.parametrize("splice", ["hash", "company", "id", "acl", "outside"])
async def test_client_reference_cannot_assert_authoritative_bytes(
    tmp_path: Path, splice: str
) -> None:
    store = FileModelEvidenceStore(tmp_path)
    reference = await store.save(envelope())
    mutations: dict[str, dict[str, object]] = {
        "hash": {"sha256": "0" * 64},
        "company": {"company_id": UUID(int=999)},
        "id": {"artifact_id": UUID(int=999)},
        "acl": {"allowed_principals": ()},
        "outside": {"reference": "/tmp/client-model-result.json"},
    }
    changes = mutations[splice]
    with pytest.raises(ValueError):
        await store.load(reference.model_copy(update=changes))


def test_symlink_or_relative_storage_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        FileModelEvidenceStore(Path("caller-relative"))
    link = tmp_path / "symlink"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        FileModelEvidenceStore(link)
