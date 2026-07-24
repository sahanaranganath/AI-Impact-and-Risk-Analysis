# AI Risk Framework — Data Model & Data Catalogue

**Scope:** SETT segment (Software Developers 15-1252, Electrical Engineers 17-2071,
Chemical Technicians 19-4031)
**Companion file:** `ai_risk_framework.py` / `AI_Risk_Framework_SETT.xlsx`

---

## 1. Purpose of this document

This catalogue documents every table used in the AI Risk Framework — where it
comes from, what one row represents, how it joins to everything else, and what
every single field means. It exists so that anyone (not just the person who
built it) can pick up the workbook or script and know exactly what they're
looking at, where a number came from, and whether it's real data or a stand-in.

---

## 2. Data Model Overview

### 2.1 The three pillars

```
PILLAR 1: EXTERNAL LABOR MARKET      PILLAR 2: AI IMPACT DATA         PILLAR 3: INTERNAL COMPANY DATA
  - BLS OEWS                           - O*NET Occupation Data          - ATS/VMS Req Data
  - BLS Employment Projections         - O*NET Task Statements          - Client Billing Data
                                        - Anthropic Job Exposure         - Candidate Pipeline Data
                                        - Anthropic Task Penetration
                                        - OECD Capability Gap Index
```

All three pillars join on **SOC Code** (or its O*NET-SOC equivalent). SOC Code
is the spine of the entire model — every table either has it natively or can
be mapped to it.

### 2.2 Entity relationship map

```
SOC_REF (master reference: 3 rows, one per occupation)
   soc_code  ─┬─────────────────────────────────────────────────────────┐
   onet_code ─┼─────────────────────────────────┐                       │
              │                                 │                       │
              ▼                                 ▼                       ▼
   ┌─────────────────────┐         ┌─────────────────────────┐   ┌──────────────┐
   │ EXTERNAL - PLAIN SOC │         │ EXTERNAL - O*NET-SOC    │   │  INTERNAL    │
   │ (6-digit code, e.g.  │         │ (SOC + ".00", e.g.      │   │  (via        │
   │  15-1252)            │         │  15-1252.00)            │   │  soc_code)   │
   ├─────────────────────┤         ├─────────────────────────┤   ├──────────────┤
   │ BLS_OEWS             │         │ ONET_OCCUPATION         │   │ ATS_VMS_REQS │
   │ BLS_PROJECTIONS      │         │ ONET_TASKS              │   │      │       │
   │ ANTHROPIC_JOB_       │         │ ANTHROPIC_TASK_         │   │      ▼       │
   │   EXPOSURE           │         │   PENETRATION (via      │   │ CLIENT_      │
   │ OECD_CAPABILITY_GAP  │         │   task_id, not SOC)     │   │   BILLING    │
   └─────────────────────┘         └─────────────────────────┘   │  (via req_id)│
                                                                   │      │       │
                                                                   │      ▼       │
                                                                   │ CANDIDATE_   │
                                                                   │   PIPELINE   │
                                                                   │  (via req_id)│
                                                                   └──────────────┘
                              │                    │                      │
                              └────────────────────┴──────────────────────┘
                                                    ▼
                                     RECONCILIATION (1 row per SOC —
                                     every pillar joined + computed fields)
                                                    ▼
                                     INSIGHTS_RECOMMENDATIONS
                                     (1 row per SOC — narrative output)
```

**The Signal Ledger and Risk & Action Matrix are a second, independent
branch off the same raw pillars** — not children of `RECONCILIATION`, and
produced together by the Signal Intelligence Agent, which runs BEFORE Data
Reconciliation in the pipeline. `SIGNAL_LEDGER` and
`RISK_ACTION_MATRIX`/`RISK_ACTION_MATRIX_REFERENCE` (Sections 3.15–3.16)
read `BLS_OEWS`, `BLS_PROJECTIONS`, `ANTHROPIC_JOB_EXPOSURE`,
`OECD_CAPABILITY_GAP`, and `Internal_Summary_by_SOC` directly, exactly as
`RECONCILIATION` does — they do not read `RECONCILIATION` itself.

### 2.3 Join key summary

