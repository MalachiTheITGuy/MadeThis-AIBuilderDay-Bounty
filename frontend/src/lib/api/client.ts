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
  company_id: string
  company: Company
  contact?: Contact
  signal: Signal
  score: number
  fit_notes: string[]
  status: string
  pipeline_stage: string
  arr: number
  current_action?: Action
  created_at: string
}

export interface OpportunitiesResponse {
  items: Opportunity[]
  total: number
  limit: number
  offset: number
}

export interface OpportunityDetail extends Opportunity {
  signal_timeline: Signal[]
  previous_actions: Array<Record<string, unknown>>
  relationship_edges: Array<Record<string, unknown>>
  why_now: string
  what_would_change_this: string[]
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
  policy_version?: number
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

export interface DecisionCard {
  action_id: string
  action_type: Action['action_type']
  target: string
  channel: Action['channel']
  timing: string
  cost_units: number
  why: string[]
  evidence: string[]
  guardrails: string[]
  learned: string[]
  next_steps: string
  expected_effect: string
}

export interface DecisionMutationResponse {
  status: string
  action_id: string
  reason?: string
}

export interface ActionTimeline {
  action_id: string
  status: string
  policy_version: number
  stages: Array<{ index: number; name: string; detail: string; completed: boolean }>
  activity: ActivityLog[]
  outcome?: Outcome | null
}

export interface LearningChanges {
  active_policy_version: number
  policies: Array<{ version: number; policy: Record<string, unknown>; created_at: string; source: string }>
  feedback: ActivityLog[]
  outcomes: Array<Record<string, unknown>>
}

export interface PolicyVersion {
  version: number
  policy: Record<string, unknown>
  created_at: string
  source: string
  diff: Record<string, { before?: unknown; after?: unknown }>
}

export interface AutopilotScope {
  enabled: boolean
  allowed_segments: string[]
  allowed_channels: string[]
  allowed_timing: string[]
  max_sends_per_day: number
  max_cost_units_per_action: number
}

export interface ApplicationSettings {
  theme: 'system' | 'light' | 'dark'
  density: 'comfortable' | 'compact'
  date_format: 'locale' | 'iso'
  time_format: '12h' | '24h'
  currency: string
  refresh_interval_seconds: number
  default_landing_page: 'today' | 'opportunities' | 'approvals' | 'activity'
  default_opportunity_sort: 'score' | 'recency' | 'value'
  feature_flags: Record<string, boolean>
}

export interface WorkspaceSettings {
  name: string
  timezone: string
  default_currency: string
  default_segment: string
}

export interface LLMProvider {
  provider_id: string
  name: string
  kind: 'openai_compatible' | 'anthropic_compatible' | 'local' | 'custom'
  base_url: string
  model: string
  api_key_env_var?: string | null
  api_key_configured: boolean
  secret_source: string
  timeout_seconds: number
  retry_count: number
  capabilities: Record<string, boolean>
  enabled: boolean
  source?: string
  last_test?: { healthy: boolean; detail: string } | null
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
  getOpportunities: (params?: { q?: string; status?: string; signal_type?: string; limit?: number; offset?: number }) => {
    const search = new URLSearchParams()
    Object.entries(params || {}).forEach(([key, value]) => { if (value !== undefined && value !== '') search.set(key, String(value)) })
    return fetchApi<OpportunitiesResponse>(`/opportunities?${search.toString()}`)
  },
  getOpportunity: (id: string) => fetchApi<OpportunityDetail>(`/opportunities/${id}`),
  getDecision: (id: string) => fetchApi<DecisionCard>(`/decisions/${id}`),
  getActionTimeline: (id: string) => fetchApi<ActionTimeline>(`/actions/${id}/timeline`),
  getLearningChanges: () => fetchApi<LearningChanges>('/learning/changes'),
  getPolicyHistory: () => fetchApi<PolicyVersion[]>('/policy/history'),
  getScope: () => fetchApi<{ scope: AutopilotScope }>('/control/scope'),
  getApplicationSettings: () => fetchApi<{ settings: ApplicationSettings }>('/settings/application'),
  updateApplicationSettings: (settings: Partial<ApplicationSettings>) => fetchApi<{ settings: ApplicationSettings }>('/settings/application', { method: 'PATCH', body: JSON.stringify(settings) }),
  resetApplicationSettings: () => fetchApi<{ settings: ApplicationSettings; reset: boolean }>('/settings/application/reset', { method: 'POST' }),
  getWorkspaceSettings: () => fetchApi<{ settings: WorkspaceSettings }>('/settings/workspace'),
  updateWorkspaceSettings: (settings: Partial<WorkspaceSettings>) => fetchApi<{ settings: WorkspaceSettings }>('/settings/workspace', { method: 'PATCH', body: JSON.stringify(settings) }),
  getLLMProviders: () => fetchApi<{ providers: LLMProvider[] }>('/settings/llm/providers'),
  createLLMProvider: (provider: Omit<LLMProvider, 'provider_id' | 'api_key_configured' | 'secret_source' | 'source' | 'last_test'> & { api_key_env_var?: string }) => fetchApi<{ provider: LLMProvider }>('/settings/llm/providers', { method: 'POST', body: JSON.stringify(provider) }),
  testLLMProvider: (providerId: string) => fetchApi<{ provider_id: string; healthy: boolean; detail: string }>(`/settings/llm/providers/${providerId}/test`, { method: 'POST' }),
  getActiveLLMProvider: () => fetchApi<{ provider: LLMProvider | null }>('/settings/llm/active'),
  setActiveLLMProvider: (providerId: string) => fetchApi<{ provider: LLMProvider }>(`/settings/llm/active`, { method: 'PUT', body: JSON.stringify({ provider_id: providerId }) }),
  getAuditExplain: (id: string) => fetchApi<Record<string, unknown>>(`/audit/explain/${id}`),
  pause: () => fetchApi<void>('/control/pause', { method: 'POST' }),
  stop: () => fetchApi<void>('/control/stop', { method: 'POST' }),
  resume: () => fetchApi<void>('/control/resume', { method: 'POST' }),
  setMode: (mode: 'PROPOSE' | 'AUTOPILOT') => 
    fetchApi<void>(`/control/mode`, { method: 'POST', body: JSON.stringify({ mode }) }),
  setScope: (scope: Partial<AutopilotScope>) =>
    fetchApi<{ scope: AutopilotScope }>('/control/scope', { method: 'POST', body: JSON.stringify(scope) }),

  // Queue
  getQueue: () => fetchApi<Action[]>('/queue'),
  approveAction: (id: string, note?: string) =>
    fetchApi<DecisionMutationResponse>(`/decisions/${id}/approve`, { method: 'POST', body: JSON.stringify(note ? { note } : {}) }),
  rejectAction: (id: string, reason: string) =>
    fetchApi<DecisionMutationResponse>(`/decisions/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  editAction: (id: string, changes: { subject?: string; body?: string }, note?: string) => 
    fetchApi<DecisionMutationResponse>(`/decisions/${id}/edit`, { method: 'POST', body: JSON.stringify({ ...changes, note }) }),

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
