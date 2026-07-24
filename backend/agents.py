"""
The 6 agents described in PROJECT_SPEC.md, Section 4: Signal Intelligence
(runs first, independent of reconciliation) plus the original 5-agent
reconciliation → recommendation chain.

Every agent is deterministic and rule-based except the Recommendation
Agent's narrative step, which optionally calls Azure OpenAI GPT-4o and
falls back to `generate_insight()` (ai_risk_framework.py) on any failure.
Nothing here reimplements reconciliation or scoring logic — it all calls
into `ai_risk_framework.py` and `patterns.py` / `job_roles.py`.
"""

import pandas as pd

from ai_risk_framework import (
    build_reconciliation, generate_insight,
    AI_EXPOSURE_LOW_MAX, AI_EXPOSURE_HIGH_MIN,
)
from backend.patterns import classify_pattern
from backend.job_roles import build_job_role_breakdown
from backend.view1_source_breakdown import build_view1
from backend.view2_comparison_matrix import build_view2
from backend import llm

AGENT_NAMES = [
    "Data Reconciliation Agent",
    "Market Demand Agent",
    "AI Impact Agent",
    "Internal Exposure Agent",
    "Recommendation Agent",
]

# The Signal Intelligence Agent doesn't depend on build_reconciliation() at
# all — it loads input/*.csv independently (see backend/view1_source_breakdown.py
# / backend/view2_comparison_matrix.py) and runs BEFORE Data Reconciliation.
# Kept out of AGENT_NAMES (whose indices backend/main.py's
# _persist_agent_output relies on) and referenced by this constant instead.
SIGNAL_INTELLIGENCE_NAME = "Signal Intelligence Agent"

# Presentation metadata for the Agent Run Panel (icon key, one-line
# description, CSV download slug). Kept alongside the agents themselves so
# there's one source of truth instead of duplicating names in the template.
# Signal Intelligence is listed first since it also runs first in the
# pipeline (see run_full_pipeline() below).
AGENT_METADATA = [
    {
        "name": SIGNAL_INTELLIGENCE_NAME,
        "slug": "signal-ledger",
        "icon": "radar",
        "description": (
            "Independently reads all source data and produces a transparent breakdown of every signal alongside an early market, demand, and AI exposure comparison for each role."
        ),
        "extra_downloads": [
            {"slug": "risk-action-matrix", "label": "Download Risk & Action Matrix"},
            {"slug": "risk-action-matrix-reference", "label": "Download matrix reference table"},
        ],
    },
    {
        "name": AGENT_NAMES[0],
        "slug": "reconciliation",
        "icon": "layers",
        "description": (
            "Combines external labor market data with internal hiring, billing, and pipeline data into a single, unified record for each occupation"
        ),
        "extra_downloads": [],
    },
    {
        "name": AGENT_NAMES[1],
        "slug": "market-demand",
        "icon": "trending-up",
        "description": (
            "Scores each occupation's national market growth on a 0 to 100 scale and labels it Expanding, Stable, or Contracting."
        ),
        "extra_downloads": [],
    },
    {
        "name": AGENT_NAMES[2],
        "slug": "ai-impact",
        "icon": "cpu",
        "description": (
            "Combines real AI usage data with capability research into one exposure score, showing whether both sources agree on the level of risk."
        ),
        "extra_downloads": [],
    },
    {
        "name": AGENT_NAMES[3],
        "slug": "internal-exposure",
        "icon": "briefcase",
        "description": (
            "Tracks the company's own hiring volume, time to fill, and pricing trends for each role, down to individual job titles."
        ),
        "extra_downloads": [],
    },
    {
        "name": AGENT_NAMES[4],
        "slug": "recommendation",
        "icon": "lightbulb",
        "description": (
            "Combines every upstream signal with the named pattern "
            "classification into one narrative recommendation per "
            "occupation — via Azure OpenAI GPT-4o when configured, "
            "otherwise a deterministic rule-based template."
        ),
        "extra_downloads": [],
    },
]


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _exposure_band(x):
    if x >= AI_EXPOSURE_HIGH_MIN:
        return "High"
    if x < AI_EXPOSURE_LOW_MAX:
        return "Low"
    return "Moderate"


