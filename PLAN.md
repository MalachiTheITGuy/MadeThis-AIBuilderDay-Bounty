# MadeThis Bounty — Self-Improving GTM Agent ("Loop") Implementation Plan — 1-Day Sprint, Fully Local

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a MadeThis-inspired agent ("Loop") that owns one end-to-end GTM loop — signal → opportunity → proposed action → approval/autopilot execution → observed outcome → behavior change — with persistent memory, guardrails, and an explainable activity trail, delivered as a working, fully-local prototype in a **1-day (≈8h) sprint**, winning the AI Builder Day bounty.

**Architecture:** A Python service with a six-stage agent loop (SENSE → DECIDE → PROPOSE → ACT → OBSERVE → LEARN). SQLite is the single source of truth (contacts, warm-relationship graph, playbook experiments, decision traces, outcomes, policies). A deterministic, policy-driven template engine generates personalized outreach (LLM is an *optional* adapter — never a dependency). A permission layer routes actions to the approval queue (Propose mode) or guardrail-checked auto-execution (Autopilot mode). The learning engine updates Thompson-sampled experiment statistics from outcomes *and* maps human edits/rejections to policy deltas — so feedback changes the next action, not just a note.

**Tech Stack:** Python 3.11+, FastAPI + uvicorn, SQLite (stdlib `sqlite3`), pydantic v2, Jinja2 + htmx, pytest. **Zero network dependencies at runtime** — the demo runs entirely offline from a seeded SQLite DB. Optional (stretch): `litellm` for an LLM generator backend; never required.

---

## 1. Goal, Context & Assumptions

### Judging-matrix mapping (kept from v1)

| Judging criteria | Weight | How "Loop" hits it |
|---|---|---|
| End-to-end GTM impact | 30% | One complete, recognizable motion: outbound sales with warm-intro support. Vertical slice from buying signal to booked meeting, not a dashboard. |
| Quality of learning loop | 25% | Behavior changes, provably: Thompson sampling over variant stats picks different messages/channels/timing after outcomes; human rejections/edits mutate the policy that generates the *next* message. Before/after cycle is demo-able. |
| Trust, permissions, guardrails | 20% | Propose/Autopilot modes, action-class approval matrix (irreversible/external/high-cost always require approval), budgets, rate caps, kill switch, full activity log. |
| UX & explainability | 15% | Every action ships as a decision card: target, reasoning, evidence links, channel, expected effect, what it learned, what happens next. |
| Technical execution & originality | 10% | Clean six-stage state machine, warm-relationship graph (bonus), experiment selection (bonus), versioned playbooks + rollback (bonus), heartbeat scheduling (bonus). |

### Assumptions (revised for 1-day sprint)

1. **Single developer, 1 day (~8 focused hours).** Everything below is on the critical path for the demo; stretch items are explicitly marked and cuttable.
2. **Demo runs 100% locally, offline.** No LLM key, no network, no external services. The message generator is a deterministic template engine; outcomes are simulated locally with deterministic timing. The optional LLM adapter is a stretch item and never required for the demo.
3. Prototype runs from `python run.py` (uvicorn) + `python demo.py` (scripted demo driver); DB seeded deterministically.
4. Competition-scale data only: SQLite, hundreds of contacts.
5. Single-user app (one approver). Multi-user RBAC out of scope.
6. No real contacts, no real sends, no spend paths. All external actions simulated behind a channel-adapter interface.
7. Organizer details (date, deadline, award, team rules) still TBD — single-team assumption, plan is team-agnostic.

---

## 2. The Loop We Own

**Motion: Outbound sales with a warm-relationship graph** (primary), with referrals/introductions as the natural second hop (bonus).

```
Buying signal (synthetic, local feed)   →  SENSE
Firmographic qualification              →  DECIDE (score ≥ threshold → Opportunity)
Next-best-action selection              →  DECIDE (playbook × Thompson sampling × warm graph)
Personalized outreach drafted           →  DECIDE (template engine under policy state)
Decision card → approval / guardrails   →  PROPOSE
Simulated send (email / LinkedIn)       →  ACT
Reply / meeting / rejection / no-reply  →  OBSERVE
Stats + feedback → playbook & policy    →  LEARN
Next action for contact replanned       →  LOOP
```

Why this motion: most recognizable "real GTM" loop for judges; exercises every required capability; warm graph gives a differentiated second act (auto-surfacing an intro path) without a second pipeline.

