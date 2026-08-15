# Loop — Design Spec (DESIGN.md)

Companion to **`loop-console.html`** (the clickable prototype = source of truth for visuals + interaction). This file covers the 18 requested deliverables. In-code comments in the prototype name each component and its states.

---

## 1. Product design thesis

Loop is not an analytics product; it is a **decision product**. The interface exists to answer one operator question — *"What should Loop do next, why does it believe that, what happens if I allow it, and what did it learn?"* — in under five seconds, then get out of the way. Every screen is a stage of the loop (Signal → Opportunity → Action → Approval → Execution → Outcome → Learning → Changed behavior); navigation is the loop made spatial. Trust is engineered through evidence-adjacency (never a claim without its proof within one glance), plain language (the audience is a founder, not an ML engineer — "confidence 78%", never "Thompson posterior" in surface copy), and reversibility (every policy change is diffable and rollback-able).

## 2. Information architecture

Two axes: **Operate** (Today, Opportunities, Approvals, Action review, Activity) and **Improve/Control** (Learning, Relationships, Settings). Objects: Company, Contact, Opportunity, Action (carries DecisionTrace), Event, Policy version, Variant, WarmEdge. The Action is the atomic unit — every surface links back to one action id (`ACT-2214`).

## 3. Sitemap

```
Loop
├─ Today ............ agent brief, needs-decision, next-best, learning deltas, funnel, timeline
├─ Opportunities .... queue → opportunity detail (company / contact / signals / evidence / path / recommendation / why-now / what-if)
├─ Approvals ........ queue + autopilot log + scope summary
│   └─ Action review  3-pane: context rail | editor | reasoning rail → confirm / rejected states
├─ Activity ......... ledger (expandable events) → Action trace overlay (9-stage loop chart)
├─ Learning ........ behavior-changed hero, before/after, params, next-action-changed, variants+CI, timing, feedback taxonomy, policy timeline + rollback
├─ Relationships ... connectors | SVG warm graph | path detail + intro-request CTA
└─ Settings ........ mode, autopilot scope, approval rules, guardrails, policy editor, playbooks, integrations, simulation
```

## 4. Primary user journey (the 11 moments)

| # | Moment | Where it lives in the prototype |
|---|--------|-------------------------------|
| 1 | Funding signal found | Today brief + queue row "Series B · $32M · 2d" |
| 2 | User opens opportunity | Queue row → detail workspace |
| 3 | Sees why company was selected | "Why it qualified" evidence rail + ICP/warm/signal cards |
| 4 | Agent proposes personalized action | Action review, draft visible in editor |
| 5 | User edits message | Subject/body editable inline; "Edited by you · changes tracked" |
| 6 | Approves with note | Note field → confirm sheet → confirmation state |
| 7 | Executes in simulation | Confirmation "what happens next" + ledger event (+2.6s toast) |
| 8 | Outcome arrives | +6.2s: reply event, status "Replied — hot" |
| 9 | Policy changes | v15 "fast-reply priority" appears in policy timeline |
| 10 | Next action visibly differs | Queue shows "Reply now · policy v15"; Learning shows was→now explainer |
| 11 | Inspect & roll back | Learning → Roll back → v14 restored, audit event, toast |

State persists to localStorage — refresh mid-demo keeps context (never lose context between steps).

## 5–6. Wireframes

The prototype **is** the wireframe deck: Tweaks panel (bottom-right) → **Wireframe mode** toggles grayscale + dashed region labels (`data-wf` attributes render as annotation chips: AGENT BRIEF, NEEDS YOUR DECISION, CONTEXT RAIL, ACTION EDITOR, REASONING RAIL, LOOP TRACE…). Force-mobile-frame shows Today / Opportunities / Action review / Learning at 390px with bottom nav + sticky approve bar.

## 7. High-fidelity visual direction

*Editorial operations console meets signal intelligence.* Warm paper ground, deep warm ink, one oxidized-teal accent. Serif (Iowan/Charter/Georgia stack) is the agent's voice — briefs and reasoning; system sans is the UI; monospace is machine metadata (IDs, policy versions, timestamps, scores). Color budget per screen: teal = agent/action, amber = awaiting human, green = outcome, coral = risk only. Borders and whitespace do the work; radii and shadows are rare and meaningful.

## 8. Design tokens

See `:root` in `loop-console.html`. Summary:

