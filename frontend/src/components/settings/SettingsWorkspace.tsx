import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { ArrowRight, CircleAlert, Database, KeyRound, Link2, LockKeyhole, Pause, Play, Settings2, ShieldCheck, SlidersHorizontal, StopCircle, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { useCompanies, usePolicyHistory, useScope, useSetScope } from "@/lib/api/hooks"

function Panel({ children, className = "" }: { children: ReactNode; className?: string }) { return <div className={`loop-panel ${className}`}>{children}</div> }

type SettingsPage = "overview" | "llm" | "integrations" | "user" | "application" | "autonomy" | "data" | "security"

const pages: Array<{ id: SettingsPage; label: string; description: string; icon: typeof Settings2 }> = [
  { id: "overview", label: "Overview", description: "Workspace configuration", icon: Settings2 },
  { id: "llm", label: "LLM providers", description: "Models and API endpoints", icon: KeyRound },
  { id: "integrations", label: "Integrations", description: "Channels and external systems", icon: Link2 },
  { id: "user", label: "User settings", description: "Profile and notifications", icon: UserRound },
  { id: "application", label: "Application", description: "Display and behavior", icon: SlidersHorizontal },
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

  useEffect(() => { localStorage.setItem("loop.settings.page", page) }, [page])

  const currentScope = scope.data?.scope
  const segments = Array.from(new Set((companies.data || []).map((company) => company.segment).filter(Boolean))) as string[]
  const navigate = (next: SettingsPage) => setPage(next)

  return <div className="settings-workspace">
    <div className="page-intro settings-page-intro"><div><span className="eyebrow">CONTROL / SETTINGS</span><h1>{pages.find((item) => item.id === page)?.label}</h1><p>{pages.find((item) => item.id === page)?.description}</p></div><span className="settings-breadcrumb">Settings / {pages.find((item) => item.id === page)?.label}</span></div>
    <div className="settings-shell">
      <nav className="settings-page-nav" aria-label="Settings pages">{pages.map((item) => { const Icon = item.icon; return <button key={item.id} className={page === item.id ? "settings-page-active" : ""} aria-current={page === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><Icon size={15} /><span><strong>{item.label}</strong><small>{item.description}</small></span></button> })}</nav>
      <div className="settings-page-content">
        {page === "overview" && <SettingsOverview status={status} mode={mode} policyHistory={policyHistory.data || []} scope={currentScope} onNavigate={navigate} />}
        {page === "autonomy" && <AutonomyPage status={status} mode={mode} scope={currentScope} segments={segments} loading={scope.isLoading || companies.isLoading} onMode={onMode} onPause={onPause} onStop={onStop} onResume={onResume} onSave={(patch) => setScope.mutate(patch)} />}
        {page !== "overview" && page !== "autonomy" && <ConfigurationPlaceholder page={page} />}
      </div>
    </div>
  </div>
}

function SettingsOverview({ status, mode, policyHistory, scope, onNavigate }: { status?: SettingsWorkspaceProps["status"]; mode: string; policyHistory: Array<{ version: number; source: string; created_at: string }>; scope?: { enabled: boolean; allowed_channels: string[]; allowed_segments: string[]; max_sends_per_day: number }; onNavigate: (page: SettingsPage) => void }) {
  return <div className="settings-overview">
    <div className="settings-overview-grid">
      <OverviewCard title="Operating mode" value={mode} detail={scope ? `${scope.max_sends_per_day} actions/day scope` : "Scope is loading"} tone={mode === "autopilot" ? "info" : "plain"} icon={<ShieldCheck size={17} />} onClick={() => onNavigate("autonomy")} />
      <OverviewCard title="LLM provider" value="Not configured" detail="No provider status endpoint is connected" tone="warn" icon={<KeyRound size={17} />} onClick={() => onNavigate("llm")} />
      <OverviewCard title="Integrations" value={status?.simulation_mode ? "Simulation mode" : "Configuration unavailable"} detail={status?.simulation_mode ? "External sends are disabled" : "Connection health is not available"} tone={status?.simulation_mode ? "info" : "warn"} icon={<Link2 size={17} />} onClick={() => onNavigate("integrations")} />
      <OverviewCard title="Budget today" value={`${status?.today_budget_used ?? 0} units`} detail="Live from system status" tone="plain" icon={<SlidersHorizontal size={17} />} onClick={() => onNavigate("autonomy")} />
    </div>
    <section className="settings-overview-section"><div className="section-heading"><h2>Workspace configuration</h2><span className="mono">backend-backed</span></div><div className="settings-summary-list"><SummaryRow label="Workspace scope" value={scope ? `${scope.allowed_segments.length} segments · ${scope.allowed_channels.length} channels` : "Loading"} onClick={() => onNavigate("autonomy")} /><SummaryRow label="Simulation safety" value={status?.simulation_mode ? "Enabled" : "Unavailable"} onClick={() => onNavigate("data")} /><SummaryRow label="Policy history" value={`${policyHistory.length} version${policyHistory.length === 1 ? "" : "s"}`} onClick={() => onNavigate("autonomy")} /><SummaryRow label="User preferences" value="Not configured" onClick={() => onNavigate("user")} /></div></section>
    <section className="settings-overview-section"><div className="section-heading"><h2>Recent configuration changes</h2><span className="mono">{policyHistory.length} policy events</span></div>{policyHistory.length ? <div className="settings-change-list">{policyHistory.slice(-5).reverse().map((item) => <div key={item.version} className="settings-change"><span className="mono">v{item.version}</span><span><strong>{item.source}</strong><small>{item.created_at}</small></span></div>)}</div> : <div className="settings-empty"><CircleAlert size={17} /><span>No configuration changes recorded yet.</span></div>}</section>
  </div>
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

function InfoIcon({ page }: { page: SettingsPage }) { const Icon = pages.find((item) => item.id === page)?.icon || Settings2; return <Icon size={20} /> }

function AutonomyPage({ status, mode, scope, segments, loading, onMode, onPause, onStop, onResume, onSave }: { status?: SettingsWorkspaceProps["status"]; mode: string; scope?: { enabled: boolean; allowed_channels: string[]; allowed_segments: string[]; allowed_timing: string[]; max_sends_per_day: number; max_cost_units_per_action: number }; segments: string[]; loading: boolean; onMode: (autopilot: boolean) => void; onPause: () => void; onStop: () => void; onResume: () => void; onSave: (patch: Partial<NonNullable<typeof scope>>) => void }) {
  if (loading || !scope) return <Panel className="query-state"><span className="state-spinner" /><p>Loading persisted autonomy scope...</p></Panel>
  const toggleSegment = (segment: string) => onSave({ allowed_segments: scope.allowed_segments.includes(segment) ? scope.allowed_segments.filter((item) => item !== segment) : [...scope.allowed_segments, segment] })
  const toggleEmail = (checked: boolean) => onSave({ allowed_channels: checked ? [...new Set([...scope.allowed_channels, "EMAIL"])] : scope.allowed_channels.filter((channel) => channel !== "EMAIL") })
  return <div className="settings-sections"><Panel className="autopilot-preview"><span>Live preview · persisted scope</span><p>Loop may execute up to {scope.max_sends_per_day} actions/day across {scope.allowed_channels.join(", ") || "no channels"} for {scope.allowed_segments.join(", ") || "no segments"}. Mandatory approval rules remain active.</p></Panel><SettingSection title="Operating mode"><div className="segmented-control"><button className={mode === "propose" ? "segmented-active" : ""} onClick={() => onMode(false)}>Propose · everything asks first</button><button className={mode === "autopilot" ? "segmented-active" : ""} onClick={() => onMode(true)}>Autopilot · scoped execution</button></div></SettingSection><SettingSection title="Autopilot scope"><SettingToggle label="Enabled" detail="Whether scoped actions can execute automatically" checked={scope.enabled} onChange={(checked) => onSave({ enabled: checked })} /><SettingToggle label="Email channel" detail="Allowed channel" checked={scope.allowed_channels.includes("EMAIL")} onChange={toggleEmail} /><div className="setting-row"><span><strong>Segments in scope</strong><small>Derived from backend companies</small></span><div className="setting-chips">{segments.map((segment) => <button key={segment} className={scope.allowed_segments.includes(segment) ? "chip-selected" : ""} onClick={() => toggleSegment(segment)}>{segment}</button>)}</div></div><div className="setting-row"><span><strong>Daily send cap</strong><small>Persisted autopilot limit</small></span><Input className="scope-number" type="number" min={1} value={scope.max_sends_per_day} onChange={(event) => onSave({ max_sends_per_day: Number(event.target.value) })} /></div></SettingSection><SettingSection title="Approval rules · always ask"><SettingToggle label="Intro requests" detail="Always require human approval" checked onChange={() => undefined} /><SettingToggle label="External actions" detail="Always require human approval" checked onChange={() => undefined} /><SettingToggle label="Budget exceptions" detail="Always require human approval" checked onChange={() => undefined} /></SettingSection><SettingSection title="Agent controls"><div className="control-buttons">{status?.stopped ? <Button className="teal-button" onClick={onResume}><Play size={14} /> Resume</Button> : <><Button variant="outline" onClick={onPause}><Pause size={14} /> Pause</Button><Button variant="outline" onClick={onStop}><StopCircle size={14} /> Stop</Button></>}</div><p className="mono muted-copy">Today: {status?.today_budget_used ?? 0} action units used.</p></SettingSection></div>
}

function SettingSection({ title, children }: { title: string; children: ReactNode }) { return <section className="setting-section"><h2>{title}</h2><Panel>{children}</Panel></section> }
function SettingToggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (checked: boolean) => void }) { return <div className="setting-row"><span><strong>{label}</strong><small>{detail}</small></span><Switch checked={checked} onCheckedChange={onChange} aria-label={label} /></div> }
