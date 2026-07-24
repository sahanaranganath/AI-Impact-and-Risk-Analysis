# AI Risk Framework — Application Spec (as built)

This document describes the application **as it currently exists**, not a
build plan for a future version. When the app changes, this file should
be updated in the same session so it never drifts from the code.

Companion files: `ai_risk_framework.py` (data load + reconciliation +
scoring logic — the ground truth for every number the app shows) and
`data_model_and_catalogue.md` (field-by-field data dictionary, join keys,
and data-quality caveats).

---

## 0. Architecture summary

**One process, one service.** FastAPI owns the data, the agent pipeline,
the scoring logic, the REST + SSE API, *and* the HTML frontend
(server-rendered Jinja2 templates + plain CSS). There is no separate
frontend framework, no React/Streamlit, and only a handful of vanilla-JS
lines on one screen (consuming the live pipeline SSE stream — the one
thing a static page genuinely can't do).

```
input/*.csv  →  ai_risk_framework.py (load + reconcile)  →  backend/agents.py (6 agents: Signal
                                                             Intelligence runs first, then the
                                                             5-agent reconciliation chain)
                                                                    │
                                                                    ▼
                                          output/agents/*.csv + output/reports/*.xlsx
                                                                    │
                                                                    ▼
                                    Dashboard / Insights & Recommendations / Export
                                    (read ONLY from those output files — never compute)
```

- **`input/`** — every data table the app uses, as CSV files, read by
  `ai_risk_framework.py`. This is the only place "data" lives; nothing is
  hardcoded in Python anymore.
- **`output/agents/`** — one CSV per agent (plus a job-roles table and the
  Signal Ledger / Risk & Action Matrix tables — see Section 4.1), written
  every time the pipeline runs. This is also what each agent's "Download"
  button on the Agent Run Panel serves directly.
- **`output/reports/`** — the final extended Excel workbook
  (`AI_Risk_Framework_SETT.xlsx`) plus a lightweight standalone workbook
  containing only the Signal Ledger / Risk & Action Matrix sheets
  (`Signal_Intelligence_Report.xlsx`), both regenerated at the end of
  every pipeline run.
- **`data/annotations.csv`** — user-entered "include in report" state per
  SOC, saved from the Insights & Recommendations screen (plain CSV via
  pandas, not a database).

**The Signal Intelligence Agent is independent of the Data Reconciliation
Agent, and runs BEFORE it.** Its two outputs — the **Signal Ledger**
(`backend/view1_source_breakdown.py:build_view1()`) and the **Risk &
Action Matrix** (`backend/view2_comparison_matrix.py:build_view2()`) —
never take `reconciliation_df` as a parameter and never read
`output/agents/*.csv`. Each calls `ai_risk_framework.load_all_data()` and
computes straight from `input/*.csv` itself (the same pattern
`build_reconciliation()` uses), so they always reflect the source data
as-is, unaffected by any downstream blending or aggregation, and work
even if the Data Reconciliation Agent hasn't run yet in this session. The
Recommendation Agent separately calls `build_view2()` itself (rather than
reading a persisted file) so its narrative can reference the Risk &
Action Matrix's resolved action; see Section 4.6.

**Dynamic by construction:** adding a SOC means adding rows to the
`input/*.csv` files — nothing in the code hardcodes a SOC list or a count
of 3. `build_reconciliation()` re-reads every input file at the start of
each call, so a newly added SOC is picked up by the next "Run Pipeline"
click with **no server restart**. (Internally: `ai_risk_framework.py`'s
data tables are module attributes reassigned by `load_all_data()`;
every consumer accesses them via `ai_risk_framework.SOC_REF` etc. — a
module attribute lookup, not a `from ... import SOC_REF` value copied
once at start-up — specifically so this refresh is visible everywhere.)

**Nothing shows until the pipeline has actually run.** Dashboard,
Insights & Recommendations, and Export do not compute anything
themselves. If `output/agents/*.csv` doesn't exist yet, they render an
empty-state panel ("Go to Agent Run Panel") instead of any data; the
JSON API returns `409` in the same situation.

---

## 1. Scope boundaries

- No live external data feeds — `input/*.csv` is a static, already-
  reconciled snapshot (see `data_model_and_catalogue.md` for provenance).
- No real ATS/CRM/HRIS integrations — internal data (`ats_vms_reqs.csv`,
  `client_billing.csv`, `candidate_pipeline.csv`) stays synthetic/dummy,
  labeled as such everywhere it's shown.
- Ships with 3 SOC codes (15-1252 Software Developers, 17-2071 Electrical
  Engineers, 19-4031 Chemical Technicians), but the app itself has no
  fixed SOC count — see "Dynamic by construction" above.
- No scenario simulation, no feedback-loop learning.

---

## 2. Job-role-level granularity

The Dashboard shows two levels:

1. **SOC level** (aggregated) — one row per occupation with composite
   scores, risk rating, and pattern classification.
2. **Job-role level** (drill-down) — within each SOC, the individual job
   titles from `ATS_VMS_REQS.job_title`, each with req count, fill
   status, days-to-fill, bill/pay rate, and margin, pulled from
   `ATS_VMS_REQS` / `CLIENT_BILLING` / `CANDIDATE_PIPELINE` filtered to
   that SOC (`backend/job_roles.py:build_job_role_breakdown`).

**UI:** SOC-level cards are the default Dashboard view; a native
`<details>/<summary>` "View job roles within this occupation" expander
under each card reveals the job-role table — no JS needed, collapsed by
default so the page stays uncluttered.

---

## 3. Pattern-interpretation library

Every SOC is classified into a **named pattern** (in addition to the
numeric HIGH/MODERATE/LOW risk rating), with a plain-English meaning and
a recommended leadership action. Implemented as `backend/patterns.py:
classify_pattern(row)`.

All numeric cutoffs below come from `ai_risk_framework.py`'s shared
business-logic threshold section (Section 4.1 explains the AI-exposure
bounds specifically) — this table, `classify_risk()`, the AI Impact
Agent, and the Risk & Action Matrix all read from the same constants, so
they never disagree on what "high AI exposure" or "weak growth" means.

| Pattern | Trigger condition | What it means | Recommended leadership interpretation |
|---|---|---|---|
| **Structural Displacement Risk** | `composite_ai_exposure >= 0.60` (`AI_EXPOSURE_HIGH_MIN`) AND `internal_req_volume_trend_pct <= -10` AND low adjacency | Structural displacement risk — high AI exposure and shrinking internal demand with nowhere adjacent to redeploy people. Most serious pattern in the library. | **Step Back or Harvest with a client transition plan.** |
| **AI-Augmented Recomposition** | `composite_ai_exposure >= 0.60` AND internal demand roughly flat/stable (`-10 < trend < 10`) | The role is being recomposed (tasks changing, augmented by AI) rather than eliminated outright. | **Reposition into an AI-augmented archetype** — retrain/rebrand rather than reduce headcount. |
| **External Demand Down + Internal Revenue Down** | `bls_emp_change_pct < 8` AND `internal_margin_trend_pct < 0` | Market decline is flowing into the business, not just a national trend. | **High risk:** prioritize Harvest, Reposition, or Step Back. |
| **External Demand Down + Internal Revenue Stable** | `bls_emp_change_pct < 8` AND `internal_margin_trend_pct >= 0` | Current demand may be protected for now, but pipeline could weaken as the market softens. | **Watch-list:** protect renewals, reposition proactively. |
| **Execution Gap** | `bls_emp_change_pct >= 10` AND `internal_req_volume_trend_pct < 0` | The market is growing, but the firm isn't capturing its share. | Investigate sales, sourcing, pricing, or capability issues — an internal problem, not a market one. |
| **Invest and Scale** | `bls_emp_change_pct >= 10` AND `internal_req_volume_trend_pct > 0` | Both the market and the internal book support growth. | **Invest and scale.** |
| **Mixed Signal / No Dominant Pattern** | none of the above (e.g. growth in the 8–10% gap between "weak" and "strong") | Signals don't line up with a named pattern. | Watch-list; re-check next cycle. |

Evaluation order: the two AI-exposure patterns are checked first (this
is an AI risk framework — they're the more specific, more actionable
signal), then the external/internal market 2×2, then the catch-all.

`low_adjacency` has no sibling-SOC data modeled yet, so it always
defaults to `True` — surfaced as an `assumptions` caveat in the pattern
output and shown as a warning banner in the UI whenever that pattern
fires.

**Why `AI_EXPOSURE_HIGH_MIN` is 0.60, not 0.25:** `composite_ai_exposure`
averages Anthropic's real observed-usage exposure (rarely above ~0.30-0.35
for any occupation) with OECD's forward-looking capability-gap score
(typically 0.7-0.95 for professional/technical occupations — it barely
differentiates between them). Averaged together, a knowledge-work
occupation's composite realistically lands somewhere between ~0.30 and
~0.65 — not the full 0-1 range a generic threshold would assume. A cutoff
of 0.25 sits at the floor of that range, so it read almost every
occupation as "HIGH" off OECD's near-constant ceiling alone, regardless of
how much real usage Anthropic actually observed. 0.60 requires both
signals to be genuinely elevated before a role counts as HIGH.

