"""Unit tests for the Tasks API controller."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nexus.api.tasks import CreateTaskRequest, TaskResponse


@pytest.mark.asyncio
async def test_create_task_request_model() -> None:
    """CreateTaskRequest should validate instruction and default source."""
    req = CreateTaskRequest(instruction="Hello world")
    assert req.instruction == "Hello world"
    assert req.source == "human"


@pytest.mark.asyncio
async def test_create_task_request_custom_source() -> None:
    """CreateTaskRequest should accept a2a source."""
    req = CreateTaskRequest(instruction="Test", source="a2a")
    assert req.source == "a2a"


@pytest.mark.asyncio
async def test_task_response_model() -> None:
    """TaskResponse should correctly serialize all fields."""
    resp = TaskResponse(
        id=str(uuid4()),
        trace_id=str(uuid4()),
        instruction="Test instruction",
        status="completed",
        source="human",
        tokens_used=500,
        output={"result": "success"},
        error=None,
        created_at="2026-03-07T12:00:00",
        started_at="2026-03-07T12:00:01",
        completed_at="2026-03-07T12:00:10",
    )
    assert resp.status == "completed"
    assert resp.output == {"result": "success"}
    assert resp.error is None


@pytest.mark.asyncio
async def test_task_response_minimal() -> None:
    """TaskResponse should handle None optional fields."""
    resp = TaskResponse(
        id=str(uuid4()),
        trace_id=str(uuid4()),
        instruction="Test",
        status="queued",
        source="human",
        tokens_used=0,
        created_at="2026-03-07T12:00:00",
    )
    assert resp.output is None
    assert resp.started_at is None
    assert resp.completed_at is None
