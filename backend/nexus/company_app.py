"""Isolated owner-facing company API factory; no legacy agents or business intake."""

from __future__ import annotations

from litestar import Controller, Litestar
from litestar.config.cors import CORSConfig
from litestar.di import Provide
from litestar.exceptions import ValidationException
from litestar.handlers.base import BaseRouteHandler
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin

from nexus.api.company_auth import validate_company_auth_configuration
from nexus.api.company_brain_routes import CompanyBrainController
from nexus.api.company_management_routes import CompanyManagementController
from nexus.api.company_openapi import CompanyJsonRenderPlugin, CompanyYamlRenderPlugin
from nexus.api.company_routes import CompanyController, company_health, validation_error_handler
from nexus.api.company_session_routes import CompanySessionController
from nexus.company.brain.api_services import BrainServices
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.pilot_session import PilotSessionService
from nexus.company.services import CompanyServices


def create_company_app(
    services: CompanyServices,
    *,
    brain_services: BrainServices | None = None,
    management_services: ManagementApiServices | None = None,
    pilot_sessions: PilotSessionService | None = None,
    cors_config: CORSConfig | None = None,
) -> Litestar:
    """Fail closed on signer configuration before building an isolated company profile.

    Services use an explicitly configured company database. This factory starts
    no Kafka consumer, legacy agent, model/provider client or durable worker.
    Default HTTP records decisions without new work. Optional management admits
    bounded work only through actual owner-approved plans, and starts no execution.
    """
    validate_company_auth_configuration()

    def provide_services() -> CompanyServices:
        return services

    dependencies = {"services": Provide(provide_services, use_cache=True, sync_to_thread=False)}
    if brain_services is not None:
        mounted_brain = brain_services

        def provide_brain_services() -> BrainServices:
            return mounted_brain

        dependencies["brain_services"] = Provide(
            provide_brain_services, use_cache=True, sync_to_thread=False
        )

    route_handlers: list[BaseRouteHandler | type[Controller]] = [company_health, CompanyController]
    if brain_services is not None:
        route_handlers.append(CompanyBrainController)
    if management_services is not None:
        mounted_management = management_services

        def provide_management_services() -> ManagementApiServices:
            return mounted_management

        dependencies["management_services"] = Provide(
            provide_management_services, use_cache=True, sync_to_thread=False
        )
        route_handlers.append(CompanyManagementController)

    if pilot_sessions is not None:
        mounted_sessions = pilot_sessions

        def provide_pilot_sessions() -> PilotSessionService:
            return mounted_sessions

        dependencies["pilot_sessions"] = Provide(
            provide_pilot_sessions, use_cache=True, sync_to_thread=False
        )
        route_handlers.append(CompanySessionController)

    return Litestar(
        route_handlers=route_handlers,
        debug=False,
        dependencies=dependencies,
        cors_config=cors_config,
        openapi_config=OpenAPIConfig(
            title="Nexus company API",
            version="2",
            render_plugins=[
                CompanyJsonRenderPlugin(),
                CompanyYamlRenderPlugin(),
                SwaggerRenderPlugin(),
            ],
        ),
        exception_handlers={ValidationException: validation_error_handler},
    )