| Group | Tokens |
|---|---|
| Color | `--bg oklch(96.5% .008 85)` · `--surface 99% .004 85` · `--ink 25% .02 60` · `--muted 46%` · `--line 88.5% .01 80` · accent `--teal oklch(46% .075 178)` (+soft/strong/ink ramp) · amber 62% .12 75 · green 50% .12 152 · coral 52% .17 25 (each with soft+ink variants) |
| Type | display serif 17–21px · body 13.5–14px · small 12.5px · mono 10–12.5px; letter-spacing −.01em display |
| Space | 4px base; panel pad 12px; section gap 16px; row height 52 (42 compact) |
| Radii | 6 / 10 / 14px only |
| Borders | 1px hairlines; 3px left rule marks the agent's brief; teal border = recommended |
| Elevation | flat surfaces; `--sh-1` subtle, `--sh-2` only for overlays/toasts |
| Motion | 0.14s fast, 0.26s med `cubic-bezier(.2,.7,.2,1)`; heartbeat 2.4s pulse; graph path dash 1.2s; `prefers-reduced-motion` honored |

## 9. Component inventory

Shell (sidebar/topbar/bottom-nav/status card) · workspace switcher · agent status indicator · mode switcher · heartbeat · budget meter · opportunity row · signal badge · contact/company identity blocks · warmth dots · action review workspace · message editor · reasoning panel · evidence item · guardrail check · approval footer · structured rejection selector · confirm sheet · confirmation state · activity event · loop trace stepper · learning delta · before/after comparison · parameter delta bar · variant table + CI whisker · policy timeline row · relationship graph node/edge · intro path · autopilot preview · switch · toast · empty/error (honest-stub) states · Tweaks panel. (Loading = skeleton shimmer on data hooks in React build; loading/error states are hook-driven, see §10.)

## 10. State matrix (critical components)

| Component | Default | Hover | Focus | Disabled | Loading | Error | Empty | Mobile | Keyboard | A11y |
|---|---|---|---|---|---|---|---|---|---|---|
| Opportunity row | queued row | surface-2 wash, hot accent left | 2px teal outline | bulk-select disabled by design | rows shimmer 300ms | retry pill | dashed empty panel | 3-cell stacked card | Enter/Space opens | `role=button` + company label |
| Message editor | agent draft, meta chips | — | teal border on field | when confirming | draft skeleton | save-conflict banner | n/a | full-width, 16px text | standard inputs, Tab order natural | `aria-disabled` on confirm |
| Approve | filled teal | darker teal | ring | after decision | spinner inline | API error → stays enabled + toast | n/a | sticky footer bar | Enter on confirm sheet | labelled button |
| Guardrail check | green check row | reveal detail | n/a | n/a | skeleton row | red state + reason | n/a | stacks | n/a | pass/fail text not color-only |
| Variant row | bar + CI whisker | row wash | — | — | — | CI hidden if n<5 | "not enough sends" | horizontal scroll table | — | CI in text too |
| Graph node | ink/teal/surface fill | scale ring | focus ring | — | static fallback list | — | — | tap = select panel | role=button | node name announced |
| Policy row | active pill | rollback red on latest | — | rollback only latest | — | — | — | stacks | — | state in text |

## 11. Annotated Action Review workflow

Left rail = **who/what** (target identity, signal, guardrails 5/5, runtime policy+variant+budget). Center = **the decision** (channel/timing/type chips → editable subject + body with edit-tracking → expected effect → note input → structured reject select → Approve → confirm sheet ("deliberate, not default") → confirmation state with next steps + recorded learning). Right rail = **why** (ranked reasons w/ evidence, alternatives scored, what-would-change-this, trace link). Reject requires a reason — the reason is product data, not friction.

## 12. Annotated Learning workflow

Hero states the change in one sentence → before/after messages side-by-side with the trigger between → parameter deltas (words 132→68, assertiveness 0.70→0.48, personalization 1→2) → variants with 90% CI whiskers + Thompson share → feedback taxonomy → policy timeline with rollback on the live version → "next action changed because" explainer (was/now + trigger + evidence + scope). Rollback writes an audit event; v15 remains visible as history.

## 13. API-to-screen mapping

