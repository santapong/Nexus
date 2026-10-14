"""Credential envelopes travel through bounded inherited pipes, never a file or environment."""

import os
import threading
from pathlib import Path

import pytest

from nexus.tests.integration import notification_process as module
from nexus.tests.integration.notification_process import read_worker_credential


def test_fifo_credential_is_read_into_secret_and_descriptor_closed() -> None:
    reader, writer = os.pipe()
    os.write(writer, b"header.payload.signature")
    os.close(writer)
    secret = read_worker_credential(reader)
    assert secret.get_secret_value() == "header.payload.signature"
    assert "header" not in repr(secret)
    with pytest.raises(OSError):
        os.fstat(reader)


@pytest.mark.parametrize("raw", [b"", b"header payload", b"\xff"])
def test_empty_whitespace_or_non_ascii_envelope_is_constant_safe_denial(raw: bytes) -> None:
    reader, writer = os.pipe()
    os.write(writer, raw)
    os.close(writer)
    with pytest.raises(ValueError, match=r"^Notification process credential is unavailable$"):
        read_worker_credential(reader)


def test_regular_file_descriptor_cannot_replace_inherited_credential_pipe(tmp_path: Path) -> None:
    path = tmp_path / "ordinary"
    path.write_text("not-a-credential")
    reader = os.open(path, os.O_RDONLY)
    with pytest.raises(ValueError, match=r"^Notification process credential is unavailable$"):
        read_worker_credential(reader)


def test_pipe_envelope_over_bound_is_denied_and_writer_terminates() -> None:
    reader, writer = os.pipe()

    def send() -> None:
        try:
            os.write(writer, b"A" * 8192)
            os.write(writer, b"A")
        finally:
            os.close(writer)

    thread = threading.Thread(target=send)
    thread.start()
    with pytest.raises(ValueError, match=r"^Notification process credential is unavailable$"):
        read_worker_credential(reader)
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_held_open_empty_pipe_has_finite_read_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, writer = os.pipe()
    monkeypatch.setattr(module, "CREDENTIAL_READ_TIMEOUT_SECONDS", 0.01)
    try:
        with pytest.raises(ValueError, match=r"^Notification process credential is unavailable$"):
            read_worker_credential(reader)
    finally:
        os.close(writer)
