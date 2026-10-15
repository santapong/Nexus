"""Bounded supplied-data export/selector probes, without browser or native effects."""

from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import pytest
from markdown_it import MarkdownIt
from markdown_it.token import Token

from nexus.company.brain.sources import UTF8Span
from nexus.company.contracts.actions import ActionProposal
from nexus.company.cycle_artifacts.action_parameters import (
    ClosedCycleActionParameters,
    CycleAuthorSelector,
    PresentationCheckParameters,
    PresentationWriteParameters,
    SupportCheckParameters,
    SupportWriteParameters,
    decode_cycle_action,
)
from nexus.company.cycle_artifacts.check_contracts import cycle_check_snapshot
from nexus.company.cycle_artifacts.checker import check_cycle_artifact
from nexus.company.cycle_artifacts.citations import quote_sources
from nexus.company.cycle_artifacts.common import CycleKind, digest
from nexus.company.cycle_artifacts.production import prepare_presentation, prepare_support
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import SourceQuoteClaim
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.cycle_deliverable_fixture import DeliverableCase, deliverable_case


def action(case: DeliverableCase, phase: str) -> ActionProposal:
    # This >50-line fixture binds both closed role parameter schemas to their exact source basis.
    basis = case.basis
    params: ClosedCycleActionParameters
    model: type[ClosedCycleActionParameters]
    if phase == "write":
        model = (
            PresentationWriteParameters
            if basis.artifact_kind == "presentation"
            else SupportWriteParameters
        )
        params = model.model_validate(
            {
                "artifact_kind": basis.artifact_kind,
                "selector": CycleAuthorSelector(
                    company_id=basis.company_id,
                    goal=basis.goal,
                    producing_plan=basis.producing_plan,
                    procedure_id=basis.procedure_id,
                    author=basis.author,
                    registration_sha256=basis.author_registration_sha256,
                ),
                "output_manifest_sha256": case.prepared.output_manifest_sha256,
                "input_snapshot_sha256": canonical_sha256(basis),
                "input_manifest_sha256": canonical_sha256(basis.inputs),
            }
        )
        binding = basis.author
        action_id = case.action_id
    else:
        check = check_cycle_artifact(case.command())
        model = (
            PresentationCheckParameters
            if basis.artifact_kind == "presentation"
            else SupportCheckParameters
        )
        params = model.model_validate(
            {
                "artifact_kind": basis.artifact_kind,
                "author_action_id": case.action_id,
                "verification_target_sha256": check.target_sha256,
                "author_output_manifest_sha256": case.prepared.output_manifest_sha256,
                "output_sha256": digest(check.model_dump_json().encode()),
                "input_snapshot_sha256": canonical_sha256(cycle_check_snapshot(case.command())),
                "input_manifest_sha256": canonical_sha256(case.command().inputs),
            }
        )
        binding = basis.verifier
        action_id = uuid4()
    return ActionProposal(
        company_id=basis.company_id,
        action_id=action_id,
        actor_id=binding.actor_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        revision=1,
        tool=f"company.cycle-artifact.{phase}.v1",
        tool_version="v1",
        resource="cycle.output",
        parameters=params.model_dump(mode="json"),
        estimated_cost_usd="0.01",
        policy_version="fixture",
        price_version="fixture",
    )


@pytest.mark.parametrize("kind", ["presentation", "support"])
@pytest.mark.parametrize("phase", ["write", "check"])
def test_new_tagged_kind_and_role_require_their_exact_closed_schema(
    kind: CycleKind, phase: str
) -> None:
    case = deliverable_case(kind)
    proposed = action(case, phase)
    permission = ToolPermission(tool=proposed.tool, tool_version="v1", resource=proposed.resource)
    binding = case.basis.author if phase == "write" else case.basis.verifier
    parsed = decode_cycle_action(
        proposed, expected_kind=kind, phase=phase, binding=binding, permission=permission
    )
    assert isinstance(
        parsed,
        (
            PresentationWriteParameters,
            SupportWriteParameters,
            PresentationCheckParameters,
            SupportCheckParameters,
        ),
    )
    assert parsed.artifact_kind == kind
    other = "support" if kind == "presentation" else "presentation"
    with pytest.raises(ValueError):
        decode_cycle_action(
            proposed, expected_kind=other, phase=phase, binding=binding, permission=permission
        )
    for key in ("artifact_kind", "output_manifest_sha256" if phase == "write" else "output_sha256"):
        raw = {k: v for k, v in proposed.parameters.items() if k != key}
        with pytest.raises(ValueError):
            decode_cycle_action(
                proposed.model_copy(update={"parameters": raw}),
                expected_kind=kind,
                phase=phase,
                binding=binding,
                permission=permission,
            )


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.links.extend(
            value for key, value in attrs if key in {"href", "src"} and value is not None
        )