| Screen | Existing endpoint |
|---|---|
| Shell status, heartbeat, mode, budget | `GET /status`, `POST /control/{pause,stop,resume,mode,scope}` |
| Today brief, funnel, deltas | `GET /briefing`, `GET /pipeline`, `GET /attribution` |
| Opportunities queue/detail | `GET /companies`, `GET /contacts`, (+ new, §14) |
| Approvals + review | `GET /queue`, `GET /decisions/{id}` (structured payload: target, signal, message, reasoning, alternatives, guardrails), `POST /decisions/{id}/{approve,reject,edit}` |
| Activity + trace | `GET /activity`, `GET /audit/explain/{id}`, `GET /audit/export` |
| Learning | `GET /experiments/analysis`, `GET /experiments/regret`, `GET /leaderboard`, `GET /variants`, `GET/PATCH /policy`, (+ new §14) |
| Relationships | `GET /warm-graph` |
| Outcomes | `POST /outcomes` |

## 14. Required backend additions

`GET /opportunities` (+`/{id}`: evidence, why-now, what-if, path) · `GET /actions/{id}/timeline` (9-stage trace) · `GET /learning/changes` (behavior diffs + next-action-changed) · `GET /policy/history` · `GET /control/scope` · structured decision payload on `/decisions/{id}`. Prototype data already mirrors these shapes.

## 15. React implementation sequence

1. Tokens → Tailwind theme extension + `index.css` (map `:root` verbatim).
2. App shell (react-router areas; keep TanStack Query 5s polling) + status card from `/status`.
3. Today (briefing) → 4. Opportunities (list from `/companies`+new `/opportunities`) → 5. Action review (replace `DecisionCard.tsx` six-tab pattern with 3-pane; reuse Radix Select/Dialog/Switch) → 6. Activity + trace overlay (`/audit/explain`) → 7. Learning (variants CI chart as inline SVG; rollback → `PATCH /policy`) → 8. Relationships (SVG graph; pan/zoom later) → 9. Settings (scope → `POST /control/scope`, live preview client-side) → 10. Mobile pass + a11y audit. No rewrite needed: same stack, same hooks.

## 16. Accessibility checklist

Focus-visible rings everywhere · color never the only signal (pills carry dot+text, graph edges carry width+dash) · `aria-current` on nav · switches are `role=switch` + `aria-checked` · overlay is `role=dialog` + Esc-to-close + backdrop click · rows are `role=button` + Enter/Space · toasts `aria-live=polite` · contrast: ink on paper 13.8:1, teal-ink on teal-soft ≥ 4.5:1 · reduced-motion honored · hit targets ≥ 40px (approve bar ≥ 44 mobile).

## 17. Demo walkthrough (Acme / Ava, ~4 min)

1. **Today** — read the brief (30s: what Loop is, what it wants, that it's safe).
2. **Needs your decision → Review action** — walk the three panes: target/signal/guardrails → draft → why ranked + alternatives.
3. Edit the subject ("one idea for Q3" → your words), note "keep teardown angle", **Approve → Confirm**.
4. Wait ~6s: toast — Ava replied; policy v15.
5. **Learning** — before/after from earlier rejections, then "Next action changed because" (was: follow-up Thu → now: reply now), variants CI.
6. **Roll back v15** — next action reverts; audit event appears.
7. **Activity** — expand events, **Open action trace** — the 9-stage loop chart, click stage 5 (Guardrails).
8. **Relationships** — select Ava: animated You→Marcus→Ava path, decay bar, "Draft intro request" → lands in Approvals.
9. **Settings** — toggle segments/budget, watch the dark autopilot preview sentence recompute.

## 18. Design decisions & tradeoffs

- **Workflow-first shell** over the current 4-tab dashboard — tabs buried the loop; nav groups now mirror it.
- **Split-pane review over card+tabs** — tabs hid evidence behind clicks; three panes keep target/message/reasoning co-visible (accepts a wider minimum viewport; mobile collapses rails into accordions/sticky bar).
- **Serif = agent voice** — instant visual distinction between agent-authored briefs and human UI chrome; tradeoff: one more family to keep disciplined.
- **Structured rejection required** — friction traded for learning signal quality.
- **Simulated outcomes fire on real timers** in the demo (2.6s/6.2s) — compresses the loop honestly; labeled "simulation, send time compressed".
- **Bulk select visible but disabled** — operators see the affordance exists; safe enablement later.
- **Wireframe + hi-fi in one file** — review speed; tradeoff: one large artifact (kept < 1,500 lines).
- **Graph is hand-laid SVG, not a force layout** — deterministic, legible, dependency-free; force layout is v2 if node count grows.
- **Warmth shown as 3-dot ramp, not emoji/fire** — reads at 11px, prints in grayscale.
