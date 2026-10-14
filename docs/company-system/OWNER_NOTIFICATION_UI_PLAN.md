# Owner inbox dashboard integration

Root prepares frontend in /tmp/nexus-owner-inbox-ui-20261014/frontend to preserve
the held human signup page and its running source. No primary frontend edits or
UAT restart until a coordinated integration point. This is the accepted existing
company visual language; no new design/dependency or sending controls.

Generate exact types from the optional actual company app route export and mounted
Pydantic serialization schemas. Add bounded owner inbox list/detail via existing
companyFetch and session-version keys, TanStack Query server state, pagination,
safe loading/error/refresh states, plain text draft content and distinct recorded
submission/delivery/reconciliation. Hide previous bodies while refreshing or on
qualification error. Read-only requests never send, poll providers or approve.

Files: generated types/type aliases, company API methods, notification hook,
inbox/detail pages, notification card, router and company navigation. Tests-first
client checks preserve encoded IDs, bounded cursor URL and no mutation methods;
reuse existing session-race checks. Typecheck/build and visible separate synthetic
preview verify unknown delivery, accepted submission and denied refreshed page.
React checklist covers hooks, query keys, accessibility and plain escaped text.

Done: source patch, exact schema/type/build receipts and separate browser evidence
are reviewable. Actual owner access/current API persistence remains agent-qualified;
synthetic UI preview is not owner signup, live email or full release acceptance.
