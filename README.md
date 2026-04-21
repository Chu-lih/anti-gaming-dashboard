# Compliance Sentinel — Anti-Gaming Fraud Dashboard

> A SOC-style compliance-auditing dashboard that detects and forensically reviews
> agents who "game" mandatory training sessions. Built for the KGI Financial
> Holdings MA program, Project 6.

---

## Overview

When training is tied to bonuses, licenses, or KPIs, some employees will look
for shortcuts — speed-clicking through a 7-minute AML compliance module in 12
seconds, blind-guessing a quiz in under 5 seconds, or switching to LINE six
times mid-lecture. If that agent later commits a violation, the FSC will ask
the Financial Holding Company: *"You knew they didn't read it. Why did your
system let them complete it?"*

This system acts as the company's **automated compliance auditor**:

1. **Detects** gaming behaviour against a dynamic set of rules whose
   thresholds managers can tune in real time.
2. **Surfaces** flagged sessions in a Risk Inbox that reads like a cyber
   threat monitor, not a training back-office.
3. **Reconstructs** each session as a forensic timeline so a manager can
   see *exactly* what happened — every tab switch, every card swipe, every
   quiz submission — before deciding to approve, void, or escalate.
4. **Records** every managerial decision and every rule change into
   DB-level immutable tables, so an FSC auditor can later reconstruct
   "what rules were in force, and who signed off on what, at any point
   in time."

---

## Business Context — the Forgetting Curve

The broader micro-learning platform (see `docs/The Forgetting Curve`) breaks
compliance training into 7-minute bite-sized sprints delivered during an
agent's "in-between" moments (MRT commute, waiting for a client, between
coding sprints). Spaced repetition and reinforcement learning push recall
quizzes exactly when the forgetting curve predicts the knowledge is about
to decay.

That philosophy **only works if agents actually engage with the content.**
When training is mandated and bonus-linked, the incentive to "get it done"
replaces the incentive to "learn it." This dashboard is the counterweight:
it makes gaming visible at the individual session level, turning a hidden
compliance risk into a reviewable artefact.

---

## Key Features

| Feature | Why it matters |
|---|---|
| **Dynamic Rule Engine** | Thresholds live in `ComplianceRules.parameter_json`, not code. A compliance officer can loosen `SPEEDING` from 20% → 30% in the UI and have it take effect on the next scan — no deploy, no restart. |
| **Strategy Pattern dispatch** | Each rule is a `RuleChecker` subclass registered by `rule_code`. Adding a fourth rule means writing one class; the scan loop is closed for modification. |
| **Forensic Timeline** | Dual-axis SVG: a comparative view (12s actual vs 420s average) and a zoomed event track with layered markers. Makes *"they clicked through a 7-minute module in 12 seconds and switched to LINE six times"* visually obvious in under a second. |
| **Immutable Audit Trail** | `ComplianceAuditLog` (session decisions) and `RuleChangeLog` (rule edits) both have `BEFORE UPDATE / BEFORE DELETE` triggers that `RAISE(ABORT)`. Enforced at the DB layer, not just the application — even a DBA with SQL access can't rewrite history. |
| **Role-based Resolution** | Every decision is signed by the currently-logged-in manager. Three actions — *Approve / Void & Require Retake / Escalate to HR* — mapped to the spec's required outcomes. |
| **Dark / Light Theme** | Single `data-theme` attribute flips every `slate-*` utility across all pages via `rgb(var(--color-slate-N) / <alpha-value>)` tokens. No HTML change required. |

---

## Architecture