# ---------------------------------------------------------------------
# 4.1 Signal Intelligence Agent — runs FIRST, ahead of and independent of
# Data Reconciliation. Produces the Signal Ledger (build_view1()) and the
# Risk & Action Matrix (build_view2()); neither takes reconciliation_df.
# ---------------------------------------------------------------------

def run_signal_intelligence_agent():
    """Reads input/*.csv directly — before anything is merged or averaged —
    and produces the Signal Ledger (every underlying signal, one row per
    source) and the Risk & Action Matrix (per-SOC comparison + the fixed
    8-row reference matrix). No LLM, ever."""
    signal_ledger_df = build_view1()
    risk_matrix_comparison_df, risk_matrix_reference_df = build_view2()
    return {
        "output_summary": (
            f"Built the Signal Ledger ({len(signal_ledger_df)} source-level "
            f"rows) and resolved the Risk & Action Matrix for "
            f"{len(risk_matrix_comparison_df)} SOCs — directly from "
            f"input/*.csv, ahead of and independent of the Data "
            f"Reconciliation Agent."
        ),
        "signal_ledger": signal_ledger_df,
        "risk_matrix_comparison": risk_matrix_comparison_df,
        "risk_matrix_reference": risk_matrix_reference_df,
    }


# ---------------------------------------------------------------------
# 4.2 Data Reconciliation Agent
# ---------------------------------------------------------------------

def run_data_reconciliation_agent():
    """Calls build_reconciliation() directly. No LLM involved, ever."""
    df = build_reconciliation()
    return {
        "output_summary": (
            f"Reconciled external, AI-impact, and internal data for "
            f"{len(df)} SOC codes: "
            + ", ".join(f"{r.soc_code} ({r.soc_title})" for r in df.itertuples())
            + "."
        ),
        "reconciliation": df,
    }


# ---------------------------------------------------------------------
# 4.3 Market Demand Agent
# ---------------------------------------------------------------------

def run_market_demand_agent(reconciliation_df):
    results = {}
    for row in reconciliation_df.itertuples():
        pct = row.bls_emp_change_pct
        index = round(_clip(50 + pct * 3), 1)
        direction = "Expanding" if pct >= 10 else "Contracting" if pct < 0 else "Stable"
        narrative = (
            f"BLS projects national employment for {row.soc_title} to be "
            f"{direction.lower()} at {pct:+.1f}% over 2024-34, with "
            f"{row.bls_annual_openings_k:.1f}k average annual openings. "
            f"Demand Growth Index: {index:.0f}/100."
        )
        results[row.soc_code] = {
            "demand_growth_index": index,
            "direction": direction,
            "narrative": narrative,
        }
    return {
        "output_summary": (
            "Computed Demand Growth Index and direction for "
            f"{len(results)} SOCs from BLS projections."
        ),
        "results": results,
    }


# ---------------------------------------------------------------------
# 4.4 AI Impact Agent
# ---------------------------------------------------------------------

def run_ai_impact_agent(reconciliation_df):
    results = {}
    for row in reconciliation_df.itertuples():
        composite = row.composite_ai_exposure
        band = _exposure_band(composite)
        anthropic_band = _exposure_band(row.anthropic_observed_exposure)
        oecd_band = _exposure_band(row.oecd_gap_index_reversed_norm)

        if anthropic_band == oecd_band:
            agreement_note = (
                f"Anthropic (usage-based) and OECD (capability-based) both "
                f"indicate {anthropic_band} exposure — sources agree."
            )
        else:
            agreement_note = (
                f"Sources diverge: Anthropic (usage-based) indicates "
                f"{anthropic_band} exposure while OECD (capability-based) "
                f"indicates {oecd_band} exposure."
            )
        if row.oecd_is_proxy:
            agreement_note += (
                " Caveat: this SOC's OECD score is a PROXY (borrowed from "
                "an adjacent occupation), not a direct measurement."
            )

        narrative = (
            f"{row.soc_title}: composite AI exposure {composite:.2f} "
            f"({band}). Anthropic observed usage-based exposure is "
            f"{row.anthropic_observed_exposure:.2f}; OECD capability-gap "
            f"exposure is {row.oecd_gap_index_reversed_norm:.2f}. "
            f"{agreement_note}"
        )
        results[row.soc_code] = {
            "composite_ai_exposure": round(composite, 4),
            "exposure_band": band,
            "agreement_note": agreement_note,
            "narrative": narrative,
        }
    return {
        "output_summary": (
            "Computed composite AI exposure, exposure band, and "
            f"source-agreement note for {len(results)} SOCs."
        ),
        "results": results,
    }


