# Provider pricing research for the supervised release

Checked2026-10-15 against fetched official documentation and backendf4cc659.
This is a candidate list and illustrative arithmetic. No provider/account access,
registry/pricebook change, health/evaluation evidence or paid request was created.

The current company adapter implements OpenAI Responses and Google GenerateContent.
The broader registry also describes compatible APIs, but CompanyModelAdapters
explicitly rejects unsupported families. Legacy usage.py prices are not the
company PriceCard authority and must not supply an implicit release fallback.

| Candidate | Input USD/1M | Output USD/1M | Token-only example:20k input+4k total output | Source |
| --- | ---: | ---: | ---: | --- |
| OpenAI `gpt-5.4-mini-2026-03-17` |0.75 |4.50 |0.033000 | [Official model pricing and snapshot](https://developers.openai.com/api/docs/models/gpt-5.4-mini) |
| Google `gemini-3.5-flash-lite` |0.30 |2.50 |0.016000 | [Official Standard paid pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite), [stable model ID](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) |
| Groq `openai/gpt-oss-120b` — later adapter candidate |0.15 |0.60 |0.005400 | [Official Groq model pricing](https://console.groq.com/docs/model/openai/gpt-oss-120b) |

OpenAI lists the dated snapshot and structured output/tool support. The older
GPT-5 Mini page now marks that model deprecated; its lower historical price alone
is insufficient for a new release choice. No migration is performed here.
[OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5-mini)

Google's listed output rate includes thinking tokens. Its pricing separates
caching/storage and grounding charges; the example uses ordinary text only.
Its model page identifies the stable ID and structured outputs/function calling.
This does not establish compatibility with the pinned SDK's actual endpoint.
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite),
[Google model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)

The Groq option is research only: current company execution does not support its
required adapter family. Adding that path needs an explicit scoped implementation
and conformance qualification; changing provider labels cannot make it supported.

Derived example: three calls to each of the first two candidates, each bounded to
20k total input and4k total billed output, sum to0.147000USD at these text rates.
That is a token calculation, not an invoice, spend authorization or proven cap.
The arithmetic record is model-gate/PRICING_RESEARCH_CALCULATIONS_2026-10-15.json,
SHA256 `5fdc3da5245f03693c3927e8090bba8e81421f29c88f4a8eef64600195458527`.

Before an actual bounded pilot, freeze exact model/endpoint/API, current dated
PriceCards, provider-enforced total-output semantics, complete input framing/schema
bound and raw usage normalization. Use native current authorization/attempt/hold
gates and the Bangkok-day5USD ceiling, with all existing unknown holds conserved.
Record real task quality and usage separately from SDK conformance; unavailable
usage stays unknown without automatic retry or refund. Candidate pricing does not
replace any of those release requirements. Re-fetch prices at pilot preparation.
