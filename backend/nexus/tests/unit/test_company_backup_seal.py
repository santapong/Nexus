"""Authenticated bounded backups reject wrong keys and corrupted envelopes."""

from collections.abc import Callable

import pytest

from nexus.operations.backup_seal import MAGIC, open_backup, seal_backup


def test_sealed_backup_roundtrip_and_fresh_nonce() -> None:
    key = b"k" * 32
    payload = b"matching database and protected artifact bytes"
    first, second = seal_backup(payload, key), seal_backup(payload, key)
    assert first != second
    assert payload not in first
    assert open_backup(first, key) == payload
    assert open_backup(second, key) == payload


@pytest.mark.parametrize("mutation", ["header", "nonce", "ciphertext", "tag", "truncate", "extra"])
def test_corruption_never_returns_plaintext(mutation: str) -> None:
    key = b"k" * 32
    sealed = seal_backup(b"protected backup", key)
    changes: dict[str, Callable[[bytes], bytes]] = {
        "header": lambda data: b"!" + data[1:],
        "nonce": lambda data: (
            data[: len(MAGIC)] + bytes([data[len(MAGIC)] ^ 1]) + data[len(MAGIC) + 1 :]
        ),
        "ciphertext": lambda data: data[:40] + bytes([data[40] ^ 1]) + data[41:],
        "tag": lambda data: data[:-1] + bytes([data[-1] ^ 1]),
        "truncate": lambda data: data[:-1],
        "extra": lambda data: data + b"extra",
    }
    with pytest.raises(ValueError):
        open_backup(changes[mutation](sealed), key)


def test_wrong_key_and_empty_data_denied() -> None:
    with pytest.raises(ValueError):
        open_backup(seal_backup(b"protected", b"k" * 32), b"z" * 32)
    with pytest.raises(ValueError):
        seal_backup(b"", b"k" * 32)


@pytest.mark.parametrize("key", [b"", b"short", b"k" * 16, b"k" * 33])
def test_exact_256_bit_key_required(key: bytes) -> None:
    with pytest.raises(ValueError):
        seal_backup(b"protected", key)


def test_bounds_apply_before_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexus.operations.backup_seal as codec

    monkeypatch.setattr(codec, "MAX_BACKUP_BYTES", 8)
    with pytest.raises(ValueError):
        seal_backup(b"ninebytes", b"k" * 32)
    with pytest.raises(ValueError):
        open_backup(b"x" * 100, b"k" * 32)
