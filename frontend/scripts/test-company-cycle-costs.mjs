import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const directory = await mkdtemp(join(tmpdir(), 'nexus-cycle-finances-'))
try {
  const output = join(directory, 'checks.mjs')
  await build({ stdin: { contents: "export * from './src/api/companyCycleCosts'\nexport { CycleCostContent } from './src/components/company/CompanyCycleCosts'",
    resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, platform: 'node', format: 'esm',
    outfile: output, logLevel: 'silent', define: { 'import.meta.env': '{}' } })
  globalThis.localStorage = { getItem: () => 'synthetic-cycle-cost-session' }
  const { companyCycleCostApi, CycleCostContent } = await import(pathToFileURL(output))
  const requests = []
  globalThis.fetch = async (url, init) => { requests.push({ url, init }); return new Response('{}') }
  await companyCycleCostApi.read('company/id')
  assert.equal(requests[0].url, '/api/v2/companies/company%2Fid/management/cycle-costs')
  assert.equal(requests[0].init.cache, 'no-store')
  assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer synthetic-cycle-cost-session')
  const data = { company_id: 'company/id', goal: { goal_id: 'goal', revision_id: 'r1', sha256: 'a'.repeat(64) },
    observed_at: '2026-10-16T00:00:00Z', complete_membership: false, profile_bound: true,
    expected_task_ids: ['report-author'], missing_task_ids: ['missing'], extra_task_ids: [], mismatched_task_ids: [],
    totals: { known_spent_usd: '0.05', held_usd: null, actual_total_usd: null, unconfirmed_action_ids: ['unknown'] },
    blockers: ['missing_registered_work'], charges: [{ action_id: 'unknown', task_id: 'coder',
      attempt_kind: 'model_requests', ledger_actual_usd: '0.05', reserved_usd: '0.1', confirmation: 'unconfirmed',
      blockers: ['<script>source_denied</script>'], native_state: 'failed', hold_state: 'reconciled' }] }
  const markup = renderToStaticMarkup(createElement(CycleCostContent, { data }))
  assert.match(markup, /0\.05/)
  assert.match(markup, /Incomplete/)
  assert.match(markup, /Unknown/)
  assert.match(markup, /unconfirmed/)
  assert.match(markup, /&lt;script&gt;source denied&lt;\/script&gt;/)
  assert.ok(!markup.includes('<script>'))
  assert.ok(!markup.includes('Complete total'))
  console.log('Current cycle no-store read, retained spend, unknown totals and escaped blockers passed')
} finally { await rm(directory, { recursive: true, force: true }) }