**UI display:** pattern name as a colored badge next to the risk-rating
badge, followed by the meaning and recommended action — on both the
Dashboard and the Insights & Recommendations screen.

---

## 4. Agents

All 6 agents are in `backend/agents.py`. Every agent is deterministic and
rule-based except the Recommendation Agent's narrative step. Running the
pipeline (`POST /api/run-pipeline`) executes all 6 in sequence over SSE
— **Signal Intelligence runs first**, ahead of and independent of Data
Reconciliation — and each one's result is written to `output/agents/*.csv`
as it completes (see `backend/main.py:_persist_agent_output`).

### 4.1 Signal Intelligence Agent
`backend/agents.py:run_signal_intelligence_agent()`, calling
`backend/view1_source_breakdown.py:build_view1()` and
`backend/view2_comparison_matrix.py:build_view2()`. **Runs first, before
Data Reconciliation** — it reads the raw external and internal data
directly (reloading `input/*.csv` itself), before anything is merged or
averaged, so its output always reflects the source data as-is, unaffected
by any downstream blending or aggregation. No LLM, ever. Produces two
outputs:

- **Signal Ledger** — a transparent, line-by-line record of every
  underlying data point that feeds the risk assessment: one row per
  (dimension, source, SOC) across **External Demand (ED)** (BLS OEWS
  employment, BLS Projections growth % and annual openings), **AI
  Impact** (Anthropic observed exposure, OECD capability gap — flagged if
  a proxy), **Internal Demand (ID)** (ATS/VMS req-volume trend), and
  **Exposure** (client-billing margin trend, candidate-pipeline
  submittal trend) — each with a formatted value and a plain-English
  description of what it means. Use this to trace a conclusion back to
  its source. → `output/agents/signal_ledger.csv`.
