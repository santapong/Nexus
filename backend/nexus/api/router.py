from __future__ import annotations

from litestar import Router

from nexus.api.agents import AgentController
from nexus.api.approvals import ApprovalController
from nexus.api.health import HealthController
from nexus.api.tasks import TaskController
from nexus.api.websocket import agent_activity_ws

api_router = Router(
    path="/api",
    route_handlers=[
        TaskController,
        AgentController,
        ApprovalController,
    ],
)

# Health is at root, not under /api
health_router = Router(
    path="/",
    route_handlers=[HealthController, agent_activity_ws],
)
