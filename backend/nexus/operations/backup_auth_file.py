"""An empty owned temporary passfile suppresses ambient credential lookup; it stores no secrets."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


@contextmanager
def empty_password_file() -> Iterator[Path]:
    with TemporaryDirectory(prefix="nexus-backup-auth-", dir="/tmp") as directory:
        root = Path(directory)
        if root.stat().st_mode & 0o777 != 0o700:
            raise ValueError("Backup temporary authentication root is unavailable")
        path = root / "empty-passfile"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        if path.stat().st_mode & 0o777 != 0o600:
            raise ValueError("Backup empty authentication file is unavailable")
        yield path
