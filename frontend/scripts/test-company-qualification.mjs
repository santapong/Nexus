import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const directory = await mkdtemp(join(tmpdir(), 'nexus-model-checks-'))
try {
  const destination = join(directory, 'checks.mjs')
  await build({ stdin: { contents: [
    "export * from './src/api/companyQualification'",
    "export * from './src/hooks/companyQualificationActions'",
    "export * from './src/hooks/companyQualificationState'",
    "export * from './src/components/company/CompanyModelCheckResult'",
  ].join('\n'), resolveDir: process.cwd(), loader: 'tsx' }, bundle: true,
    platform: 'node', format: 'esm', outfile: destination, logLevel: 'silent',
    define: { 'import.meta.env': '{}' } })
  const values = new Map([['nexus_token', 'synthetic-model-check-session']])
  globalThis.localStorage = { getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const { companyQualificationApi: api, decideQualification, dispatchQualification,
    qualificationPhase, canDecideQualification, canDispatchQualification,
    CompanyModelCheckResult } = await import(pathToFileURL(destination))
  const hash = 'a'.repeat(64)
  const original = {
    observed_at: '2026-10-16T05:00:00Z',
    action: { company_id: 'company/id', state: 'awaiting_approval', proposal_hash: hash,
      consumed_at: null, approval: null, proposal: { company_id: 'company/id',
        action_id: 'action/id', task_id: 'task/id', trace_id: 'original-trace',
        tool: 'model.qualify.v1', tool_version: 'v1', estimated_cost_usd: '0.876000',
        parameters: { recipe_sha256: hash } } },
    recipe: { recipe_sha256: hash, availability: 'current',
      expires_at: '2026-10-17T00:00:00Z' },
    work: { company_id: 'company/id', state: 'eligible', registration: {
      workflow_name: 'company.model-qualification.v1', model_profile: 'qualification-only.v1',
      work: { company_id: 'company/id', task_id: 'task/id', trace_id: 'original-trace' } } },
    hold: null, effect: null, dispatch: null,
  }
  const clone = () => structuredClone(original)
  let current = clone()
  const requests = []
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init })
    return new Response(JSON.stringify(init.method === 'POST' ? { recorded: true } : current), { status: 200 })
  }
  await api.recipes('company/id')
  await api.prepare('company/id', 'public-json')
  await api.result('company/id', 'action/id')
  assert.equal(requests[0].url, '/api/v2/companies/company%2Fid/model-qualification/recipes')
  assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer synthetic-model-check-session')
  assert.deepEqual(JSON.parse(requests[1].init.body), { recipe_id: 'public-json' })
  assert.equal(requests[2].url, '/api/v2/companies/company%2Fid/model-qualification/actions/action%2Fid/result')
  assert.equal(requests.filter(item => item.init.method === 'POST').length, 1)

  requests.length = 0
  current.action.proposal_hash = 'b'.repeat(64)
  await assert.rejects(decideQualification('company/id', 'action/id', hash, true), /matches|changed/)
  assert.equal(requests.length, 1)
  current = clone()
  current.recipe.recipe_sha256 = 'b'.repeat(64)
  await assert.rejects(decideQualification('company/id', 'action/id', hash, true), /matches|changed/)
  current = clone()
  current.action.company_id = 'foreign-company'
  await assert.rejects(decideQualification('company/id', 'action/id', hash, true), /matches|changed/)
  assert.equal(requests.filter(item => item.init.method === 'POST').length, 0)

  current = clone()
  requests.length = 0
  await decideQualification('company/id', 'action/id', hash, true)
  assert.equal(requests.length, 2)
  assert.equal(requests[1].url, '/api/v2/companies/company%2Fid/work/task%2Fid/actions/action%2Fid/decision')
  assert.deepEqual(JSON.parse(requests[1].init.body), { schema_version: 'nexus.company.api.v1',
    trace_id: 'original-trace', expected_hash: hash, approved: true })
  assert.equal(qualificationPhase(current), 'awaiting_approval')
  assert.equal(canDispatchQualification(current, false), false)

  current.action.approval = { decision: 'approved', expires_at: '2026-10-17T00:00:00Z' }
  assert.equal(qualificationPhase(current), 'approved')
  requests.length = 0
  await dispatchQualification('company/id', 'action/id', hash)
  assert.equal(requests.length, 2)
  assert.equal(requests[1].url, '/api/v2/companies/company%2Fid/model-qualification/actions/action%2Fid/dispatch')
  assert.deepEqual(JSON.parse(requests[1].init.body), { expected_hash: hash })
  assert.equal(canDispatchQualification(current, true), false)
  current.observed_at = '2026-10-18T00:00:00Z'
  assert.equal(canDispatchQualification(current, false), false)
  assert.equal(qualificationPhase(current), 'expired')

  current = clone()
  current.work.state = 'outcome_unknown'
  current.effect = { state: 'outcome_unknown', evidence_sha256s: [hash] }
  current.hold = { state: 'unknown', amount_usd: '0.478413', actual_usd: null, day: '2026-10-16' }
  assert.equal(qualificationPhase(current), 'unknown')
  assert.equal(canDecideQualification(current, false, true), false)
  assert.equal(canDispatchQualification(current, false), false)
  requests.length = 0
  await assert.rejects(dispatchQualification('company/id', 'action/id', hash), /dispatch|changed/)
  assert.equal(requests.length, 1)
  const markup = renderToStaticMarkup(createElement(CompanyModelCheckResult, { status: current,
    result: { availability: 'available', native_outcome: 'outcome_unknown', actual_usd: null,
      captured_at: '2026-10-16T05:00:01Z', sha256: hash,
      provider_result: { billing: 'unknown', text: '<script>unsafe</script>', structured_json: null } } }))
  assert.match(markup, /Usage unconfirmed/)
  assert.match(markup, /0\.478413/)
  assert.ok(!markup.includes('<script>'))
  assert.ok(!markup.includes('Qualified') && !markup.includes('Company complete'))
  const history = clone()
  history.work.state = 'outcome_unknown'
  history.effect = { state: 'succeeded', evidence_sha256s: [hash] }
  assert.equal(qualificationPhase(history), 'recorded')
  assert.equal(canDispatchQualification(history, false), false)
  const failed = clone()
  failed.effect = { state: 'failed', evidence_sha256s: [hash] }
  failed.hold = { state: 'reconciled', amount_usd: '0.876000', actual_usd: '0.000165', day: '2026-10-16' }
  const safeText = renderToStaticMarkup(createElement(CompanyModelCheckResult, { status: failed,
    result: { availability: 'available', native_outcome: 'failed', actual_usd: '0.000165',
      captured_at: '2026-10-16T05:00:01Z', sha256: hash,
      provider_result: { billing: 'known', text: '<script>unsafe</script>', structured_json: null } } }))
  assert.match(safeText, /&lt;script&gt;/)
  assert.match(safeText, /Check stopped/)
  assert.ok(!safeText.includes('<script>'))
  const crossed = renderToStaticMarkup(createElement(CompanyModelCheckResult, { status: failed,
    result: { availability: 'available', native_outcome: 'succeeded', actual_usd: '0.000165',
      captured_at: '2026-10-16T05:00:01Z', sha256: 'b'.repeat(64),
      provider_result: { billing: 'known', text: 'FOREIGN_RESPONSE_BODY', structured_json: null } } }))
  assert.ok(!crossed.includes('FOREIGN_RESPONSE_BODY'))
  assert.match(crossed, /Check stopped/)
  console.log('Model-check routes, exact review, current dispatch, unknown billing and safe result rendering passed')
} finally {
  await rm(directory, { recursive: true, force: true })
}
