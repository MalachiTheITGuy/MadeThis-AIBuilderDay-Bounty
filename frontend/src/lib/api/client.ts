// API Types based on the backend schema

export interface Signal {
  id: string
  company_id: string
  type: 'FUNDING' | 'HIRING' | 'PRODUCT' | 'PRICING' | 'CONTENT'
  payload: Record<string, unknown>
  detected_at: string
}

export interface Company {
  id: string
  name: string
  domain?: string
  industry?: string
  segment?: string
  stage?: string
  employees?: number
  size?: string
  location?: string
  tech_stack?: string[]
  tags?: string[]
  created_at?: string
  updated_at?: string
}

export interface Contact {
  id: string
  company_id: string
  email?: string
  name?: string
  first_name?: string
  last_name?: string
  title?: string
  seniority?: string
  linkedin_url?: string
  linkedin?: string
  warmth?: string
  created_at?: string
  updated_at?: string
}

export interface Opportunity {
  id: string
  signal_id: string
  company_id: string
  contact_id: string
  qualification_score: number
  fit_notes: string[]
  icp_hits: string[]
  status: 'QUALIFIED' | 'PLANNED' | 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'SENT' | 'OUTCOME_RECORDED' | 'LEARNING_APPLIED' | 'DISMISSED' | 'SKIPPED'
  created_at: string
  updated_at: string
}

export interface Action {
  id: string
  opportunity_id: string
  action_type: 'OUTREACH_EMAIL' | 'LINKEDIN_CONNECT' | 'INTRO_REQUEST' | 'FOLLOW_UP'
  variant_id: string
  channel: 'EMAIL' | 'LINKEDIN'
  timing: string
  segment: string
  expected_effect: string
  confidence: number
  subject?: string
  body?: string
  contact_id?: string
  contact_name?: string
  contact_title?: string
  company_name?: string
  cost_units?: number
  status: 'PLANNED' | 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'EDITED' | 'SENT' | 'FAILED'
  decision_trace?: DecisionTrace
  created_at: string
  updated_at: string
}

export interface DecisionTrace {
  what: string
  why: string
  evidence: EvidenceLink[]
  guardrails: GuardrailCheck[]
  learned: LearningDelta[]
  next_steps: string
}

export interface EvidenceLink {
  type: 'signal' | 'contact' | 'company' | 'warm_edge'
  id: string
  description: string
  payload?: Record<string, unknown>
}

export interface GuardrailCheck {
  rule: string
  passed: boolean
  details?: string
}

export interface LearningDelta {
  source: 'outcome' | 'feedback' | 'warm_graph'
  field: string
  delta: string
  description: string
}

export interface Outcome {
  id: string
  action_id: string
  result: 'REPLY' | 'MEETING' | 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'REJECTION' | 'UNSUB' | 'NO_RESPONSE'
  detail: string
  at: string
}

export interface Variant {
  id: string
  name: string
  template: string
  channel: 'EMAIL' | 'LINKEDIN'
  timing_slot: string
  tone_profile: string
  personalization_depth: number
  segment: string
  stats: VariantStats
}

export interface VariantStats {
  sent: number
  replies: number
  meetings: number
  positive: number
  negative: number
  unsub: number
}

export interface Policy {
  version: number
  brevity_weight: number
  tone_assertiveness: number
  personalization_depth: number
  banned_phrases: string[]
  updated_at: string
}

export interface WarmEdge {
  id: string
  source_contact_id: string
  target_contact_id: string
  strength: number
  direction: 'OUTBOUND' | 'INBOUND' | 'MUTUAL'
  last_interaction: string
  warmth_signal: 'REPLIED' | 'MET' | 'ENGAGED' | 'COLD'
  source: string
}

export interface ActivityLog {
  id: string
  at: string
  actor: 'AGENT' | 'USER'
  action_id: string
  event: string
  status: string
  outcome?: string
  reason?: string
  detail?: string
  policy_version: number
}

export interface SystemStatus {
  mode: 'PROPOSE' | 'AUTOPILOT'
  paused: boolean
  stopped: boolean
  queue_count: number
  active_opportunities: number
  today_sent: number
  today_budget_used: number
  schema_version?: number
  actions?: number
  outcomes?: number
  simulation_mode?: boolean
}

