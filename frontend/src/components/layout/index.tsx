import { useEffect, useState } from "react"
import type { HTMLAttributes, ReactNode } from "react"
import type { LucideIcon } from "lucide-react"
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Bell,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileClock,
  GitBranch,
  Info,
  Mail,
  Menu,
  Network,
  Pause,
  Play,
  Radar,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Stamp,
  StopCircle,
  Sun,
  TrendingUp,
  X,
  Zap,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  useActivity,
  useApproveAction,
  useBriefing,
  useEditAction,
  usePause,
  usePipeline,
  usePolicy,
  useQueue,
  useRejectAction,
  useResume,
  useRollbackPolicy,
  useSetMode,
  useStop,
  useSystemStatus,
  useVariants,
  useWarmEdges,
} from "@/lib/api/hooks"
import type { Action, ActivityLog, PipelineStage, Variant, WarmEdge } from "@/lib/api/client"

type Screen = "today" | "opportunities" | "approvals" | "review" | "activity" | "learning" | "relationships" | "settings"
type DecisionState = "pending" | "confirming" | "approved" | "rejected"

interface DemoOpportunity {
  id: string
  company: string
  contact: string
  role: string
  signal: string
  signalType: string
  age: string
  strength: number
  icp: number
  warmth: number
  nextBest: number
  action: string
  status: string
  why: string
}

interface DemoAction {
  id: string
  opportunity_id: string
  action_type: Action["action_type"]
  variant_id: string
  channel: Action["channel"]
  timing: string
  segment: string
  expected_effect: string
  confidence: number
  status: Action["status"]
  subject: string
  body: string
  company_name: string
  contact_name: string
  contact_title: string
}

const demoOpportunities: DemoOpportunity[] = [
  { id: "OPP-1042", company: "Acme Analytics", contact: "Ava Chen", role: "VP Growth", signal: "Series B - $32M", signalType: "funding", age: "2d", strength: 86, icp: 92, warmth: 3, nextBest: 94, action: "Warm intro email via Marcus", status: "PROPOSED", why: "Fresh raise + warm path + peak fit" },
  { id: "OPP-1039", company: "Fathom ML", contact: "Ben Osei", role: "Co-founder", signal: "Trials 3x in 10 days", signalType: "product", age: "1d", strength: 72, icp: 88, warmth: 1, nextBest: 86, action: "Founder-to-founder email", status: "QUALIFIED", why: "Usage spike, tiny window" },
  { id: "OPP-1036", company: "Driftwood Retail", contact: "Mara Voss", role: "eCommerce Director", signal: "Podcast: waste 30% on Meta", signalType: "content", age: "3d", strength: 58, icp: 74, warmth: 2, nextBest: 79, action: "CAC case study + Dana intro", status: "PLANNED", why: "Named pain, warm via Dana" },
  { id: "OPP-1031", company: "Cobalt Health", contact: "Priya Nair", role: "Head of Ops", signal: "4 growth roles posted", signalType: "hiring", age: "5d", strength: 64, icp: 81, warmth: 2, nextBest: 77, action: "Ops checklist + Dana intro", status: "PLANNED", why: "Scaling pain, ICP strong" },
  { id: "OPP-1027", company: "Elm & Oak", contact: "Sophie Laurent", role: "Managing Partner", signal: "Seed extension rumored", signalType: "funding", age: "9d", strength: 39, icp: 58, warmth: 2, nextBest: 61, action: "-", status: "SKIPPED", why: "Below budget bar this week" },
]

const demoAction: DemoAction = {
  id: "ACT-2214",
  opportunity_id: "OPP-1042",
  action_type: "OUTREACH_EMAIL",
  variant_id: "B - warm + short",
  channel: "EMAIL",
  timing: "Tomorrow, 9:12 AM local time",
  segment: "SaaS - Analytics",
  expected_effect: "A concise warm-path email with a 14.6% predicted reply chance.",
  confidence: 0.78,
  status: "PROPOSED",
  subject: "Congrats on the raise, Ava - one idea for Q3",
  body: "Hi Ava,\n\nMarcus flagged the Series B - congratulations. Going from 8 to 40 heads in a year is the fun part and the hard part.\n\nOne thought before you scale spend: we made a 6-minute teardown of how B2B analytics teams trimmed CAC 15-25% in their first two quarters post-raise. Acme is one of the three examples.\n\nWorth a look now, or better after launch week?\n\n- Jordan",
  company_name: "Acme Analytics",
  contact_name: "Ava Chen",
  contact_title: "VP Growth",
}

const demoActivity: ActivityLog[] = [
  { id: "EV-902", at: "09:41", actor: "AGENT", action_id: "ACT-2209", event: "Sent ops checklist email", status: "EXECUTED", outcome: "Delivered", reason: "Within autopilot scope", detail: "Cobalt Health", policy_version: 14 },
  { id: "EV-901", at: "09:12", actor: "AGENT", action_id: "ACT-2201", event: "Proposed case-study email", status: "PROPOSED", outcome: "Awaiting you", reason: "Outside autopilot scope", detail: "Driftwood Retail", policy_version: 14 },
  { id: "EV-900", at: "08:55", actor: "AGENT", action_id: "ACT-2198", event: "Outcome recorded: reply, positive", status: "LEARNED", outcome: "Send the deck - Ben Osei", reason: "Feed -> learning", detail: "Fathom ML", policy_version: 14 },
  { id: "EV-899", at: "08:30", actor: "AGENT", action_id: "ACT-2191", event: "Guardrail block", status: "BLOCKED", outcome: "Held - weekly contact cap", reason: "Rule: 1 touch / 7d / contact", detail: "Elm & Oak", policy_version: 14 },
  { id: "EV-898", at: "Yesterday", actor: "AGENT", action_id: "-", event: "Policy v13 -> v14 applied", status: "LEARNED", outcome: "Openers capped at 70 words", reason: "3 too-long rejections", detail: "Policy", policy_version: 14 },
]

const demoVariants = [
  { id: "A", name: "Direct ask", sent: 41, replies: 4, rate: 9.8, ci: [3.3, 21.4], share: 22 },
  { id: "B", name: "Warm + short", sent: 38, replies: 7, rate: 18.4, ci: [9, 32.1], share: 58 },
  { id: "C", name: "Question opener", sent: 29, replies: 3, rate: 10.3, ci: [2.7, 26], share: 14 },
  { id: "D", name: "Resource-first", sent: 12, replies: 1, rate: 8.3, ci: [1.2, 33.1], share: 6 },
]

const navGroups: Array<{ label: string; items: Array<{ id: Screen; label: string; icon: LucideIcon }> }> = [
  { label: "Operate", items: [{ id: "today", label: "Today", icon: Sun }, { id: "opportunities", label: "Opportunities", icon: Radar }, { id: "approvals", label: "Approvals", icon: Stamp }, { id: "review", label: "Action review", icon: Mail }, { id: "activity", label: "Activity", icon: Activity }] },
  { label: "Improve", items: [{ id: "learning", label: "Learning", icon: GitBranch }, { id: "relationships", label: "Relationships", icon: Network }] },
  { label: "Control", items: [{ id: "settings", label: "Settings", icon: Settings2 }] },
]

function initials(name: string) {
  return name.split(" ").map((part) => part[0]).slice(0, 2).join("").toUpperCase()
}

function formatStatus(status: string) {
  return status.toLowerCase().replaceAll("_", " ")
}

function warmLabel(value: number) {
  return value >= 3 ? "warm" : value === 2 ? "medium" : "cold"
}

function Panel({ children, className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`loop-panel ${className}`} {...props}>{children}</div>
}

function Pill({ children, tone = "plain", dot = false }: { children: ReactNode; tone?: "plain" | "info" | "warn" | "ok" | "risk"; dot?: boolean }) {
  return <span className={`loop-pill pill-${tone}`}>{dot && <span className="pill-dot" />}{children}</span>
}

function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  return <div className={`loop-avatar avatar-${size}`}>{initials(name)}</div>
}

