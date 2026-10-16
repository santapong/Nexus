import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const directory = await mkdtemp(join(tmpdir(), 'nexus-coding-owner-'))
try {
  const output = join(directory, 'checks.mjs')
  await build({ stdin: { contents: [
    "export * from './src/api/companyCoding'",
    "export * from './src/hooks/companyCodingActions'",
    "export * from './src/hooks/companyCodingState'",
    "export * from './src/components/company/CompanyCodingInput'",
    "export { CodingCandidateContent } from './src/components/company/CompanyCodingCandidate'",
    "export { setCompanySessionToken } from './src/api/company'",
  ].join('\n'), resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, platform: 'node',
    format: 'esm', outfile: output, logLevel: 'silent', define: { 'import.meta.env': '{}' } })
  const storage = new Map([['nexus_token', 'synthetic-coding-session']])
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  const { companyCodingApi, decideCoding, dispatchCoding, requireCodingInputReview,
    canDecideCoding, canPrepareCoding, canDispatchCoding, canRecoverCodingWait,
    codingStage, CompanyCodingInput, CodingCandidateContent, setCompanySessionToken } = await import(pathToFileURL(output))
  const hash = 'a'.repeat(64), requestHash = 'b'.repeat(64), headerHash = 'c'.repeat(64)
  const goal = { company_id: 'company/id', goal_id: 'goal/id', revision_id: 'goal-r1', sha256: 'd'.repeat(64) }
  const call = { company_id: goal.company_id, action_id: 'action/id', attempt_id: 'action/id',
    task_id: 'task/id', trace_id: 'trace', actor_id: 'coder', request_id: 'request',
    registry_id: 'coder-model', registry_revision: 'registry-v1', price_version: 'price-v1',
    input_text: '<script>PRIVATE_SOURCE</script>', system_text: 'Company coding instructions', tools: [],
    bounds: { input_tokens: 10000, max_output_tokens: 512, input_bound_kind: 'model_input_ceiling_v1' },
    output_schema: { schema_json: '{"type":"object"}' } }
  const prepared = { request: call, request_sha256: requestHash,
    context: { input_text: call.input_text, system_text: call.system_text },
    binding: { goal, plan: { plan_revision_id: 'head' }, task_id: call.task_id, trace_id: call.trace_id,
      actor_id: call.actor_id, allowed_write_paths: ['src/app.py'], source: { commit: 'commit-pin' } },
    input_recipe: { recipe_id: 'code-input', revision: 'v1', conformance_reference: 'proof-v1' },
    input_estimate: { request_hash: requestHash, registry_id: call.registry_id,
      registry_revision: call.registry_revision, recipe_id: 'code-input', recipe_revision: 'v1',
      whole_request: { tokens: 10000, method: 'model_input_ceiling_v1',
        recipe_sha256: 'e'.repeat(64), model_sha256: 'f'.repeat(64), registry_sha256: '1'.repeat(64),
        conformance_reference: 'proof-v1' } } }
  const proposal = { company_id: call.company_id, action_id: call.action_id, actor_id: call.actor_id,
    task_id: call.task_id, trace_id: call.trace_id, tool: 'model.request.v1', tool_version: 'v1',
    resource: 'model:coder-model', estimated_cost_usd: '0.05',
    parameters: { request_hash: requestHash, request_id: call.request_id, attempt_id: call.action_id,
      registry_id: call.registry_id, registry_revision: call.registry_revision, price_version: call.price_version,
      input_recipe_id: 'code-input', input_recipe_revision: 'v1', input_recipe_hash: '2'.repeat(64) },
    preconditions: [{ resource: `coding.prepared:${call.action_id}`, revision: `sha256:${headerHash}:bytes:1234` }] }
  const originalInput = { company_id: call.company_id, action_id: call.action_id, prepared,
    proposal, proposal_sha256: hash, request_sha256: requestHash, header_sha256: headerHash,
    reference: { company_id: call.company_id, action_id: call.action_id, request_sha256: requestHash,
      header: { company_id: call.company_id, sha256: headerHash, byte_length: 1234 } },
    model: { registry_id: call.registry_id, provider: 'openai', model_id: 'reviewed-coder' }, maximum_reservation_usd: '0.05',
    currency: 'USD', company_completed: false, execution_permitted: false }
  const originalReview = { company_id: call.company_id, availability: 'available',
    audit: { action_id: call.action_id, proposal_sha256: hash, state: 'awaiting_approval', owner_decision: null, consumed_at: null },
    detail: { task_id: call.task_id, trace_id: call.trace_id, proposal_sha256: hash, proposal } }
  const originalStatus = { company_id: call.company_id, goal, current: { plan_revision_id: 'head' }, approved_r2: true,
    observed_at: '2026-10-16T00:00:00Z', action_id: call.action_id, proposal_sha256: hash,
    action_state: 'awaiting_approval', work_state: 'awaiting_approval', workflow_id: null,
    native_state: null, resources_pending: false, company_completed: false }
  let input = structuredClone(originalInput), review = structuredClone(originalReview), status = structuredClone(originalStatus)
  const requests = []
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init })
    const value = init.method === 'POST' ? { recorded: true } : url.endsWith('/input') ? input
      : url.endsWith('/status') ? status : review
    return new Response(JSON.stringify(value), { status: 200 })
  }
  requireCodingInputReview(input, review, call.company_id, call.action_id, hash, headerHash)
  input.proposal.parameters = Object.fromEntries(Object.entries(input.proposal.parameters).reverse())
  requireCodingInputReview(input, review, call.company_id, call.action_id, hash, headerHash)
  input = structuredClone(originalInput)
  assert.equal(canDecideCoding(review, false), true)
  assert.equal(canDecideCoding(review, true), false)
  const markup = renderToStaticMarkup(createElement(CompanyCodingInput, { data: input }))
  assert.match(markup, /reviewed-coder/)
  assert.match(markup, /0\.05/)
  assert.match(markup, /&lt;script&gt;PRIVATE_SOURCE&lt;\/script&gt;/)
  assert.ok(!markup.includes('<script>'))
  requests.length = 0
  await decideCoding(call.company_id, call.action_id, hash, headerHash, true)
  assert.equal(requests.filter(row => row.init.method === 'POST').length, 1)
  assert.deepEqual(JSON.parse(requests.at(-1).init.body), { schema_version: 'nexus.company.api.v1',
    trace_id: call.trace_id, expected_hash: hash, approved: true })
  for (const mutate of [v => { v.header_sha256 = '9'.repeat(64) },
    v => { v.company_id = 'foreign' }, v => { v.reference.request_sha256 = '9'.repeat(64) },
    v => { v.prepared.binding.actor_id = 'foreign' }, v => { v.prepared.context.input_text = 'crossed' },
    v => { v.proposal.parameters.request_id = 'crossed' },
    v => { v.model.registry_id = 'crossed-model' },
    v => { v.prepared.input_estimate.whole_request = null },
    v => { v.prepared.request.tools = ['unexpected'] }]) {
    input = structuredClone(originalInput); mutate(input); requests.length = 0
    await assert.rejects(decideCoding(call.company_id, call.action_id, hash, headerHash, true), /match|unavailable|changed/)
    assert.equal(requests.filter(row => row.init.method === 'POST').length, 0)
  }
  input = structuredClone(originalInput)
  review.audit.owner_decision = { decision: 'approved', action_id: call.action_id, action_hash: hash,
    expires_at: '2040-01-01T00:00:00Z', issued_at: '2026-10-16T00:00:00Z' }
  assert.equal(canDispatchCoding(status, review), true)
  requests.length = 0
  await dispatchCoding(call.company_id, call.action_id, hash, { goal, expected_current_revision_id: 'head' })
  assert.equal(requests.filter(row => row.init.method === 'POST').length, 1)
  assert.equal(requests.at(-1).url, '/api/v2/companies/company%2Fid/coding/actions/action%2Fid/dispatch')
  for (const change of [{ workflow_id: 'issued' }, { native_state: 'outcome_unknown' },
    { resources_pending: true }, { approved_r2: false }, { work_state: 'blocked' }]) {
    status = { ...originalStatus, ...change }; requests.length = 0
    await assert.rejects(dispatchCoding(call.company_id, call.action_id, hash, { goal, expected_current_revision_id: 'head' }))
    assert.equal(requests.filter(row => row.init.method === 'POST').length, 0)
  }
  status = structuredClone(originalStatus)
  review.audit.owner_decision.expires_at = '2000-01-01T00:00:00Z'
  assert.equal(canDispatchCoding(status, review), false)
  assert.equal(canPrepareCoding({ ...status, action_id: null, proposal_sha256: null, work_state: 'eligible' }), true)
  assert.equal(canPrepareCoding({ ...status, action_id: null, work_state: 'eligible', approved_r2: false }), false)
  assert.equal(canRecoverCodingWait({ ...status, work_state: 'blocked' }, originalReview), true)
  assert.match(codingStage({ ...status, native_state: 'outcome_unknown' }), /unconfirmed|held/)
  requests.length = 0
  await companyCodingApi.prepare(call.company_id, { goal, expected_current_revision_id: 'head' })
  await companyCodingApi.candidate(call.company_id, call.action_id, 'head/id')
  await companyCodingApi.recoverWait(call.company_id, call.action_id,
    { goal, expected_current_revision_id: 'head', expected_hash: hash })
  assert.ok(requests.every(row => row.init.cache === 'no-store'))
  assert.ok(requests[1].url.endsWith('/candidate?expected_current_revision_id=head%2Fid'))
  const candidate = renderToStaticMarkup(createElement(CodingCandidateContent, { data: {
    recorded_at: '2026-10-16T00:00:00Z', content: { patch: '<script>UNTRUSTED_PATCH</script>',
      explanation: 'Proposed change', questions: ['Needs independent verification'], evidence_ids: [] },
    binding: { allowed_write_paths: ['src/app.py'] }, receipt_id: 'receipt', artifact_sha256: hash,
  } }))
  assert.match(candidate, /&lt;script&gt;UNTRUSTED_PATCH&lt;\/script&gt;/)
  assert.ok(!candidate.includes('<script>'))
  assert.match(candidate, /independent verification/)
  input = structuredClone(originalInput); review = structuredClone(originalReview); requests.length = 0
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init }); setCompanySessionToken('new-synthetic-session')
    return new Response(JSON.stringify(url.endsWith('/input') ? input : review))
  }
  await assert.rejects(decideCoding(call.company_id, call.action_id, hash, headerHash, true), /session changed/)
  assert.equal(requests.filter(row => row.init.method === 'POST').length, 0)
  console.log('Coding exact input, fresh decisions/dispatch, blocked ambiguity and escaped candidate checks passed')
} finally { await rm(directory, { recursive: true, force: true }) }