```
                          ┌─────────────────────────────────┐
                          │  Browser (Tailwind CDN + Vanilla JS)
                          │  · Inbox   · Timeline   · Rules   │
                          └──────────────┬──────────────────┘
                                         │ fetch / forms
                          ┌──────────────▼──────────────────┐
                          │          Flask (app.py)          │
                          │  Pages: /inbox /timeline /rules  │
                          │  APIs : /api/resolve             │
                          │         /api/rules/update|toggle │
                          │         /api/rescan              │
                          │         /api/inbox-data          │
                          └──────────────┬──────────────────┘
                                         │ sqlite3  (?-parameterised)
        ┌────────────────────────────────▼──────────────────────────────┐
        │                   SQLite (database.db)                         │
        │                                                                │
        │  ComplianceRules ─── parameter_json ──────────┐                │
        │        │                                      │                │
        │        │  reads                               │ dispatched by  │
        │        ▼                                      ▼                │
        │  rule_engine.py ────── scans ─────▶ LearningSessions           │
        │        │                                      │                │
        │        │ writes                               │                │
        │        ▼                                      │                │
        │  FlaggedSessions ◀── read by inbox/timeline ◀─┘                │
        │        │                                                       │
        │        │ resolved by manager                                   │
        │        ▼                                                       │
        │  ComplianceAuditLog (INSERT-only, DB triggers)                 │
        │                                                                │
        │  RuleChangeLog (INSERT-only, DB triggers)                      │
        └────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.10+ · Flask 3.0 | Minimum ceremony, maximum readable routes. |
| Data | SQLite (single file) | Zero setup, transactional, supports triggers, fits a demo laptop. |
| Frontend | Tailwind CSS (CDN) · Vanilla JS | No build tool, no `node_modules`. Opens in any browser. |
| Charts | Hand-rolled SVG | Full control over the dual-axis layout — off-the-shelf libs would fight the design. |
| Tests | Flask test client + CLI assertions | Enough to verify every route + every rule decision deterministically. |

---

## Getting Started

```bash
# 1. Install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Seed
python3 seed_data.py        # builds database.db, 15 agents, 80 sessions
python3 rule_engine.py      # first scan writes 22 FlaggedSessions

# 3. Run
python3 app.py              # → http://127.0.0.1:5001
```

The app auto-scans on first boot if `FlaggedSessions` is empty, so step 2's
`rule_engine.py` is optional — it's there so you can also exercise the CLI.

### CLI usage of the rule engine

```bash
python3 rule_engine.py              # normal scan + write
python3 rule_engine.py --dry-run    # list hits, don't write
python3 rule_engine.py --test       # assert demo cases trigger expected rule sets
```

---

## Demo Scenarios

After seeding, these three curated sessions each hit a distinct rule
combination. All three stay on page 1 of the Risk Inbox sorted by severity.

| Session ID | Agent | Module | What it does | Timeline URL |
|---|---|---|---|---|
| **S-DEMO-01** | 王大明 (A001) | AML 反洗錢基礎 | Finishes a 420s module in 12 seconds. Switches to LINE six times. Quiz: 0/3 correct in 4 seconds. → **Triggers SPEEDING + BLIND_GUESSING + DISTRACTION, all 3 rules.** | `/timeline/1` |
| **S-DEMO-02** | 陳美麗 (A002) | 投資型保單 DM 揭露要點 | 300s module done in 48s with a perfect quiz score. → Only `SPEEDING`. | `/timeline/4` |
| **S-DEMO-03** | 林志豪 (A003) | FSC 金融消費者保護法新規 | Completes in a normal 460s but switches browser tabs 9 times mid-session. → Only `DISTRACTION`. | `/timeline/5` |

### Recommended interview demo flow (≈4 min)

1. **Open `/inbox`.** 14 High + 8 Medium pending. Point out severity-coded KPI cards, the rescan button (rule engine is live), and the zebra-striped table.
2. **Click S-DEMO-01 row.** The dual-axis timeline shows the 12s ACTUAL bar dwarfed by the 420s AVG dashed line — "3% of expected duration" is the headline. Below, the zoomed event track shows three layers of events with the red pulsing tab-switch triangles clustered tight.
3. **Hover a tab-switch marker.** Tooltip: `t=11s · tab_switch · switched to LINE`.
4. **Write a note, click `Void & Require Retake`.** Toast confirms an audit entry; 2 seconds later the inbox returns, and the row is gone.
5. **Jump to `/rules`.** Loosen `SPEEDING.min_completion_ratio` from `0.2` to `0.5`, click Save, click Rescan in the header. Toast: *"23 total rule hits evaluated."* Switch back to inbox; new flags appear. Swap it back to `0.2`, rescan, audit trail at the bottom of `/rules` shows both edits signed by "張經理".
6. **Flip the theme toggle to Light.** Every page stays readable.

---

## Database Schema

Five tables, two of them append-only and trigger-protected:

```
ComplianceRules          ← the logic dictionary (parameter_json is the knob)
  ├─ rule_id PK / rule_code UNIQUE
  └─ severity_level (Low/Medium/High) · is_active

Modules                  ← lookup for "what's the company average for this module?"
  └─ module_name UNIQUE · avg_completion_seconds

LearningSessions         ← raw telemetry the engine scans
  ├─ session_id PK · agent_id · module_name
  └─ completion_seconds · quiz_score · quiz_seconds · tab_switch_count
     · telemetry_json (full event array) · started_at

