"""Registered no-expiry sources remain fresh; an empty deadline alone proves nothing."""

from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.check_contracts import CitationCheckSource, ReportCheckInput
from nexus.company.management.report_checker import check_internal_report
from nexus.tests.unit.test_company_management_checker import actual_report as actual_report


def no_expiry_policy() -> SourcePolicy:
    return SourcePolicy(
        source_symbol="immutable.repo.v1",
        authority_profile="repo.commit.v1",
        data_classification="internal",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=None,
    )


def changed_source(command: ReportCheckInput, *, policy: SourcePolicy | None) -> ReportCheckInput:
    assert command.snapshot is not None
    source = command.snapshot.citations[0]
    source = CitationCheckSource.model_validate_json(
        source.model_copy(
            update={
                "head": source.head.model_copy(update={"fresh_until": None}),
                "source_policy": policy,
            }
        ).model_dump_json()
    )
    return command.model_copy(
        update={"snapshot": command.snapshot.model_copy(update={"citations": (source,)})}
    )


def test_exact_registered_no_expiry_policy_qualifies_actual_source(
    actual_report: ReportCheckInput,
) -> None:
    result = check_internal_report(changed_source(actual_report, policy=no_expiry_policy()))
    assert result.verdict == "pass"


def test_empty_head_expiry_without_registered_policy_cannot_claim_fresh(
    actual_report: ReportCheckInput,
) -> None:
    result = check_internal_report(changed_source(actual_report, policy=None))
    assert result.verdict == "reject"


def test_timed_policy_cannot_qualify_empty_head_deadline(actual_report: ReportCheckInput) -> None:
    policy = no_expiry_policy().model_copy(update={"freshness_seconds": 3600})
    result = check_internal_report(changed_source(actual_report, policy=policy))
    assert result.verdict == "reject"


def test_policy_key_set_has_order_independent_exact_canonical_identity() -> None:
    from nexus.company.management.canonical import canonical_sha256

    first = no_expiry_policy().model_copy(update={"allowed_external_keys": frozenset(("a", "b"))})
    second = no_expiry_policy().model_copy(update={"allowed_external_keys": frozenset(("b", "a"))})
    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256(first) != canonical_sha256(no_expiry_policy())