@pytest.mark.parametrize("kind", ["presentation", "support"])
def test_hostile_source_text_stays_escaped_or_literal_without_remote_content(
    kind: CycleKind,
) -> None:
    case = deliverable_case(kind)
    text = (
        "<script>alert(1)</script>\n![pixel](https://example.invalid/a)\n"
        '<a href="javascript:x">x</a>'
    )
    old = case.basis.citations[0]
    quote = SourceQuoteClaim.model_validate(
        old.model_dump() | {"quote": text, "span_sha256": digest(text.encode())}
    )
    basis = case.basis.model_copy(update={"citations": (quote,)})
    prepare = prepare_presentation if kind == "presentation" else prepare_support
    prepared = prepare(basis, case.action_id)
    if kind == "presentation":
        parsed = Tags()
        parsed.feed(prepared.human_export.decode())
        assert "script" not in parsed.tags and "img" not in parsed.tags
        assert parsed.links and all(url.startswith("#") for url in parsed.links)
        assert b"&lt;script&gt;" in prepared.human_export
    else:
        assert all(
            "    " + line in prepared.human_export.decode().splitlines()
            for line in text.splitlines()
        )
        assert "<script>" not in [line[:8] for line in prepared.human_export.decode().splitlines()]


@pytest.mark.parametrize("change", ["export", "drop_part", "add_input", "recipe"])
def test_independent_check_requires_both_exact_outputs_and_complete_manifest(change: str) -> None:
    case = deliverable_case()
    command = case.command()
    if change == "export":
        command = command.model_copy(update={"human_export": b"<script>changed</script>"})
    elif change == "drop_part":
        command = command.model_copy(
            update={
                "target": command.target.model_copy(
                    update={"artifacts": command.target.artifacts[:1]}
                )
            }
        )
    elif change == "add_input":
        ref = command.inputs.artifacts[0].model_copy(
            update={"artifact_revision_id": uuid4(), "artifact_id": uuid4()}
        )
        command = command.model_copy(
            update={
                "inputs": command.inputs.model_copy(
                    update={"artifacts": (*command.inputs.artifacts, ref)}
                )
            }
        )
    else:
        command = command.model_copy(
            update={
                "target": command.target.model_copy(update={"check_recipe": "report-mechanical"})
            }
        )
    result = check_cycle_artifact(command)
    assert result.verdict != "pass"


def _quoted_support(text: str) -> DeliverableCase:
    """Build coherent supplied UTF8/evidence/span/manifest data; not a native ingest or READ."""
    case = deliverable_case("support")
    source = case.sources[0]
    raw = text.encode()
    old = source.evidence.artifact
    artifact = old.model_copy(update={"sha256": digest(raw), "byte_length": len(raw)})
    evidence = source.evidence.model_copy(
        update={
            "artifact": artifact,
            "raw_span": UTF8Span(start_byte=0, end_byte=len(raw)),
            "span_sha256": digest(raw),
        }
    )
    source = source.model_copy(update={"raw_text": text, "evidence": evidence})
    inputs = case.basis.inputs.model_copy(
        update={
            "artifacts": tuple(
                artifact if ref == old else ref for ref in case.basis.inputs.artifacts
            )
        }
    )
    basis = case.basis.model_copy(
        update={"inputs": inputs, "citations": quote_sources((source,), case.basis.observed_at)}
    )
    prepared = prepare_support(basis, case.action_id)
    return DeliverableCase(case.evidence, (source,), basis, case.action_id, prepared)


def _all_tokens(tokens: list[Token]) -> list[Token]:
    return [child for token in tokens for child in [token, *_all_tokens(token.children or [])]]


@pytest.mark.parametrize("ending", ["\r", "\r\n", "\n", "\r\n\n\r"])
@pytest.mark.parametrize("prefix", ["", "\t"])
@pytest.mark.parametrize(
    "attack",
    [
        "![pixel](https://example.invalid/a)",
        '<img src="https://example.invalid/a">',
        "<script>untrusted</script>",
    ],
)
def test_every_commonmark_physical_source_line_remains_literal(
    ending: str, prefix: str, attack: str, tmp_path: Path
) -> None:
    assert version("markdown-it-py") == "4.2.0"
    text = "safe" + ending + ending + prefix + attack
    case = _quoted_support(text)
    prepared, source = case.prepared, case.sources[0]
    body = prepared.typed_json
    # Preserve exact input/output vectors in the nominated pytest temp root on the original red.
    (tmp_path / "original-basis.json").write_bytes(case.basis.model_dump_json().encode())
    (tmp_path / "original-draft.json").write_bytes(body)
    (tmp_path / "original-source.utf8").write_bytes(source.raw_text.encode())
    (tmp_path / "original-human.md").write_bytes(prepared.human_export)
    (tmp_path / "original-manifest.json").write_bytes(prepared.manifest.model_dump_json().encode())
    tokens = _all_tokens(
        MarkdownIt("commonmark", {"html": True}).parse(prepared.human_export.decode())
    )
    unsafe = [
        token.type
        for token in tokens
        if token.type in {"image", "link_open", "html_block", "html_inline"}
    ]
    assert unsafe == []
    assert attack in "".join(token.content for token in tokens if token.type == "code_block")
    quote = case.basis.citations[0]
    assert quote.quote.encode() == source.raw_text.encode() == text.encode()
    assert quote.span_sha256 == source.evidence.span_sha256 == digest(text.encode())
    assert quote.source_event == source.evidence.source_event
    assert prepared == prepare_support(case.basis, case.action_id)
    assert prepared.typed_json == body
    assert check_cycle_artifact(case.command()).verdict == "pass"
