# Nexus multi-provider readiness and remaining activation work

Checked 2026-10-16, including source follow-ups to the audit at40024f5. **Activation is blocked, not performed.** The provider research/source fixes did not inspect key values/presence or credential stores, contact provider accounts/APIs, access DB/native/Pi services or change active configuration. Official documentation was fetched; local source and installed package metadata were read. No live quality or evaluation is claimed.

## Exact nominated pair

| Provider | Model and current implemented API | Server endpoint | Standard USD/1M input / output | State |
| --- | --- | --- | --- | --- |
| OpenAI | `gpt-5.4-mini-2026-03-17`; `openai_responses` | `https://api.openai.com/v1` → `POST /responses` | `0.75 / 4.50` | Candidate, account/quality untested |
| Google | `gemini-3.5-flash-lite`; `google_generate_content` | `https://generativelanguage.googleapis.com` → pinned SDK default `v1beta/models/{model}:generateContent` | `0.30 / 2.50` | Candidate, continuation guard source/mock-checked; live qualification open |

OpenAI documents the dated snapshot, Responses, structured outputs/function calling, 400k context and 128k output. Use the dated ID; do not silently select an alias. [Model/pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini). Google lists this stable ID, 1,048,576 input/65,536 output limits and structured output/function calling. [Model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite). Its standard output price includes thinking. [Pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite). These are vendor capabilities, not Nexus conformance evidence.

Only these two provider/API combinations pass `CompanyModelAdapters._registration`; registry descriptions of compatible APIs, embeddings, or generic legacy factory providers do not enable Company execution. Initial trials: public text only, no tools/hosted services, media, history, cache creation, streaming, Agent.run or fallback/retry loop. Cached-read rates, if supported in the frozen PriceCards, are OpenAI0.075/Google0.03; quotes still reserve ordinary full input. Storage/hosted-tool charges remain unsupported.

## Credentials and exact runtime