# ---------------------------------------------------------------------
# 4.5 Internal Exposure Agent
# ---------------------------------------------------------------------

def run_internal_exposure_agent(reconciliation_df):
    results = {}
    for row in reconciliation_df.itertuples():
        trend = row.internal_req_volume_trend_pct
        index = round(_clip(50 + trend), 1)
        direction = "Growing" if trend > 0 else "Declining" if trend < 0 else "Stable"
        job_roles = build_job_role_breakdown(row.soc_code)
        narrative = (
            f"Internal req volume for {row.soc_title} is {direction.lower()} "
            f"({trend:+.1f}% early-vs-late period); average time-to-fill is "
            f"{row.internal_avg_days_to_fill:.0f} days across "
            f"{row.internal_total_reqs} reqs ({row.internal_open_reqs} still "
            f"open) spanning {len(job_roles)} distinct job titles. Internal "
            f"Demand Index: {index:.0f}/100."
        )
        results[row.soc_code] = {
            "internal_demand_index": index,
            "direction": direction,
            "narrative": narrative,
            "job_roles": job_roles,
        }
    return {
        "output_summary": (
            "Computed Internal Demand Index and job-role-level breakdown "
            f"for {len(results)} SOCs."
        ),
        "results": results,
    }


# ---------------------------------------------------------------------
# 4.6 Recommendation Agent (pattern + narrative synthesis)
# ---------------------------------------------------------------------

def run_recommendation_agent(reconciliation_df, market_results, ai_results, internal_results):
    results = {}
    llm_calls_attempted = 0
    llm_calls_succeeded = 0

    # The Risk & Action Matrix comparison table is independent of
    # reconciliation_df (it re-reads input/*.csv itself — see
    # backend/view2_comparison_matrix.py), so it's simply called again here
    # rather than threaded through the pipeline. Its `recommended_action`
    # must show up explicitly in this agent's narrative, not just the risk
    # rating/pattern in isolation.
    view2_comparison_df, _ = build_view2()
    view2_by_soc = {row.soc_code: row._asdict() for row in view2_comparison_df.itertuples()}

    for row in reconciliation_df.itertuples():
        row_dict = row._asdict()
        pattern = classify_pattern(row_dict)
        risk_rating = row.risk_rating
        view2_row = view2_by_soc.get(row.soc_code, {})

        structured_payload = {
            "soc_code": row.soc_code,
            "soc_title": row.soc_title,
            "risk_rating": risk_rating,
            "pattern_name": pattern["pattern_name"],
            "pattern_meaning": pattern["meaning"],
            "pattern_recommended_action": pattern["recommended_action"],
            "pattern_assumptions": pattern["assumptions"],
            "market_demand": market_results[row.soc_code],
            "ai_impact": ai_results[row.soc_code],
            "internal_exposure": {
                k: v for k, v in internal_results[row.soc_code].items()
                if k != "job_roles"
            },
            "risk_action_matrix": {
                "ed_direction": view2_row.get("ed_direction"),
                "id_direction": view2_row.get("id_direction"),
                "ai_level": view2_row.get("ai_level"),
                "recommended_action": view2_row.get("recommended_action"),
                "rationale": view2_row.get("rationale"),
            },
        }

        used_llm = False
        narrative = None
        llm_error = None
        if llm.is_configured():
            llm_calls_attempted += 1
            try:
                narrative = llm.generate_recommendation_narrative(structured_payload)
                used_llm = True
                llm_calls_succeeded += 1
            except Exception as exc:  # noqa: BLE001 - any LLM failure falls back
                llm_error = str(exc)

        if narrative is None:
            narrative = (
                generate_insight(row_dict) + " PATTERN: " + pattern["pattern_name"]
                + " — " + pattern["meaning"] + " " + pattern["recommended_action"]
                + " RISK & ACTION MATRIX: external demand is "
                + f"{view2_row.get('ed_direction')}, internal demand is "
                + f"{view2_row.get('id_direction')}, and composite AI exposure is "
                + f"{view2_row.get('ai_level')} — this resolves to "
                + f"'{view2_row.get('recommended_action')}': "
                + f"{view2_row.get('rationale')}"
            )

        results[row.soc_code] = {
            "risk_rating": risk_rating,
            "pattern": pattern,
            "narrative": narrative,
            "used_llm": used_llm,
            "llm_error": llm_error,
        }

    if not llm.is_configured():
        summary = (
            "Running in rule-based mode (no LLM configured) — generated "
            f"templated narratives for {len(results)} SOCs."
        )
    else:
        summary = (
            f"Generated narratives for {len(results)} SOCs "
            f"({llm_calls_succeeded}/{llm_calls_attempted} via Azure OpenAI "
            "GPT-4o, remainder rule-based fallback)."
        )

    return {"output_summary": summary, "results": results}


