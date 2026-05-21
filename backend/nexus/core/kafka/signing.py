"""Kafka message signing — HMAC-SHA256 integrity verification.

Every Kafka message is signed before publishing and verified on consumption.
Prevents message tampering in transit and ensures only trusted producers
can inject messages into the system.

Enterprise security requirement: messages without valid signatures are
rejected by consumers and routed to the dead letter queue.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import structlog

from nexus.settings import settings

logger = structlog.get_logger()

# Use JWT secret as HMAC key — already a strong secret present in every deployment
_SIGNING_KEY: bytes = b""


_DEV_FALLBACK_KEY = "nexus-dev-signing-key"
_DEV_ENVIRONMENTS = frozenset({"dev", "development", "local", "test"})


def _get_signing_key() -> bytes:
    """Lazily load the signing key from settings.

    The signing key is derived from ``settings.jwt_secret_key``. If it is
    missing/empty:

    * In a dev/local/test environment we fall back to a well-known literal
      so local development is friction-free. A WARNING is logged so the
      fallback is never silent.
    * In any other environment we raise ``RuntimeError`` — running with a
      predictable signing key in production would let any attacker forge
      valid Kafka messages and bypass HMAC integrity checks entirely.

    Raises:
        RuntimeError: If ``jwt_secret_key`` is empty in a non-dev environment.
    """
    global _SIGNING_KEY
    if not _SIGNING_KEY:
        key_material = settings.jwt_secret_key
        if not key_material:
            env = (settings.app_env or "").lower()
            if env not in _DEV_ENVIRONMENTS:
                msg = (
                    "FATAL: jwt_secret_key is empty and the Kafka signing key "
                    "fallback is only allowed in dev/local/test environments "
                    f"(current app_env={settings.app_env!r}). Set a strong "
                    "JWT_SECRET_KEY before starting the service."
                )
                raise RuntimeError(msg)
            logger.warning(
                "kafka_signing_key_dev_fallback",
                app_env=settings.app_env,
                hint=(
                    "Using hardcoded dev signing key. Set JWT_SECRET_KEY "
                    "to a strong random secret outside dev/local/test."
                ),
            )
            key_material = _DEV_FALLBACK_KEY
        _SIGNING_KEY = key_material.encode("utf-8")
    return _SIGNING_KEY


def sign_message(payload: dict[str, Any]) -> str:
    """Generate HMAC-SHA256 signature for a Kafka message payload.

    The signature covers the canonical JSON serialization of the payload
    (sorted keys, no whitespace). This ensures deterministic signing
    regardless of dict ordering.

    Args:
        payload: The message payload to sign.

    Returns:
        Hex-encoded HMAC-SHA256 signature.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hmac.new(
        _get_signing_key(),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload: dict[str, Any], signature: str) -> bool:
    """Verify the HMAC-SHA256 signature of a Kafka message.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        payload: The message payload to verify.
        signature: The hex-encoded signature to check against.

    Returns:
        True if the signature is valid, False otherwise.
    """
    # Remove the signature field itself from verification
    payload_copy = {k: v for k, v in payload.items() if k != "_signature"}
    expected = sign_message(payload_copy)
    return hmac.compare_digest(expected, signature)


def inject_signature(payload: dict[str, Any]) -> dict[str, Any]:
    """Add HMAC signature to a message payload before publishing.

    Args:
        payload: The message payload to sign.

    Returns:
        The payload with `_signature` field added.
    """
    # Sign without the signature field
    payload_copy = {k: v for k, v in payload.items() if k != "_signature"}
    payload["_signature"] = sign_message(payload_copy)
    return payload


def validate_signed_message(raw: dict[str, Any]) -> bool:
    """Validate a received message's signature.

    If no signature is present, the message is considered unsigned
    and is rejected in strict mode (production) but accepted in
    development mode for backwards compatibility.

    Args:
        raw: The raw message dict from Kafka.

    Returns:
        True if the message is valid (signed and verified).
    """
    signature = raw.get("_signature")

    if signature is None:
        # In development, accept unsigned messages for backwards compatibility
        if settings.is_development:
            return True
        logger.warning(
            "unsigned_message_rejected",
            message_id=raw.get("message_id", "unknown"),
            task_id=raw.get("task_id", "unknown"),
        )
        return False

    if not verify_signature(raw, signature):
        logger.warning(
            "invalid_signature_rejected",
            message_id=raw.get("message_id", "unknown"),
            task_id=raw.get("task_id", "unknown"),
        )
        return False

    return True