- **Risk & Action Matrix** — compares market direction, internal demand,
  and AI exposure side by side for each role, and maps that combination
  to a recommended action (Invest, Reposition, Watch-list, Harvest, …)
  based on a consistent decision framework applied across every
  occupation. Calls the shared
  `ai_risk_framework.compute_composite_ai_exposure()` helper (also used by
  `build_reconciliation()`, so the two never disagree on the number). For
  each SOC:
  - **External demand direction** (UP/DOWN) — UP requires BLS growth to
    clear `WEAK_GROWTH_THRESHOLD` (8%), not just be positive; +2-3%
    growth is economy-wide noise, not a genuine expansion story.
  - **Internal demand direction** (UP/DOWN) — UP requires the req-volume
    trend to clear `INTERNAL_TREND_FLAT_BAND` (10%), for the same reason
    (this internal metric is a noisier, smaller-sample signal than BLS's
    national projection).
  - **AI exposure level** (LOW/MODERATE/HIGH) — from
    `AI_EXPOSURE_LOW_MAX`/`AI_EXPOSURE_HIGH_MIN` (Section 3), the same
    bounds `classify_risk()` and the AI Impact Agent use.

  It then describes how the three relate to each other, and resolves the
  combination against a fixed, non-computed 8-row reference matrix to get
  a `recommended_action` + `rationale`. The matrix's AI axis is strictly
  LOW/HIGH (no MODERATE row exists), so **MODERATE folds to LOW**, not
  HIGH — a mixed signal shouldn't trigger the same AI-reshaping action as
  a clearly HIGH reading. Returns two tables — the per-SOC comparison and
  the full 8-row reference matrix — written to
  `output/agents/risk_action_matrix.csv` and
  `output/agents/risk_action_matrix_reference.csv`.