function Meter({ value, tone = "teal" }: { value: number; tone?: "teal" | "green" | "amber" | "coral" }) {
  return <div className={`loop-meter meter-${tone}`}><span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>
}

function SectionHeading({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return <div className="section-heading"><h2>{title}</h2>{action && <button className="text-link" onClick={onAction}>{action} <ArrowRight size={13} /></button>}</div>
}

function getFallbackAction(action?: Action): DemoAction {
  if (!action) return demoAction
  return { ...demoAction, ...action, subject: action.subject || demoAction.subject, body: action.body || demoAction.body, company_name: action.company_name || demoAction.company_name, contact_name: action.contact_name || demoAction.contact_name, contact_title: action.contact_title || demoAction.contact_title }
}

export function Layout() {
  const [screen, setScreen] = useState<Screen>(() => (localStorage.getItem("loop.screen") as Screen) || "today")
  const [selectedOpportunity, setSelectedOpportunity] = useState<string | null>(null)
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null)
  const [decisionState, setDecisionState] = useState<DecisionState>("pending")
  const [subject, setSubject] = useState(demoAction.subject)
  const [body, setBody] = useState(demoAction.body)
  const [note, setNote] = useState("")
  const [rejectReason, setRejectReason] = useState("")
  const [edited, setEdited] = useState(false)
  const [regenerated, setRegenerated] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)
  const [traceStage, setTraceStage] = useState(4)
  const [toast, setToast] = useState<{ message: string; tone: "ok" | "info" | "risk" } | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const { data: status } = useSystemStatus()
  const { data: briefing } = useBriefing()
  const { data: pipeline } = usePipeline()
  const { data: queue = [] } = useQueue()
  const { data: activity = [] } = useActivity({ limit: 25 })
  const { data: variants = [] } = useVariants()
  const { data: policy } = usePolicy()
  const { data: warmEdges = [] } = useWarmEdges()
  const pauseMutation = usePause()
  const stopMutation = useStop()
  const resumeMutation = useResume()
  const setModeMutation = useSetMode()
  const approveMutation = useApproveAction()
  const rejectMutation = useRejectAction()
  const editMutation = useEditAction()
  const rollbackMutation = useRollbackPolicy()

  const liveAction = queue.find((item) => item.id === selectedActionId) || queue[0]
  const activeAction = getFallbackAction(liveAction)
  const liveActionSelected = Boolean(liveAction)
  const liveActivity = activity.length > 0 ? activity : demoActivity
  const liveVariants = variants.length > 0 ? variants : demoVariants.map((item) => ({ id: item.id, name: item.name, template: "", channel: "EMAIL" as const, timing_slot: "MORNING", tone_profile: "WARM", personalization_depth: 2, segment: "saas-b2b", stats: { sent: item.sent, replies: item.replies, meetings: 0, positive: item.replies, negative: 0, unsub: 0 } }))
  const livePipeline = pipeline && pipeline.length > 0 ? pipeline : [{ stage: "QUALIFIED", count: 48, arr: 0 }, { stage: "PROPOSED", count: 31, arr: 0 }, { stage: "SENT", count: 22, arr: 0 }, { stage: "OUTCOME", count: 6, arr: 0 }, { stage: "WON", count: 2, arr: 184000 }]

  const isPaused = Boolean(status?.paused)
  const isStopped = Boolean(status?.stopped)
  const currentMode = status?.mode === "AUTOPILOT" ? "autopilot" : "propose"
  const pendingCount = (status?.queue_count ?? queue.length) || 1
  const currentPolicy = policy?.version ?? 14

  useEffect(() => { localStorage.setItem("loop.screen", screen) }, [screen])
  useEffect(() => { setSubject(activeAction.subject); setBody(activeAction.body); setDecisionState(activeAction.status === "REJECTED" ? "rejected" : "pending"); setEdited(false) }, [activeAction.id])

  const notify = (message: string, tone: "ok" | "info" | "risk" = "info") => {
    setToast({ message, tone })
    window.setTimeout(() => setToast(null), 4200)
  }

  const navigate = (next: Screen) => { setScreen(next); setSelectedOpportunity(null); setMobileNavOpen(false) }
  const openReview = (actionId?: string) => { if (actionId) setSelectedActionId(actionId); setDecisionState("pending"); setScreen("review") }
  const toggleMode = (autopilot: boolean) => { setModeMutation.mutate(autopilot ? "AUTOPILOT" : "PROPOSE"); notify(autopilot ? "Autopilot on - scoped per Settings" : "Autopilot off - every action asks first") }
  const confirmApproval = () => {
    if (liveActionSelected) approveMutation.mutate({ id: activeAction.id, note })
    setDecisionState("approved")
    notify("Approved - scheduled in simulation", "ok")
    if (!liveActionSelected) {
      window.setTimeout(() => notify("Sent in simulation - guardrails re-checked, 5/5", "ok"), 2600)
      window.setTimeout(() => notify("Ava replied - positive. Policy v15 applied.", "ok"), 6200)
    }
  }
  const reject = () => {
    if (!rejectReason) { notify("Choose a reason first - that feedback trains Loop", "risk"); return }
    if (liveActionSelected) rejectMutation.mutate({ id: activeAction.id, reason: rejectReason })
    setDecisionState("rejected")
    notify(`Rejected - “${rejectReason}” recorded as feedback`)
  }
  const saveEdit = () => { if (liveActionSelected) editMutation.mutate({ id: activeAction.id, changes: { subject, body }, note }); setEdited(true); notify("Edits saved - Loop will learn from this decision", "ok") }
  const regenerate = () => {
    setRegenerated((current) => !current)
    setSubject(regenerated ? demoAction.subject : "Acme's Series B - a small gift for the growth team")
    setBody(regenerated ? demoAction.body : "Hi Ava,\n\nSaw the news - congratulations on the round.\n\nQuick idea: a 6-minute teardown of what 14 B2B analytics teams did to their CAC in the two quarters after raising. Acme-shaped, no pitch.\n\nWant it now, or after launch week?\n\n- Jordan")
    setEdited(false)
    notify("New draft requested - second angle selected")
  }

  return <div className="loop-app">
    <aside className={`loop-sidebar ${mobileNavOpen ? "sidebar-open" : ""}`} aria-label="Primary navigation">
      <div className="loop-brand"><div className="loop-mark">L</div><span>Loop</span></div>
      <button className="workspace-switch"><span>Kestrel Labs</span><span className="mono">GT-01 <ChevronDown size={13} /></span></button>
      <nav className="loop-nav">{navGroups.map((group) => <div key={group.label} className="nav-group"><div className="nav-label">{group.label}</div>{group.items.map((item) => { const Icon = item.icon; const count = item.id === "approvals" ? pendingCount : item.id === "learning" ? 2 : undefined; return <button key={item.id} className={`nav-link ${screen === item.id ? "nav-active" : ""}`} aria-current={screen === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><Icon size={16} /><span>{item.label}</span>{count !== undefined && <span className="nav-count">{count}</span>}</button> })}</div>)}</nav>
      <div className="agent-status"><div className="status-title"><span className={`heartbeat-dot ${isPaused || isStopped ? "dot-muted" : ""}`} /> Agent status <Pill tone={currentMode === "autopilot" ? "info" : "plain"}>{currentMode}</Pill></div><div className="status-row"><span>Heartbeat</span><strong>{isStopped ? "stopped" : isPaused ? "paused" : "live"}</strong></div><div className="status-row"><span>Budget today</span><strong>{status?.today_budget_used ?? 22} / 40</strong></div><Meter value={((status?.today_budget_used ?? 22) / 40) * 100} tone="teal" /><Pill tone="ok" dot><ShieldCheck size={12} /> Guardrails healthy</Pill></div>
    </aside>

    <div className="loop-main">
      <header className="loop-topbar"><button className="mobile-menu" onClick={() => setMobileNavOpen((open) => !open)} aria-label="Open navigation"><Menu size={19} /></button><div className="breadcrumb"><span>Loop</span><ChevronRight size={13} /><strong>{screen === "review" ? "Approvals / ACT-2214" : navGroups.flatMap((group) => group.items).find((item) => item.id === screen)?.label}</strong></div><div className="topbar-spacer" /><div className="mode-switch"><button className={currentMode === "propose" ? "mode-selected" : ""} onClick={() => toggleMode(false)}>Propose</button><button className={currentMode === "autopilot" ? "mode-selected" : ""} onClick={() => toggleMode(true)}>Autopilot</button></div><div className="heartbeat"><span className={`heartbeat-dot ${isPaused || isStopped ? "dot-muted" : ""}`} /> {isStopped ? "stopped" : isPaused ? "paused" : "heartbeat live"}</div><button className="icon-button" aria-label="Notifications"><Bell size={16} /></button><Avatar name="Jordan Reyes" size="sm" /></header>
      <main className="loop-view"><div className="loop-content">
        {screen === "today" && <TodayScreen status={status} briefing={briefing} pipeline={livePipeline} activity={liveActivity} currentPolicy={currentPolicy} decisionState={decisionState} onReview={() => openReview()} onNavigate={navigate} />}
        {screen === "opportunities" && <OpportunitiesScreen selected={selectedOpportunity} onSelect={setSelectedOpportunity} onReview={openReview} onNavigate={navigate} />}
        {screen === "approvals" && <ApprovalsScreen queue={queue} pendingCount={pendingCount} onReview={openReview} onNavigate={navigate} currentMode={currentMode} />}
        {screen === "review" && <ReviewScreen action={activeAction} state={decisionState} subject={subject} body={body} note={note} rejectReason={rejectReason} edited={edited} onSubjectChange={(value) => { setSubject(value); setEdited(true) }} onBodyChange={(value) => { setBody(value); setEdited(true) }} onNoteChange={setNote} onRejectReasonChange={setRejectReason} onApprove={() => setDecisionState("confirming")} onConfirm={confirmApproval} onBack={() => setDecisionState("pending")} onReject={reject} onSaveEdit={saveEdit} onRegenerate={regenerate} onNavigate={navigate} onTrace={() => setTraceOpen(true)} mutationPending={approveMutation.isPending || rejectMutation.isPending || editMutation.isPending} />}
        {screen === "activity" && <ActivityScreen activity={liveActivity} onTrace={() => setTraceOpen(true)} />}
        {screen === "learning" && <LearningScreen variants={liveVariants} policyVersion={currentPolicy} onRollback={() => { rollbackMutation.mutate(currentPolicy - 1); notify("Policy rolled back - future actions reverted") }} onNavigate={navigate} />}
        {screen === "relationships" && <RelationshipsScreen warmEdges={warmEdges} onQueue={() => { notify("Intro request drafted - added to Approvals", "ok"); navigate("approvals") }} />}
        {screen === "settings" && <SettingsScreen status={status} mode={currentMode} onMode={toggleMode} onPause={() => { pauseMutation.mutate(); notify("Agent paused - approvals still queue") }} onStop={() => { stopMutation.mutate(); notify("Agent stopped", "risk") }} onResume={() => { resumeMutation.mutate(); notify("Agent resumed - heartbeat live", "ok") }} />}
      </div></main>
      <nav className="mobile-bottom-nav" aria-label="Mobile navigation">{["today", "opportunities", "approvals", "activity"].map((item) => <button key={item} className={screen === item ? "mobile-nav-active" : ""} onClick={() => navigate(item as Screen)}>{item === "today" ? <Sun size={17} /> : item === "opportunities" ? <Radar size={17} /> : item === "approvals" ? <Stamp size={17} /> : <Activity size={17} />}{item === "approvals" && <em>{pendingCount}</em>}<small>{item === "opportunities" ? "Opps" : item[0].toUpperCase() + item.slice(1)}</small></button>)}</nav>
    </div>
    {toast && <div className={`loop-toast toast-${toast.tone}`} role="status"><span className="toast-icon">{toast.tone === "ok" ? <Check size={15} /> : toast.tone === "risk" ? <CircleAlert size={15} /> : <Info size={15} />}</span>{toast.message}</div>}
    {traceOpen && <TraceOverlay action={activeAction} selectedStage={traceStage} onSelectStage={setTraceStage} onClose={() => setTraceOpen(false)} />}
  </div>
}

