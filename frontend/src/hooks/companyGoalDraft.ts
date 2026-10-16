import type { BrainRetrievalResult, BrainSearchRead, CompanyIdentity, CompanyView, DueIntent, GoalPublish, MaterializedEvidence } from '@/types/company'

export interface GoalDraftValues { title: string; target: string; due: string; reason: string }
export interface CitationSummary { evidenceId: string; label: string; sourceDate: string; ingestedAt: string }

function object(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null }

export function citationSummaries(result: BrainRetrievalResult, company: string): CitationSummary[] {
  return result.handles.flatMap(row => {
    if (!object(row) || !object(row.handle) || !object(row.handle.record)) return []
    const record = row.handle.record
    if (row.handle.company_id !== company || record.company_id !== company
      || typeof record.evidence_id !== 'string' || !object(record.artifact) || !object(record.raw_span)
      || !object(record.source_event) || typeof record.ingested_at !== 'string') return []
    const label = [record.raw_span.path, record.raw_span.section, record.artifact.revision]
      .find((value): value is string => typeof value === 'string' && Boolean(value)) || 'Source excerpt'
    return [{ evidenceId: record.evidence_id, label, ingestedAt: record.ingested_at,
      sourceDate: typeof record.source_event.value === 'string' ? record.source_event.value : 'Date unknown' }]
  })
}

export function searchRequest(value: string): BrainSearchRead {
  const query = value.trim()
  if (!query || new TextEncoder().encode(query).length > 2000)
    throw new Error('Enter a search of up to 2,000 UTF-8 bytes.')
  return { search: { query, explicit_evidence_ids: [], entity_ids: [], claim_kinds: [], include_history: false } }
}

export function desiredGoalDate(due: DueIntent): string {
  const source = due.source_time
  return `Desired date: ${source.value ?? 'Unknown'} (${source.precision}) · ${source.basis}`
}

export function goalAvailability(identity: CompanyIdentity, company: CompanyView, evidence: MaterializedEvidence, revalidating = false): string | null {
  if (revalidating) return 'Revalidating current access and citation. Saving is temporarily unavailable.'
  if (identity.membership_role !== 'owner' || identity.principal_id !== identity.owner_id
    || !identity.company_active || !identity.workspace_active || !identity.principal_active || !identity.membership_active)
    return 'Current owner access is required to create a goal.'
  if (company.company_id !== identity.company_id || evidence.company_id !== identity.company_id
    || evidence.record.company_id !== identity.company_id)
    return 'This citation and company no longer match your current workspace.'
  if (company.paused) return 'The company is paused. Your cited draft can be reviewed after it resumes.'
  if (!company.mandate?.active) return 'A current owner-approved mandate is required before creating a goal.'
  if (company.mandate.revision.mandate.goals.length > 0)
    return 'The current mandate limits which goals may exist. An owner must update that mandate before adding a new goal.'
  if (evidence.source_state !== 'current' || evidence.freshness === 'stale')
    return 'This source is historical or stale. Refresh the source before creating a goal from it.'
  return null
}

export function goalRequest(identity: CompanyIdentity, company: CompanyView, evidence: MaterializedEvidence,
  goalId: string, values: GoalDraftValues): GoalPublish {
  const blocked = goalAvailability(identity, company, evidence)
  if (blocked) throw new Error(blocked)
  const title = values.title.trim(), reason = values.reason.trim()
  if (!title || title.length > 128) throw new Error('Give the goal a title of up to 128 characters.')
  if (!reason || reason.length > 128) throw new Error('Explain the unknown baseline in up to 128 characters.')
  if (!/^[1-9]\d{0,8}$/.test(values.target)) throw new Error('Choose a target count from 1 to 999,999,999.')
  if (values.due && (!/^\d{4}-\d{2}-\d{2}$/.test(values.due)
    || !Number.isFinite(Date.parse(values.due)) || new Date(values.due).toISOString().slice(0, 10) !== values.due))
    throw new Error('Choose a valid calendar date.')
  const mandate = company.mandate!.revision
  return {
    definition: { schema_version: 'nexus.company.management.v1', company_id: identity.company_id,
      goal_id: goalId, title, owner_id: identity.principal_id,
      mandate: { schema_version: 'nexus.company.management.v1', company_id: mandate.company_id,
        revision_id: mandate.revision_id, version: mandate.version, sha256: mandate.sha256 },
      metrics: [{ schema_version: 'nexus.company.management.v1', company_id: identity.company_id,
        metric_id: 'verified-items', unit: 'items', comparator: 'ge', target: values.target,
        observation_recipe: null, baseline: { kind: 'unknown', reason, evidence: [{
          schema_version: 'nexus.company.brain.v1', company_id: identity.company_id, evidence_id: evidence.record.evidence_id,
        }] } }],
      due: { source_time: values.due ? { precision: 'day', value: values.due, basis: 'Owner selected date' }
        : { precision: 'unknown', value: null, basis: 'No deadline selected' }, actionable_at: null, actionable_basis: null },
    }, version: 'v1', expected_revision_id: null,
  }
}
