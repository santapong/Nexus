import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { companyApi, companySessionVersion } from '@/api/company'
import type { MetricObservationIntent, PlanView } from '@/types/company'

export function useCompanyMetrics(company: string, goal: string, after?: string | null) {
  return useQuery({ queryKey: ['company', company, 'metrics', goal, after, companySessionVersion()],
    queryFn: () => companyApi.metrics(company, goal, after), retry: false, staleTime: 0 })
}

export function useMetricObservation(plan: PlanView) {
  const client = useQueryClient()
  const [attempt, setAttempt] = useState<MetricObservationIntent | null>(null)
  const mutation = useMutation({ mutationFn: (body: MetricObservationIntent) => companyApi.observeMetric(plan.company_id, body),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['company', plan.company_id] }) } })
  const observe = (metric: string, tasks: string[]) => {
    const body = attempt ?? { operation_id: crypto.randomUUID(), audit_trace_id: crypto.randomUUID(),
      request: { schema_version: 'nexus.company.management.v1' as const, company_id: plan.company_id,
        observation_id: crypto.randomUUID(), goal: plan.declaration.goal, plan: plan.reference,
        metric_id: metric, task_ids: tasks } }
    setAttempt(body)
    mutation.mutate(body)
  }
  const newObservation = () => { setAttempt(null); mutation.reset() }
  return { attempt, mutation, observe, newObservation }
}

export function useRecordedMetric(company: string, observation: string) {
  return useMutation({ mutationFn: () => companyApi.recordedMetric(company, observation) })
}