FlaggedSessions          ← the manager's inbox queue
  ├─ flag_id PK · session_id · rule_violated_id → ComplianceRules
  ├─ resolution_status: pending|approved|voided|escalated
  └─ UNIQUE(session_id, rule_violated_id) → rescans are idempotent

ComplianceAuditLog       ← INSERT-only · DB triggers block UPDATE/DELETE
  └─ flag_id → FlaggedSessions · manager_id · action_taken · notes · timestamp

RuleChangeLog            ← INSERT-only · DB triggers block UPDATE/DELETE
  └─ rule_id → ComplianceRules · change_type · old_value · new_value · manager
```

---

## Rule Engine Design

`rule_engine.py` uses the **Strategy pattern**:

```
RuleChecker (abstract)
    ├── SpeedingChecker       rule_code="SPEEDING"
    ├── BlindGuessingChecker  rule_code="BLIND_GUESSING"
    └── DistractionChecker    rule_code="DISTRACTION"

CHECKER_REGISTRY = { "SPEEDING": SpeedingChecker, ... }
```

**Three deliberate choices worth calling out in interview:**

1. **No silent defaults.** Each checker calls `self._require(key)` and raises
   `ValueError` if `parameter_json` is missing a field. A misconfigured rule
   fails loudly at load time rather than producing wrong audit records in
   production.

2. **Parameters only from DB.** No checker holds a magic number. A reviewer
   can read `SpeedingChecker.check()` and see `self.params["min_completion_ratio"]`
   — the actual threshold lives in `ComplianceRules` and changes via the UI.

3. **Idempotent scans.** The DB has `UNIQUE(session_id, rule_violated_id)` on
   `FlaggedSessions` and the engine uses `INSERT OR IGNORE`. Scanning twice,
   or scanning after a rule tightens, never double-flags a session.

---

## Audit Trail Design

Two separate INSERT-only tables, not one big table. The reason:

* `ComplianceAuditLog` answers *"who resolved which session flag, and how?"* —
  the spec-mandated audit record that an FSC examiner reads.
* `RuleChangeLog` answers *"who changed which threshold, and when?"* —
  needed to reconstruct "what rules were even in force when that session was
  flagged."

Folding both into one table would have forced either widening
`action_taken CHECK` beyond the spec or making `flag_id` nullable on an
FSC-critical audit table. Keeping them separate lets each table's schema
match exactly what it records.

Both tables are defended by the same pattern:

```sql
CREATE TRIGGER trg_audit_no_update
BEFORE UPDATE ON ComplianceAuditLog
BEGIN
    SELECT RAISE(ABORT, 'ComplianceAuditLog is immutable — UPDATE is forbidden for FSC compliance');
END;
```

Application-layer discipline is not enough for a regulator — this is enforced
at the engine level. You can verify it: open `sqlite3 database.db` and try
`UPDATE ComplianceAuditLog SET manager_name='hacker'` — SQLite refuses.

---

## Project Structure

```
anti_gaming_dashboard/
├── docs/                       Reference Word docs for the MA brief
├── app.py                      Flask app — routes, DB helpers, error handlers
├── rule_engine.py              Strategy-pattern rule checkers + CLI
├── seed_data.py                Builds database.db with 15 agents, 80 sessions
├── schema.sql                  DDL — 5 tables + 4 immutability triggers
├── requirements.txt            Flask 3.0.3 only
├── static/
│   ├── css/style.css           Theme tokens + custom animations
│   └── js/
│       ├── common.js           Toast, manager switcher, theme toggle
│       ├── inbox.js            AJAX filter + rescan wiring
│       ├── timeline.js         Dual-axis SVG renderer + resolution flow
│       └── rules.js            JSON editor validation + toggle + save
├── templates/
│   ├── base.html               Sidebar + status bar layout
│   ├── inbox.html              Risk Inbox
│   ├── timeline.html           Forensic Timeline
│   └── rules.html              Dynamic Rules Engine
└── database.db                 Generated — not in version control
```

---

## Notes for the Reviewer

* Session state (current manager, theme) lives in the Flask session cookie
  and in memory respectively — no `localStorage`, no external stores.
  Reload returns to a deterministic state.
* All SQL uses `?` parameter binding. No string concatenation anywhere near
  `execute()`.
* The dev server is Flask's built-in; the `_bootstrap_flags_if_empty()` helper
  in `app.py` auto-scans on first launch if `FlaggedSessions` is empty so
  the demo is robust to `rm database.db`.