| External Demand | Internal Demand | AI Exposure | Recommended Action |
|---|---|---|---|
| UP | UP | LOW | Invest |
| UP | UP | HIGH | Focus More / Reposition into AI-augmented archetype |
| UP | DOWN | LOW | Execution Gap |
| UP | DOWN | HIGH | Reposition |
| DOWN | UP | LOW | Maintain / Protect Renewals |
| DOWN | UP | HIGH | Reposition (urgent) |
| DOWN | DOWN | LOW | Watch-list |
| DOWN | DOWN | HIGH | Harvest / Step Back |

### 4.2 Data Reconciliation Agent
Calls `build_reconciliation()` directly (re-reads `input/*.csv` first).
No LLM, ever. Output → `output/agents/data_reconciliation_agent.csv`.

### 4.3 Market Demand Agent
Input: `bls_emp_change_pct`, `bls_annual_openings_k`. Output: Demand
Growth Index (0–100), direction (Expanding/Stable/Contracting),
narrative. → `output/agents/market_demand_agent.csv`.

### 4.4 AI Impact Agent
Input: `anthropic_observed_exposure`, `oecd_gap_index_reversed_norm`,
`oecd_is_proxy`. Output: `composite_ai_exposure`, exposure band
(Low/Moderate/High), source-agreement note. →
`output/agents/ai_impact_agent.csv`.

### 4.5 Internal Exposure Agent
Input: `build_internal_summary()` aggregates plus the job-role-level
breakdown. Output: Internal Demand Index (0–100), direction, narrative,
and the job-role table. → `output/agents/internal_exposure_agent.csv`
plus `output/agents/job_roles_by_soc.csv`.

### 4.6 Recommendation Agent (pattern + narrative synthesis)
Combines 4.3–4.5's outputs with `classify_risk()` and `classify_pattern()`.
**The only agent that calls Azure OpenAI GPT-4o** — the prompt includes
ONLY the already-computed structured outputs (grounding rule: no outside
claims about the occupation, AI capabilities, or the labor market).
Falls back to `generate_insight()` + the pattern's meaning/action on any
failure or missing config; tags `used_llm: True/False`. Also the point at
which both Excel reports are (re)built into `output/reports/` (Section 8).
→ `output/agents/recommendation_agent.csv`.

This agent also calls `build_view2()` (4.1) directly and includes a
`risk_action_matrix` object (ed/id direction, AI level, resolved
`recommended_action`, `rationale`) in the structured payload sent to the
LLM, and appends the same fields to the rule-based fallback narrative.
Both paths **must name the Risk & Action Matrix's `recommended_action`
explicitly** — not just restate the risk rating and pattern independently
of it. (The LLM's system prompt in `backend/llm.py` states this
requirement outright.)

---

## 5. Backend — API Endpoints

All endpoints that return pipeline data respond `409` with
`"Pipeline has not been run yet."` if `output/agents/*.csv` doesn't exist.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Agent Run Panel (HTML) |
| GET | `/dashboard` | Dashboard (HTML) |
| GET | `/insights` | Insights & Recommendations (HTML) |
| POST | `/insights/annotations/{soc_code}` | Save "include in report" from the Insights form (redirects back) |
| GET | `/export` | Export screen (HTML) |
| GET | `/api/socs` | SOC reference list (for filter dropdowns) |
| GET | `/api/llm-status` | Whether Azure OpenAI is configured |
| POST | `/api/run-pipeline` | Runs all 6 agents in sequence (Signal Intelligence first); streams status via SSE (`agent_name`, `status`, `output_summary`); writes each agent's output file as it completes |
| GET | `/api/reconciliation` | Full SOC-level reconciled table |
| GET | `/api/reconciliation/{soc_code}` | Single SOC's reconciled record |
| GET | `/api/job-roles/{soc_code}` | Job-role-level breakdown for one SOC |
| GET | `/api/pattern/{soc_code}` | Pattern classification for one SOC |
| GET | `/api/insights/{soc_code}` | Narrative + recommendation for one SOC (includes `used_llm`) |
| GET | `/api/heatmap` | Data shaped for the 3-dimension heatmap |
| GET | `/api/annotations` | All saved annotations |
| GET | `/api/annotations/{soc_code}` | One SOC's saved annotation |
| POST | `/api/annotations` | Save a note/include-in-report flag (JSON API) |
| GET | `/api/report/excel` | Downloads the full persisted Excel workbook (`AI_Risk_Framework_SETT.xlsx`) from `output/reports/` |
| GET | `/api/report/views-excel` | Downloads the standalone Signal Intelligence workbook (`Signal_Intelligence_Report.xlsx` — Signal Ledger + Risk & Action Matrix only) from `output/reports/` |
| GET | `/api/agents/{slug}/csv` | Downloads one agent's persisted CSV from `output/agents/` (`slug` ∈ signal-ledger, risk-action-matrix, risk-action-matrix-reference, reconciliation, market-demand, ai-impact, internal-exposure, recommendation) |

