"""Closed nominated image correspondence; current native qualification remains mandatory."""

from typing import Final

from nexus.builder.contracts import Architecture

# Retained public-image manifest/config, successful load and exact-reference/ID preflight.
# A manifest reference and its config image ID are distinct cryptographic identities.
NOMINATED_NODE_MANIFEST_SHA256: Final = (
    "c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d"
)
NOMINATED_NODE_IMAGE_ID: Final = "8f3dff4193637723b9f3f4ded64cccf28c7b35dc1c96d3320b1f5a64ff41e76d"
NOMINATED_NODE_IMAGE_REFERENCE: Final = (
    "localhost/nexus-node-22.23.3-bookworm@sha256:" + NOMINATED_NODE_MANIFEST_SHA256
)
_NOMINATED_BINDING: Final = (
    "amd64",
    NOMINATED_NODE_IMAGE_REFERENCE,
    NOMINATED_NODE_MANIFEST_SHA256,
    NOMINATED_NODE_IMAGE_ID,
)


def require_selected_image_binding(
    architecture: Architecture, reference: str, image_id: str
) -> None:
    """Check exact server configuration data; this never observes or authorizes an image."""
    if type(architecture) is not str or type(reference) is not str or type(image_id) is not str:
        raise ValueError("Selected nominated image binding differs")
    manifest = reference.partition("@sha256:")[2]
    if (architecture, reference, manifest, image_id) != _NOMINATED_BINDING:
        raise ValueError("Selected nominated image binding differs")