| Join key | Format | Used by |
|---|---|---|
| `soc_code` | 6-digit, e.g. `15-1252` | BLS_OEWS, BLS_PROJECTIONS, ANTHROPIC_JOB_EXPOSURE, OECD_CAPABILITY_GAP, all internal tables, RECONCILIATION |
| `onet_code` | SOC + `.00`, e.g. `15-1252.00` | ONET_OCCUPATION, ONET_TASKS |
| `req_id` | Free-text ID, e.g. `REQ-1001` | ATS_VMS_REQS ↔ CLIENT_BILLING ↔ CANDIDATE_PIPELINE |
| `task_id` | Numeric O*NET task ID, e.g. `21662` | ONET_TASKS ↔ ANTHROPIC_TASK_PENETRATION |

**Why two SOC formats exist:** BLS and internal systems use the plain 6-digit
SOC code. O*NET, and datasets built on top of O*NET (Anthropic's task file,
OECD's file), use the O*NET-SOC code, which appends `.00` (or a more specific
suffix like `.01` for a sub-specialization). Every table in this model carries
whichever format its source system natively uses — conversion happens only at
join time, not by altering the source data.

---

## 3. Data Catalogue

Each table below lists: **grain** (what one row represents), **source**,
**refresh cadence** (how often the real-world source updates, for future
reference), and a **full field dictionary**.

---

### 3.1 `SOC_REF` — SOC Master Reference

- **Grain:** one row per occupation in scope
- **Source:** BLS SOC 2018 structure (bls.gov/soc/2018/soc_structure_2018.pdf)
- **Refresh cadence:** SOC structure is revised roughly every 8-10 years (last major revision 2018); effectively static
- **Role in model:** the master key — every join in the model ultimately traces back to this table

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | 6-digit Standard Occupational Classification code identifying the occupation. This is the primary join key across nearly every table in the model. |
| `soc_title` | text | Official BLS title for the occupation (e.g. "Software Developers"). |
| `onet_code` | text | SOC code with `.00` appended, matching O*NET's occupation-code format. Used to join against O*NET, Anthropic task-level, and OECD data. |

---

### 3.2 `BLS_OEWS` — Occupational Employment & Wage Statistics

- **Grain:** one row per occupation, national cross-industry total
- **Source:** bls.gov/oes (May 2025 estimates)
- **Refresh cadence:** annual
- **Role in model:** answers "how big is this occupation and how well does it pay, today"

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | Join key back to `SOC_REF`. |
| `occ_title` | text | Occupation title as published by BLS OEWS (should match `soc_title`; kept separately as a cross-check). |
| `tot_emp` | integer | Estimated total national employment in this occupation, rounded to the nearest 10, excluding self-employed workers. |
| `emp_prse` | float (%) | Percent Relative Standard Error on the employment estimate — a data-quality/precision indicator. Lower = more reliable. |
| `h_mean` | float ($) | Mean **hourly** wage across all workers in this occupation nationally. |
| `a_mean` | float ($) | Mean **annual** wage across all workers in this occupation nationally. |
| `mean_prse` | float (%) | Percent Relative Standard Error on the wage estimate — same precision caveat as `emp_prse`, applied to pay instead of headcount. |
| `h_pct10` | float ($) | Hourly wage at the 10th percentile — i.e., the low end of the pay range for this occupation (10% of workers earn less than this). |

---

### 3.3 `BLS_PROJECTIONS` — Employment Projections, 2024–34