Names only: `OPENAI_API_KEY` and `GOOGLE_API_KEY`, declared as `Settings.openai_api_key/google_api_key` in `backend/nexus/settings.py:32–33`. Settings names are case-insensitive; `.env` is relative to launcher cwd (normally backend). **No `.env` or environment/key values were read.** Company adapters do not consume Settings themselves: the new server-owned `SettingsEndpointResolver` binds exact endpoint symbols to `ServerEndpoint(api_key=SecretStr(...), base_url=..., timeout_seconds=30)`. No key/URL belongs in request, journal, registry, browser or evidence DTOs. Do not use SDK environment fallback as that resolver. [Official OpenAI SDK/key convention](https://developers.openai.com/api/docs/libraries), [Google SDK](https://ai.google.dev/gemini-api/docs/libraries).

Observed runtime: `/home/santapong/.codex/nexus-local-runtime-20261014/bin/python`; pydantic-ai-slim2.54.0, openai3.29.0, google-genai2.30.1, pydantic2.13.4, httpx2 2.13.1. Reuse these pins; no install/upgrade is proposed. Current adapter maps `max_tokens` to Responses `max_output_tokens` and Google `max_output_tokens`/wire `maxOutputTokens`. Output bounds include hidden tokens. [OpenAI accounting](https://developers.openai.com/api/docs/guides/token-counting), [Google thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking).

**Concrete Google blocker:** installed2.30.1 `_extra_utils.should_enable_automatic_continuation` defaults true; async Models loops HTTP hops on continuation tokens. PydanticAI2.54 Google config construction and Company SDK path do not explicitly disable it. Retry attempts1 is not continuation control. The proposed512 cap is below documented long-decode use, but a one-intent/one-POST invariant must not depend on that assumption. Disable via a supported seam and test a mocked continuation response before live Google use; no third-party patch or API switch. [Official continuation default and opt-out](https://ai.google.dev/gemini-api/docs/generate-content/long-decode). The supported repair uses the existing bounded response hook: WireObserver captures valid first-hop usage, then continuation markers are rejected before SDK adoption. The actual SDK/mock regression changes from two POSTs to one, with failed status and no adopted output. All71 focused conformance checks and independent source review pass. This does not disable the SDK default globally or prove live provider qualification. See ADR-131.

## Proposed qualification envelope — not spend authorization

The old2048-input/0.05USD proposal was conditional on an estimator that did not
exist. It is superseded for activation planning. The implemented candidate instead
reserves the full reviewed input ceiling. That is a conservative financial bound,
not proof that a prompt fits or a vendor will accept it. No guessed tokenizer or
unproven framing overhead supplies that guarantee.

| Provider | Financial input ceiling | Unqualified financial output ceiling | First output-cap probe hold | Later512-output quote, only after cap qualification |
| --- | --- | --- | --- | --- |
| OpenAI | 400000 | 128000 | 0.876000USD | 0.302304USD |
| Google | 1048576 | 65536 | 0.478413USD | 0.315853USD |

The actual requested output remains512. Before output-cap behavior is qualified,
the financial hold covers the documented full output ceiling too. Known actual
usage settles the hold; missing/ambiguous usage retains it. Arithmetic uses the
exact dated candidate prices above and six-decimal ceiling rounding.

The separate operational qualification goal uses one permanent owner-reviewed
Work allocation, proposed1.000000USD, with at most12 lifetime model attempts and
zero tools/rework/plan revisions. Both providers share that same Work and company
budget; its fixed target set is pinned. This allowance does not promise12 calls
or a complete six-call pilot: current held+spent money can deny the next request.
Changing a recipe, goal revision, day or request ID cannot reset the root.

Concurrency is1, public fixtures only, no tools, endpoint timeout30s, original
finite approval/recipe/price windows and one-use clients. Company held+spent money
counts against≤5USD on the `Asia/Bangkok` date under CompanyControl. Current live
budget/unknown holds were not queried. Stop on the first denied/failed/unknown
outcome; do not retry or switch providers after an ambiguous request. Neither
this packet nor the native preparation service approves or sends a paid call.

## Fresh no-model company: supported ordering and missing pieces

1. Keep current preview unactivated: `pilot_catalog(PREVIEW_PROFILE)` has zero models/profiles. Freeze a proposed complete candidate registry/PriceCards outside active work. Obtain genuine dated health, exact SDK/API conformance and profile evaluation receipts first; do not turn docs, TestModel score1 or an observation DTO into live eligibility.
2. **Bootstrap integration:** normal adapter/routing require enabled/current healthy/evaluated models before a governed call. Empty/unknown rows cannot bootstrap themselves. A separate public-only qualification service/client is now under integration, using actual owner approval, native holds/attempts/leases and its own protected evidence. Its result never claims profile quality or enables a model. Actual database delivery and approved live conformance are still required. Never write invented healthy/evaluation values.
3. Freeze initial exact enabled registry, dated shared pricebook, admitted profiles and source/role catalog before immutable planning Work. Observations can only refresh health/evaluations for original row SHA and originally declared profiles; cannot add a model/profile, enable it, or change endpoint/prices. The preview empty registry cannot be activated with an observation alone.
4. After prerequisites, use normal company001–016 and restricted application connections, then create public company/membership/goal/source/charter state and an owner-reviewed **planning-only initial PlanPayload** with permanently bounded model children using `ManagementPlanStore.propose/approve_and_register`. This admits model spend before generating a fuller revision2. A CompanyControlScope alone authorizes no request. Preserve the same root, quota, request/action IDs and budget; each call needs its actual signed actor/current execute lease and exact registered owner approval.
5. Existing execution seam: `ExecutionStore.claim` + `CompanyJournal.submit/approve_registered/authorize_registered`; bind `model_action_parameters(call, recipe)` and conservative quote to `model.request.v1`. Compose `PersistentModelCallAuthorizer(...management,resources,input_estimator,recipe,evidence_store,observations)` and `GovernedModelClient(...same registry/observations,execution,lease,identity).request_once`. Pre-intent/final/pre-SDK current checks remain mandatory. Protected ModelEvidence/native receipt/cost recording and bounded release follow; unknown or unconfirmed recording preserves the hold and consumed request.
6. Review actual request count, resolved model identity, raw usage, protected receipt and ledger before the next call. WireObserver currently requires exact returned OpenAI `model`/Google `modelVersion`, explicit reasoning/thought usage, totals and supported units. Actual Google alias spelling/zero-thought fields are unverified; mismatch stays denied/unknown, not silently normalized. Smoke/JSON checks prove compatibility only; representative Nexus reasoning/routine/verification quality remains separately measured and owner-reviewed.

The initial audit found no production concrete EndpointResolver, InputEstimator,
non-test GovernedModelClient caller, live qualification producer or owner
goal→planning bridge. The endpoint resolver is source-checked. The new
FullContextInputEstimator pins actual reviewed source/version/registry/model/recipe
identity; its whole-input mode keeps normal allowed-data and eligibility rules.
The new governed planning consumer returns a bounded historical candidate and
preserves its original goal/plan-head binding. These components and the separate
qualification path are under integration, rather than completed activation.
The owner goal→planning bridge, formal candidate mapping, actual quality and
runtime wiring remain open. Legacy `preflight.py`/`factory.py` direct Agent.run
paths are not Company-budgeted activation commands. No ready paid CLI is claimed.

Peer management source audit also identifies a later boundary: current native E/EV profile requires an engineering root with model_requests0 and exactly2 children. A reasoning/planning root that consumed model requests cannot simply become that native pair. Ordinary model-plan revision is supported; same-goal mixed planning/native composition needs a separate bounded design, not quota/root replacement.

## Existing offline command and release evidence

Future verification only, **not run here**, from `backend`:

```sh
env -u PYTHONPATH -u OPENAI_API_KEY -u GOOGLE_API_KEY -u GEMINI_API_KEY PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/santapong/.codex/nexus-local-runtime-20261014/bin/python -m pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin -p no:cacheprovider -q nexus/tests/unit/test_company_model_registry.py nexus/tests/unit/test_company_model_pricing.py nexus/tests/unit/test_company_model_authorizer.py nexus/tests/unit/test_company_model_client.py nexus/tests/unit/test_company_model_observations.py nexus/tests/unit/test_company_model_eligibility_gateway.py
```

Then Root reviews the combined resolver/estimator/qualification/planning boundary
and pinned-SDK one-POST/cap/usage/expiry negatives. The fresh restricted-PG
qualification integration uses its own exact test database, actual native stores
and SDKs over mock HTTP; it never targets the owner's preview. Only after this
passes can a concrete frozen paid packet be considered. Required actual receipt:
exact source/SDK/model/API/price/inputs, one native attempt per HTTP call, original
role/source windows, output/cost normalization, latency, recording/release status
and independent quality findings. Provider accounts, invoices and quality remain
unknown. No new agent framework is proposed.

Detailed original audit/source pins are retained locally at `/var/tmp/nexus-provider-readiness-20261016-1/READ_PINS.json`; original gateway/eligibility/pricing plans remain context rather than live qualification. Packet is ready for source planning and owner review, not activation.
