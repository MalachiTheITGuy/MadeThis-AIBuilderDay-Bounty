import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { ArrowRight, CheckCircle2, CircleAlert, Database, KeyRound, Link2, LockKeyhole, Pause, Play, Settings2, ShieldCheck, SlidersHorizontal, StopCircle, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { useActiveLLMProvider, useApplicationSettings, useCompanies, useCreateLLMProvider, useLLMProviders, usePolicyHistory, useResetApplicationSettings, useScope, useSetActiveLLMProvider, useSetScope, useTestLLMProvider, useUpdateApplicationSettings, useUpdateWorkspaceSettings, useWorkspaceSettings } from "@/lib/api/hooks"

function Panel({ children, className = "" }: { children: ReactNode; className?: string }) { return <div className={`loop-panel ${className}`}>{children}</div> }
function Pill({ children, tone = "plain", dot = false }: { children: ReactNode; tone?: "plain" | "info" | "warn" | "ok"; dot?: boolean }) { return <span className={`loop-pill pill-${tone}`}>{dot && <span className="pill-dot" />}{children}</span> }

type SettingsPage = "overview" | "llm" | "integrations" | "user" | "application" | "workspace" | "autonomy" | "data" | "security"

const pages: Array<{ id: SettingsPage; label: string; description: string; icon: typeof Settings2 }> = [
  { id: "overview", label: "Overview", description: "Workspace configuration", icon: Settings2 },
  { id: "llm", label: "LLM providers", description: "Models and API endpoints", icon: KeyRound },
  { id: "integrations", label: "Integrations", description: "Channels and external systems", icon: Link2 },
  { id: "user", label: "User settings", description: "Profile and notifications", icon: UserRound },
  { id: "application", label: "Application", description: "Display and behavior", icon: SlidersHorizontal },
  { id: "workspace", label: "Workspace", description: "Workspace defaults", icon: Settings2 },
  { id: "autonomy", label: "Autonomy & guardrails", description: "What Loop may do", icon: ShieldCheck },
  { id: "data", label: "Data & simulation", description: "Privacy and data handling", icon: Database },
  { id: "security", label: "Security & access", description: "Secrets and audit", icon: LockKeyhole },
]

interface SettingsWorkspaceProps {
  status?: { stopped?: boolean; today_budget_used?: number; simulation_mode?: boolean }
  mode: string
  onMode: (autopilot: boolean) => void
  onPause: () => void
  onStop: () => void
  onResume: () => void
}

export function SettingsWorkspace({ status, mode, onMode, onPause, onStop, onResume }: SettingsWorkspaceProps) {
  const [page, setPage] = useState<SettingsPage>(() => (localStorage.getItem("loop.settings.page") as SettingsPage) || "overview")
  const scope = useScope()
  const companies = useCompanies()
  const policyHistory = usePolicyHistory()
  const setScope = useSetScope()
  const application = useApplicationSettings()
  const updateApplication = useUpdateApplicationSettings()
  const resetApplication = useResetApplicationSettings()
  const workspace = useWorkspaceSettings()
  const updateWorkspace = useUpdateWorkspaceSettings()
  const llmProviders = useLLMProviders()
  const activeLLM = useActiveLLMProvider()
  const createLLM = useCreateLLMProvider()
  const testLLM = useTestLLMProvider()
  const setActiveLLM = useSetActiveLLMProvider()

  useEffect(() => { localStorage.setItem("loop.settings.page", page) }, [page])

  const currentScope = scope.data?.scope
  const segments = Array.from(new Set((companies.data || []).map((company) => company.segment).filter(Boolean))) as string[]
  const navigate = (next: SettingsPage) => setPage(next)

  return <div className="settings-workspace">
    <div className="page-intro settings-page-intro"><div><span className="eyebrow">CONTROL / SETTINGS</span><h1>{pages.find((item) => item.id === page)?.label}</h1><p>{pages.find((item) => item.id === page)?.description}</p></div><span className="settings-breadcrumb">Settings / {pages.find((item) => item.id === page)?.label}</span></div>
    <div className="settings-shell">
      <nav className="settings-page-nav" aria-label="Settings pages">{pages.map((item) => { const Icon = item.icon; return <button key={item.id} className={page === item.id ? "settings-page-active" : ""} aria-current={page === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><Icon size={15} /><span><strong>{item.label}</strong><small>{item.description}</small></span></button> })}</nav>
      <div className="settings-page-content">
        {page === "overview" && <SettingsOverview status={status} mode={mode} policyHistory={policyHistory.data || []} scope={currentScope} activeProvider={activeLLM.data?.provider} onNavigate={navigate} />}
        {page === "autonomy" && <AutonomyPage status={status} mode={mode} scope={currentScope} segments={segments} loading={scope.isLoading || companies.isLoading} onMode={onMode} onPause={onPause} onStop={onStop} onResume={onResume} onSave={(patch) => setScope.mutate(patch)} />}
        {page === "llm" && <LLMPage providers={llmProviders} active={activeLLM} create={createLLM} test={testLLM} setActive={setActiveLLM} />}
        {page === "application" && <ApplicationPage query={application} update={updateApplication} reset={resetApplication} />}
        {page === "workspace" && <WorkspacePage query={workspace} update={updateWorkspace} segments={segments} />}
        {page !== "overview" && page !== "autonomy" && page !== "llm" && page !== "application" && page !== "workspace" && <ConfigurationPlaceholder page={page} />}
      </div>
    </div>
  </div>
}

function SettingsOverview({ status, mode, policyHistory, scope, activeProvider, onNavigate }: { status?: SettingsWorkspaceProps["status"]; mode: string; policyHistory: Array<{ version: number; source: string; created_at: string }>; scope?: { enabled: boolean; allowed_channels: string[]; allowed_segments: string[]; max_sends_per_day: number }; activeProvider?: { name: string; model: string; api_key_configured: boolean } | null; onNavigate: (page: SettingsPage) => void }) {
  return <div className="settings-overview">
    <div className="settings-overview-grid">
      <OverviewCard title="Operating mode" value={mode} detail={scope ? `${scope.max_sends_per_day} actions/day scope` : "Scope is loading"} tone={mode === "autopilot" ? "info" : "plain"} icon={<ShieldCheck size={17} />} onClick={() => onNavigate("autonomy")} />
      <OverviewCard title="LLM provider" value={activeProvider?.name || "Not configured"} detail={activeProvider ? `${activeProvider.model} · secret ${activeProvider.api_key_configured ? "configured" : "missing"}` : "No active provider"} tone={activeProvider?.api_key_configured ? "info" : "warn"} icon={<KeyRound size={17} />} onClick={() => onNavigate("llm")} />
      <OverviewCard title="Integrations" value={status?.simulation_mode ? "Simulation mode" : "Configuration unavailable"} detail={status?.simulation_mode ? "External sends are disabled" : "Connection health is not available"} tone={status?.simulation_mode ? "info" : "warn"} icon={<Link2 size={17} />} onClick={() => onNavigate("integrations")} />
      <OverviewCard title="Budget today" value={`${status?.today_budget_used ?? 0} units`} detail="Live from system status" tone="plain" icon={<SlidersHorizontal size={17} />} onClick={() => onNavigate("autonomy")} />
    </div>
    <section className="settings-overview-section"><div className="section-heading"><h2>Workspace configuration</h2><span className="mono">backend-backed</span></div><div className="settings-summary-list"><SummaryRow label="Workspace scope" value={scope ? `${scope.allowed_segments.length} segments · ${scope.allowed_channels.length} channels` : "Loading"} onClick={() => onNavigate("autonomy")} /><SummaryRow label="Simulation safety" value={status?.simulation_mode ? "Enabled" : "Unavailable"} onClick={() => onNavigate("data")} /><SummaryRow label="Policy history" value={`${policyHistory.length} version${policyHistory.length === 1 ? "" : "s"}`} onClick={() => onNavigate("autonomy")} /><SummaryRow label="User preferences" value="Not configured" onClick={() => onNavigate("user")} /></div></section>
    <section className="settings-overview-section"><div className="section-heading"><h2>Recent configuration changes</h2><span className="mono">{policyHistory.length} policy events</span></div>{policyHistory.length ? <div className="settings-change-list">{policyHistory.slice(-5).reverse().map((item) => <div key={item.version} className="settings-change"><span className="mono">v{item.version}</span><span><strong>{item.source}</strong><small>{item.created_at}</small></span></div>)}</div> : <div className="settings-empty"><CircleAlert size={17} /><span>No configuration changes recorded yet.</span></div>}</section>
  </div>
}

function LLMPage({ providers, active, create, test, setActive }: { providers: ReturnType<typeof useLLMProviders>; active: ReturnType<typeof useActiveLLMProvider>; create: ReturnType<typeof useCreateLLMProvider>; test: ReturnType<typeof useTestLLMProvider>; setActive: ReturnType<typeof useSetActiveLLMProvider> }) {
  const [name, setName] = useState("")
  const [kind, setKind] = useState("openai_compatible")
  const [baseUrl, setBaseUrl] = useState("")
  const [model, setModel] = useState("")
  const [envVar, setEnvVar] = useState("LLM_API_KEY")
  const items = providers.data?.providers || []
  const submit = () => { if (!name || !baseUrl || !model) return; create.mutate({ name, kind: kind as "openai_compatible", base_url: baseUrl, model, api_key_env_var: envVar, timeout_seconds: 30, retry_count: 2, capabilities: { chat: true }, enabled: true }, { onSuccess: () => { setName(""); setBaseUrl(""); setModel("") } }) }
  if (providers.isLoading || active.isLoading) return <Panel className="query-state"><span className="state-spinner" /><p>Loading LLM provider configuration...</p></Panel>
  if (providers.error || active.error) return <Panel className="query-state query-error"><CircleAlert size={20} /><strong>LLM provider configuration unavailable</strong><p>{providers.error?.message || active.error?.message}</p><Button variant="outline" className="small-button" onClick={() => void providers.refetch()}>Retry</Button></Panel>
  return <div className="settings-sections"><Panel className="settings-secret-note"><KeyRound size={16} /><span>Provider metadata is persisted. API keys are never stored or returned; configure the named environment variable in the server runtime.</span></Panel><SettingSection title="Active provider"><div className="setting-row"><span><strong>{active.data?.provider?.name || "No active provider"}</strong><small>{active.data?.provider ? `${active.data.provider.model} · ${active.data.provider.api_key_configured ? "secret configured" : "secret missing"}` : "Create and validate a provider before activation."}</small></span>{active.data?.provider && <Pill tone={active.data.provider.api_key_configured ? "ok" : "warn"} dot>{active.data.provider.api_key_configured ? "ready" : "incomplete"}</Pill>}</div></SettingSection><SettingSection title="Configured providers">{items.length ? items.map((provider) => <div className="setting-row" key={provider.provider_id}><span><strong>{provider.name}</strong><small>{provider.kind} · {provider.model} · {provider.base_url}</small></span><div className="llm-provider-actions"><Pill tone={provider.last_test?.healthy ? "ok" : provider.api_key_configured ? "plain" : "warn"} dot>{provider.last_test?.healthy ? "healthy" : provider.api_key_configured ? "untested" : "missing secret"}</Pill><Button variant="outline" className="small-button" onClick={() => test.mutate(provider.provider_id)}>Test</Button><Button className="teal-button small-button" onClick={() => setActive.mutate(provider.provider_id)} disabled={!provider.enabled || !provider.api_key_configured}>Use provider</Button></div></div>) : <p className="empty-copy">No providers are configured.</p>}</SettingSection><SettingSection title="Add provider"><div className="settings-form-grid"><label>Name<Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Provider name" /></label><label>Kind<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="openai_compatible">OpenAI-compatible</option><option value="anthropic_compatible">Anthropic-compatible</option><option value="local">Local</option><option value="custom">Custom</option></select></label><label>Base URL<Input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://provider.example/v1" /></label><label>Model<Input value={model} onChange={(event) => setModel(event.target.value)} placeholder="model-name" /></label><label>API key environment variable<Input value={envVar} onChange={(event) => setEnvVar(event.target.value)} placeholder="LLM_API_KEY" /></label></div><Button className="teal-button" onClick={submit} disabled={create.isPending || !name || !baseUrl || !model}>Add provider</Button></SettingSection></div>
}

function OverviewCard({ title, value, detail, tone, icon, onClick }: { title: string; value: string; detail: string; tone: "plain" | "info" | "warn"; icon: ReactNode; onClick: () => void }) {
  return <button className={`settings-overview-card card-${tone}`} onClick={onClick}><span className="overview-card-icon">{icon}</span><span><small>{title}</small><strong>{value}</strong><em>{detail}</em></span><ArrowRight size={14} /></button>
}

function SummaryRow({ label, value, onClick }: { label: string; value: string; onClick: () => void }) {
  return <button className="settings-summary-row" onClick={onClick}><span>{label}</span><strong>{value}</strong><ArrowRight size={14} /></button>
}

function ConfigurationPlaceholder({ page }: { page: SettingsPage }) {
  const meta = pages.find((item) => item.id === page)
  return <Panel className="settings-placeholder"><div className="settings-placeholder-icon"><InfoIcon page={page} /></div><span className="eyebrow">{meta?.label}</span><h2>{meta?.description}</h2><p>This settings surface is ready for its backend configuration contract. It will not display fabricated connection or profile state.</p><div className="placeholder-status"><CircleAlert size={15} /><span>Backend configuration endpoint not available yet</span></div></Panel>
}

function ApplicationPage({ query, update, reset }: { query: ReturnType<typeof useApplicationSettings>; update: ReturnType<typeof useUpdateApplicationSettings>; reset: ReturnType<typeof useResetApplicationSettings> }) {
  const settings = query.data?.settings
  if (query.isLoading) return <Panel className="query-state"><span className="state-spinner" /><p>Loading application preferences...</p></Panel>
  if (query.error || !settings) return <Panel className="query-state query-error"><CircleAlert size={20} /><strong>Application preferences unavailable</strong><p>{query.error?.message || "The backend did not return settings."}</p><Button variant="outline" className="small-button" onClick={() => void query.refetch()}>Retry</Button></Panel>
  return <div className="settings-sections"><SettingSection title="Appearance"><div className="setting-row"><span><strong>Theme</strong><small>Stored as an application preference</small></span><select value={settings.theme} onChange={(event) => update.mutate({ theme: event.target.value as typeof settings.theme })}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div><div className="setting-row"><span><strong>Density</strong><small>How much information appears in a workspace</small></span><select value={settings.density} onChange={(event) => update.mutate({ density: event.target.value as typeof settings.density })}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></div></SettingSection><SettingSection title="Formatting"><div className="setting-row"><span><strong>Time format</strong><small>Used in activity and schedules</small></span><select value={settings.time_format} onChange={(event) => update.mutate({ time_format: event.target.value as typeof settings.time_format })}><option value="12h">12 hour</option><option value="24h">24 hour</option></select></div><div className="setting-row"><span><strong>Currency</strong><small>Used for simulated ARR</small></span><Input className="scope-number" maxLength={3} value={settings.currency} onChange={(event) => update.mutate({ currency: event.target.value.toUpperCase() })} /></div></SettingSection><SettingSection title="Workspace behavior"><div className="setting-row"><span><strong>Refresh interval</strong><small>Minimum 5 seconds</small></span><Input className="scope-number" type="number" min={5} max={3600} value={settings.refresh_interval_seconds} onChange={(event) => update.mutate({ refresh_interval_seconds: Number(event.target.value) })} /></div><div className="setting-row"><span><strong>Default landing page</strong><small>Where the app opens after sign-in</small></span><select value={settings.default_landing_page} onChange={(event) => update.mutate({ default_landing_page: event.target.value as typeof settings.default_landing_page })}><option value="today">Today</option><option value="opportunities">Opportunities</option><option value="approvals">Approvals</option><option value="activity">Activity</option></select></div><div className="setting-row"><span><strong>Default opportunity sort</strong><small>Initial queue ordering</small></span><select value={settings.default_opportunity_sort} onChange={(event) => update.mutate({ default_opportunity_sort: event.target.value as typeof settings.default_opportunity_sort })}><option value="score">Next-best score</option><option value="recency">Signal recency</option><option value="value">Expected value</option></select></div></SettingSection><div className="settings-action-row"><Button variant="outline" onClick={() => reset.mutate()}>Reset application preferences</Button><span className="mono">Only UI preferences are reset.</span></div></div>
}

function WorkspacePage({ query, update, segments }: { query: ReturnType<typeof useWorkspaceSettings>; update: ReturnType<typeof useUpdateWorkspaceSettings>; segments: string[] }) {
  const settings = query.data?.settings
  if (query.isLoading) return <Panel className="query-state"><span className="state-spinner" /><p>Loading workspace preferences...</p></Panel>
  if (query.error || !settings) return <Panel className="query-state query-error"><CircleAlert size={20} /><strong>Workspace preferences unavailable</strong><p>{query.error?.message || "The backend did not return settings."}</p><Button variant="outline" className="small-button" onClick={() => void query.refetch()}>Retry</Button></Panel>
  return <div className="settings-sections"><SettingSection title="Workspace identity"><div className="setting-row"><span><strong>Workspace name</strong><small>Shown in the operator shell</small></span><Input value={settings.name} placeholder="Workspace name" onChange={(event) => update.mutate({ name: event.target.value })} /></div><div className="setting-row"><span><strong>Timezone</strong><small>Used for schedule previews and activity timestamps</small></span><Input value={settings.timezone} onChange={(event) => update.mutate({ timezone: event.target.value })} /></div></SettingSection><SettingSection title="Workspace defaults"><div className="setting-row"><span><strong>Currency</strong><small>Default workspace reporting currency</small></span><Input className="scope-number" maxLength={3} value={settings.default_currency} onChange={(event) => update.mutate({ default_currency: event.target.value.toUpperCase() })} /></div><div className="setting-row"><span><strong>Default segment</strong><small>Used when a workflow does not specify one</small></span><select value={settings.default_segment} onChange={(event) => update.mutate({ default_segment: event.target.value })}><option value="">No default</option>{segments.map((segment) => <option key={segment} value={segment}>{segment}</option>)}</select></div></SettingSection><div className="settings-empty"><CheckCircle2 size={17} /><span>Workspace preferences are persisted by the backend and audited on change.</span></div></div>
}

function InfoIcon({ page }: { page: SettingsPage }) { const Icon = pages.find((item) => item.id === page)?.icon || Settings2; return <Icon size={20} /> }

function AutonomyPage({ status, mode, scope, segments, loading, onMode, onPause, onStop, onResume, onSave }: { status?: SettingsWorkspaceProps["status"]; mode: string; scope?: { enabled: boolean; allowed_channels: string[]; allowed_segments: string[]; allowed_timing: string[]; max_sends_per_day: number; max_cost_units_per_action: number }; segments: string[]; loading: boolean; onMode: (autopilot: boolean) => void; onPause: () => void; onStop: () => void; onResume: () => void; onSave: (patch: Partial<NonNullable<typeof scope>>) => void }) {
  if (loading || !scope) return <Panel className="query-state"><span className="state-spinner" /><p>Loading persisted autonomy scope...</p></Panel>
  const toggleSegment = (segment: string) => onSave({ allowed_segments: scope.allowed_segments.includes(segment) ? scope.allowed_segments.filter((item) => item !== segment) : [...scope.allowed_segments, segment] })
  const toggleEmail = (checked: boolean) => onSave({ allowed_channels: checked ? [...new Set([...scope.allowed_channels, "EMAIL"])] : scope.allowed_channels.filter((channel) => channel !== "EMAIL") })
  return <div className="settings-sections"><Panel className="autopilot-preview"><span>Live preview · persisted scope</span><p>Loop may execute up to {scope.max_sends_per_day} actions/day across {scope.allowed_channels.join(", ") || "no channels"} for {scope.allowed_segments.join(", ") || "no segments"}. Mandatory approval rules remain active.</p></Panel><SettingSection title="Operating mode"><div className="segmented-control"><button className={mode === "propose" ? "segmented-active" : ""} onClick={() => onMode(false)}>Propose · everything asks first</button><button className={mode === "autopilot" ? "segmented-active" : ""} onClick={() => onMode(true)}>Autopilot · scoped execution</button></div></SettingSection><SettingSection title="Autopilot scope"><SettingToggle label="Enabled" detail="Whether scoped actions can execute automatically" checked={scope.enabled} onChange={(checked) => onSave({ enabled: checked })} /><SettingToggle label="Email channel" detail="Allowed channel" checked={scope.allowed_channels.includes("EMAIL")} onChange={toggleEmail} /><div className="setting-row"><span><strong>Segments in scope</strong><small>Derived from backend companies</small></span><div className="setting-chips">{segments.map((segment) => <button key={segment} className={scope.allowed_segments.includes(segment) ? "chip-selected" : ""} onClick={() => toggleSegment(segment)}>{segment}</button>)}</div></div><div className="setting-row"><span><strong>Daily send cap</strong><small>Persisted autopilot limit</small></span><Input className="scope-number" type="number" min={1} value={scope.max_sends_per_day} onChange={(event) => onSave({ max_sends_per_day: Number(event.target.value) })} /></div></SettingSection><SettingSection title="Approval rules · always ask"><SettingToggle label="Intro requests" detail="Always require human approval" checked onChange={() => undefined} /><SettingToggle label="External actions" detail="Always require human approval" checked onChange={() => undefined} /><SettingToggle label="Budget exceptions" detail="Always require human approval" checked onChange={() => undefined} /></SettingSection><SettingSection title="Agent controls"><div className="control-buttons">{status?.stopped ? <Button className="teal-button" onClick={onResume}><Play size={14} /> Resume</Button> : <><Button variant="outline" onClick={onPause}><Pause size={14} /> Pause</Button><Button variant="outline" onClick={onStop}><StopCircle size={14} /> Stop</Button></>}</div><p className="mono muted-copy">Today: {status?.today_budget_used ?? 0} action units used.</p></SettingSection></div>
}

function SettingSection({ title, children }: { title: string; children: ReactNode }) { return <section className="setting-section"><h2>{title}</h2><Panel>{children}</Panel></section> }
function SettingToggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (checked: boolean) => void }) { return <div className="setting-row"><span><strong>{label}</strong><small>{detail}</small></span><Switch checked={checked} onCheckedChange={onChange} aria-label={label} /></div> }