---

## 3. System Architecture

### 3.1 Component diagram

```
                        ┌──────────────────────────────────────────────┐
                        │                   LOOP CORE                   │
                        │                                              │
  signal feed  ────────► │  SENSE ──► DECIDE ──► PROPOSE ──► ACT        │
  (local generator)     │                     │            │           │
                        │                     ▼            ▼           │
                        │              Permission     Channel         │
                        │              Layer         Adapters         │
                        │                │  autopilot  │ (EmailSim /   │
                        │                ▼             │  LinkedinSim) │
                        │           Guardrails   outcome feed (local) │
                        │           budgets/caps      │               │
                        │                │            ▼               │
                        │                │        OBSERVE ──► LEARN   │
                        │                │                 │          │
                        └────────────────┼─────────────────┼──────────┘
                                         │                 │
                    ┌────────────────────┘                 ▼
                    ▼                        ┌──────────────────────┐
          ┌──────────────────┐               │   MEMORY & LEARNING  │
          │  WEB UI (FastAPI)│◄─────────────►│  SQLite (local file):│
          │  approval queue  │               │  contacts, warm graph│
          │  activity trail  │               │  playbook experiments│
          │  explain cards   │               │  decisions, outcomes │
          │  pause/kill      │               │  policies, versions  │
          │  edit policy/    │               │  ────────────────────│
          │  playbook/memory │               │  Thompson sampling   │
          └──────────────────┘               │  feedback→policy map │
                                             │  rollback/versioning │
                                             └──────────────────────┘
```

### 3.2 State machine (per Opportunity)

```
signal ─► QUALIFIED ─► PLANNED ─► PROPOSED ─► APPROVED ─► SENT ─► OUTCOME_RECORDED ─► LEARNING_APPLIED ─► (replan)
                │           │           │           │
                │           │           │           └─► REJECTED ─► REASON_CAPTURED ─► LEARNING_APPLIED
                │           │           └─► EDITED
                │           └─► SKIPPED (below threshold / guardrail block)
                └─► DISMISSED (user kills)
States persisted in `actions` + `opportunities` tables; every transition appends an activity-log row.
```

### 3.3 Interface contracts (pseudocode)

```python
# sense.py
class Signal(BaseModel):
    id: str; company_id: str; type: SignalType   # FUNDING | HIRING | PRODUCT | PRICING | CONTENT
    payload: dict; detected_at: datetime

# qualify
class Qualification(BaseModel):
    score: float; fit_notes: list[str]; icp_hits: list[str]   # evidence for explainability

# plan.py — next best action
class PlannedAction(BaseModel):
    action_type: ActionType        # OUTREACH_EMAIL | LINKEDIN_CONNECT | INTRO_REQUEST | FOLLOW_UP
    variant_id: str; channel: Channel; timing: str; segment: str
    expected_effect: str; confidence: float

# generate.py — message under policy
class DraftedMessage(BaseModel):
    subject: str; body: str; personalization: list[str]
    policy_version: str; prompt_trace: dict

# permission.py
class PermissionDecision(BaseModel):
    mode: Mode                     # PROPOSE | AUTOPILOT
    requires_approval: bool; reasons: list[str]; guardrail_blocks: list[str]

# observe.py
class Outcome(BaseModel):
    action_id: str; result: Result # REPLY | MEETING | POSITIVE | NEUTRAL | NEGATIVE | REJECTION | UNSUB | NO_RESPONSE
    detail: str; at: datetime

# learn.py — behavior change, not note-taking
class LearningDelta(BaseModel):
    variant_updates: dict[str, dict]
    policy_deltas: list[PolicyDelta]       # {field, delta, source}
    warm_graph_deltas: list[EdgeDelta]
    playbook_new_version: int
```

### 3.4 Repo layout (final, 1-day)

