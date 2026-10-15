"""Supplied deterministic compiler/rule data only; no native E acceptance or SQL permission."""

from dataclasses import dataclass
from typing import Literal

from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.cycle_artifacts.common import CycleKind
from nexus.company.cycle_artifacts.production import PreparedCycleDeliverable
from nexus.company.cycle_artifacts.publication_contracts import CycleArtifactRule
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.cycle_deliverable_fixture import DeliverableCase, deliverable_case


def cycle_policies() -> tuple[SourcePolicy, ...]:
    values = []
    media: dict[str, Literal["text/plain", "text/markdown", "text/html", "application/json"]] = {
        "json": "application/json",
        "check": "application/json",
        "html": "text/html",
        "markdown": "text/markdown",
    }

    for kind in ("presentation", "support"):
        for part in ("json", "html" if kind == "presentation" else "markdown", "check"):
            values.append(
                SourcePolicy(
                    source_symbol=f"generated.{kind}-{part}.v1",
                    authority_profile="cycle.private.v1",
                    data_classification="internal",
                    origin_kind="derived",
                    media_type=media[part],
                    parser_version="utf8.v1",
                    chunker_version="fixed.v1",
                    search_config="simple",
                    freshness_seconds=None,
                    max_bytes=262144,
                )
            )
    return tuple(values)


@dataclass(frozen=True)
class CycleRowCase:
    case: DeliverableCase
    write_rule: CycleArtifactRule
    check_rule: CycleArtifactRule

    @property
    def prepared(self) -> PreparedCycleDeliverable:
        return self.case.prepared


def row_case(kind: CycleKind = "presentation") -> CycleRowCase:
    case = deliverable_case(kind)
    policies = {row.source_symbol: row for row in cycle_policies()}
    rules = []
    for phase in ("write", "check"):
        parts = (
            ("check",)
            if phase == "check"
            else ("json", "html" if kind == "presentation" else "markdown")
        )
        rules.append(
            CycleArtifactRule(
                company_id=case.basis.company_id,
                kind=kind,
                phase=phase,
                permission=ToolPermission(
                    tool=f"company.cycle-artifact.{phase}.v1",
                    tool_version="v1",
                    resource="cycle.private",
                ),
                target=case.basis.target,
                policies=tuple(policies[f"generated.{kind}-{part}.v1"] for part in parts),
            )
        )
    return CycleRowCase(case, rules[0], rules[1])
