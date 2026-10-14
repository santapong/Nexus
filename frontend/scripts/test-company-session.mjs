import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const directory = await mkdtemp(join(tmpdir(), 'nexus-company-session-'))
const destination = join(directory, 'client.mjs')
try {
  await build({ entryPoints: ['src/api/company.ts'], bundle: true, platform: 'node', format: 'esm',
    outfile: destination, define: { 'import.meta.env': '{}' }, logLevel: 'silent' })
  const values = new Map()
  globalThis.localStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key),
  }
  const { companyFetch, companySessionVersion, setCompanySessionToken } = await import(pathToFileURL(destination))
  let resolveRequest
  globalThis.fetch = () => new Promise(resolve => { resolveRequest = resolve })
  setCompanySessionToken('disposable-old-session')
  const initialVersion = companySessionVersion()
  const previousRead = companyFetch('/bounded-test')
  setCompanySessionToken('disposable-new-session')
  resolveRequest(new Response(JSON.stringify({ private: 'old-owner-value' }), { status: 200 }))
  await assert.rejects(previousRead, /Company session changed/)
  assert.ok(companySessionVersion() > initialVersion)

  const previousError = companyFetch('/bounded-test')
  setCompanySessionToken('disposable-newer-session')
  resolveRequest(new Response(JSON.stringify({ detail: 'old-401' }), { status: 401 }))
  await assert.rejects(previousError, /Company session changed/)
  assert.equal(localStorage.getItem('nexus_token'), 'disposable-newer-session')

  let resolveBody
  globalThis.fetch = async () => ({ ok: true, json: () => new Promise(resolve => { resolveBody = resolve }) })
  const delayedBody = companyFetch('/bounded-test')
  await new Promise(resolve => setImmediate(resolve))
  setCompanySessionToken(null)
  resolveBody({ private: 'old-body-after-logout' })
  await assert.rejects(delayedBody, /Company session changed/)

  setCompanySessionToken('disposable-current-session')
  globalThis.fetch = async () => new Response(JSON.stringify({ current: true }), { status: 200 })
  assert.deepEqual(await companyFetch('/bounded-test'), { current: true })
  console.log('4 company session race/current-response checks passed; no network or issued JWT used')
} finally {
  await rm(directory, { recursive: true, force: true })
}
