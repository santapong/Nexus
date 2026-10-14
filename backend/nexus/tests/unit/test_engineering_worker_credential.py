"""Engineering credential seams accept only the frozen verifier's sealed process witness."""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity


@pytest.mark.parametrize("store", [EngineeringWorkAcceptanceStore, EngineeringAcceptanceRecovery])
def test_arbitrary_credential_object_cannot_supply_a_deadline(
    store: type[EngineeringWorkAcceptanceStore] | type[EngineeringAcceptanceRecovery],
) -> None:
    with pytest.raises(ValueError, match="credential witness"):
        store(
            cast(async_sessionmaker[AsyncSession], object()),
            cast(PlanAdmissionCatalog, object()),
            cast(RegisteredEngineeringInputs, object()),
            cast(EngineeringProofStorage, object()),
            credential=cast(AuthenticatedWorkerIdentity, object()),
        )


@pytest.mark.parametrize("store", [EngineeringWorkAcceptanceStore, EngineeringAcceptanceRecovery])
def test_default_no_credential_retains_existing_constructor_semantics(
    store: type[EngineeringWorkAcceptanceStore] | type[EngineeringAcceptanceRecovery],
) -> None:
    value = store(
        cast(async_sessionmaker[AsyncSession], object()),
        cast(PlanAdmissionCatalog, object()),
        cast(RegisteredEngineeringInputs, object()),
        cast(EngineeringProofStorage, object()),
    )
    assert value.credential is None
