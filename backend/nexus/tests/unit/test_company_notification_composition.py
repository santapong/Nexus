"""Optional inbox mounting preserves default isolation and exact response schemas."""

import pytest
from litestar.testing import AsyncTestClient

from nexus.api.company_openapi import company_schema_document
from nexus.company.notifications.api_services import NotificationApiServices
from nexus.company.notifications.inbox_contracts import (
    NotificationInboxEntry,
    NotificationInboxPage,
)
from nexus.company_app import create_company_app
from nexus.settings import settings
from nexus.tests.unit.test_company_api import services


@pytest.mark.parametrize("mounted", [False, True])
async def test_notification_mount_is_explicit_and_anonymous_body_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    mounted: bool,
) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "unit-fixture-key-with-at-least-32-characters")
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    base = services()
    app = create_company_app(
        base, notification_services=NotificationApiServices(base.directory) if mounted else None
    )
    async with AsyncTestClient(app) as client:
        route = "/api/v2/companies/00000000-0000-0000-0000-000000000001/notifications/"
        response = await client.get(route)
        assert response.status_code == (401 if mounted else 404)
        document = (await client.get("/schema/openapi.json")).json()
        exact = company_schema_document(document)
        schemas = exact["components"]["schemas"]
        if not mounted:
            assert "NotificationInboxPage" not in schemas
            assert "NotificationInboxEntry" not in schemas
        else:
            for model in (NotificationInboxPage, NotificationInboxEntry):
                expected = model.model_json_schema(
                    mode="serialization", ref_template="#/components/schemas/{model}"
                )
                expected.pop("$defs", None)
                assert schemas[model.__name__] == expected
