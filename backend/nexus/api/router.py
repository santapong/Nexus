from __future__ import annotations

from litestar import Router

from nexus.api.a2a_tokens import A2ATokenController
from nexus.api.agent_builder import AgentBuilderController
from nexus.api.agents import AgentController
from nexus.api.analytics import AnalyticsController
from nexus.api.approvals import ApprovalController
from nexus.api.audit import AuditController
from nexus.api.billing import BillingController
from nexus.api.eval import EvalController
from nexus.api.federation import FederationController
from nexus.api.health import HealthController
from nexus.api.marketplace import MarketplaceController
from nexus.api.oauth import OAuthController
from nexus.api.prompts import PromptController
from nexus.api.schedules import ScheduleController
from nexus.api.tasks import TaskController
from nexus.api.webhooks import WebhookController
from nexus.api.websocket import agent_activity_ws
from nexus.api.workspaces import AuthController, WorkspaceController
from nexus.integrations.a2a.routes import A2AGatewayController, AgentCardController
from nexus.integrations.stripe.webhooks import StripeWebhookController

api_router = Router(
    path="/api",
    route_handlers=[
        TaskController,
        AgentController,
        ApprovalController,
        PromptController,
        AnalyticsController,
        AuditController,
        A2ATokenController,
        EvalController,
        MarketplaceController,
        BillingController,
        AgentBuilderController,
        AuthController,
        WorkspaceController,
        OAuthController,
        WebhookController,
        ScheduleController,
        FederationController,
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

# Stripe webhook route (outside /api — Stripe sends to root path)
stripe_router = Router(
    path="/",
    route_handlers=[StripeWebhookController],
)
