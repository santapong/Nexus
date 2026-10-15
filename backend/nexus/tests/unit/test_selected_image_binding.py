"""Exact retained image tuple with all remaining selected configuration supplied."""

from typing import cast

import pytest

from nexus.builder.contracts import Architecture
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.selected_image_binding import require_selected_image_binding
from nexus.builder.selected_strategy_contracts import SelectedBuilderTemplate
from nexus.tests.unit.selected_strategy_pins_fixture import selected_case

REFERENCE = (
    "localhost/nexus-node-22.23.3-bookworm@"
    "sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
)
MANIFEST = "c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
IMAGE_ID = "8f3dff4193637723b9f3f4ded64cccf28c7b35dc1c96d3320b1f5a64ff41e76d"


def configured(
    reference: str = REFERENCE, image_id: str = IMAGE_ID, architecture: str = "amd64"
) -> SelectedBuilderTemplate:
    case = selected_case()
    pins = NodeRuntimeInputs.model_validate(
        case.template.runtime_inputs.model_dump()
        | {"image_id": image_id, "architecture": architecture}
    )
    policy = BuilderToolPolicy.model_validate(
        case.policy.model_dump() | {"image": reference, "runtime_inputs": pins}
    )
    return SelectedBuilderTemplate.model_validate(
        case.template.model_dump()
        | {"policy": policy, "runtime_inputs": pins, "architecture": architecture}
    )


def test_retained_distinct_manifest_config_tuple_is_valid_description() -> None:
    value = configured()
    assert value.policy.image == REFERENCE
    assert value.runtime_inputs.image_id == IMAGE_ID != MANIFEST


def test_unrecognized_equal_pair_never_qualifies_selected_template() -> None:
    equalized = REFERENCE.split("@sha256:")[0] + "@sha256:" + IMAGE_ID
    with pytest.raises(ValueError):
        configured(equalized)


@pytest.mark.parametrize(
    "reference,image_id",
    [
        (REFERENCE, MANIFEST),
        (REFERENCE, "f" * 64),
        (REFERENCE.replace(MANIFEST, IMAGE_ID), MANIFEST),
        (REFERENCE.replace(MANIFEST, "f" * 64), "f" * 64),
        (REFERENCE.replace("localhost/", "docker.io/library/"), IMAGE_ID),
        (REFERENCE.replace("localhost/", "localhost:5000/"), IMAGE_ID),
        (REFERENCE.replace("nexus-node-22.23.3-bookworm", "other"), IMAGE_ID),
        (REFERENCE + "x", IMAGE_ID),
        (REFERENCE.split("@")[0] + ":latest", IMAGE_ID),
    ],
)
def test_reference_manifest_config_alias_or_crosspair_denies(reference: str, image_id: str) -> None:
    with pytest.raises(ValueError):
        configured(reference, image_id)
    with pytest.raises(ValueError, match="nominated image binding"):
        require_selected_image_binding("amd64", reference, image_id)


@pytest.mark.parametrize("architecture", ["arm64", "AMD64", "amd64 ", "ppc64le", ""])
def test_unqualified_or_unrecognized_architecture_denies(architecture: str) -> None:
    with pytest.raises(ValueError):
        configured(architecture=architecture)
    with pytest.raises(ValueError, match="nominated image binding"):
        require_selected_image_binding(cast(Architecture, architecture), REFERENCE, IMAGE_ID)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("value", [True, None, 1, ["amd64"]])
def test_closed_tuple_check_never_coerces_runtime_inputs(index: int, value: object) -> None:
    inputs: list[object] = ["amd64", REFERENCE, IMAGE_ID]
    inputs[index] = value
    with pytest.raises(ValueError, match="nominated image binding"):
        require_selected_image_binding(
            cast(Architecture, inputs[0]), cast(str, inputs[1]), cast(str, inputs[2])
        )


def test_agreeing_copied_fields_cannot_bypass_tuple_revalidation() -> None:
    value = configured()
    pins = value.runtime_inputs.model_copy(update={"image_id": MANIFEST})
    policy = value.policy.model_copy(update={"runtime_inputs": pins})
    copied = value.model_copy(update={"runtime_inputs": pins, "policy": policy})
    with pytest.raises(ValueError, match="nominated image binding"):
        SelectedBuilderTemplate.model_validate(copied.model_dump())


@pytest.mark.parametrize("verifier", [False, True])
def test_selected_fixture_uses_real_distinct_pair_with_other_supplied_data(verifier: bool) -> None:
    case = selected_case(verifier)
    assert case.policy.image == REFERENCE
    assert case.template.runtime_inputs.image_id == IMAGE_ID != MANIFEST
    case.check()  # Consistency only; no actual READ/owner/lease/intent/permit is produced.
