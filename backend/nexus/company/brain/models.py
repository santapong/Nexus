"""Explicit complete Brain metadata import; not wired to the company Alembic environment."""

from nexus.company.brain.access_models import BrainAccessEvent, BrainResource, BrainResourceAccess
from nexus.company.brain.claim_models import (
    BrainClaimEvidence,
    BrainClaimHead,
    BrainClaimLink,
    BrainClaimLinkEvidence,
    BrainClaimRevision,
)
from nexus.company.brain.derivation_models import (
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
)
from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.brain.evidence_models import (
    BrainChunk,
    BrainEvidence,
    BrainParseFailure,
    BrainParseRevision,
)
from nexus.company.brain.model_base import BrainBase
from nexus.company.brain.ontology_models import (
    BrainEntity,
    BrainEntityEvidence,
    BrainEntityRevision,
    BrainRelationshipEvidence,
    BrainRelationshipRevision,
)
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)

__all__ = [
    "BrainAccessEvent",
    "BrainArtifactRevision",
    "BrainBase",
    "BrainChunk",
    "BrainClaimEvidence",
    "BrainClaimHead",
    "BrainClaimLink",
    "BrainClaimLinkEvidence",
    "BrainClaimRevision",
    "BrainDerivation",
    "BrainDerivationEvidence",
    "BrainDerivationSource",
    "BrainEntity",
    "BrainEntityEvidence",
    "BrainEntityRevision",
    "BrainEvent",
    "BrainEventCursor",
    "BrainEvidence",
    "BrainParseFailure",
    "BrainParseRevision",
    "BrainRelationshipEvidence",
    "BrainRelationshipRevision",
    "BrainResource",
    "BrainResourceAccess",
    "BrainSource",
    "BrainSourceHead",
    "BrainSourceRevision",
]


# All tables must be declared before registering these fixed metadata indexes.
from nexus.company.brain.model_indexes import register_indexes

register_indexes()