export interface Briefing {
  period: string
  generated_at: string
  what_ran: { total_actions: number; by_channel: Record<string, number> }
  leaderboard_shifts: Array<{ variant_id: string; sent: number; replies: number; meetings: number; success_rate: number }>
  policy_changes: Array<{ version: number; source: string; created_at: string }>
  warm_movements: Array<{ contact_a: string; contact_b: string; strength: number; source: string }>
  needs_attention: { pending_approval: number; actions_sent_this_period: number; weekly_budget: number; budget_headroom: number; guardrail_blocks: number }
  suggested_actions: string[]
}

export interface PipelineStage {
  stage: string
  count: number
  arr: number
}

// API Client
const API_BASE = '/api/v1'

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP error! status: ${response.status}`)
  }

  return response.json()
}

// API Functions
export const api = {
  // System
  getStatus: () => fetchApi<SystemStatus>('/status'),
  getBriefing: () => fetchApi<Briefing>('/briefing'),
  getPipeline: () => fetchApi<PipelineStage[]>('/pipeline'),
  getAuditExplain: (id: string) => fetchApi<Record<string, unknown>>(`/audit/explain/${id}`),
  pause: () => fetchApi<void>('/control/pause', { method: 'POST' }),
  stop: () => fetchApi<void>('/control/stop', { method: 'POST' }),
  resume: () => fetchApi<void>('/control/resume', { method: 'POST' }),
  setMode: (mode: 'PROPOSE' | 'AUTOPILOT') => 
    fetchApi<void>(`/control/mode`, { method: 'POST', body: JSON.stringify({ mode }) }),

  // Queue
  getQueue: () => fetchApi<Action[]>('/queue'),
  approveAction: (id: string, note?: string) => 
    fetchApi<Action>(`/decisions/${id}/approve`, { method: 'POST', body: JSON.stringify({ note }) }),
  rejectAction: (id: string, reason: string) => 
    fetchApi<Action>(`/decisions/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  editAction: (id: string, changes: { subject?: string; body?: string }, note?: string) => 
    fetchApi<Action>(`/decisions/${id}/edit`, { method: 'POST', body: JSON.stringify({ ...changes, note }) }),

  // Activity
  getActivity: (params?: { limit?: number; offset?: number; filter?: string }) => {
    const searchParams = new URLSearchParams()
    if (params?.limit) searchParams.set('limit', params.limit.toString())
    if (params?.offset) searchParams.set('offset', params.offset.toString())
    if (params?.filter) searchParams.set('filter', params.filter)
    return fetchApi<ActivityLog[]>(`/activity?${searchParams.toString()}`)
  },

  // Contacts & Companies
  getCompanies: () => fetchApi<Company[]>('/companies'),
  getContacts: (companyId?: string) => {
    const params = companyId ? `?company_id=${companyId}` : ''
    return fetchApi<Contact[]>(`/contacts${params}`)
  },

  // Variants & Playbook
  getVariants: () => fetchApi<Variant[]>('/variants'),
  createVariant: (variant: Omit<Variant, 'id' | 'stats'>) => 
    fetchApi<Variant>('/variants', { method: 'POST', body: JSON.stringify(variant) }),
  updateVariant: (id: string, variant: Partial<Variant>) => 
    fetchApi<Variant>(`/variants/${id}`, { method: 'PATCH', body: JSON.stringify(variant) }),

  // Policy
  getPolicy: () => fetchApi<Policy>('/policy'),
  updatePolicy: (policy: Partial<Policy>) => 
    fetchApi<Policy>('/policy', { method: 'PATCH', body: JSON.stringify(policy) }),
  rollbackPolicy: (version: number) => 
    fetchApi<Policy>(`/policy/rollback/${version}`, { method: 'POST' }),

  // Warm Graph
  getWarmEdges: () => fetchApi<WarmEdge[]>('/warm-graph'),
  updateWarmEdge: (id: string, edge: Partial<WarmEdge>) => 
    fetchApi<WarmEdge>(`/warm-graph/${id}`, { method: 'PATCH', body: JSON.stringify(edge) }),

  // Outcomes
  recordOutcome: (outcome: Omit<Outcome, 'id'>) => 
    fetchApi<Outcome>('/outcomes', { method: 'POST', body: JSON.stringify(outcome) }),
}
