import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const directory = await mkdtemp(join(tmpdir(), 'nexus-planning-input-'))
try {
  const output = join(directory, 'checks.mjs')
  await build({ stdin: { contents: [
    "export * from './src/api/companyPlanning'",
    "export * from './src/hooks/companyPlanningActions'",
    "export * from './src/hooks/companyPlanningState'",
    "export * from './src/components/company/CompanyPlanningInput'",
  ].join('\n'), resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, platform: 'node',
    format: 'esm', outfile: output, logLevel: 'silent', define: { 'import.meta.env': '{}' } })
  const storage = new Map([['nexus_token', 'synthetic-planning-session']])
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  const { companyPlanningApi, decidePlanning, requirePlanningInputReview, canDecidePlanning,
    CompanyPlanningInput } = await import(pathToFileURL(output))
  const proposal = 'a'.repeat(64), request = 'b'.repeat(64), descriptor = 'c'.repeat(64)
  const recipe = 'f'.repeat(64)
  const call = { company_id: 'company/id', action_id: 'action/id', attempt_id: 'action/id',
    request_id: 'request/id', task_id: 'task/id', trace_id: 'native-trace', actor_id: 'actor',
    registry_id: 'planner', registry_revision: 'registry-v1', price_version: 'prices-v1',
    input_text: '<script>PRIVATE_INPUT</script>', system_text: 'Exact company instructions',
    bounds: { input_tokens: 400000, max_output_tokens: 512, input_bound_kind: 'model_input_ceiling_v1' },
    output_schema: { schema_json: '{"type":"object"}' }, tools: [] }
  const originalInput = { company_id: call.company_id, action_id: call.action_id,
    company_completed: false, execution_permitted: false,
    proposal_sha256: proposal, request_sha256: request, descriptor_sha256: descriptor,
    provider: 'openai', model_id: 'reviewed-model', maximum_reservation_usd: '0.302304', currency: 'USD',
    prepared: { request: call, request_sha256: request,
      binding: { goal: { company_id: call.company_id } },
      context: { input_text: call.input_text, system_text: call.system_text },
      input_recipe: { recipe_id: 'full-input', revision: 'v1', conformance_reference: 'source-pins' },
      input_estimate: { request_hash: request, registry_id: call.registry_id,
        registry_revision: call.registry_revision, recipe_id: 'full-input', recipe_revision: 'v1',
        whole_request: { method: 'model_input_ceiling_v1', tokens: 400000, recipe_sha256: recipe,
          registry_sha256: 'd'.repeat(64), model_sha256: 'e'.repeat(64), conformance_reference: 'source-pins' } } } }
  const originalReview = { company_id: call.company_id, availability: 'available',
    audit: { action_id: call.action_id, proposal_sha256: proposal, state: 'awaiting_approval', owner_decision: null },
    detail: { task_id: call.task_id, trace_id: call.trace_id, proposal_sha256: proposal,
      proposal: { company_id: call.company_id, action_id: call.action_id, actor_id: call.actor_id,
        task_id: call.task_id, trace_id: call.trace_id, tool: 'model.request.v1', tool_version: 'v1',
        resource: 'model:planner', estimated_cost_usd: '0.302304',
        parameters: { request_hash: request, request_id: call.request_id, attempt_id: call.attempt_id,
          registry_id: call.registry_id, registry_revision: call.registry_revision, price_version: call.price_version,
          input_recipe_id: 'full-input', input_recipe_revision: 'v1', input_recipe_hash: recipe },
        preconditions: [{ resource: 'planning.prepared:descriptor:revision', revision: `sha256:${descriptor}:bytes:1024` }] } } }
  let input = structuredClone(originalInput), review = structuredClone(originalReview)
  const requests = []
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init })
    return new Response(JSON.stringify(init.method === 'POST' ? { recorded: true }
      : url.endsWith('/input') ? input : review), { status: 200 })
  }
  await companyPlanningApi.input('company/id', 'action/id')
  assert.equal(requests[0].url, '/api/v2/companies/company%2Fid/planning/actions/action%2Fid/input')
  assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer synthetic-planning-session')
  assert.equal(requests[0].init.cache, 'no-store')
  requirePlanningInputReview(input, review, 'company/id', 'action/id', proposal, descriptor)
  assert.equal(canDecidePlanning(review, false), true)
  assert.equal(canDecidePlanning(review, true), false)
  const markup = renderToStaticMarkup(createElement(CompanyPlanningInput, { data: input }))
  assert.match(markup, /reviewed-model/)
  assert.match(markup, /0\.302304/)
  assert.match(markup, /&lt;script&gt;PRIVATE_INPUT&lt;\/script&gt;/)
  assert.ok(!markup.includes('<script>'))
  assert.match(markup, /512/)
  requests.length = 0
  await decidePlanning('company/id', 'action/id', proposal, descriptor, true)
  const writes = requests.filter(row => row.init.method === 'POST')
  assert.equal(writes.length, 1)
  assert.equal(writes[0].url, '/api/v2/companies/company%2Fid/work/task%2Fid/actions/action%2Fid/decision')
  assert.deepEqual(JSON.parse(writes[0].init.body), { schema_version: 'nexus.company.api.v1',
    trace_id: 'native-trace', expected_hash: proposal, approved: true })
  for (const mutation of [
    value => { value.company_id = 'foreign' },
    value => { value.proposal_sha256 = 'x'.repeat(64) },
    value => { value.descriptor_sha256 = 'x'.repeat(64) },
    value => { value.prepared.request.actor_id = 'foreign' },
    value => { value.prepared.request_sha256 = 'x'.repeat(64) },
    value => { value.prepared.context.input_text = 'CROSSED_BODY' },
    value => { value.prepared.input_estimate = null },
  ]) {
    input = structuredClone(originalInput); mutation(input); requests.length = 0
    await assert.rejects(decidePlanning('company/id', 'action/id', proposal, descriptor, true), /changed|match|unavailable/)
    assert.equal(requests.filter(row => row.init.method === 'POST').length, 0)
  }
  input = structuredClone(originalInput)
  review.audit.owner_decision = { decision: 'approved' }
  assert.equal(canDecidePlanning(review, false), false)
  requests.length = 0
  await assert.rejects(decidePlanning('company/id', 'action/id', proposal, descriptor, true), /changed|decid/)
  assert.equal(requests.filter(row => row.init.method === 'POST').length, 0)
  console.log('Planning input auth, exact-source joins, fresh decisions, no extra effects and escaped rendering passed')
} finally {
  await rm(directory, { recursive: true, force: true })
}
