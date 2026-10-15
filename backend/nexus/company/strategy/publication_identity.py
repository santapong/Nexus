"""Fixed strategy bundle identities; hashes describe bytes and never mint authority."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.blob_store import validate_utf8
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.base import require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.strategy.artifact_identity import strategy_artifact_id, strategy_reference
from nexus.company.strategy.contracts import StrategyCheckSnapshot
from nexus.company.strategy.producer import prepare_strategy_artifact, strategy_input_bundle_bytes
from nexus.company.strategy.producer_contracts import (
    StrategyOriginalInputBundle,
    StrategyOriginalInputBundleRef,
    StrategyProductionPolicy,
)

if TYPE_CHECKING:
    from nexus.company.strategy.publication_contracts import PreparedStrategyPublication


def strategy_bundle_id(company_id: UUID, action_id: UUID) -> UUID:
    """Name one immutable bundle from its original S action, never from changing bytes."""
    return uuid5(strategy_artifact_id(company_id, action_id), "input-bundle:v2")


def strategy_bundle_derivation_id(company_id: UUID, action_id: UUID) -> UUID:
    """Keep bundle derivation identity distinct from the Brief's native derivation."""
    return uuid5(strategy_bundle_id(company_id, action_id), "derivation:v1")


def strategy_bundle_reference(
    company_id: UUID,
    action_id: UUID,
    raw: bytes,
    snapshot_sha256: str,
    policy_sha256: str,
    target: ResourceRef,
) -> StrategyOriginalInputBundleRef:
    """Return exact pending bytes/reference only; no storage or READ is implied."""
    require_company(company_id, target)
    validate_utf8(raw)
    artifact_id = strategy_bundle_id(company_id, action_id)
    return StrategyOriginalInputBundleRef(
        company_id=company_id,
        artifact=ArtifactRevisionRef(
            company_id=company_id,
            artifact_id=artifact_id,
            artifact_revision_id=uuid5(artifact_id, "revision:v2"),
            revision="strategy-inputs-v2",
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        ),
        resource=target,
        input_snapshot_sha256=snapshot_sha256,
        producer_policy_sha256=policy_sha256,
    )


def prepare_strategy_publication(
    snapshot: StrategyCheckSnapshot,
    policy: StrategyProductionPolicy,
    action_id: UUID,
    target: ResourceRef,
) -> PreparedStrategyPublication:
    """Compile exact B/Brief data; only the native store may establish actual publication."""
    from nexus.company.strategy.publication_contracts import PreparedStrategyPublication

    raw = strategy_input_bundle_bytes(snapshot, policy)
    original = StrategyOriginalInputBundle(
        company_id=snapshot.company_id, snapshot=snapshot, policy=policy
    )
    reference = strategy_bundle_reference(
        snapshot.company_id,
        action_id,
        raw,
        canonical_sha256(snapshot),
        canonical_sha256(policy),
        target,
    )
    compiled = prepare_strategy_artifact(snapshot, policy, original_bundle=reference)
    return PreparedStrategyPublication(
        action_id=action_id,
        original=original,
        bundle_bytes=raw,
        compiled=compiled,
        brief=strategy_reference(compiled.prepared, action_id),
    )
