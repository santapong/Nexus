"""Closed process fixture database/root mapping never accepts arbitrary absolute paths."""

import os
from pathlib import Path

PROCESS_ROOTS = {
    f"nexus_company_test_engineering_process_{phase}": Path(
        f"/tmp/nexus-engineering-process-{phase}-20261015-1"
    )
    for phase in ("intent", "result", "receipt", "proof", "acceptance")
}


def require_process_root(database: str, root: Path, *, existing: bool) -> None:
    """Only exact reviewed owned ordinary fixture roots can be created or reconstructed."""
    if PROCESS_ROOTS.get(database) != root or root.resolve() != root or root.is_symlink():
        raise ValueError("Engineering process root differs from the reviewed scope")
    if existing:
        info = root.stat()
        if not root.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
            raise ValueError("Engineering process root must be owned and private")
    elif root.exists():
        raise ValueError("Engineering process preparation requires a new root")
