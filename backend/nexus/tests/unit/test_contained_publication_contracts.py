"""Optional configuration and protected references cannot replace actual sidecar bytes."""

import hashlib
import json
from pathlib import Path

import pytest

from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.result_store import BuilderResultStore
from nexus.tests.contained_sidecar_fixture import contained_result, legacy_result, publisher


@pytest.mark.parametrize(
    "configuration",
    [
        {"execution_method_sha256": "a" * 64},
        {"containment_store": object()},
        {
            "containment_store": object(),
            "execution_method_sha256": CONTAINED_EXECUTION_METHOD_SHA256,
        },
    ],
)
def test_incomplete_or_nonconcrete_configuration_denies(configuration: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        publisher(**configuration)


def test_default_v1_summary_keeps_full_digest_and_omits_containment() -> None:
    value = legacy_result()
    raw = publisher().payload(value)
    # Captured from the original a2149a6 publisher with this fixed v1 metadata.
    assert (
        hashlib.sha256(raw).hexdigest()
        == "b869cd8599163221850debb91971ae3c72806ae326bf474ef3fe29490c639bc9"
    )
    payload = json.loads(raw)
    assert "containment" not in payload
    assert payload["result_sha256"] == BuilderResultStore.digest(value)


async def test_unconfigured_v2_cannot_generate_a_protected_summary(tmp_path: Path) -> None:
    value, _ = await contained_result(tmp_path)
    with pytest.raises(ValueError):
        publisher().payload(value)


async def test_wrong_closed_method_denies_even_with_an_actual_store(tmp_path: Path) -> None:
    _, store = await contained_result(tmp_path)
    with pytest.raises(ValueError):
        publisher(containment_store=store, execution_method_sha256="0" * 64)


async def test_v2_summary_contains_exact_full_ref_and_full_result_digest(tmp_path: Path) -> None:
    value, store = await contained_result(tmp_path)
    configured = publisher(
        containment_store=store, execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256
    )
    payload = json.loads(configured.payload(value))
    assert value.containment is not None
    assert payload["containment"] == value.containment.model_dump(mode="json")
    assert payload["result_sha256"] == BuilderResultStore.digest(value)


def test_engineering_publisher_forwards_only_keyword_configuration(tmp_path: Path) -> None:
    base = publisher()
    with pytest.raises(ValueError):
        EngineeringArtifactPublisher(
            base.factory,
            base.blobs,
            base.target,
            base.policy,
            tmp_path,
            containment_store=None,
            execution_method_sha256="0" * 64,
        )