# ---------------------------------------------------------------------
# Flat DataFrame representations of each agent's output — the one place
# that defines what gets written to output/agents/*.csv (and what a CSV
# download contains). One row per SOC in every case.
# ---------------------------------------------------------------------

def reconciliation_to_frame(reconciliation_df):
    return reconciliation_df


def market_demand_to_frame(results):
    return pd.DataFrame([{"soc_code": soc, **r} for soc, r in results.items()])


def ai_impact_to_frame(results):
    return pd.DataFrame([{"soc_code": soc, **r} for soc, r in results.items()])


def internal_exposure_to_frame(results):
    rows = [
        {
            "soc_code": soc,
            "internal_demand_index": r["internal_demand_index"],
            "direction": r["direction"],
            "narrative": r["narrative"],
        }
        for soc, r in results.items()
    ]
    return pd.DataFrame(rows)


def recommendation_to_frame(results):
    rows = [
        {
            "soc_code": soc,
            "risk_rating": r["risk_rating"],
            "pattern_name": r["pattern"]["pattern_name"],
            "pattern_meaning": r["pattern"]["meaning"],
            "recommended_action": r["pattern"]["recommended_action"],
            "narrative": r["narrative"],
            "used_llm": r["used_llm"],
        }
        for soc, r in results.items()
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# Full pipeline (used by the SSE endpoint, and reusable for plain calls)
# ---------------------------------------------------------------------

def run_full_pipeline():
    """Run all 5 agents in sequence and return every intermediate result.

    Yields (agent_name, status, output_summary, payload) tuples so callers
    (e.g. the SSE endpoint) can stream progress; `payload` is None for
    'running' events and the agent's result dict for 'done' events.
    """
    # Signal Intelligence runs FIRST — it doesn't depend on the Data
    # Reconciliation Agent's output at all (it re-reads input/*.csv itself),
    # so it always reflects the source data as-is, ahead of any blending.
    yield (SIGNAL_INTELLIGENCE_NAME, "running", None, None)
    signal_out = run_signal_intelligence_agent()
    yield (SIGNAL_INTELLIGENCE_NAME, "done", signal_out["output_summary"], signal_out)

    yield (AGENT_NAMES[0], "running", None, None)
    recon_out = run_data_reconciliation_agent()
    df = recon_out["reconciliation"]
    yield (AGENT_NAMES[0], "done", recon_out["output_summary"], recon_out)

    yield (AGENT_NAMES[1], "running", None, None)
    market_out = run_market_demand_agent(df)
    yield (AGENT_NAMES[1], "done", market_out["output_summary"], market_out)

    yield (AGENT_NAMES[2], "running", None, None)
    ai_out = run_ai_impact_agent(df)
    yield (AGENT_NAMES[2], "done", ai_out["output_summary"], ai_out)

    yield (AGENT_NAMES[3], "running", None, None)
    internal_out = run_internal_exposure_agent(df)
    yield (AGENT_NAMES[3], "done", internal_out["output_summary"], internal_out)

    yield (AGENT_NAMES[4], "running", None, None)
    rec_out = run_recommendation_agent(
        df, market_out["results"], ai_out["results"], internal_out["results"]
    )
    yield (AGENT_NAMES[4], "done", rec_out["output_summary"], rec_out)