- **Grain:** one row per occupation, "Line item" detail level (not rolled up to a broader Summary group)
- **Source:** bls.gov/emp/tables.htm, Table 1.2
- **Refresh cadence:** biennial (BLS reissues 10-year projections roughly every two years)
- **Role in model:** separates AI-driven change from pre-existing structural growth/decline that would happen regardless of AI

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | Join key back to `SOC_REF`. |
| `occ_title` | text | Occupation title as published in the projections table. |
| `emp_2024_k` | float (thousands) | National employment level in the 2024 base year, in thousands of workers. |
| `emp_2034_k` | float (thousands) | Projected national employment level in 2034, in thousands of workers. |
| `emp_change_numeric_k` | float (thousands) | Raw projected change in employment (2034 minus 2024), in thousands of workers. Positive = growth, negative = decline. |
| `emp_change_pct` | float (%) | Same change expressed as a percentage — the primary "is this occupation growing or shrinking" signal used in the reconciliation. |
| `annual_openings_k` | float (thousands) | Average annual job openings projected 2024–34, combining growth, retirements, and other turnover. A better real-world demand proxy than raw employment change alone, since it captures replacement need even in a flat-growth occupation. |
| `median_wage_2024` | integer ($) | Median annual wage in the 2024 base year. Cross-check against BLS OEWS's `a_mean` — median and mean will differ, especially in right-skewed pay distributions. |
| `typical_education` | text | BLS's stated typical entry-level education requirement (e.g. "Bachelor's degree", "Associate's degree"). Context for how substitutable/credentialed the role is. |

---

### 3.4 `ONET_OCCUPATION` — O*NET Occupation Data

- **Grain:** one row per O*NET-SOC occupation
- **Source:** onetcenter.org/database.html, "Occupation Data" file
- **Refresh cadence:** O*NET data is updated on a rolling basis (typically a few times a year per occupation)
- **Role in model:** provides the plain-English definition of what the job actually involves, and is the crosswalk anchor between SOC and O*NET-SOC

| Field | Type | Description |
|---|---|---|
| `onet_code` | text | O*NET-SOC code (SOC + suffix, e.g. `15-1252.00`). Join key to O*NET-based tables. |
| `title` | text | O*NET's occupation title. |
| `description` | text | Full narrative description of the occupation's scope of work, as defined by O*NET. Used as qualitative context when interpreting why an AI-exposure score is high or low. |

---

### 3.5 `ONET_TASKS` — O*NET Task Statements

- **Grain:** one row per **task** per occupation (many rows per SOC — this is a one-to-many child table of `ONET_OCCUPATION`)
- **Source:** onetcenter.org/database.html, "Task Statements" file
- **Coverage note:** in the current build, only **Software Developers (15-1252.00)** has its full task list captured; Electrical Engineers and Chemical Technicians are not yet populated at the task level. SOC-level reconciliation is unaffected (it uses job-level exposure scores), but task-level drill-down is currently limited to Software Developers.
- **Role in model:** the task-level foundation that AI-exposure scoring (Anthropic, and indirectly OECD) is built on top of

| Field | Type | Description |
|---|---|---|
| `onet_code` | text | Parent occupation's O*NET-SOC code. |
| `title` | text | Parent occupation title, denormalized for readability. |
| `task_id` | integer | O*NET's unique identifier for this specific task. Join key to `ANTHROPIC_TASK_PENETRATION`. |
| `task` | text | The task description itself, e.g. "Analyze user needs and software requirements to determine feasibility of design within time and cost constraints." |
| `task_type` | text | "Core" (essential/frequently performed) or "Supplemental" (less central to the role). Only Core tasks were retained in this build. |

---

### 3.6 `ANTHROPIC_JOB_EXPOSURE` — Anthropic Economic Index (Occupation-Level)

- **Grain:** one row per occupation
- **Source:** huggingface.co/datasets/Anthropic/EconomicIndex, `job_exposure.csv`
- **Refresh cadence:** tied to Anthropic's periodic Economic Index releases (observed roughly every few months)
- **Role in model:** the model's only **real-world usage-based** AI signal — not a theoretical estimate of what AI *could* do, but a measure of what AI is *actually being used for*, derived from real Claude conversations classified against O*NET tasks

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | Join key back to `SOC_REF`. |
| `title` | text | Occupation title as published by Anthropic. |
| `observed_exposure` | float (0–1) | Share of this occupation's task content that shows up in real, classified Claude usage. **Higher = more exposed / more AI usage observed.** Not expected to approach 1.0 for most roles, since most jobs mix exposed and non-exposed tasks. |

---

### 3.7 `ANTHROPIC_TASK_PENETRATION` — Anthropic Economic Index (Task-Level)

