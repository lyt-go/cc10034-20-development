/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

export type ReviewCheck = {
  ok: boolean
  detail: string
  source?: string
}

export type PackageEvaluation = {
  query_id: number
  query_no?: string
  eligible: boolean
  reasons: string[]
  checks: {
    input: ReviewCheck
    fee: ReviewCheck
    params: ReviewCheck
  }
  claimed_version: string
  locked_fingerprint: string
  current_effective_version: string
}

export type ReviewPackage = {
  id: number
  receipt_no: string
  query_id: number
  query_no: string
  status: string
  reexecuted: boolean
  created_at: string
  superseded_at?: string
  evaluation: PackageEvaluation
  snapshot: { evaluation: PackageEvaluation; captured_at: string }
  latest_evaluation?: PackageEvaluation
  evidence?: ParamEvidence[]
  requests?: ReviewRequest[]
}

export type ParamEvidence = {
  id: number
  evidence_no: string
  query_id: number
  query_no: string
  param_version: string
  source: string
  fingerprint: string
  valid: boolean
  match_detail: string
  snapshot: Record<string, string>
  received_at: string
}

export type ReviewRequest = {
  id: number
  request_no: string
  query_id: number
  query_no: string
  status: string
  opened_at: string
  submitted_at: string | null
  receipt_no: string | null
  block_reasons: string[]
  supplement_evidence_no?: string
  latest_evaluation?: PackageEvaluation
}

export type ParamVersion = {
  config_id: string
  version: string
  status: string
  fingerprint: string
  params: Record<string, string>
}

export type ReviewEnvelope<T> = {
  ok: boolean
  message: string
  entry: T | null
}
