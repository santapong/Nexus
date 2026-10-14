"""Explicit synthetic UAT source bytes; never StockFlow readiness or customer evidence."""

from typing import cast

from nexus.company.brain.base import SourceTime
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import SourceRegistration
from nexus.company.pilot_config import PilotConfig
from nexus.core.llm.company_registry import DataClassification

PUBLIC_TEXT = (
    "# Disposable supervised owner UAT\n"
    "This synthetic source supports local UI and native governance checks only.\n"
    "No live model/provider, customer delivery, revenue or completed business work is asserted.\n"
    "The owner may review a native internal report and its independently checked result.\n"
    "Budget remains supervised; unknown billing remains unconfirmed.\n"
)
PRIVATE_TEXT = (
    "# UAT private owner note\n"
    "Synthetic confidential note used to test current READ denial for the UAT member.\n"
    "This contains no production secret or customer data.\n"
)


class PilotSourceReader:
    def __init__(self, config: PilotConfig) -> None:
        self.config = config

    async def read(self, registration: SourceRegistration, revision: str) -> SourceSnapshot:
        valid = {
            self.config.public_source_id: ("uat.synthetic.public.v1", PUBLIC_TEXT),
            self.config.private_source_id: ("uat.synthetic.private.v1", PRIVATE_TEXT),
        }
        selected = valid.get(registration.source_id)
        if (
            selected is None
            or selected[0] != registration.source_symbol
            or revision != "uat-synthetic-v1"
        ):
            raise BrainDeniedError("Nominated synthetic UAT source is unavailable")
        return SourceSnapshot(
            company_id=self.config.company_id,
            source_id=registration.source_id,
            source_symbol=registration.source_symbol,
            external_key=registration.external_key,
            revision=revision,
            raw_bytes=selected[1].encode(),
            source_event=SourceTime(
                precision="instant",
                value=self.config.created_at.isoformat(),
                basis="Synthetic UAT dataset created by explicit local operator",
            ),
        )


def pilot_sources(config: PilotConfig) -> SourceRegistry:
    policies = tuple(
        SourcePolicy(
            source_symbol=symbol,
            authority_profile="uat.synthetic-reported.v1",
            data_classification=cast(DataClassification, classification),
            media_type="text/plain",
            parser_version="utf8-identity-v1",
            chunker_version="utf8-sections-v1",
            search_config="simple",
            freshness_seconds=None,
            allowed_external_keys=frozenset({key}),
        )
        for symbol, classification, key in (
            ("uat.synthetic.public.v1", "internal", "uat-public"),
            ("uat.synthetic.private.v1", "confidential", "uat-private"),
        )
    )
    return SourceRegistry((*policies, generated_policy()), PilotSourceReader(config))


def generated_policy() -> SourcePolicy:
    return SourcePolicy(
        source_symbol="generated.report.v1",
        authority_profile="native.generated.v1",
        data_classification="internal",
        origin_kind="derived",
        media_type="application/json",
        parser_version="native-json-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=None,
        max_bytes=262144,
    )