function TodayScreen({ status, briefing, pipeline, activity, currentPolicy, decisionState, onReview, onNavigate }: { status?: { mode?: string; today_sent: number; today_budget_used: number }; briefing?: { what_ran?: { total_actions: number } }; pipeline: PipelineStage[]; activity: ActivityLog[]; currentPolicy: number; decisionState: DecisionState; onReview: () => void; onNavigate: (screen: Screen) => void }) {
  const resolved = decisionState === "approved"
  return <><section className="loop-brief"><div className="brief-kicker"><Sparkles size={13} /> Agent brief <span>Today · {briefing?.what_ran?.total_actions ?? 214} companies screened overnight</span></div><p>{resolved ? "You approved the Acme intro email. It is scheduled in simulation; I will surface the outcome here when it lands." : "Good morning, Jordan. Overnight I screened 214 companies and found 3 worth your time. The standout is Acme Analytics: a fresh Series B signal, a strong ICP fit, and Ava Chen - your warmest way in via Marcus Reed."}</p><div className="brief-meta"><span>mode: {status?.mode?.toLowerCase() ?? "propose"}</span><span>heartbeat: live</span><span>guardrails: 5/5 today</span><span>policy v{currentPolicy}</span></div></section><SectionHeading title="Needs your decision" action="All approvals" onAction={() => onNavigate("approvals")} /><Panel className={resolved ? "decision-resolved" : "decision-hero"}>{resolved ? <div className="decision-resolved-inner"><div className="decision-icon"><Check size={18} /></div><div><strong>Acme intro email scheduled</strong><p>Tomorrow, 9:12 AM · simulation · guardrails passed 5/5</p><button className="text-link" onClick={() => onNavigate("learning")}>See what changed because of this <ArrowRight size={13} /></button></div></div> : <><div><Pill tone="warn" dot>Waiting 4h · expires in 20h</Pill><h3>Warm intro: congratulate the raise, offer the CAC teardown</h3><p>Acme Analytics · Ava Chen, VP Growth · email via Marcus Reed's path · expected reply 14.6%</p></div><div className="decision-cta"><Button className="teal-button" onClick={onReview}>Review action <ArrowRight size={14} /></Button><span>approval takes ~30 seconds</span></div></>}</Panel><div className="today-grid"><div><SectionHeading title="Next best actions" action="Full queue" onAction={() => onNavigate("opportunities")} /><Panel>{demoOpportunities.slice(1, 4).map((item) => <button className="next-action-row" key={item.id} onClick={() => onNavigate("opportunities")}><strong>{item.nextBest}<small>NEXT-BEST</small></strong><span><b>{item.company}</b><em>{item.contact} · {item.action}</em><small>{item.why}</small></span><Pill tone="plain">{item.age} old</Pill></button>)}</Panel><SectionHeading title="Learning since yesterday" action="Why it changed" onAction={() => onNavigate("learning")} /><Panel><Delta title="Emails got shorter" detail="After 3 too-long rejections, openers dropped 132 -> 68 words." icon={<TrendingUp size={15} />} /><Delta title="Mid-week mornings win" detail="Tue-Thu 9-11 AM now out-replies Monday 1.8x." icon={<Zap size={15} />} /></Panel></div><div><SectionHeading title="The loop today" /><Panel className="loop-today"><Funnel pipeline={pipeline} /><div className="mini-ledger">{activity.slice(0, 4).map((event) => <div className="mini-event" key={event.id}><span className={`event-dot event-${event.status.toLowerCase()}`} /><span><small>{event.at} · {event.actor}</small><b>{event.detail || event.event}</b><em>{event.outcome || event.reason}</em></span></div>)}</div><div className="today-budget"><span>Today sent</span><strong>{status?.today_sent ?? 22} <small>/ 40 actions</small></strong><Meter value={((status?.today_budget_used ?? 22) / 40) * 100} /></div></Panel></div></div></>
}

function Delta({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) { return <div className="delta-row"><div className="delta-icon">{icon}</div><div><strong>{title}</strong><p>{detail}</p></div></div> }

function Funnel({ pipeline }: { pipeline: PipelineStage[] }) { const max = Math.max(...pipeline.map((stage) => stage.count), 1); return <div className="funnel"><div className="funnel-bars">{pipeline.slice(0, 5).map((stage) => <div className="funnel-step" key={stage.stage}><strong>{stage.count}</strong><span style={{ height: `${Math.max(7, stage.count / max * 60)}px` }} /><small>{stage.stage}</small></div>)}</div><div className="funnel-arr"><strong>${Math.round((pipeline.find((stage) => stage.stage === "WON")?.arr ?? 184000) / 1000)}k</strong><small>SIM. ARR</small></div></div> }

function OpportunitiesScreen({ selected, onSelect, onReview, onNavigate }: { selected: string | null; onSelect: (id: string | null) => void; onReview: (id?: string) => void; onNavigate: (screen: Screen) => void }) {
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState("all")
  const selectedOpportunity = demoOpportunities.find((item) => item.id === selected)
  const rows = demoOpportunities.filter((item) => filter === "all" || item.signalType === filter).filter((item) => `${item.company} ${item.contact} ${item.signal}`.toLowerCase().includes(query.toLowerCase()))
  if (selectedOpportunity) return <OpportunityDetail opportunity={selectedOpportunity} onBack={() => onSelect(null)} onReview={onReview} onNavigate={onNavigate} />
  return <><div className="page-intro"><div><span className="eyebrow">OPERATE / WORKING QUEUE</span><h1>Opportunities</h1><p>Signals with enough evidence to deserve a next action.</p></div><Pill tone="plain">7 open · 3 action-ready</Pill></div><div className="queue-toolbar"><div className="search-field"><Search size={15} /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search company, contact, signal..." aria-label="Search opportunities" /></div><div className="filter-chips">{["all", "funding", "hiring", "product", "content", "pricing"].map((item) => <button key={item} className={filter === item ? "filter-active" : ""} onClick={() => setFilter(item)}>{item === "all" ? "All signals" : item}</button>)}</div></div><Panel className="opportunity-table"><div className="opportunity-header"><span>Company / contact</span><span>Signal</span><span>ICP</span><span>Warmth</span><span>Next action</span><span>Status</span><span>Score</span></div>{rows.map((item) => <button className={`opportunity-row ${item.id === "OPP-1042" ? "opportunity-hot" : ""}`} key={item.id} onClick={() => onSelect(item.id)}><div className="opportunity-company"><Avatar name={item.company} size="sm" /><span><strong>{item.company}</strong><small>{item.contact} · {item.role}</small></span></div><span><Pill tone="plain">{item.signal}</Pill><small className="mono">{item.age} ago · strength {item.strength}</small></span><span className="score-cell"><Meter value={item.icp} /><b>{item.icp}</b></span><Warmth value={item.warmth} /><span className="next-action-cell">{item.action}</span><Pill tone={item.status === "PROPOSED" ? "warn" : item.status === "SKIPPED" ? "plain" : "info"} dot>{formatStatus(item.status)}</Pill><strong className="next-score">{item.nextBest}</strong></button>)}</Panel><p className="table-footnote">{rows.length} opportunities shown · bulk select remains disabled by design</p></>
}

function Warmth({ value }: { value: number }) { return <span className={`warmth warmth-${value}`} title={`${warmLabel(value)} relationship`}><i /><i /><i /><small>{warmLabel(value)}</small></span> }

function OpportunityDetail({ opportunity, onBack, onReview, onNavigate }: { opportunity: DemoOpportunity; onBack: () => void; onReview: (id?: string) => void; onNavigate: (screen: Screen) => void }) {
  const isAcme = opportunity.id === "OPP-1042"
  return <><button className="back-link" onClick={onBack}><ArrowLeft size={14} /> All opportunities</button><div className="detail-heading"><div><Avatar name={opportunity.company} size="lg" /><div><span className="eyebrow">{opportunity.id} · opened {opportunity.age} ago</span><h1>{opportunity.company}</h1><p>{opportunity.contact} · {opportunity.role}</p></div></div>{isAcme && <Button className="teal-button" onClick={() => onReview()}>Review proposed action <ArrowRight size={14} /></Button>}</div><div className="detail-grid"><div className="detail-column"><Panel><h3>Company</h3><DefinitionList entries={[["Segment", "SaaS · Analytics"], ["Size", "84 seats"], ["ARR band", "$8-12M ARR"], ["Location", "Austin"], ["ICP fit", `${opportunity.icp} / 100 · model v6`]]} /></Panel><Panel><h3>Contact</h3><div className="identity-row"><Avatar name={opportunity.contact} /><span><strong>{opportunity.contact}</strong><small>{opportunity.role} · {opportunity.company}</small></span></div><DefinitionList entries={[["Email", "ava.chen@acmeanalytics.co"], ["Note", "Took over growth in Jan · ex-Northbeam"]]} /></Panel><Panel><h3>Signal timeline</h3><Timeline items={[["Mar 10", "Series B announced - $32M led by Ridgeline"], ["Mar 11", "Ava Chen promoted to VP Growth"], ["Mar 11", "4 growth roles posted"], ["Mar 12", "Marcus Reed path identified · strength 0.86"]]} /></Panel></div><div className="detail-column"><Panel><h3>Why it qualified</h3><EvidenceList items={["ICP fit 92 · B2B analytics, 84 seats, 4 growth roles", "Signal strength 86 · $32M Series B, 2 days old", "Warm path Marcus -> Ava · 0.86 · 3/3 intros replied", "Timing · Day 2 post-raise · send window opens tomorrow"]} /></Panel><Panel><h3>Relationship path</h3><div className="relationship-path"><span>You</span><ArrowRight size={13} /><span className="path-strong">Marcus Reed · 0.86</span><ArrowRight size={13} /><span>{opportunity.contact}</span></div><p className="muted-copy">Marcus worked with Ava at Northbeam for 2 years. His 3 intros all got replies.</p><button className="text-link" onClick={() => onNavigate("relationships")}>Open graph <ArrowRight size={13} /></button></Panel><Panel><h3>Previous actions</h3><p className="empty-copy">None - first touch. Last contact was 214 days ago.</p></Panel></div><div className="detail-column"><Panel className="recommendation-panel"><h3>Current recommendation</h3><h2>{isAcme ? "Warm intro email - congratulate the raise, offer the CAC teardown" : opportunity.action}</h2><DefinitionList entries={[["Channel", "Email · via Marcus's intro"], ["Timing", "Tomorrow, 9:12 AM"], ["Variant", "B · warm + short · 78% confidence"]]} />{isAcme && <Button className="teal-button full-button" onClick={() => onReview()}>Open in action review</Button>}</Panel><Panel><h3>Why now?</h3><p className="long-copy">{opportunity.why}. Reply windows to funding news peak days 3-5; this signal is approaching the window.</p></Panel><Panel><h3>What would change this?</h3><div className="what-if-list"><span>No reply by Mar 20 {"->"} follow up Thursday</span><span>Marcus opts out {"->"} direct Variant A email</span><span>Round details wrong {"->"} pause and re-verify</span></div></Panel></div></div></>
}

function ApprovalsScreen({ queue, pendingCount, onReview, onNavigate, currentMode }: { queue: Action[]; pendingCount: number; onReview: (id?: string) => void; onNavigate: (screen: Screen) => void; currentMode: string }) {
  const items = queue.length > 0 ? queue : [demoAction as Action, { ...demoAction, id: "ACT-2201", company_name: "Driftwood Retail", contact_name: "Mara Voss", subject: "Mara - the 30% you mentioned on podcast", status: "PROPOSED" as const }]
  return <><div className="page-intro"><div><span className="eyebrow">OPERATE / WAITING ON YOU</span><h1>Approvals</h1><p>Human decisions are product data. Every reason stays attached to the action.</p></div><Pill tone="warn" dot>{pendingCount} waiting</Pill></div><Panel className="approval-queue">{items.map((item) => { const action = getFallbackAction(item); return <div className="approval-row" key={item.id}><Avatar name={action.company_name} /><div className="approval-copy"><strong>{action.company_name}</strong><span>{action.contact_name} · {action.action_type.replaceAll("_", " ")}</span><small>{action.id} · {action.timing}</small></div><Pill tone="warn" dot>{item.id === demoAction.id ? "waiting 4h" : "queued"}</Pill><Button className="teal-button small-button" onClick={() => onReview(item.id)}>Review <ArrowRight size={13} /></Button></div> })}</Panel><div className="two-column"><Panel><h3>Autopilot log · today</h3><Timeline items={[["09:41 · Loop", "Cobalt Health - ops checklist sent automatically"], ["09:12 · Loop", "Driftwood case study held for you"], ["08:55 · Loop", "Fathom outcome recorded: positive reply"]]} /></Panel><Panel><h3>What autopilot may do</h3><p className="long-copy">With the current scope, Loop may execute email actions for approved segments inside the daily budget. Intro requests, external actions, and budget exceptions still need your approval.</p><button className="text-link" onClick={() => onNavigate("settings")}>Adjust boundaries <ArrowRight size={13} /></button><div className="mode-summary"><Pill tone={currentMode === "autopilot" ? "info" : "plain"} dot>{currentMode}</Pill><span>Mode is controlled in Settings</span></div></Panel></div></>
}

function ReviewScreen({ action, state, subject, body, note, rejectReason, edited, onSubjectChange, onBodyChange, onNoteChange, onRejectReasonChange, onApprove, onConfirm, onBack, onReject, onSaveEdit, onRegenerate, onNavigate, onTrace, mutationPending }: { action: DemoAction; state: DecisionState; subject: string; body: string; note: string; rejectReason: string; edited: boolean; onSubjectChange: (value: string) => void; onBodyChange: (value: string) => void; onNoteChange: (value: string) => void; onRejectReasonChange: (value: string) => void; onApprove: () => void; onConfirm: () => void; onBack: () => void; onReject: () => void; onSaveEdit: () => void; onRegenerate: () => void; onNavigate: (screen: Screen) => void; onTrace: () => void; mutationPending: boolean }) {
  if (state === "approved") return <DecisionComplete tone="approved" subject={subject} edited={edited} onNavigate={onNavigate} />
  if (state === "rejected") return <DecisionComplete tone="rejected" reason={rejectReason} onNavigate={onNavigate} onRetry={onBack} />
  const confirming = state === "confirming"
  return <><div className="page-intro review-intro"><div><span className="eyebrow">APPROVALS / {action.id}</span><h1>Action review</h1><p>Target, message, evidence, and safety boundary in one view.</p></div><Pill tone="warn" dot>Propose mode · waiting</Pill></div><div className="review-grid"><aside className="review-rail"><ReviewContext action={action} /></aside><section className="review-editor"><Panel><div className="editor-meta"><Pill tone="info"><Mail size={12} /> Email · via Marcus's intro</Pill><Pill tone="plain"><Clock3 size={12} /> {action.timing}</Pill><span className={`edited-label ${edited ? "edited-active" : ""}`}>{edited ? <><Check size={12} /> Edited by you · changes tracked</> : "Agent-drafted · editable"}</span><button className="text-link" onClick={onRegenerate}><RotateCcw size={13} /> New draft</button></div><div className="editor-fields"><div><Label htmlFor="review-subject">Subject <span>agent-drafted · editable</span></Label><Input id="review-subject" value={subject} onChange={(event) => onSubjectChange(event.target.value)} disabled={confirming} /></div><div><Label htmlFor="review-body">Message <span>personalization depth 2 · policy v14</span></Label><Textarea id="review-body" value={body} onChange={(event) => onBodyChange(event.target.value)} disabled={confirming} /></div></div><div className="expect-row"><span>Expected effect</span><Pill tone="plain">Reply chance <b>14.6%</b></Pill><Pill tone="plain">Meeting chance <b>3.1%</b></Pill><Pill tone="plain">Simulated ARR <b>+$9.2k</b></Pill></div>{!confirming && <div className="editor-note"><Label htmlFor="approval-note">Approval note <span>optional</span></Label><Input id="approval-note" value={note} onChange={(event) => onNoteChange(event.target.value)} placeholder="Why you approved, or what to watch" /></div>}</Panel>{confirming ? <ConfirmSheet action={action} subject={subject} body={body} note={note} edited={edited} onConfirm={onConfirm} onBack={onBack} pending={mutationPending} /> : <div className="approval-footer"><div className="reject-controls"><select aria-label="Rejection reason" value={rejectReason} onChange={(event) => onRejectReasonChange(event.target.value)}><option value="">Reject because...</option><option>Too long</option><option>Too salesy</option><option>Missing personalization</option><option>Wrong target</option><option>Wrong channel</option><option>Bad timing</option><option>Not relevant now</option><option>Other</option></select><Button variant="outline" className="reject-button" onClick={onReject} disabled={mutationPending}><X size={14} /> Reject</Button></div><Button className="teal-button approve-button" onClick={() => { if (edited) onSaveEdit(); onApprove() }} disabled={mutationPending}><Check size={15} /> Approve</Button></div>}<p className="editor-footnote">Rejecting with a reason is how Loop learns - the reason feeds policy, not a trash can.</p></section><aside className="review-rail"><ReviewReasoning onTrace={onTrace} /></aside></div></>
}

function ReviewContext({ action }: { action: DemoAction }) { return <div className="rail-stack"><Panel><h3>Target</h3><div className="identity-row"><Avatar name={action.contact_name} /><span><strong>{action.contact_name}</strong><small>{action.contact_title} · {action.company_name}</small></span></div><Warmth value={3} /><div className="mono contact-email">ava.chen@acmeanalytics.co</div></Panel><Panel><h3>Signal</h3><Pill tone="plain">Series B · $32M</Pill><DefinitionList entries={[["Age", "2 days"], ["Strength", "86 / 100"], ["Source", "Ridgeline press + coverage"]]} /></Panel><Panel><h3>Guardrails · 5/5 pass</h3>{["Frequency · first touch", "Daily budget · 18 of 40 left", "Claims check · source matched", "Sender reputation · 96 / 100", "Data source · public + opt-in"].map((item) => <div className="guardrail-row" key={item}><CheckCircle2 size={14} /> <span>{item}</span></div>)}</Panel><Panel><h3>Runtime</h3><DefinitionList entries={[["Policy", "v14 · Mar 11"], ["Variant", "B · warm + short"], ["Confidence", "78%"], ["Budget", "18 of 40 left"]]} /></Panel></div> }

function ReviewReasoning({ onTrace }: { onTrace: () => void }) { return <div className="rail-stack"><Panel><h3>Why this action</h3><EvidenceList items={["Reply windows to funding news peak on days 3-5.", "Warm path found: Marcus Reed -> Ava Chen, 3/3 intros replied.", "ICP fit 92 - B2B analytics, 84 seats.", "Variant B beats Variant A by +6.2 pts on warm paths."]} /></Panel><Panel><h3>Alternatives considered</h3>{[["Wait 3 days, send Thursday", 71], ["LinkedIn DM only", 63], ["Do nothing for 14 days", 12]].map(([label, score]) => <div className="alternative-row" key={String(label)}><span>{label}</span><b>{score}</b><Meter value={Number(score)} /></div>)}</Panel><Panel><h3>What would change this?</h3><div className="what-if-list"><span>No reply by Mar 20 {"->"} follow up Thursday</span><span>Marcus opts out {"->"} direct Variant A</span><span>Round details wrong {"->"} pause and verify</span></div></Panel><Panel><h3>Audit</h3><Button variant="outline" className="full-button" onClick={onTrace}><GitBranch size={14} /> Open action trace</Button><p className="mono muted-copy">9 stages · signal {"->"} learning</p></Panel></div> }

function ConfirmSheet({ action, subject, body, note, edited, onConfirm, onBack, pending }: { action: DemoAction; subject: string; body: string; note: string; edited: boolean; onConfirm: () => void; onBack: () => void; pending: boolean }) { return <Panel className="confirm-sheet"><div className="confirm-title"><ShieldCheck size={16} /> Approve this send - deliberate, not default</div><div className="confirm-list"><div><b>Action</b><span>Send "{subject}" to {action.contact_name} · tomorrow 9:12 AM · simulation.</span></div><div><b>Your edits</b><span>{edited ? "Yes - originals stay in the audit trail." : "None - sending as drafted."}</span></div><div><b>Note</b><span>{note || "None"}</span></div><div><b>Guardrails</b><span>5/5 passed · re-checked at send time.</span></div><div><b>Learning</b><span>{edited ? "Approval with edits strengthens the edits-help signal." : "Approval reinforces Variant B on warm paths."}</span></div></div><div className="confirm-actions"><Button className="teal-button" onClick={onConfirm} disabled={pending}><Check size={14} /> {pending ? "Approving..." : "Confirm approval"}</Button><Button variant="outline" onClick={onBack}>Back to editor</Button></div><p className="mono confirm-meta">{body.split(/\s+/).length} words · simulation mode · no external send</p></Panel> }

function DecisionComplete({ tone, subject = "", reason = "", edited = false, onNavigate, onRetry }: { tone: "approved" | "rejected"; subject?: string; reason?: string; edited?: boolean; onNavigate: (screen: Screen) => void; onRetry?: () => void }) { const approved = tone === "approved"; return <div className="decision-complete"><div className={`complete-icon ${approved ? "complete-ok" : "complete-risk"}`}>{approved ? <Check size={25} /> : <X size={25} />}</div><span className="eyebrow">ACTION {approved ? "RECORDED" : "REJECTED"}</span><h1>{approved ? `Approved${edited ? " with your edits" : ""}` : `Rejected - ${reason || "feedback recorded"}`}</h1><p>{approved ? `"${subject}" goes out tomorrow at 9:12 AM in simulation. The outcome and what it teaches will land in Learning.` : "The reason is attached to this action. Acme stays qualified, and the next draft will use the feedback."}</p>{approved && <Panel className="next-steps-panel"><h3>What happens next</h3><Timeline items={[["Schedule", "Queued for tomorrow, 9:12 AM local time"], ["Guardrails", "5/5 re-checked at send time"], ["Learning", edited ? "Approval with edits recorded" : "Approval on warm path recorded"], ["Watch", "Reply window is days 1-5"]]} /></Panel>}<div className="complete-actions">{approved ? <><Button variant="outline" onClick={() => onNavigate("activity")}>See activity trail</Button><Button variant="outline" onClick={() => onNavigate("today")}>Back to Today</Button></> : <><Button variant="outline" onClick={onRetry}>Request a new draft</Button><Button className="teal-button" onClick={() => onNavigate("learning")}>See how feedback is used <ArrowRight size={14} /></Button></>}</div></div> }

function ActivityScreen({ activity, onTrace }: { activity: ActivityLog[]; onTrace: () => void }) { const [filter, setFilter] = useState("all"); const filtered = activity.filter((item) => filter === "all" || filter === "blocked" && item.status === "BLOCKED" || filter === "outcomes" && item.outcome || filter === "waiting" && item.status === "PROPOSED" || filter === "learned" && item.status === "LEARNED"); return <><div className="page-intro"><div><span className="eyebrow">OPERATE / OPERATIONAL LEDGER</span><h1>Activity</h1><p>Every action, decision, outcome, and policy change remains reconstructable.</p></div><Button variant="outline" className="small-button"><FileClock size={14} /> Export audit</Button></div><div className="activity-filters">{[["all", "All events"], ["outcomes", "Outcomes"], ["waiting", "Awaiting you"], ["blocked", "Guardrail blocks"], ["learned", "Policy & feedback"]].map(([value, label]) => <button key={value} className={filter === value ? "filter-active" : ""} onClick={() => setFilter(value)}>{label}</button>)}</div><Panel className="activity-ledger">{filtered.map((event) => <ActivityRow key={event.id} event={event} onTrace={onTrace} />)}</Panel></> }

function ActivityRow({ event, onTrace }: { event: ActivityLog; onTrace: () => void }) { return <details className="activity-event"><summary><span className="event-time">{event.at}</span><span className={`actor actor-${event.actor.toLowerCase()}`}>{event.actor}</span><span className="event-main"><strong>{event.detail || event.event}</strong><small>{event.reason}</small></span><Pill tone={event.status === "BLOCKED" ? "risk" : event.status === "PROPOSED" ? "warn" : event.status === "LEARNED" ? "info" : "ok"} dot>{event.status.toLowerCase()}</Pill><span className="mono">v{event.policy_version}</span><ChevronRight className="details-chevron" size={15} /></summary><div className="activity-detail"><DefinitionList entries={[["Outcome", event.outcome || "-"], ["Reason", event.reason || "-"], ["Policy version", `v${event.policy_version}`]]} /><Button variant="outline" className="small-button" onClick={onTrace}><GitBranch size={14} /> Reconstruct full trace</Button></div></details> }

function LearningScreen({ variants, policyVersion, onRollback, onNavigate }: { variants: Variant[]; policyVersion: number; onRollback: () => void; onNavigate: (screen: Screen) => void }) { return <><div className="page-intro"><div><span className="eyebrow">IMPROVE / BEHAVIOR CHANGES</span><h1>Learning</h1><p>Feedback is only useful when it changes what Loop does next.</p></div><Pill tone="ok" dot>Policy v{policyVersion} active</Pill></div><div className="learning-grid"><div><section className="learning-hero"><div className="brief-kicker"><TrendingUp size={13} /> What the agent learned · your feedback, applied</div><p>After three <b>too salesy</b> rejections, emails got shorter and warmer. Reply rate moved <b>+3.1 pts</b> in the first week - and every draft since carries the change.</p></section><SectionHeading title="Before / after" /><div className="before-after"><MessageCard label="Before · policy v13" tone="before" subject="Boost your pipeline with revolutionary GTM intelligence" body="Hi Ava - I noticed Acme just raised. Our platform helps analytics companies like yours 10x their pipeline in weeks. Industry leaders trust our revolutionary approach." /><div className="before-after-arrow"><ArrowRight size={19} /><span>3 too-salesy<br />+ 1 too-long<br />{"->"} v14</span></div><MessageCard label="After · policy v14" tone="after" subject="Congrats on the raise, Ava - one idea for Q3" body="Hi Ava - Marcus flagged the Series B, congratulations. One thought before you scale spend: a 6-minute teardown of how B2B analytics teams trimmed CAC 15-25% post-raise. Worth a look now?" /></div><Panel className="parameter-deltas"><Parameter label="Words in opener" before="132" after="68" delta="-48%" beforeWidth={100} afterWidth={52} /><Parameter label="Tone assertiveness" before="0.70" after="0.48" delta="-0.22" beforeWidth={70} afterWidth={48} /><Parameter label="Personalization depth" before="1" after="2" delta="+1" beforeWidth={25} afterWidth={50} /></Panel><SectionHeading title="Next action changed because..." action="See it in the queue" onAction={() => onNavigate("opportunities")} /><Panel className="next-changed"><div><span className="mono">WAS · UNDER V14</span><strong>Follow-up Thursday at 9:12 AM</strong><small>Standard 48h follow-up cadence</small></div><ArrowRight size={18} /><div><span className="mono">NOW · UNDER V15</span><strong>Reply now - offer the walkthrough</strong><small>Warm-thread replies jump the queue</small></div><p>Trigger: positive reply on a warm-path thread. Scope: threads where you approved the first touch.</p></Panel><SectionHeading title="Variant performance" action="90% uncertainty intervals" /><VariantTable variants={variants} /></div><aside className="learning-sidebar"><SectionHeading title="Policy timeline" /><Panel className="policy-timeline"><PolicyRow version={12} title="Banned-phrase list" detail="Revolutionary, game-changer, synergy blocked at draft time." trigger="Content guardrails edit" /><PolicyRow version={13} title="Personalization depth >= 2" detail="Every draft cites two company specifics." trigger="Low reply rate on generic drafts" /><PolicyRow version={14} title="Shorter openers" detail="First paragraph capped at 70 words." trigger="3 too-long / too-salesy rejections" /><PolicyRow version={15} title="Fast-reply priority" detail="Warm-thread replies jump the queue." trigger="Positive reply on warm path" active onRollback={onRollback} /></Panel><Panel className="timing-panel"><h3>When emails win</h3><Parameter label="Tue-Thu · 9-11 AM" before="" after="19.2%" delta="" beforeWidth={0} afterWidth={96} /><Parameter label="Mon · morning" before="" after="10.7%" delta="" beforeWidth={0} afterWidth={54} /><Parameter label="Fri · afternoon" before="" after="7.9%" delta="" beforeWidth={0} afterWidth={40} /><p>Timing shifted automatically after 63 tracked sends.</p></Panel><Panel className="rollback-note"><h3>Rollback is reversible</h3><p>Rollback restores the previous policy for future actions. Already-sent email is untouched, and the rollback remains visible in Activity.</p></Panel></aside></div></> }

function MessageCard({ label, tone, subject, body }: { label: string; tone: string; subject: string; body: string }) { return <div className={`message-card message-${tone}`}><span>{label}</span><strong>{subject}</strong><p>{body}</p>{tone === "after" && <Pill tone="ok" dot>Replies +3.1 pts · first week</Pill>}</div> }
function Parameter({ label, before, after, delta, beforeWidth, afterWidth }: { label: string; before: string; after: string; delta: string; beforeWidth: number; afterWidth: number }) { return <div className="parameter"><span>{label}</span><div className="parameter-bars"><i style={{ width: `${beforeWidth}%` }} /><b style={{ width: `${afterWidth}%` }} /></div><strong>{before && `${before} -> `}{after} {delta && <em>{delta}</em>}</strong></div> }
function PolicyRow({ version, title, detail, trigger, active = false, onRollback }: { version: number; title: string; detail: string; trigger: string; active?: boolean; onRollback?: () => void }) { return <div className="policy-row"><span className="policy-version">v{version}</span><div><strong>{title}</strong><p>{detail}</p><small>{version === 15 ? "Live" : "Mar"} · trigger: {trigger}</small></div>{active ? <><Pill tone="ok" dot>active</Pill><Button variant="outline" className="rollback-button" onClick={onRollback}><RotateCcw size={12} /> Roll back</Button></> : <Pill tone="plain">superseded</Pill>}</div> }
function VariantTable({ variants }: { variants: Variant[] }) { const rows = variants.length > 0 ? variants : []; return <Panel className="variant-table"><div className="variant-head"><span>Variant</span><span>Sent</span><span>Replies</span><span>Reply rate · 90% CI</span><span>Share</span></div>{rows.slice(0, 6).map((variant, index) => { const sent = variant.stats?.sent ?? 0; const replies = variant.stats?.replies ?? 0; const rate = sent ? replies / sent * 100 : 0; const fallback = demoVariants[index]; return <div className="variant-row" key={variant.id}><strong>{String.fromCharCode(65 + index)} · {variant.name}{index === 1 && <Pill tone="info">Thompson favorite</Pill>}</strong><span className="mono">{sent || fallback?.sent || 0}</span><span className="mono">{replies || fallback?.replies || 0}</span><span className="ci-cell"><b>{(rate || fallback?.rate || 0).toFixed(1)}%</b><span className="ci-line"><i style={{ left: `${(fallback?.ci[0] ?? 3) * 2.5}%`, width: `${(fallback ? fallback.ci[1] - fallback.ci[0] : 17) * 2.5}%` }} /></span><small>{fallback?.ci[0] ?? 0}-{fallback?.ci[1] ?? 0}%</small></span><span><Meter value={fallback?.share ?? 10} /><small className="mono">{fallback?.share ?? 10}%</small></span></div> })}</Panel> }

function RelationshipsScreen({ warmEdges, onQueue }: { warmEdges: WarmEdge[]; onQueue: () => void }) { const [selected, setSelected] = useState("ava"); const selectedInfo = selected === "ava" ? { name: "Ava Chen", strength: 0.74, source: "Colleagues at Northbeam · 2 years · 3 intros made, 3 replied", last: "6d ago", decay: 78, why: "Marcus's intros to growth leaders have a 3/3 reply rate - and Ava just took over growth." } : selected === "mara" ? { name: "Mara Voss", strength: 0.71, source: "Dana ran Driftwood's CAC audit · monthly contact", last: "11d ago", decay: 64, why: "Dana's audit is the exact opener for the CAC case study already drafted." } : { name: "Priya Nair", strength: 0.55, source: "Dana advised Cobalt's ops team last year", last: "23d ago", decay: 41, why: "Ops-scaling pain is live - 4 roles open. Dana can vouch credibly." }; return <><div className="page-intro"><div><span className="eyebrow">IMPROVE / WARM PATHS</span><h1>Relationships</h1><p>Find the shortest credible path to a target, then ask before using it.</p></div><Pill tone="info" dot>{warmEdges.length || 12} edges mapped</Pill></div><div className="relationship-grid"><aside><SectionHeading title="Strongest connectors" /><Panel className="connector-list">{[["marcus", "Marcus Reed", "0.86", "12 interactions · met Dec"], ["dana", "Dana Ruiz", "0.62", "8 interactions · client"], ["leo", "Leo Marsh", "0.25", "1 exchange · cold-ish"]].map(([id, name, strength, detail]) => <button key={id} className={`connector-row ${id === "marcus" ? "connector-active" : ""}`} onClick={() => setSelected(id)}><Avatar name={name} size="sm" /><span><strong>{name}</strong><small>{detail}</small></span><b>{strength}</b></button>)}</Panel><Panel className="relationship-note"><h3>Why graphs decay</h3><p>Warmth fades without contact. Loop reprioritizes paths before they expire.</p></Panel></aside><Panel className="graph-panel"><RelationshipGraph selected={selected} onSelect={setSelected} /><div className="graph-legend"><span><i className="legend-weak" /> weak</span><span><i className="legend-medium" /> medium</span><span><i className="legend-strong" /> strong</span><span><i className="legend-path" /> recommended path</span></div></Panel><aside><SectionHeading title={selectedInfo.name} /><div className="intro-path"><span>You</span><ArrowRight size={14} /><span className="path-strong">Marcus Reed</span><ArrowRight size={14} /><span>{selectedInfo.name}</span></div><Panel><DefinitionList entries={[["Path strength", `${selectedInfo.strength} · strong`], ["Source", selectedInfo.source], ["Last interaction", selectedInfo.last], ["Warmth decay", `${selectedInfo.decay}% remaining`]]} /><Meter value={selectedInfo.decay} /><p className="long-copy"><b>Why this intro:</b> {selectedInfo.why}</p><Button className="teal-button full-button" onClick={onQueue}><Mail size={14} /> Draft intro request</Button><p className="mono muted-copy">goes to Approvals · never sends without you</p></Panel></aside></div></> }

function RelationshipGraph({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) { const nodes = [{ id: "you", x: 55, y: 52, label: "You", kind: "you" }, { id: "marcus", x: 205, y: 30, label: "Marcus", kind: "connector" }, { id: "dana", x: 205, y: 100, label: "Dana", kind: "connector" }, { id: "ava", x: 370, y: 18, label: "Ava", kind: "target" }, { id: "ben", x: 405, y: 55, label: "Ben", kind: "target" }, { id: "priya", x: 405, y: 92, label: "Priya", kind: "target" }, { id: "mara", x: 370, y: 130, label: "Mara", kind: "target" }]; const edges = [[55, 52, 205, 30, "strong"], [205, 30, 370, 18, "path"], [55, 52, 205, 100, "medium"], [205, 100, 370, 130, "strong"], [205, 100, 405, 92, "medium"], [205, 30, 405, 55, "weak"]]; return <svg className="relationship-svg" viewBox="0 0 470 164" role="img" aria-label="Warm relationship graph">{edges.map(([x1, y1, x2, y2, kind], index) => <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} className={`graph-edge graph-edge-${kind}`} />)}{nodes.map((node) => <g key={node.id} className="graph-node" onClick={() => onSelect(node.id)} tabIndex={0} role="button"><circle cx={node.x} cy={node.y} r={selected === node.id ? 16 : 12} className={`graph-circle graph-${node.kind} ${selected === node.id ? "graph-selected" : ""}`} /><text x={node.x} y={node.y + 4} textAnchor="middle">{node.label.slice(0, 2)}</text><text x={node.x} y={node.y + 30} textAnchor="middle" className="graph-label">{node.label}</text></g>)}</svg> }

function SettingsScreen({ status, mode, onMode, onPause, onStop, onResume }: { status?: { stopped?: boolean; today_budget_used?: number }; mode: string; onMode: (autopilot: boolean) => void; onPause: () => void; onStop: () => void; onResume: () => void }) { const [email, setEmail] = useState(true); const [linkedin, setLinkedin] = useState(false); const [segments, setSegments] = useState(["SaaS", "Agency"]); const [budget, setBudget] = useState(24); const preview = `With these settings, Loop may automatically execute up to ${Math.max(2, Math.round(budget / 3))} actions/day across ${email ? "email" : "no channels"}${linkedin ? " and LinkedIn" : ""} for ${segments.length ? segments.join(", ") : "no segments"} accounts. Intro requests, external actions, and budget exceptions still need approval.`; return <><div className="page-intro"><div><span className="eyebrow">CONTROL / AUTONOMY & SAFETY</span><h1>Settings</h1><p>Boundaries are explicit, versioned, and visible before the agent acts.</p></div><Pill tone={mode === "autopilot" ? "info" : "plain"} dot>{mode}</Pill></div><Panel className="autopilot-preview"><span>Live preview · what autopilot may do without asking</span><p>{preview}</p></Panel><div className="settings-layout"><nav className="settings-nav">{["Operating mode", "Autopilot scope", "Approval rules", "Content guardrails", "Policy editor", "Playbooks", "Integrations", "Data & simulation"].map((item, index) => <button key={item} className={index === 0 ? "settings-nav-active" : ""}>{item}</button>)}</nav><div className="settings-sections"><SettingSection title="Operating mode"><div className="segmented-control"><button className={mode === "propose" ? "segmented-active" : ""} onClick={() => onMode(false)}>Propose · everything asks first</button><button className={mode === "autopilot" ? "segmented-active" : ""} onClick={() => onMode(true)}>Autopilot · scoped execution</button></div><p className="long-copy">Propose is the default until you have approved 10 actions. Loop switches nothing on its own.</p></SettingSection><SettingSection title="Autopilot scope"><SettingToggle label="Email channel" detail="Autosend email within segments and budgets below" checked={email} onChange={setEmail} /><SettingToggle label="LinkedIn channel" detail="Off - requires manual send until enabled" checked={linkedin} onChange={setLinkedin} /><div className="setting-row"><span><strong>Segments in scope</strong><small>Where autopilot may act at all</small></span><div className="setting-chips">{["SaaS", "Agency", "Logistics"].map((segment) => <button key={segment} className={segments.includes(segment) ? "chip-selected" : ""} onClick={() => setSegments((current) => current.includes(segment) ? current.filter((item) => item !== segment) : [...current, segment])}>{segment}</button>)}</div></div><div className="setting-row"><span><strong>Daily budget</strong><small>Hard cap across all actions</small></span><div className="range-setting"><input aria-label="Daily action budget" type="range" min="8" max="48" step="2" value={budget} onChange={(event) => setBudget(Number(event.target.value))} /><b>{budget}/day</b></div></div><div className="setting-row"><span><strong>Per-contact frequency</strong><small>Enforced by guardrail, not goodwill</small></span><Pill tone="plain">1 touch / 7 days</Pill></div></SettingSection><SettingSection title="Approval rules · always ask"><SettingToggle label="Intro requests" detail="Anything that uses another person's relationship" checked onChange={() => undefined} /><SettingToggle label="External actions" detail="Anything leaving email or LinkedIn" checked onChange={() => undefined} /><SettingToggle label="Budget exceptions" detail="Anything that would exceed the daily cap" checked onChange={() => undefined} /></SettingSection><SettingSection title="Content guardrails"><pre className="guardrail-code">{`{

function SettingSection({ title, children }: { title: string; children: ReactNode }) { return <section className="setting-section"><h2>{title}</h2><Panel>{children}</Panel></section> }
function SettingToggle({ label, detail, checked = false, onChange }: { label: string; detail: string; checked?: boolean; onChange: (checked: boolean) => void }) { return <div className="setting-row"><span><strong>{label}</strong><small>{detail}</small></span><Switch checked={checked} onCheckedChange={onChange} aria-label={label} /></div> }

function TraceOverlay({ action, selectedStage, onSelectStage, onClose }: { action: DemoAction; selectedStage: number; onSelectStage: (stage: number) => void; onClose: () => void }) { const stages = [["Signal", "06:12", "Funding signal detected"], ["Qualify", "06:14", "ICP 92 · warm path found"], ["Select", "06:14", "Variant B · 78% confidence"], ["Draft", "06:15", "68 words · assertiveness 0.48"], ["Guardrails", "06:15", "5/5 passed"], ["Decision", "Now", "Awaiting human"], ["Execute", "-", "Simulation"], ["Outcome", "-", "Pending"], ["Learn", "-", "Outcomes feed policy review"]]; return <div className="trace-overlay" role="dialog" aria-modal="true" aria-label="Action trace"><div className="trace-modal"><div className="trace-header"><div><span className="eyebrow">FULL RECONSTRUCTION</span><h2>Action trace · {action.id}</h2><p>{action.company_name} · policy v14 · {action.variant_id}</p></div><button className="icon-button" onClick={onClose} aria-label="Close trace"><X size={17} /></button></div><div className="trace-stepper">{stages.map((stage, index) => <button key={stage[0]} className={`${index <= selectedStage ? "trace-done" : ""} ${index === selectedStage ? "trace-selected" : ""}`} onClick={() => onSelectStage(index)}><span>{index + 1}</span><strong>{stage[0]}</strong><small>{stage[1]}</small></button>)}</div><div className="trace-detail"><span className="eyebrow">STAGE {selectedStage + 1} · {stages[selectedStage][0]}</span><h3>{stages[selectedStage][2]}</h3><p>{selectedStage === 0 ? "Series B · $32M led by Ridgeline, attached to Acme Analytics within 38 minutes of publication." : selectedStage === 4 ? "Frequency, budget, claims, reputation, and data source all passed before this action reached you." : selectedStage === 8 ? "Outcomes feed variant posteriors and policy review. Nothing changes silently; every change lands in Learning." : "The decision trace preserves the evidence, state, and policy used at this point in the loop."}</p></div></div></div> }

function DefinitionList({ entries }: { entries: Array<[string, string]> }) { return <dl className="definition-list">{entries.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl> }
function EvidenceList({ items }: { items: string[] }) { return <div className="evidence-list">{items.map((item, index) => <div className="evidence-row" key={`${item}-${index}`}><span>{index + 1}</span><p>{item}</p></div>)}</div> }
function Timeline({ items }: { items: Array<[string, string]> }) { return <div className="console-timeline">{items.map(([time, text], index) => <div className="timeline-item" key={`${time}-${text}`}><span className={index === 0 ? "timeline-dot timeline-active" : "timeline-dot"} /><div><small>{time}</small><p>{text}</p></div></div>)}</div> }
