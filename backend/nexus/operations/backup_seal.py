"""Bounded authenticated binary envelope; callers provide separately held keys."""

from __future__ import annotations

import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"NEXUSBACKUP\x00v1\x00\x00\x00"
MAX_BACKUP_BYTES = 268_435_456
NONCE_BYTES, TAG_BYTES = 12, 16
HEADER_BYTES = len(MAGIC) + NONCE_BYTES + 8


def _key(key: bytes) -> None:
    if type(key) is not bytes or len(key) != 32:
        raise ValueError("Backup requires an exact externally held256-bit key")


def seal_backup(payload: bytes, key: bytes) -> bytes:
    """Encrypt bounded bytes with a fresh nonce and authenticated length/version.

    CPU-bound codec: async coordinators execute it in a worker thread. The key is
    never returned, serialized or saved; this function grants no capture authority.
    """
    _key(key)
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_BACKUP_BYTES:
        raise ValueError("Backup plaintext exceeds its nonempty bound")
    nonce = os.urandom(NONCE_BYTES)
    header = MAGIC + nonce + struct.pack(">Q", len(payload))
    return header + AESGCM(key).encrypt(nonce, payload, header)


def open_backup(envelope: bytes, key: bytes) -> bytes:
    """Authenticate complete bounded envelope before returning any plaintext."""
    _key(key)
    if (
        type(envelope) is not bytes
        or not HEADER_BYTES + TAG_BYTES
        < len(envelope)
        <= MAX_BACKUP_BYTES + HEADER_BYTES + TAG_BYTES
        or envelope[: len(MAGIC)] != MAGIC
    ):
        raise ValueError("Backup envelope is unavailable")
    header, ciphertext = envelope[:HEADER_BYTES], envelope[HEADER_BYTES:]
    size = struct.unpack(">Q", header[-8:])[0]
    if not 1 <= size <= MAX_BACKUP_BYTES or len(ciphertext) != size + TAG_BYTES:
        raise ValueError("Backup envelope length is unavailable")
    try:
        result = AESGCM(key).decrypt(header[len(MAGIC) : -8], ciphertext, header)
    except (InvalidTag, ValueError):
        raise ValueError("Backup authentication failed") from None
    if len(result) != size:
        raise ValueError("Backup plaintext length is unavailable")
    return result
