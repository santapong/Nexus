# Optional owner notification API composition

Root task: mount the explicit owner inbox controller only when server-provided
notification_services is supplied to create_company_app. Default remains unmounted.
No timer, worker, provider, preparation, credential entry or held UAT change.

Files: company_app.py optional DI, company_openapi.py exact mounted response
overlays, new focused startup/schema tests. Agent owns routes/store/DTOs and real
HTTP/privacy tests. Frontend follows its frozen schema and existing company design.

Tests first: omitted dependency returns404 and exports no notification roots;
explicit service mounts both signed-only routes, no anonymous bodies; exported
notification response schemas equal exact Pydantic serialization roots. Existing
company API unit acceptance stays green. No fake current owner or database rows.

Done: optional composition/startup/serialization checks pass, then agent real
restricted015 owner HTTP tests qualify the integrated store. Medium risk is
accidental default activation or schema drift; mitigate exact mount/DI tests.
