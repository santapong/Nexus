"""Isolated owner-facing company API factory; no legacy agents or business intake."""

from __future__ import annotations

from litestar import Litestar
from litestar.di import Provide
from litestar.exceptions import ValidationException

from nexus.api.company_auth import validate_company_auth_configuration
from nexus.api.company_brain_routes import CompanyBrainController
from nexus.api.company_routes import CompanyController, company_health, validation_error_handler
from nexus.company.brain.api_services import BrainServices
from nexus.company.services import CompanyServices


def create_company_app(
    services: CompanyServices, *, brain_services: BrainServices | None = None
) -> Litestar:
    """Fail closed on signer configuration before building an isolated company profile.

    Services use an explicitly configured company database. This factory starts
    no Kafka consumer, legacy agent, model/provider client or durable worker.
    The HTTP surface records decisions but does not create or execute new work.
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

    return Litestar(
        route_handlers=[company_health, CompanyController, CompanyBrainController]
        if brain_services is not None
        else [company_health, CompanyController],
        debug=False,
        dependencies=dependencies,
        exception_handlers={ValidationException: validation_error_handler},
    )
