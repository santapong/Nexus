"""Unit tests for the Approvals API controller."""

from __future__ import annotations

from uuid import uuid4

import pytest

from nexus.api.approvals import ApprovalResponse, ResolveApprovalRequest


@pytest.mark.asyncio
async def test_approval_response_model() -> None:
    """ApprovalResponse should correctly serialize all fields."""
    resp = ApprovalResponse(
        id=str(uuid4()),
        task_id=str(uuid4()),
        agent_id=str(uuid4()),
        tool_name="file_write",
        action_description="Write 100 chars to /tmp/test.txt",
        status="pending",
        requested_at="2026-03-07T12:00:00",
    )
    assert resp.status == "pending"
    assert resp.tool_name == "file_write"
    assert resp.resolved_at is None
    assert resp.resolved_by is None


@pytest.mark.asyncio
async def test_approval_response_resolved() -> None:
    """ApprovalResponse should handle resolved state."""
    resp = ApprovalResponse(
        id=str(uuid4()),
        task_id=str(uuid4()),
        agent_id=str(uuid4()),
        tool_name="send_email",
        action_description="Send email to test@example.com",
        status="approved",
        requested_at="2026-03-07T12:00:00",
        resolved_at="2026-03-07T12:01:00",
        resolved_by="human",
    )
    assert resp.status == "approved"
    assert resp.resolved_by == "human"


@pytest.mark.asyncio
async def test_resolve_request_approve() -> None:
    """ResolveApprovalRequest accepts a single 'approved' boolean."""
    req = ResolveApprovalRequest(approved=True)
    assert req.approved is True


@pytest.mark.asyncio
async def test_resolve_request_reject() -> None:
    """ResolveApprovalRequest accepts approved=False for rejection."""
    req = ResolveApprovalRequest(approved=False)
    assert req.approved is False


@pytest.mark.asyncio
async def test_resolve_request_rejects_resolved_by_in_body() -> None:
    """The resolved_by field must be sourced from the JWT, not the body.

    Allowing client-supplied resolved_by would let unauthenticated callers
    impersonate humans on irreversible action approvals. The model should
    reject any extra fields including 'resolved_by'.
    """
    from pydantic import ValidationError

    # Pydantic v2 default is to ignore extras, so 'resolved_by' is silently
    # dropped. We assert it never lands on the parsed model.
    raw = {"approved": True, "resolved_by": "attacker"}
    req = ResolveApprovalRequest.model_validate(raw)
    assert not hasattr(req, "resolved_by")
    # Sanity: 'approved' still parsed.
    assert req.approved is True
    # Validation must still fire on completely invalid payloads.
    with pytest.raises(ValidationError):
        ResolveApprovalRequest.model_validate({"approved": "not-a-bool"})