```
gtm-loop/
├── README.md                  # competition deliverable (§11)
├── pyproject.toml
├── .env.example               # SIMULATION_MODE=on; LLM_* optional (stretch)
├── run.py                     # uvicorn entrypoint (+ --demo flag: 10s heartbeat)
├── seed_data.py               # deterministic synthetic world + signals + variants
├── demo.py                    # scripted demo driver (scenes 1–8)
├── src/
│   ├── config.py              # budgets, caps, guardrails, thresholds, toggles
│   ├── domain/models.py       # pydantic contracts above
│   ├── domain/enums.py
│   ├── store/db.py            # sqlite schema v1 + versioned migration
│   ├── store/repositories.py  # contacts, opportunities, actions, outcomes, activity
│   ├── store/memory.py        # warm graph ops + namespaced memory_kv
│   ├── engine/sense.py        # local signal feed + qualification
│   ├── engine/plan.py         # NBAM: Thompson sampling + warm-graph action typing
│   ├── engine/generate.py     # TemplateGenerator (deterministic, policy-driven); LLM adapter (stretch)
│   ├── engine/propose.py      # decision card builder (explainability)
│   ├── engine/permission.py   # mode routing, action classes, guardrails, budget/caps
│   ├── engine/execute.py      # EmailSim / LinkedinSim adapters; SIMULATION_MODE guard
│   ├── engine/observe.py      # outcome ingestion (feed + manual entry)
│   ├── engine/learn.py        # stats, feedback→policy map, warm graph, rollback
│   ├── api/main.py            # FastAPI app + asyncio heartbeat scheduler
│   ├── api/routes.py          # /queue /decisions /activity /contacts /memory /control /playbook
│   └── web/templates/         # dashboard, decision cards, trail, explain modal, edit forms
└── tests/
    ├── test_schema.py         # migrate + seed + FK integrity (smoke)
    ├── test_qualify.py        # threshold + evidence capture
    ├── test_plan.py           # NBAM exploration vs exploitation (seeded)
    ├── test_generate.py       # policy directives reflected in output
    ├── test_permission.py     # ★ guardrails, classes, budgets, kill switch
    ├── test_execute.py        # sim safety (no real send possible)
    ├── test_learn.py          # ★★★ 5 behavior-change tests (judge-proof)
    └── test_e2e_demo.py       # ★ full loop: signal → learn → different next action
```

---

## 4. The Learning Engine (the 25%)

The single most important design constraint from the brief: **"Self-improving must change behavior, not just store a note."** Three mechanisms, each with observable behavior change:

### 4.1 Experiment playbook + Thompson sampling (outcome-driven learning)

- Playbook = set of `experiments`: `{variant_id, template, channel, timing_slot, tone_profile, personalization_depth, segment}`.
- Each variant carries success stats `{sent, replies, meetings, positive, negative, unsub}` from observed outcomes.
- NBAM (`plan.py`) samples each eligible variant's success rate from a Beta posterior (Thompson sampling) and picks the argmax — standard exploration/exploitation.
- **Observable change:** after outcomes arrive, the same segment may get a different variant (e.g., short warm email at 9:30 AM local vs. long-form at 11 AM). Decision card shows live stats ("3/12 replied, 1 meeting — currently best for Series A SaaS").

### 4.2 Feedback → policy map (human-driven learning)

Every human decision is captured with a structured reason:

- **Approve** (optional note) → reinforce current policy weights.
- **Edit** → diff draft vs. approved version; measurable deltas (length, personalization count, tone words, CTA type) push the policy in that direction.
- **Reject + reason** → taxonomy maps to policy deltas:

| Rejection reason (selectable) | Policy delta |
|---|---|
| `too_long` | brevity weight ↑ (target length ↓) |
| `too_salesy` / `too_pushy` | tone_assertiveness ↓, softener phrases ↑ |
| `missing_personalization` | personalization_depth ↑ (require ≥2 evidence-linked details) |
| `wrong_channel` | channel prior for that segment ↓ |
| `bad_timing` | timing slot prior ↓ |
| `wrong_target` | ICP fit threshold ↑, segment exclusion note |

Policy deltas mutate the **policy state** consumed by `generate.py` → the *next* drafted message is measurably different. Version bump on every mutation → rollback point.

### 4.3 Warm-relationship graph (bonus + learning substrate)

- Nodes: contacts; edges: relationship strength (0..1), direction, last interaction, warmth_signal (replied > met > engaged > cold), source.
- NBAM uses warmth to select action type: warm edges → `INTRO_REQUEST` / direct ask; cold → `OUTREACH_EMAIL` / `LINKEDIN_CONNECT`.
- Outcomes update edge strength → the graph *is* learned memory, not a static CRM field. Intro requests do a simple 1-hop traversal (shared connection).

### 4.4 Proof the loop works (test-first, judge-proof)

