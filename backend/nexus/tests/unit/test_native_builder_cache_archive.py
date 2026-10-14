"""Public CAS archive paths, links, counts and expanded sizes fail before cache creation."""

import io
import tarfile
from pathlib import Path

import pytest

from nexus.builder.cache_archive import extract_cache


@pytest.mark.parametrize("kind", ["link", "path", "size"])
def test_cache_archive_unsafe_entry_denies_before_destination(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "cache.tar"
    with tarfile.open(path, "w") as archive:
        row = tarfile.TarInfo("../outside" if kind == "path" else "store/file")
        if kind == "link":
            row.type = tarfile.SYMTYPE
            row.linkname = "/home/private"
        elif kind == "size":
            row.size = 2_147_483_649
        else:
            row.size = 1
        # Deliberately oversized metadata is read before its missing payload.
        if kind == "size":
            archive.fileobj.write(row.tobuf())
        else:
            archive.addfile(row, None if kind == "link" else io.BytesIO(b"x"))
    root = tmp_path / "qualified"
    with pytest.raises(ValueError):
        extract_cache(path, root)
    assert not root.exists() and not (tmp_path / "outside").exists()


def test_cache_archive_ordinary_bytes_are_private_readonly_files(tmp_path: Path) -> None:
    path = tmp_path / "cache.tar"
    with tarfile.open(path, "w") as archive:
        row = tarfile.TarInfo("store/v3/files/01/content")
        row.size = 6
        archive.addfile(row, io.BytesIO(b"public"))
    root = tmp_path / "qualified"
    extract_cache(path, root)
    file = root / "store" / "v3" / "files" / "01" / "content"
    assert file.read_bytes() == b"public" and file.stat().st_mode & 0o777 == 0o400


def test_gnu_cafs_long_filename_and_executable_import_preserve_safe_ordinary_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "long.tar"
    name = "store/v3/files/01/" + "a" * 126 + "-index.json"
    with tarfile.open(path, "w", format=tarfile.GNU_FORMAT) as archive:
        row = tarfile.TarInfo(name)
        row.size = 6
        row.mode = 0o755
        archive.addfile(row, io.BytesIO(b"public"))
    root = tmp_path / "qualified"
    extract_cache(path, root)
    assert (root / name).read_bytes() == b"public" and (root / name).stat().st_mode & 0o777 == 0o500


@pytest.mark.parametrize("kind", ["pax", "uid", "mtime"])
def test_cache_archive_unqualified_metadata_denied_before_destination(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "metadata.tar"
    with tarfile.open(
        path, "w", format=tarfile.PAX_FORMAT if kind == "pax" else tarfile.GNU_FORMAT
    ) as archive:
        row = tarfile.TarInfo("store/file")
        row.size = 6
        if kind == "pax":
            row.pax_headers = {"SCHILY.xattr.user.hidden": "unknown"}
        elif kind == "uid":
            row.uid = 1000
        else:
            row.mtime = 1
        archive.addfile(row, io.BytesIO(b"public"))
    root = tmp_path / "qualified"
    with pytest.raises(ValueError, match="metadata differs"):
        extract_cache(path, root)
    assert not root.exists()
