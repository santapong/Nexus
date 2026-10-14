"""Explicit opt-in task UAT authentication; never mounted by the default company profile."""

from litestar import Controller, post
from litestar.di import NamedDependency

from nexus.company.pilot_session import (
    PilotLogin,
    PilotSessionService,
    PilotSessionToken,
    PilotSignup,
)


class CompanySessionController(Controller):
    path = "/api/v2/company-session"

    @post("/login", status_code=200)
    async def login(
        self, data: PilotLogin, pilot_sessions: NamedDependency[PilotSessionService]
    ) -> PilotSessionToken:
        return await pilot_sessions.login(data)

    @post("/signup", status_code=201)
    async def signup(
        self, data: PilotSignup, pilot_sessions: NamedDependency[PilotSessionService]
    ) -> PilotSessionToken:
        return await pilot_sessions.signup(data)
