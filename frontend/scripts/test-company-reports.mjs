import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const directory = await mkdtemp(join(tmpdir(), 'nexus-company-reports-'))
try {
  const destination = join(directory, 'client.mjs')
  await build({ entryPoints: ['src/api/company.ts'], bundle: true, platform: 'node', format: 'esm',
    outfile: destination, define: { 'import.meta.env': '{}' }, logLevel: 'silent' })
  globalThis.localStorage = { getItem: () => null }
  const requests = []
  globalThis.fetch = async (path, init) => {
    requests.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body) : null })
    return new Response(JSON.stringify({ report_id: 'saved-report' }), { status: 200 })
  }
  const { companyApi } = await import(pathToFileURL(destination))
  const body = { plan_revision_id: 'revision', author_task_id: 'author', selected_task_ids: ['work'],
    period_start: '2026-10-13T00:00:00.000Z', period_end: '2026-10-14T00:00:00.000Z' }
  await companyApi.saveReport('company/one', body)
  assert.deepEqual(requests[0], { path: '/api/v2/companies/company%2Fone/management/reports/', method: 'POST', body })
  await companyApi.report('company/one', 'report/one')
  assert.equal(requests[1].path, '/api/v2/companies/company%2Fone/management/reports/report%2Fone')
  const profile = { report_id: 'saved-report', commitment_id: 'commitment', evidence_ids: ['evidence'] }
  await companyApi.resolveReportProfile('company/one', profile)
  assert.deepEqual(requests[2].body, profile)
  const reference = { report_id: 'saved-report', report_sha256: 'actual-server-pin' }
  await companyApi.prepareReportAuthor('company/one', reference)
  assert.deepEqual(requests[3].body, { reference })
  assert.equal(requests[3].path, '/api/v2/companies/company%2Fone/management/reports/profiles/prepare-author')
  assert.equal(requests.length, 4)
  console.log('4 exact company report request checks passed; no network or credential')
} finally {
  await rm(directory, { recursive: true, force: true })
}
