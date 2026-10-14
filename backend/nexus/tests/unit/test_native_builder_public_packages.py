"""Public cache rejects changed lock, unsupported transports/platforms and cleanup overflow."""

import base64
import hashlib
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped]  # Existing safe YAML loader has no local stub package.

from nexus.builder.public_download import DownloadBudget, PublicDownloader
from nexus.builder.public_package_download import download_packages
from nexus.builder.public_package_manifest import public_manifest


def lock() -> bytes:
    sri = "sha512-" + base64.b64encode(hashlib.sha512(b"exact public package").digest()).decode()
    return str(
        yaml.safe_dump(
            {
                "lockfileVersion": "9.0",
                "packages": {
                    "@scope/tool@1.2.3": {
                        "resolution": {"integrity": sri},
                        "os": ["linux"],
                        "cpu": ["x64"],
                    },
                    "other@1.0.0": {"resolution": {"integrity": sri}, "os": ["darwin"]},
                },
            }
        )
    ).encode()


@pytest.mark.parametrize("case", ["changed", "transport", "negative", "url"])
def test_lock_and_package_transport_boundaries(case: str) -> None:
    raw = lock()
    expected = hashlib.sha256(raw).hexdigest()
    if case == "changed":
        raw += b"\n# changed"
    elif case in {"transport", "negative"}:
        value = yaml.safe_load(raw)
        if case == "transport":
            value["packages"]["@scope/tool@1.2.3"]["resolution"]["tarball"] = (
                "https://private.invalid/secret"
            )
        else:
            value["packages"]["@scope/tool@1.2.3"]["os"] = ["!linux"]
        raw = yaml.safe_dump(value).encode()
        expected = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        manifest = public_manifest(raw, expected)
        value = manifest.packages[0].model_dump()
        value["url"] = "https://private.invalid/secret"
        type(manifest.packages[0]).model_validate(value)


async def test_frozen_selected_public_packages_verify_bytes_and_no_auth(tmp_path: Path) -> None:
    raw = lock()
    manifest = public_manifest(raw, hashlib.sha256(raw).hexdigest())
    assert (
        len(manifest.packages) == 1
        and manifest.packages[0].url == "https://registry.npmjs.org/@scope/tool/-/tool-1.2.3.tgz"
    )
    requests = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append((str(request.url), request.headers.get("Authorization")))
        return httpx.Response(200, content=b"exact public package")

    downloader = PublicDownloader(
        frozenset({"registry.npmjs.org"}),
        DownloadBudget(64, 2),
        transport=httpx.MockTransport(response),
    )
    try:
        receipt = await download_packages(tmp_path / "cache", manifest, downloader=downloader)
        assert (
            receipt.downloaded_bytes == 20
            and receipt.downloaded_packages == 1
            and requests == [(manifest.packages[0].url, None)]
        )
        assert (
            tmp_path / "cache" / manifest.packages[0].filename
        ).read_bytes() == b"exact public package"
    finally:
        await downloader.close()
