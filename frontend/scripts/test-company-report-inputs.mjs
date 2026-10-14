import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const directory = await mkdtemp(join(tmpdir(), 'nexus-company-report-inputs-'))
try {
  const destination = join(directory, 'inputs.mjs')
  await build({ entryPoints: ['src/hooks/companyReportInputs.ts'], bundle: true, platform: 'node',
    format: 'esm', outfile: destination, logLevel: 'silent' })
  const { reportPeriod, evidenceSelection, reportSelection } = await import(pathToFileURL(destination))
  assert.deepEqual(reportPeriod('2026-10-13T09:00', '2026-10-14T09:00'), {
    period_start: new Date('2026-10-13T09:00').toISOString(),
    period_end: new Date('2026-10-14T09:00').toISOString(),
  })
  for (const [start, end] of [['', '2026-10-14'], ['invalid', '2026-10-14'], ['2026-10-14', '2026-10-13']])
    assert.throws(() => reportPeriod(start, end), /ordered period/)
  const uuid = '10000000-0000-4000-8000-000000000001'
  assert.deepEqual(evidenceSelection(`  ${uuid} \n`), [uuid])
  for (const value of ['', `${uuid},${uuid}`, 'not-an-id', Array(33).fill(uuid).join(',')])
    assert.throws(() => evidenceSelection(value), /unique evidence/)
  assert.deepEqual(reportSelection(['work'], ['work'], 'author', 'verifier'), ['work'])
  for (const ids of [['work', 'work'], ['unknown'], ['author'], ['verifier']])
    assert.throws(() => reportSelection(ids, ['work', 'author', 'verifier'], 'author', 'verifier'), /existing work/)
  console.log('14 report period/evidence/native selection checks passed')
} finally {
  await rm(directory, { recursive: true, force: true })
}