- **Grain:** one row per O*NET task (matched to Software Developers' tasks only in this build)
- **Source:** huggingface.co/datasets/Anthropic/EconomicIndex, `task_penetration.csv`
- **Join method:** matched by **exact task text** against `ONET_TASKS.task`, then keyed here by `task_id` for a clean join
- **Role in model:** shows *which specific tasks* within a role are already AI-touched versus untouched — much more actionable than one blended occupation-level score

| Field | Type | Description |
|---|---|---|
| `task_id` | integer | Join key back to `ONET_TASKS`. |
| `penetration` | float (0–1) | AI penetration score for this specific task. **Higher = more AI usage observed for this exact task.** A task scoring near 0 means that specific piece of the job shows negligible AI usage, even if the occupation's overall blended score is higher. |

---

### 3.8 `OECD_CAPABILITY_GAP` — OECD AI Capability Gap Index

- **Grain:** one row per occupation
- **Source:** OECD AI Exposure Measure dataset (OECD Artificial Intelligence Papers No. 59), downloaded via oecd-ilibrary.org
- **Refresh cadence:** tied to OECD's periodic AI Capability Indicators updates (infrequent — this is a research-paper-linked dataset, not a live feed)
- **Coverage note / known gap:** OECD's published dataset does **not** include SOC 15-1252 (Software Developers) directly. **15-1251.00 (Computer Programmers)** — the nearest adjacent occupation in the SOC hierarchy — is used as a **documented proxy**, flagged via `is_proxy`.
- **Role in model:** a forward-looking, capability-based exposure signal (how close AI's *current capabilities* are to fully covering the occupation's demands), complementing Anthropic's usage-based signal

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | Join key back to `SOC_REF`. For 15-1252, this is the *target* SOC even though the underlying score comes from the proxy occupation. |
| `onet_code_used` | text | The actual O*NET-SOC code the score was pulled from — may differ from the true occupation's own code when a proxy is used. |
| `occ_title_used` | text | Title of the occupation the score actually belongs to. Reads "(PROXY)" when this differs from the target SOC's real title. |
| `gap_index_reversed_norm` | float (0–1) | AI Capability Gap Index, reversed and normalized so that **higher = more exposed** (matches Anthropic's direction, for direct comparability). This is the field used in the composite exposure score. |
| `is_proxy` | boolean | `True` if this row's score was borrowed from an adjacent occupation because OECD does not cover the target SOC directly. Always check this before treating a score as a direct measurement. |

> **Note on the source file's other columns (not carried into this model):** the OECD file also publishes `AI Capability Gap Index (Total)` (unreversed — **lower** means more exposed, opposite direction from the field used here) and nine domain-level sub-scores (Language, Social Interaction, Problem Solving, Creativity, Metacognition, Knowledge/Learning/Memory, Vision, Manipulation, Robotic Intelligence). These were intentionally excluded from the core model to keep the primary exposure comparison simple, but are available in the source file for deeper "why is this score what it is" analysis later.

---

### 3.9 `ATS_VMS_REQS` — Applicant Tracking / Vendor Management System Requisitions

- **Grain:** one row per job requisition (an individual open or filled role)
- **Source:** **SYNTHETIC/DUMMY DATA** — simulates what a real ATS/VMS extract would contain
- **Refresh cadence (in a real deployment):** real-time / daily
- **Role in model:** the core internal **demand** signal — how much hiring activity is happening per SOC and how hard each role is to fill

| Field | Type | Description |
|---|---|---|
| `req_id` | text | Unique requisition identifier. Join key to `CLIENT_BILLING` and `CANDIDATE_PIPELINE`. |
| `job_title` | text | The internal/client-facing job title as posted — often more specific or varied than the standardized SOC title (e.g. "Senior Software Developer" vs. "Software Developers"). |
| `soc_code` | text | SOC code this req has been mapped to. In a real system, this mapping does not exist natively and must be built via a title-to-SOC crosswalk (see O*NET's Job Titles file). |
| `client_id` | text | Anonymized identifier for the client the req belongs to. |
| `open_date` | date | Date the requisition was opened. |
| `fill_date` | date or blank | Date the requisition was filled; blank if still open. |
| `days_to_fill` | integer or blank | Calendar days between `open_date` and `fill_date`. Blank for still-open reqs. A core measure of market tightness for this SOC. |
| `fill_status` | text | "Filled" or "Open". |
| `location` | text | Work location or "Remote". |

---

### 3.10 `CLIENT_BILLING` — Client Billing Data

- **Grain:** one row per requisition (1:1 with `ATS_VMS_REQS`)
- **Source:** **SYNTHETIC/DUMMY DATA** — simulates a finance/billing system extract
- **Refresh cadence (in a real deployment):** per pay cycle / real-time
- **Role in model:** the internal **price** signal — margin compression can indicate a role becoming commoditized (a possible early sign of AI-driven displacement); margin expansion can indicate scarcity or a growing skill premium

| Field | Type | Description |
|---|---|---|
| `req_id` | text | Join key back to `ATS_VMS_REQS`. |
| `soc_code` | text | Denormalized SOC code, carried for convenience when aggregating without a join. |
| `bill_rate` | float ($/hr) | Hourly rate charged to the client for this placement. |
| `pay_rate` | float ($/hr) | Hourly rate paid to the worker for this placement. |
| `margin` | float ($/hr) | `bill_rate` minus `pay_rate` — the per-hour spread retained. Trended over time per SOC as a price-pressure indicator. |

---

### 3.11 `CANDIDATE_PIPELINE` — Candidate Pipeline Data

- **Grain:** one row per requisition (1:1 with `ATS_VMS_REQS`)
- **Source:** **SYNTHETIC/DUMMY DATA** — simulates a recruiting CRM extract
- **Refresh cadence (in a real deployment):** real-time / daily
- **Role in model:** the internal **supply** signal — thin pipelines can reflect genuine talent scarcity or shrinking worker interest in a role (which can itself be a downstream effect of perceived AI risk)

| Field | Type | Description |
|---|---|---|
| `req_id` | text | Join key back to `ATS_VMS_REQS`. |
| `soc_code` | text | Denormalized SOC code, carried for convenience. |
| `submittals` | integer | Number of candidates submitted for this req. |
| `interviewed` | integer | Number of those candidates who reached interview stage. |
| `offers` | integer | Number of offers extended for this req (0 or 1 in this dataset, reflecting single-hire reqs). |

---

### 3.12 `Internal_Summary_by_SOC` — Derived Internal Aggregate

- **Grain:** one row per SOC code (aggregated from the three internal tables above)
- **Source:** derived — computed by `build_internal_summary()` in the script, not a raw external source
- **Role in model:** rolls up the three raw internal tables into one row per SOC so they can join cleanly into the final reconciliation

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | Join key. |
| `internal_total_reqs` | integer | Count of all reqs (open + filled) for this SOC. |
| `internal_open_reqs` | integer | Count of currently-open (unfilled) reqs for this SOC. |
| `internal_avg_days_to_fill` | float (days) | Average time-to-fill across filled reqs for this SOC. |
| `internal_avg_bill_rate` | float ($/hr) | Average bill rate across all reqs for this SOC. |
| `internal_avg_pay_rate` | float ($/hr) | Average pay rate across all reqs for this SOC. |
| `internal_avg_margin` | float ($/hr) | Average margin across all reqs for this SOC. |
| `internal_margin_trend_pct` | float (%) | Percent change in average margin between the earlier half and later half of this SOC's reqs (sorted by `open_date`). Positive = margin expanding over time; negative = compressing. **This is a simple chronological-split proxy, not a true time-series regression** — treat as directional, not precise. |
| `internal_avg_submittals` | float | Average number of submittals per req for this SOC. |
| `internal_submittal_trend_pct` | float (%) | Percent change in average submittals between the earlier and later half of this SOC's reqs. Positive = growing candidate supply; negative = shrinking. Same chronological-split-proxy caveat as above. |
| `internal_req_volume_trend_pct` | float (%) | Percent change in req *count* between the earlier and later half of the date range. Positive = demand increasing; negative = decreasing. |

---

### 3.13 `RECONCILIATION` — Final Combined Table

- **Grain:** one row per SOC code — the single "answer" table combining all three pillars
- **Source:** derived — computed by `build_reconciliation()`, joining every table above
- **Role in model:** this is the table a decision-maker would actually look at

| Field | Type | Description |
|---|---|---|
| `soc_code` / `soc_title` / `onet_code` | text | From `SOC_REF`. |
| `tot_emp`, `h_mean`, `a_mean` | numeric | From `BLS_OEWS` — current size and pay. |
| `emp_2024_k`, `emp_2034_k`, `bls_emp_change_pct`, `bls_annual_openings_k`, `bls_median_wage_2024`, `typical_education` | numeric/text | From `BLS_PROJECTIONS` — where this occupation is headed nationally, independent of AI. |
| `anthropic_observed_exposure` | float (0–1) | From `ANTHROPIC_JOB_EXPOSURE` — real usage-based AI exposure. |
| `oecd_gap_index_reversed_norm` | float (0–1) | From `OECD_CAPABILITY_GAP` — forward-looking capability-based exposure. |
| `oecd_is_proxy` | boolean | Carried through so anyone reading the reconciliation knows if the OECD figure for this row is a direct measurement or a proxy. |
| `composite_ai_exposure` | float (0–1) | **Calculated field:** simple average of `anthropic_observed_exposure` and `oecd_gap_index_reversed_norm`. The single blended AI-exposure number used in risk classification. |
| `internal_total_reqs` … `internal_req_volume_trend_pct` | numeric | From `Internal_Summary_by_SOC` — company-specific demand, price, and supply trends. |
| `risk_rating` | text (HIGH / MODERATE / LOW) | **Calculated field**, output of `classify_risk()`. See rule logic below. |

**Risk classification rule (as implemented):**
- **HIGH** — composite AI exposure ≥ `AI_EXPOSURE_HIGH_MIN` (0.60) **and** BLS projected growth < `WEAK_GROWTH_THRESHOLD` (8%) **and** internal req volume or margin trend is declining.
- **LOW** — composite AI exposure < `AI_EXPOSURE_LOW_MAX` (0.40), **or** BLS growth ≥ `STRONG_GROWTH_THRESHOLD` (10%) **and** internal demand is growing with flat/positive margin.
- **MODERATE** — everything else (mixed signals).

All four constants are defined once, in `ai_risk_framework.py`'s shared
business-logic threshold section, and reused by `backend/patterns.py`,
`backend/agents.py`'s AI Impact Agent, and
`backend/view2_comparison_matrix.py`'s Risk & Action Matrix — so this
rating, the pattern library, the AI exposure band shown in Insights, and
the Risk & Action Matrix all agree on what "high exposure" or "weak
growth" means.

**Why the AI-exposure bounds are 0.40/0.60, not the original 0.10/0.25:**
`composite_ai_exposure` averages Anthropic's real observed-usage exposure
(rarely above ~0.30-0.35 for any occupation) with OECD's forward-looking
capability-gap score (typically 0.7-0.95 for professional/technical
occupations, and barely differentiating between them). That means a
knowledge-work occupation's composite realistically lands between ~0.30
and ~0.65 — not the full 0-1 range the original 0.10/0.25 cutoffs
assumed. 0.25 sat at the floor of that real range, so nearly every
occupation read "HIGH" off OECD's near-constant ceiling alone, regardless
of how much real Anthropic usage was actually observed. These thresholds
are still **reasoned defaults, not empirically validated cutoffs** — they
should be revisited as more SOCs (with a wider range of real usage and
capability scores) are added.

---

### 3.14 `INSIGHTS_RECOMMENDATIONS` — Narrative Output

- **Grain:** one row per SOC code
- **Source:** derived — computed by `generate_insight()`, templated text built from the `RECONCILIATION` row's values
- **Role in model:** translates the numeric reconciliation into a plain-English narrative and action recommendation, covering five dimensions in a fixed order: AI exposure → external labor market → internal demand → internal price → internal supply → cross-source agreement check → recommendation

| Field | Type | Description |
|---|---|---|
| `soc_code` / `soc_title` | text | Identifiers, carried through for readability. |
| `risk_rating` | text | Same value as in `RECONCILIATION`, repeated here for convenience. |
| `insight_and_recommendation` | text | Full narrative paragraph combining all dimensions above, ending in a concrete recommendation (flag to account managers / continue standard investment / add to watch-list) depending on the risk rating. |

---

### 3.15 `SIGNAL_LEDGER` — Signal Ledger

- **Grain:** one row per (dimension, source, SOC code)
- **Source:** derived — `backend/view1_source_breakdown.py:build_view1()`,
  called by the Signal Intelligence Agent (`PROJECT_SPEC.md`, Section 4.1)
- **Independence note:** this table is **not** derived from
  `RECONCILIATION` and does not read any `output/agents/*.csv` file — it
  calls `ai_risk_framework.load_all_data()` and reads `BLS_OEWS`,
  `BLS_PROJECTIONS`, `ANTHROPIC_JOB_EXPOSURE`, `OECD_CAPABILITY_GAP`, and
  `Internal_Summary_by_SOC` directly, the same way `build_reconciliation()`
  does. The Signal Intelligence Agent runs BEFORE Data Reconciliation in
  the pipeline, so this table never waits on (or depends on) it.
- **Role in model:** a transparent, line-by-line record of every
  underlying signal — surfaced individually (rather than blended into one
  composite number), grouped into four dimensions — External Demand (ED),
  AI Impact, Internal Demand (ID), Exposure — each with a formatted value
  and a plain-English description of what it means. Use this to trace a
  conclusion back to its source.

| Field | Type | Description |
|---|---|---|
| `dimension` | text | One of `External Demand (ED)`, `AI Impact`, `Internal Demand (ID)`, `Exposure` — a fixed 4-value taxonomy, not derived from data. |
| `source` | text | Name of the underlying data source this row's value came from (e.g. "BLS OEWS", "Anthropic Job Exposure"). |
| `soc_code` | text | Join key back to `SOC_REF`. |
| `value` | text | The signal's value, pre-formatted for display (e.g. `"1,687,890"`, `"+15.8%"`, `"0.288"`). |
| `description` | text | One-sentence, plain-English explanation of the value — what it is and what it implies. OECD rows are prefixed `[PROXY — ...]` when `is_proxy` is true. |

---

### 3.16 `RISK_ACTION_MATRIX` and `RISK_ACTION_MATRIX_REFERENCE` — Risk & Action Matrix

- **Grain:** `RISK_ACTION_MATRIX` — one row per SOC code.
  `RISK_ACTION_MATRIX_REFERENCE` — always exactly 8 rows, one per (ED, ID,
  AI) scenario.
- **Source:** derived — `backend/view2_comparison_matrix.py:build_view2()`,
  called by the same Signal Intelligence Agent as the Signal Ledger above
- **Independence note:** same rule as the Signal Ledger above — never
  reads `RECONCILIATION` or any `output/agents/*.csv`; reloads
  `input/*.csv` itself. Uses the shared
  `ai_risk_framework.compute_composite_ai_exposure()` helper (also called
  by `build_reconciliation()`) so the composite AI exposure number is
  always identical between the two, never independently recomputed with a
  different formula.
- **Role in model:** compares market direction, internal demand, and AI
  exposure side by side for each role, and maps that combination to a
  recommended action (Invest, Reposition, Watch-list, Harvest, …) based
  on a consistent, fixed, non-computed decision framework applied across
  every occupation. The Recommendation Agent (Section 4.6 of
  `PROJECT_SPEC.md`) calls this directly so its narrative can cite the
  resolved action by name.

**`RISK_ACTION_MATRIX` fields:**

| Field | Type | Description |
|---|---|---|
| `soc_code` | text | Join key back to `SOC_REF`. |
| `ed_direction` | text (`UP`/`DOWN`) | External demand direction — `UP` if `bls_emp_change_pct >= WEAK_GROWTH_THRESHOLD` (8%), else `DOWN`. Requires clearing the same "faster than average" bar used everywhere else in the app, not just a positive sign — +2-3% growth is economy-wide noise, not a real expansion story. |
| `id_direction` | text (`UP`/`DOWN`) | Internal demand direction — `UP` if `internal_req_volume_trend_pct > INTERNAL_TREND_FLAT_BAND` (10%), else `DOWN`. Same reasoning: this internal metric is a noisier, smaller-sample signal than BLS's national projection, so a single-digit wobble shouldn't flip the read. |
| `ai_level` | text (`LOW`/`MODERATE`/`HIGH`) | Composite AI exposure banded: `<AI_EXPOSURE_LOW_MAX` (0.40) LOW, `>=AI_EXPOSURE_HIGH_MIN` (0.60) HIGH, else MODERATE — same bounds `classify_risk()` uses (Section 3.13). (When joining to the matrix, MODERATE is treated as LOW, not HIGH — see `ai_level_for_matrix_join` in code; the matrix itself only has a LOW/HIGH axis, and a mixed signal shouldn't trigger the same AI-reshaping action as a clearly HIGH reading.) |
| `ed_id_relationship` | text | "Aligned (both growing)" / "Aligned (both declining)" / "Diverging", from `ed_direction` vs. `id_direction`. |
| `ai_ed_relationship` | text | One-line plain-English summary of market direction vs. AI exposure level. |
| `ai_id_relationship` | text | One-line plain-English summary of internal demand direction vs. AI exposure level. |
| `recommended_action` | text | The action resolved from `RISK_ACTION_MATRIX_REFERENCE` for this SOC's (ed, id, ai) combination. |
| `rationale` | text | The matching matrix row's rationale, carried through for readability without a second lookup. |

**`RISK_ACTION_MATRIX_REFERENCE` fields** (`ed`, `id` ∈ `UP`/`DOWN`; `ai` ∈ `LOW`/`HIGH`):

| ed | id | ai | recommended_action |
|---|---|---|---|
| UP | UP | LOW | Invest |
| UP | UP | HIGH | Focus More / Reposition into AI-augmented archetype |
| UP | DOWN | LOW | Execution Gap |
| UP | DOWN | HIGH | Reposition |
| DOWN | UP | LOW | Maintain / Protect Renewals |
| DOWN | UP | HIGH | Reposition (urgent) |
| DOWN | DOWN | LOW | Watch-list |
| DOWN | DOWN | HIGH | Harvest / Step Back |

This table is a **fixed judgment table**, not computed from data — it is
the framework's encoded decision logic, defined once in
`backend/view2_comparison_matrix.py:MATRIX_ROWS` and never derived.

---

### 3.17 `EXTERNAL_SOURCES_REF` and `INTERNAL_SOURCES_REF` — Source Reference Tables

- **Grain:** one row per data source
- **Role in model:** documentation tables, not analytical inputs — a plain-language "what is this and why do we use it" index, matching the format of the catalogue you built manually earlier in this project

| Field | Type | Description |
|---|---|---|
| `name` | text | Name of the data source. |
| `description` | text | One-paragraph explanation of what the source contains, what it measures, and why it's relevant to the AI risk framework. Internal-source rows are explicitly tagged `[DUMMY DATA]` to prevent future confusion with real company data. |

---

## 4. Known limitations (summary, consolidated from notes above)

| # | Limitation | Where it shows up | Mitigation applied |
|---|---|---|---|
| 1 | OECD does not cover 15-1252 directly | `OECD_CAPABILITY_GAP` | Proxy from 15-1251 used, flagged via `is_proxy` |
| 2 | O*NET task / Anthropic task-level data only captured for Software Developers | `ONET_TASKS`, `ANTHROPIC_TASK_PENETRATION` | SOC-level reconciliation unaffected; task-level drill-down limited to one SOC for now |
| 3 | Internal data is entirely synthetic | All `ATS_VMS_REQS`, `CLIENT_BILLING`, `CANDIDATE_PIPELINE` tables | Clearly labeled `[DUMMY DATA]` everywhere it appears |
| 4 | Internal trend calculations use a simple chronological split (first half vs. second half of reqs), not a true time-series model | `Internal_Summary_by_SOC` | Documented as a "trend proxy" in both code comments and this catalogue |
| 5 | Risk-classification thresholds are reasoned defaults, not statistically validated | `RECONCILIATION.risk_rating` | Documented explicitly; recommended for revisiting once real data is in place |