`test_learn.py` encodes the judge's exact question:
1. Seed variant A (long, salesy) and B (short, warm) with priors. Feed outcomes favoring B → assert NBAM now selects B for that segment with high probability (seeded RNG).
2. Reject an A-draft with reason `too_salesy` → generate a new draft → assert tone moved toward B profile.
3. Edit a draft to add a personal detail → assert `personalization_depth` increased → next draft contains ≥2 personalization items.
4. Outcome updates a variant's stats → assert posterior/leaderboard changed.
5. Rollback: mutate policy, call rollback → assert policy_version reverted and next draft matches prior profile.

---

## 5. Permission, Autonomy & Guardrails (the 20%)

### 5.1 Two modes

- **Propose mode (default):** every action lands in the approval queue as a decision card. Approve / Reject(+reason) / Edit(+optional note). Nothing executes without a human decision.
- **Autopilot mode:** user-defined scope: allowed segments, channels, max sends/day, max per-contact frequency, cost units per action, allowed timing window. Actions within scope auto-execute; anything outside scope — or in a **mandatory-approval class** — routes to the queue.

### 5.2 Mandatory-approval action classes (never auto-executed)

| Class | Examples |
|---|---|
| Irreversible | delete, unsubscribe, close-out opportunity |
| External | any non-simulated send, publish, webhook to real service |
| High-cost | spend > threshold, bulk action > cap, anything `external:true` |

`SIMULATION_MODE=on` (default, hard-coded default) is a safety rail: `execute.py` refuses to construct real adapters; only sim adapters exist in the 1-day build.

### 5.3 Guardrail engine

- Budget: rolling daily/weekly counters on `actions`; over-budget ⇒ block + explain.
- Rate caps: min interval between actions to same contact; max follow-ups per thread (default 3).
- Content guardrails: banned-phrase list, PII scrub check on drafts, tone bounds from policy.
- Kill switch: `/control/pause` (suspend new actions, keep UI), `/control/stop` (halt everything incl. heartbeat), `/control/resume`. Every change logged.
- Activity trail: append-only `activity` table; each row: timestamp, actor (agent/user), action id, status, outcome, reason, policy_version.

---

## 6. Explainability (the 15%)

Every decision card renders:
1. **What** — action type, target, channel, timing, cost.
2. **Why** — qualification evidence (icp_hits, fit_notes), NBAM reasoning (variant stats, sampled confidence).
3. **Evidence** — links to the source signal payload and contact memory entries used for personalization.
4. **Guardrails** — which rules were checked, pass/fail per rule.
5. **What it learned** — last N feedback/outcome deltas affecting this segment/variant.
6. **What happens next** — the queued follow-up plan if approved.

Persisted as a `decision_trace` JSON per action → replayable, and it doubles as the demo's narrative backbone.

---

## 7. Data Safety (fully local)

- Seed data: fully synthetic companies/contacts (deterministic generator, no real PII).
- Signal feed: generated locally on a schedule inside the process; no web scraping.
- External sends/publishing: simulated adapters only. No real-adapter code paths in the 1-day build.
- No spend paths exist in v1 (cost = integer units only).
- DB ships with a `seed` flag; demo always resets from a deterministic seed for reproducibility.
- Runtime makes zero network calls (verify: `demo.py` runs with `unshare -n` or with network off — see verification checklist).

---

## 8. Criteria Compliance Matrix (audit: every brief requirement → plan element)

