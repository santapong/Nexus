from __future__ import annotations

from litestar import Router

from nexus.api.agents import AgentController
from nexus.api.approvals import ApprovalController
from nexus.api.health import HealthController
from nexus.api.prompts import PromptController
from nexus.api.tasks import TaskController
from nexus.api.websocket import agent_activity_ws
from nexus.gateway.routes import A2AGatewayController, AgentCardController

api_router = Router(
    path="/api",
    route_handlers=[
        TaskController,
        AgentController,
        ApprovalController,
        PromptController,
    ],
)

# Health is at root, not under /api
health_router = Router(
    path="/",
    route_handlers=[HealthController, agent_activity_ws],
)

# A2A Gateway routes (/.well-known/agent.json + /a2a/tasks)
a2a_router = Router(
    path="/",
    route_handlers=[AgentCardController, A2AGatewayController],
)
