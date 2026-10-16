import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const directory = await mkdtemp(join(tmpdir(), 'nexus-knowledge-api-'))
try {
  const destination = join(directory, 'api.mjs')
  await build({ entryPoints: ['src/api/company.ts'], bundle: true, platform: 'node', format: 'esm',
    outfile: destination, logLevel: 'silent', define: { 'import.meta.env': '{}' } })
  const storage = new Map()
  globalThis.localStorage = { getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
  const { companyApi, CompanyApiError, setCompanySessionToken } = await import(pathToFileURL(destination))
  setCompanySessionToken('synthetic-session')
  const requests = []
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init })
    return new Response(JSON.stringify({ source: 'actual mocked HTTP response' }), { status: 200 })
  }
  const search = { search: { query: 'Nexus', include_history: false, explicit_evidence_ids: [], entity_ids: [], claim_kinds: [] } }
  await companyApi.searchKnowledge('company/id', search)
  assert.equal(requests[0].url, '/api/v2/companies/company%2Fid/brain/search')
  assert.deepEqual(JSON.parse(requests[0].init.body), search)
  assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer synthetic-session')
  await companyApi.evidence('company/id', 'citation/id')
  assert.equal(requests[1].url, '/api/v2/companies/company%2Fid/brain/evidence/citation%2Fid')
  const goal = { definition: { goal_id: 'known-request-id' }, version: 'v1', expected_revision_id: null }
  await companyApi.createGoal('company/id', goal)
  assert.equal(requests[2].url, '/api/v2/companies/company%2Fid/management/goals')
  assert.deepEqual(JSON.parse(requests[2].init.body), goal)
  assert.equal(requests[2].init.method, 'POST')
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Brain resource unavailable' }), { status: 403 })
  await assert.rejects(companyApi.evidence('company', 'citation'), error => error instanceof CompanyApiError && error.status === 403)
  console.log('Knowledge/goal client routes, authentication, exact body and permission denial checks passed')
} finally { await rm(directory, { recursive: true, force: true }) }
