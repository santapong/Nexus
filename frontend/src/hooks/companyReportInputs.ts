import type { NewReportSnapshot } from '@/types/company'

export function reportPeriod(start: string, end: string): Pick<NewReportSnapshot, 'period_start' | 'period_end'> {
  const first = new Date(start), last = new Date(end)
  if (!start || !end || !Number.isFinite(first.getTime()) || !Number.isFinite(last.getTime()) || last <= first)
    throw new Error('Choose an ordered period with a start before its end.')
  return { period_start: first.toISOString(), period_end: last.toISOString() }
}

export function evidenceSelection(value: string): string[] {
  const ids = value.trim().split(/[\s,]+/).filter(Boolean).map(id => id.toLowerCase())
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
  if (ids.length < 1 || ids.length > 32 || new Set(ids).size !== ids.length || ids.some(id => !uuid.test(id)))
    throw new Error('Choose 1–32 unique evidence artifact IDs from the company Brain.')
  return ids
}

export function reportSelection(ids: string[], allowed: string[], author: string, verifier: string): string[] {
  if (ids.length > 100 || new Set(ids).size !== ids.length
    || ids.some(id => !allowed.includes(id) || id === author || id === verifier))
    throw new Error('Select existing work once, excluding the report author and verifier.')
  return ids
}
