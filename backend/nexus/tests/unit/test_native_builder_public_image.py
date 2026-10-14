"""Exact public image descriptors reject unsupported blobs before any offline load."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nexus.builder.local_toolchain import load_argv, require_stage_directory
from nexus.builder.public_download import DownloadBudget, PublicDownloader
from nexus.builder.public_image import ImageManifest, _download_blobs, digest_integrity


def manifest(size: int) -> ImageManifest:
    return ImageManifest.model_validate(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:" + "a" * 64,
                "size": size,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": "sha256:" + "b" * 64,
                    "size": size,
                }
            ],
        }
    )


async def test_declared_complete_image_budget_denies_before_blob_fetch(tmp_path: Path) -> None:
    requests: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=b"unused")

    downloader = PublicDownloader(
        frozenset({"registry-1.docker.io"}),
        DownloadBudget(10, 1),
        transport=httpx.MockTransport(response),
    )
    try:
        with pytest.raises(ValueError, match="complete stage budget"):
            await _download_blobs(tmp_path, manifest(6), downloader, "Bearer public-anonymous")
        assert requests == [] and tuple(tmp_path.iterdir()) == ()
    finally:
        await downloader.close()


def test_exact_local_load_has_no_registry_or_credential_inputs(tmp_path: Path) -> None:
    assert load_argv(tmp_path) == (
        "/usr/bin/podman",
        "--remote=false",
        "load",
        "--quiet",
        "--input",
        str(tmp_path / "node-amd64.oci.tar"),
    )
    with pytest.raises(ValueError):
        digest_integrity("sha256:../../private")
    value = json.loads(manifest(1).model_dump_json(by_alias=True))
    value["config"]["digest"] = "sha256:../../private"
    with pytest.raises(ValidationError):
        ImageManifest.model_validate(value)


def test_stage_rejects_mode_not_proven_private(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        require_stage_directory(tmp_path)


def test_saved_descriptor_roundtrip_preserves_oci_aliases() -> None:
    original = manifest(16)
    assert ImageManifest.model_validate_json(original.model_dump_json(by_alias=True)) == original
    assert (
        type(original.config).model_validate_json(original.config.model_dump_json())
        == original.config
    )