The SOC filter used by Dashboard/Insights/Export is a single query param,
`?soc=<soc_code>` (empty/omitted = all SOCs) — a dropdown in the UI. The
Dashboard's Signal Ledger section adds a second, independent query param,
`?dimension=<name>` (empty/omitted = all 4 dimensions), and both combine
(e.g. `/dashboard?soc=15-1252&dimension=AI+Impact`).

---

## 6. Frontend — Screens

Server-rendered Jinja2 (`templates/`) + plain CSS (`static/style.css`).
Charts are computed server-side as inline CSS (bars, heatmap cell
colors) in `backend/charting.py` — no charting library. The only
JavaScript (`static/app.js`) lives on the Agent Run Panel, consuming the
`/api/run-pipeline` SSE stream to update status live.

### 6.1 Agent Run Panel (`/`)
- 6 agent cards side by side (responsive grid) — **Signal Intelligence
  Agent** (Section 4.1) listed and run first, followed by the 5 agents
  from Section 4.2–4.6 — each with: an icon, the agent name, a
  permanently-visible one-line description, a status pill (Pending →
  Running → Done), and one or more **Download** buttons. The Signal
  Intelligence card has three: the Signal Ledger plus the Risk & Action
  Matrix's comparison table and its reference table.
- Every download button is hidden until that specific agent's SSE "done"
  event fires — it is never shown before the agent has actually completed.
- "Run Pipeline" button triggers the SSE run (all 6 steps in sequence).

### 6.2 Dashboard (`/dashboard`)
- SOC dropdown filter.
- **3-dimension heatmap**: rows = SOC, columns = AI Impact / Demand
  Shift / Organizational Exposure, each 0–100, colored teal→amber→red,
  with a legend explaining what each column means.
- Per-SOC card: risk + pattern badges, pattern meaning/action, caveats
  (OECD proxy, pattern assumptions), then 3 charts each with a one-line
  plain-English explanation of what it shows:
  - External (BLS) vs. internal req-volume trend (paired bars)
  - Anthropic vs. OECD exposure (horizontal bars)
  - Internal margin trend (bar)
- Job-role drill-down expander per SOC (Section 2).
- **Signal Ledger** (its own panel, below the heatmap): every raw signal
  per SOC, grouped into sub-headed blocks by dimension (External Demand
  (ED) / AI Impact / Internal Demand (ID) / Exposure), each row showing
  source, formatted value, and a plain-English description. Filterable by
  `?dimension=` (its own dropdown, preserving the page's `?soc=` selection
  via a hidden field) in addition to the shared SOC filter.
- **Risk & Action Matrix** (its own panel, below the Signal Ledger): a
  per-SOC comparison table (ED/ID direction, AI exposure level, how they
  relate, resolved recommended action + rationale), followed by the full,
  always-visible 8-row reference matrix with the row(s) the
  currently-filtered SOC(s) resolved to highlighted via a CSS class.

### 6.3 Insights & Recommendations (`/insights`)
Per SOC, in clearly labeled sections:
- **Key Metrics** — Demand Growth Index, Composite AI Exposure, Internal
  Demand Index, as metric tiles.
- **Pattern Classification** — meaning + recommended action as bullet
  points, plus any assumption caveat.
