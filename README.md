# AI-Impact-and-Risk-Analysis
AI risk framework for workforce planning. Reconciles external labor market data, real AI usage signals, and internal hiring/pricing data into a per-role risk score, pattern classification, and actionable recommendation. FastAPI + Jinja2, Azure OpenAI optional with full rule-based fallback.


# AI Risk Framework

A workforce risk intelligence tool that combines **external labor market
data**, **real-world AI usage and capability data**, and **internal hiring,
pricing, and pipeline data** into a single, reconciled view per occupation —
answering one question: *is AI actually changing hiring demand, pricing, and
talent availability for this role, right now?*

Built for staffing and workforce planning teams who need a decision-ready
view rather than a generic labor-market research report.

---

## What it does

For each occupation in scope, the app:

1. Pulls together external labor market signals (BLS employment and wage
   data, O*NET task data) and AI impact signals (Anthropic's real usage
   data, OECD's capability research) alongside internal company data (job
   requisitions, billing, candidate pipeline).
2. Reconciles all of it into one record per occupation.
3. Classifies each occupation into a named risk pattern (e.g. *Invest and
   Scale*, *Execution Gap*, *Structural Displacement Risk*) with a plain-
   English explanation and a recommended action.
4. Presents everything through an Agent Run Panel, a Dashboard, an Insights
   & Recommendations view, and downloadable Excel reports.

Everything runs with **zero external LLM configuration required** — Azure
OpenAI is used only to polish the final narrative, and every number and
recommendation is fully computed by deterministic, rule-based logic on its
own.

---

## The Agents

| Agent | What it does |
|---|---|
| **Signal Intelligence Agent** | Independently reads all source data and produces a transparent breakdown of every signal alongside an early market, demand, and AI exposure comparison for each role. |
| **Data Reconciliation Agent** | Combines external labor market data with internal hiring, billing, and pipeline data into a single, unified record for each occupation. |
| **Market Demand Agent** | Scores each occupation's national market growth on a 0 to 100 scale and labels it Expanding, Stable, or Contracting. |
| **AI Impact Agent** | Combines real AI usage data with capability research into one exposure score, showing whether both sources agree on the level of risk. |
| **Internal Exposure Agent** | Tracks the company's own hiring volume, time to fill, and pricing trends for each role, down to individual job titles. |
| **Recommendation Agent** | Synthesizes every agent's output into a final risk rating, pattern classification, and plain-English recommendation — the only agent that calls an LLM, with full fallback if none is configured. |

Agents run in sequence with live status updates (pending → running →
completed), and each one's output is downloadable individually as a CSV.

---

## Key views

- **Signal Ledger** (View 1) — presents the individual data points
  underlying each occupation's risk assessment (market size and growth, AI
  usage and capability, internal hiring demand, and pricing trends) as
  discrete, sourced line items rather than a single composite score.
  Enables users to identify which specific factor is driving a role's risk
  classification and to trace any conclusion back to its underlying
  evidence.
- **Risk & Action Matrix** (View 2) — compares market direction, internal
  demand, and AI exposure side by side for each role, and maps that
  combination to a recommended action (Invest, Reposition, Watch-list, or
  Harvest) based on a consistent decision framework applied across every
  occupation.
- **Dashboard** — a heatmap across three dimensions (AI Impact, Demand
  Shift, Organizational Exposure), per-occupation risk and pattern badges,
  supporting charts, and a job-role-level drill-down showing individual job
  titles within each occupation.
- **Insights & Recommendations** — full narrative per occupation, tagged as
  AI-assisted or rule-based, with the ability to include/exclude each
  occupation from the exported report.

---

## Data sources

**External:**
- BLS Occupational Employment & Wage Statistics (OEWS)
- BLS Employment Projections
- O*NET Occupation Data and Task Statements
- Anthropic Economic Index (real, usage-based AI exposure)
- OECD AI Capability Gap Index (forward-looking, capability-based exposure)

**Internal (synthetic/demo data, clearly labeled throughout the app):**
- ATS/VMS requisition data
- Client billing data
- Candidate pipeline data

Full field-by-field documentation, including data-quality caveats (e.g. the
OECD dataset does not directly cover every occupation and uses a documented
proxy where needed), lives in `data_model_and_catalogue.md`.

---

## Getting started

### Requirements

- Python 3.10+
- pip

### Installation

```bash
git clone <your-repo-url>
cd ai-risk-framework
pip install -r requirements.txt
```

### Running the app

```bash
uvicorn backend.main:app --reload
```

Then open `http://localhost:8000` in your browser. Click **Run Pipeline**
on the landing page to generate all agent outputs, then explore the
Dashboard, Insights & Recommendations, and Export screens.

### Adding an occupation

Add rows for the new SOC code to each relevant file under `input/*.csv`.
No code changes are required — the next pipeline run will pick it up
automatically.

### Enabling Azure OpenAI (optional)

Set the following environment variables before starting the app:

```bash
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your-gpt-4o-deployment-name
```

Without these set, the app runs entirely on rule-based logic — every score
and recommendation is still generated, just without LLM-polished narrative
text. A banner in the UI indicates which mode is active.

---

## Project structure

```
input/                      Source data (CSV). Add an occupation here.
output/
  agents/                    Per-agent output CSVs, regenerated on each run
  reports/                   Excel workbooks, regenerated on each run
data/annotations.csv         User-entered report-inclusion notes

ai_risk_framework.py         Core data loading, reconciliation, and scoring logic
data_model_and_catalogue.md  Full field-by-field data dictionary

backend/
  main.py                    FastAPI app: routes and pipeline orchestration
  agents.py                  Agent implementations
  view1_source_breakdown.py  Signal Ledger logic
  view2_comparison_matrix.py Risk & Action Matrix logic
  patterns.py                Risk pattern classification
  job_roles.py                Job-role-level breakdown
  charting.py                 CSS-based chart rendering helpers
  annotations.py               Annotation storage
  excel_export.py              Excel report generation
  llm.py                       Azure OpenAI integration with fallback

templates/                   Jinja2 HTML templates
static/                       CSS and the minimal JS used for live agent status
```

---

## Known limitations

- Internal data is synthetic and included for demonstration purposes only.
- The OECD dataset does not cover every occupation directly; a documented
  proxy occupation is used where noted.
- Risk classification thresholds are reasoned defaults and have not been
  statistically validated against real outcomes.
- No live external data feeds — all data is a static, versioned snapshot.

See `data_model_and_catalogue.md` for the complete list.

---

## License

Add your license here.