| # | Brief requirement | Covered by | Tasks | Test | Demo scene |
|---|---|---|---|---|---|
| R1 | Own a real GTM loop: signal → opportunity → action → outcome | SENSE/DECIDE/PROPOSE/ACT/OBSERVE pipeline | A3, B1–B2, C1–C2, D1, E1–E2 | test_e2e_demo | 1, 2, 5, 6 |
| R2 | Propose mode: action, target, reasoning, channel, expected effect; approve/reject/edit; capture why | decision cards + routes | D2, D3 | test_permission | 2, 3, 4 |
| R3 | Autopilot mode: scope, budgets, frequency limits, guardrails; sensitive/irreversible/high-cost → approval | permission.py | D1 | test_permission | 5 |
| R4 | Clear activity log: status, outcome, pause/stop | activity table + /control | D3, G2 | test_permission (kill switch) | 8 |
| R5 | Self-improving loop: approvals/rejections/edits/rationale/outcomes → memory/strategy; behavior change | learn.py (stats + policy + graph) | F1–F2 | test_learn (5 tests) | 4, 6, 7 |
| R6 | Before-and-after cycle: feedback changes targeting/message/channel/timing/next action | NBAM + policy deltas + graph | F1–F2 | test_learn #1–3 | 7 |
| R7 | Trust & explainability: why chosen, evidence, what it may do, what it learned, what next | decision cards + decision_trace | D2, G2 | — | 2, 8 |
| R8 | Suggested demo path (opportunity → propose → edit/reject+reason → memory/playbook update → next attempt changes → outcome informs next) | whole pipeline | all | test_e2e_demo | 1–7 |
| R9 | Deliverable: working prototype | local app | all | pytest green + offline run | — |
| R10 | Deliverable: 3–5 min demo, one realistic loop, one human decision, one learning cycle | demo.py | H2 | test_e2e_demo | 1–8 |
| R11 | Deliverable: README (architecture, models, data/integrations, permissions, guardrails, feedback→future) | README.md | H3 | — | — |
| B1 | Bonus: proactive heartbeat/scheduling | asyncio scheduler | G1 | — | 1 |
| B2 | Bonus: cross-channel orchestration | EmailSim + LinkedinSim + NBAM channel choice | C1, E1 | test_plan | 2, 5 |
| B3 | Bonus: warm-relationship graph | warm_edges + NBAM action typing + 1-hop intro | F3 | test_learn | 5, 6 |
| B4 | Bonus: experiment selection | Thompson sampling | C1–C2 | test_plan | 2, 7 |
| B5 | Bonus: editable memory/playbooks | edit UI (policy, playbook variants, memory_kv) | F4 | — | 7 |
| B6 | Bonus: rollback | policy snapshots + revert endpoint | F4 | test_learn #5 | 7 |
| B7 | Bonus: budget or rate caps | guardrail engine | D1 | test_permission | 5 |
| D1 | Data & safety: synthetic data, simulated sends, no real contact/publish/spend | seed_data + SIMULATION_MODE + no spend paths | A3, E1 | test_execute | — |

Every numbered item in the brief maps to at least one task, test, and (where relevant) demo scene. Nothing is "mention-only."

---

## 9. One-Day Schedule (≈8h, critical path)

Must-have tasks are unmarked; **[STRETCH]** items are cuttable without harming the demo.

### Block 1 — 0:00–0:30 · Scaffold & data foundation
- **A1** Init repo `gtm-loop/`: `pyproject.toml` (fastapi, uvicorn, pydantic, jinja2, pytest), `.env.example` (`SIMULATION_MODE=on`), `run.py` (uvicorn entrypoint, `--demo` flag sets 10s heartbeat).
- **A2** `src/store/db.py` — schema v1 (companies, contacts, signals, opportunities, actions, outcomes, activity, experiments, policies, warm_edges, memory_kv) + versioned migration runner.
- **A3** `seed_data.py` — 40 synthetic companies, 120 contacts, warm-graph edges, 3 signal templates (FUNDING/HIRING/PRODUCT), 8 playbook variants (2 channels × 2 timing slots × 2 tone profiles), deterministic RNG seed.
- **A4** `tests/test_schema.py` — migrate + seed + FK integrity. **Verify:** `pytest tests/test_schema.py -v` PASS.

### Block 2 — 0:30–1:15 · SENSE + DECIDE: signals → qualified opportunities
- **B1** `src/engine/sense.py` — local signal feed ingestion (generates signals per schedule, dedupe by company+type+window).
- **B2** `src/engine/qualify.py` — weighted rule scoring (firmographics + signal type) → `Qualification` with evidence → create `Opportunity` (QUALIFIED).
- **B3** `tests/test_qualify.py` — threshold behavior, evidence capture. **Verify:** PASS.

### Block 3 — 1:15–2:45 · DECIDE: playbook, NBAM, message generation (core)
- **C1** `src/engine/plan.py` — Thompson sampling NBAM over playbook experiments; seeded RNG injection; warm-graph action typing (warm → INTRO_REQUEST, cold → outreach).
- **C2** `src/engine/generate.py` — **TemplateGenerator** (deterministic, reads policy state: brevity, tone, personalization depth, banned phrases) with fallback templates. **[STRETCH]** `LLMGenerator` adapter behind `LLM_BASE_URL` env guard.
- **C3** `tests/test_plan.py` (seeded: better prior favored; exploration happens) + `tests/test_generate.py` (policy directives reflected in output). **Verify:** both PASS.

