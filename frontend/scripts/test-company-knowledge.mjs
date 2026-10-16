import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const directory = await mkdtemp(join(tmpdir(), 'nexus-company-knowledge-'))
try {
  const destination = join(directory, 'knowledge.mjs')
  await build({ entryPoints: ['src/hooks/companyGoalDraft.ts'], bundle: true, platform: 'node',
    format: 'esm', outfile: destination, logLevel: 'silent' })
  const { searchRequest, goalAvailability, goalRequest, citationSummaries } = await import(pathToFileURL(destination))
  const id = '10000000-0000-4000-8000-000000000001'
  const identity = { company_id: id, principal_id: id, owner_id: id, membership_role: 'owner',
    company_active: true, workspace_active: true, principal_active: true, membership_active: true }
  const company = { company_id: id, paused: false, mandate: { active: true,
    revision: { company_id: id, revision_id: id, version: 'v1', sha256: 'a'.repeat(64), mandate: { goals: [] } } } }
  const evidence = { company_id: id, source_state: 'current', freshness: 'fresh',
    record: { company_id: id, evidence_id: id } }
  assert.equal(searchRequest('  Nexus operating report ').search.query, 'Nexus operating report')
  for (const query of ['', ' ', 'ก'.repeat(667)]) assert.throws(() => searchRequest(query), /search/i)
  assert.equal(goalAvailability(identity, company, evidence), null)
  assert.match(goalAvailability(identity, company, evidence, true), /revalidat/i)
  for (const changed of [{ ...company, paused: true }, { ...company, mandate: null },
    { ...company, mandate: { ...company.mandate, revision: { ...company.mandate.revision, mandate: { goals: [id] } } } }])
    assert.equal(typeof goalAvailability(identity, changed, evidence), 'string')
  for (const changed of [{ ...evidence, source_state: 'historical' }, { ...evidence, freshness: 'stale' },
    { ...evidence, company_id: 'foreign' }])
    assert.equal(typeof goalAvailability(identity, company, changed), 'string')
  const values = { title: 'Clarify the Nexus operating guide', target: '1', due: '2026-11-02',
    reason: 'No current count has been recorded.' }
  const request = goalRequest(identity, company, evidence, id, values)
  assert.equal(request.definition.metrics[0].target, '1')
  assert.equal(request.definition.metrics[0].baseline.kind, 'unknown')
  assert.deepEqual(request.definition.metrics[0].baseline.evidence[0], {
    schema_version: 'nexus.company.brain.v1', company_id: id, evidence_id: id })
  assert.deepEqual(request.definition.due.source_time, { precision: 'day', value: '2026-11-02', basis: 'Owner selected date' })
  assert.equal(request.definition.due.actionable_at, null)
  assert.equal(request.expected_revision_id, null)
  assert.equal(request.definition.mandate.revision_id, company.mandate.revision.revision_id)
  const undated = { ...evidence, freshness: 'unknown' }
  assert.equal(goalAvailability(identity, company, undated), null,
    'Current permitted citations with unknown freshness can frame an unknown-baseline goal')
  const unknownGoal = goalRequest(identity, company, undated, id, values)
  assert.equal(unknownGoal.definition.metrics[0].baseline.kind, 'unknown')
  assert.equal(unknownGoal.definition.metrics[0].baseline.evidence[0].evidence_id, id)
  assert.equal(typeof goalAvailability(identity, company, { ...undated, source_state: 'historical' }), 'string')
  assert.equal(typeof goalAvailability(identity, company, undated, true), 'string')
  for (const changed of [{ ...values, target: '0' }, { ...values, target: '1e3' },
    { ...values, title: '' }, { ...values, due: '2026-02-30' }])
    assert.throws(() => goalRequest(identity, company, evidence, id, changed))
  assert.throws(() => goalRequest(identity, { ...company, paused: true }, evidence, id, values))
  const citation = { handle: { company_id: id, record: { ...evidence.record, artifact: { revision: 'Nexus guide' },
    raw_span: {}, source_event: { value: null }, ingested_at: '2026-10-16T00:00:00Z' } } }
  assert.equal(citationSummaries({ handles: [citation] }, id)[0].label, 'Nexus guide')
  assert.deepEqual(citationSummaries({ handles: [null, {}, citation] }, 'foreign'), [])
  console.log('Knowledge search, citation, mandate and truthful goal-input checks passed')
} finally {
  await rm(directory, { recursive: true, force: true })
}
