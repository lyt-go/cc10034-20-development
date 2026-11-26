/** 结果复核包接口：复核包构建/详情、参数证据登记、复核申请与提交。 */
import { request } from './client'
import type {
  ParamEvidence,
  ParamVersion,
  ReviewEnvelope,
  ReviewPackage,
  ReviewRequest,
} from '@/data/types'

async function asJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

export async function fetchParamVersions(): Promise<{
  items: ParamVersion[]
  current: string
}> {
  const response = await request('/api/review/param-versions')
  if (!response.ok) throw new Error('参数台账读取失败')
  return asJson(response)
}

export async function buildReviewPackage(
  queryId: number,
  reexecute = false,
): Promise<ReviewEnvelope<ReviewPackage>> {
  const response = await request('/api/review/packages', {
    method: 'POST',
    body: JSON.stringify({ query_id: queryId, reexecute }),
  })
  return asJson(response)
}

export async function fetchReviewPackages(
  queryId?: number,
): Promise<{ items: ReviewPackage[]; total: number }> {
  const suffix = queryId === undefined ? '' : `?query_id=${queryId}`
  const response = await request(`/api/review/packages${suffix}`)
  if (!response.ok) throw new Error('复核包列表读取失败')
  return asJson(response)
}

export async function fetchReviewPackage(
  packageId: number,
): Promise<ReviewEnvelope<ReviewPackage>> {
  const response = await request(`/api/review/packages/${packageId}`)
  return asJson(response)
}

export async function registerEvidence(payload: {
  query_id: number
  param_version: string
  snapshot: Record<string, string>
  source: string
}): Promise<ReviewEnvelope<ParamEvidence>> {
  const response = await request('/api/review/evidence', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return asJson(response)
}

export async function fetchEvidence(
  queryId?: number,
): Promise<{ items: ParamEvidence[]; total: number }> {
  const suffix = queryId === undefined ? '' : `?query_id=${queryId}`
  const response = await request(`/api/review/evidence${suffix}`)
  if (!response.ok) throw new Error('证据列表读取失败')
  return asJson(response)
}

export async function openReviewRequest(
  queryId: number,
): Promise<ReviewEnvelope<ReviewRequest>> {
  const response = await request('/api/review/requests', {
    method: 'POST',
    body: JSON.stringify({ query_id: queryId }),
  })
  return asJson(response)
}

export async function fetchReviewRequests(
  queryId?: number,
): Promise<{ items: ReviewRequest[]; total: number }> {
  const suffix = queryId === undefined ? '' : `?query_id=${queryId}`
  const response = await request(`/api/review/requests${suffix}`)
  if (!response.ok) throw new Error('复核待办读取失败')
  return asJson(response)
}

export async function submitReviewRequest(
  requestId: number,
): Promise<ReviewEnvelope<ReviewRequest>> {
  const response = await request(`/api/review/requests/${requestId}/submit`, {
    method: 'POST',
  })
  return asJson(response)
}