### Block 4 — 2:45–4:15 · PROPOSE + PERMISSION: approvals, autopilot, guardrails
- **D1** `src/engine/permission.py` — mode routing, action-class matrix, guardrail engine (budget counters, rate caps, banned content, autopilot scope).
- **D2** `src/engine/propose.py` — decision card builder (full §6 payload) + `decision_trace` persistence.
- **D3** `src/api/routes.py` — `GET /queue`, `POST /decisions/{id}/approve|reject|edit` (reason capture), `POST /control/pause|stop|resume`.
- **D4** Web UI (Jinja2+htmx): dashboard, approval queue with decision cards, edit/reject-with-reason affordances.
- **D5** `tests/test_permission.py` — irreversible blocked, budget cap enforced, autopilot respects scope, kill switch halts. **Verify:** PASS.

### Block 5 — 4:15–5:00 · ACT + OBSERVE: simulated execution, outcomes
- **E1** `src/engine/execute.py` — `EmailSim` / `LinkedinSim` adapters (status → SENT, simulated thread append); SIMULATION_MODE guard; no real-adapter code paths.
- **E2** `src/engine/observe.py` — synthetic outcome feed (deterministic reply rates/timing, scheduled in-process) + manual outcome entry route.
- **E3** `tests/test_execute.py` — sim safety (no real-send path exists), status transitions. **Verify:** PASS.

### Block 6 — 5:00–6:15 · LEARN: behavior change + rollback + editable memory (the 25%)
- **F1** `src/engine/learn.py` — variant stats update from outcomes (posterior recompute); feedback→policy map (§4.2) with version bump; warm-graph edge updates; policy snapshot + rollback.
- **F2** `tests/test_learn.py` — the five behavior-change tests (§4.4). **Verify:** all PASS. **This is the demo's proof.**
- **F3** Edit UI: policy state editor, playbook variant editor, memory_kv editor (bonus B5). **[STRETCH if time is tight]**

### Block 7 — 6:15–7:00 · Heartbeat, activity trail, explainability polish
- **G1** In-process asyncio heartbeat scheduler in `api/main.py`: periodic signal scan → NBAM → autopilot pass; 10s interval in demo mode, configurable.
- **G2** Activity trail page (filterable, replayable, status/outcome/reason), explain modal wired to `decision_trace`, visible pause/stop controls.
- **G3** Dashboard leaderboard: variant stats table (sent/replies/meetings/conversion) — the visual "learning happened" proof.

### Block 8 — 7:00–8:00 · Tests, demo script, README
- **H1** `tests/test_e2e_demo.py` — full loop: same seed ⇒ same demo; learning cycle changes second action.
- **H2** `demo.py` — scripted driver for the §10 scenes; prints scene-by-scene narration + opens the UI.
- **H3** `README.md` — full outline in §11.
- **H4** Final verification: `pytest -q` green; **offline proof**: `python demo.py` with network disabled completes; `run.py --demo` serves the UI on localhost.

**[STRETCH backlog (only if ahead of schedule):]** LLM generator wiring, Dockerfile, extra variants, nicer CSS, follow-up sequencing intelligence, activity-trail export.

### Scope-cut order (if slipping): 
1. F3 edit UI (keep F1/F2 — the learning loop is the 25%)
2. G3 leaderboard polish (keep G2 — trail/explain is the 15%)
3. C2 LLM adapter (templates alone carry the demo)
4. B1/B2 extra polish (qualification edge cases)

---

## 10. Demo Script (3–5 minutes, fully local, one human decision, one learning cycle)