- **Insight & Recommendation** — AI exposure / market demand / internal
  exposure / recommendation, as bullet points, tagged "AI-assisted" or
  "Rule-based".
- **Include this occupation in the exported report** — checkbox, saved
  via `POST /insights/annotations/{soc_code}`.

### 6.4 Export (`/export`)
- "Download Excel Report" button → `/api/report/excel` (the full workbook).
- "Download Signal Intelligence Workbook" button →
  `/api/report/views-excel` (standalone Signal Ledger + Risk & Action
  Matrix only), shown once `Signal_Intelligence_Report.xlsx` exists.
- Summary table of what's included in the current run and each SOC's
  include/exclude state.
- Empty-state until `output/reports/*.xlsx` exists.
- PDF export deferred as a fast-follow (not required for v1).

---

## 7. Fallback behavior

- **No Azure OpenAI key set:** entire app runs on rule-based logic. Each
  Insights card shows a "Rule-based" tag instead of "AI-assisted".
- **Azure OpenAI key set but call fails at runtime:** the Recommendation
  Agent catches the exception and falls back to the templated narrative
  for that SOC only. Pipeline never halts on an LLM failure.

---

## 8. Tech stack summary

| Layer | Choice |
|---|---|
| Backend + frontend | FastAPI (single process) — REST + SSE API and server-rendered Jinja2 HTML |
| Frontend rendering | Jinja2 templates + plain CSS; vanilla JS only for the live SSE status stream |
| Charts | Plain CSS (bars, heatmap cell colors) computed in `backend/charting.py` — no charting library |
| LLM (optional) | Azure OpenAI GPT-4o, via `openai` Python SDK's Azure client (Recommendation Agent only) |
| Data (input) | pandas, reading `input/*.csv` via `ai_risk_framework.py` |
| Data (output) | pandas-written CSVs under `output/agents/`, Excel workbook under `output/reports/` |
| Excel export | openpyxl, extending `ai_risk_framework.py`'s own workbook logic |
| Annotation storage | Single CSV file (`data/annotations.csv`) via pandas — no database |

---

## 9. Directory map

```
input/                      Source-of-truth data (CSV). Add a SOC here.
  soc_ref.csv, bls_oews.csv, bls_projections.csv, onet_occupation.csv,
  onet_tasks.csv, anthropic_job_exposure.csv, anthropic_task_penetration.csv,
  oecd_capability_gap.csv, ats_vms_reqs.csv, client_billing.csv,
  candidate_pipeline.csv, external_sources_ref.csv, internal_sources_ref.csv

output/                     Generated by "Run Pipeline". Not source data.
  agents/*.csv               One file per agent + job_roles_by_soc.csv,
                              signal_ledger.csv, risk_action_matrix.csv,
                              risk_action_matrix_reference.csv
  reports/AI_Risk_Framework_SETT.xlsx
  reports/Signal_Intelligence_Report.xlsx   Standalone Signal Ledger + Risk & Action Matrix workbook

data/annotations.csv        User-entered per-SOC report-inclusion state

ai_risk_framework.py         Data loading + reconciliation + scoring (ground truth)
data_model_and_catalogue.md  Field-by-field data dictionary

backend/
  main.py                    FastAPI app: API + HTML routes
  agents.py                  The 6 agents (Signal Intelligence runs first) + output-frame builders
  view1_source_breakdown.py   build_view1() — the Signal Ledger, independent of reconciliation
  view2_comparison_matrix.py  build_view2() — the Risk & Action Matrix + fixed 8-row reference table, independent of reconciliation
  patterns.py                classify_pattern()
  job_roles.py                Job-role breakdown + build_all_job_roles()
  charting.py                 CSS bar/heatmap color helpers
  annotations.py               CSV-backed annotation storage
  excel_export.py              Extended workbook builder + standalone views workbook builder
  storage.py                   output/ path + read/write helpers
  llm.py                       Azure OpenAI wrapper (Recommendation Agent only)

templates/                   Jinja2 HTML (base, index, dashboard, insights, export, partials)
static/                       style.css, app.js (SSE consumption only)
```

---

## 10. Remaining open decision

- **PDF export** — deferred as a fast-follow (Section 6.4).