1. **Heartbeat (30s):** `run.py --demo` — overnight scan finds 3 signals (Acme raised seed + hired VP Sales; BetaCorp shipped v2; Gamma rebranded). Queue shows 3 qualified opportunities with evidence cards.
2. **Two proposals, Propose mode (45s):** agent proposes outreach to Acme (long-form warm email, 9:30 AM) and BetaCorp (LinkedIn connect + short note). Decision cards show reasoning, evidence, expected effect, variant stats.
3. **Human decision #1 — edit + approve (45s):** user edits Acme email (adds detail from their funding announcement), approves with note "lead with the funding angle." Edit deltas recorded → policy nudged (funding-led hooks, personalization_depth↑).
4. **Human decision #2 — reject with reason (30s):** user rejects BetaCorp note, reason `too_salesy`. Policy tone_assertiveness↓.
5. **Autopilot (30s):** a third action (follow-up to a warm graph edge → `INTRO_REQUEST` via shared connection) auto-executes within guardrails; a fourth (bulk send, high-cost class) routes to approval — demonstrates the class matrix.
6. **Outcomes arrive (45s):** Acme replies + books meeting (warm edge ↑); BetaCorp never replies (variant stats update). Leaderboard visibly shifts.
7. **Learning cycle — second pass (45s):** next cohort: NBAM picks the short, warm variant for the segment; new Gamma outreach drafted and visibly different — shorter, softer tone, funding-led personalization. Side-by-side before/after on screen. Rollback button demoed (revert policy → draft reverts). Optional: edit policy in UI → next draft changes.
8. **Trust close (30s):** activity trail replay + explain card for any action + kill switch toggled.

Local-only guarantees: every scene is deterministic from the seed; no network calls; LLM not involved; outcome timing simulated in-process.

---

## 11. README Outline (competition deliverable)

1. What Loop is — one closed GTM loop, not a dashboard.
2. Architecture diagram + six-stage loop explanation.
3. Models — template engine under policy state; optional LLM adapter (documented, not required); Thompson sampling; feedback→policy map.
4. Data & integrations — synthetic local feed, SQLite schema, channel adapters (simulated by default; no external paths in v1).
5. Permissions & guardrails — Propose/Autopilot, action-class matrix, budgets/caps, kill switch, SIMULATION_MODE.
6. How feedback changes future actions — the three mechanisms in §4 with concrete before/after examples.
7. Demo script (the 3–5 min walkthrough, §10).
8. Run instructions — `pip install -e .`, `python run.py --demo`, `python demo.py`; fully offline; optional LLM env vars.

---

## 12. Risks, Tradeoffs & Open Questions

| Risk | Mitigation |
|---|---|
| Time slip (1-day scope) | Defined cut order (§9); template engine means no LLM-key dependency; tests only on judged paths (learn/permission/e2e) + smoke tests elsewhere |
| "Learning" judged as cosmetic | Behavior-change tests (§4.4) + demo side-by-side; stats computed from real stored outcomes |
| Judges find simulation unconvincing | Explicit simulation semantics (delays, varied reply rates), clean adapter interface, manual outcome entry |
| Demo environment restrictions | Zero network, single process, SQLite file, localhost UI — runs on any laptop |
| Scope creep | Hard scope: one loop + warm-graph second hop; stretch backlog is explicit |

**Tradeoffs:**
- Template engine primary vs. LLM primary: templates win for a 1-day, offline demo; LLM stays an adapter for "technical execution" points if time allows.
- FastAPI + SQLite + htmx vs. heavier stacks: minimal infra risk, judges score the loop, not the framework.
- Deterministic demo seed vs. live exploration: seed wins — reproducibility is worth more than surprise.

**Open questions (low-risk, don't block build):**
1. Will judges supply an LLM key/endpoint, or must the demo stay offline-only? (Adapter already handles both.)
2. Preferred demo channel emphasis: email + LinkedIn both simulated — any preference?
3. Team rules (TBD): assume single builder; README covers "team" generically.

---

## 13. Verification Checklist (definition of done)

- [ ] `pytest -q` green: schema, qualify, plan, generate, permission, execute, learn (incl. 5 behavior-change tests), e2e demo.
- [ ] `python demo.py` reproduces §10 deterministically from a clean seed.
- [ ] **Offline proof:** demo completes with network disabled (e.g., `unshare -n python demo.py` or airplane-mode) — zero external calls.
- [ ] Propose mode: no action executes without a human decision; reasons captured.
- [ ] Autopilot: scope/budget/caps enforced; irreversible/external/high-cost classes always queue.
- [ ] One rejection with reason ⇒ next draft measurably different (test-asserted).
- [ ] Outcomes update variant stats ⇒ NBAM selection changes for the segment (test-asserted).
- [ ] Activity trail records every transition with status/outcome/reason; pause/stop works.
- [ ] README covers architecture, models, data, permissions, guardrails, feedback→behavior, demo script.
- [ ] Every brief requirement (R1–R11, B1–B7, D1) has a covered row in §8 matrix with a task and test.
