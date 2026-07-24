"""
View 1 — Source & Value Breakdown (additive feature, on top of the existing
5-agent pipeline).

Hard constraint: `build_view1()` never takes `reconciliation_df` and never
reads `output/agents/*.csv` — it loads and computes everything straight from
`input/*.csv`, the same way `ai_risk_framework.build_reconciliation()` does,
so it works even before the Data Reconciliation Agent has run.
"""

import pandas as pd

import ai_risk_framework

COLUMNS = ["dimension", "source", "soc_code", "value", "description"]


def build_view1():
    """Return one row per (dimension, source, soc_code) — every raw signal
    that feeds the framework, formatted for display, straight from
    input/*.csv. Iterates every SOC in soc_ref.csv, so a SOC added to the
    input files shows up here with no code change."""
    ai_risk_framework.load_all_data()

    soc_ref = ai_risk_framework.SOC_REF
    bls_oews = ai_risk_framework.BLS_OEWS
    bls_projections = ai_risk_framework.BLS_PROJECTIONS
    anthropic = ai_risk_framework.ANTHROPIC_JOB_EXPOSURE
    oecd = ai_risk_framework.OECD_CAPABILITY_GAP
    internal_summary = ai_risk_framework.build_internal_summary()

    rows = []
    for soc in soc_ref["soc_code"]:
        oews_row = bls_oews[bls_oews["soc_code"] == soc].iloc[0]
        proj_row = bls_projections[bls_projections["soc_code"] == soc].iloc[0]
        anthropic_row = anthropic[anthropic["soc_code"] == soc].iloc[0]
        oecd_row = oecd[oecd["soc_code"] == soc].iloc[0]
        internal_row = internal_summary[internal_summary["soc_code"] == soc].iloc[0]

        # --- External Demand (ED) ---
        tot_emp = oews_row["tot_emp"]
        rows.append({
            "dimension": "External Demand (ED)", "source": "BLS OEWS", "soc_code": soc,
            "value": f"{tot_emp:,.0f}",
            "description": (
                f"There are currently {tot_emp:,.0f} people employed "
                f"nationally in this occupation."
            ),
        })

        emp_change_pct = proj_row["emp_change_pct"]
        rows.append({
            "dimension": "External Demand (ED)", "source": "BLS Projections", "soc_code": soc,
            "value": f"{emp_change_pct:+.1f}%",
            "description": (
                f"National employment is projected to "
                f"{'grow' if emp_change_pct > 0 else 'shrink'} "
                f"{abs(emp_change_pct):.1f}% over the 2024-34 projection window."
            ),
        })

        annual_openings_k = proj_row["annual_openings_k"]
        rows.append({
            "dimension": "External Demand (ED)", "source": "BLS Projections", "soc_code": soc,
            "value": f"{annual_openings_k:.1f}k/year",
            "description": (
                f"An average of {annual_openings_k * 1000:,.0f} job openings "
                f"per year are projected nationally, from growth plus "
                f"replacement need."
            ),
        })

        # --- AI Impact ---
        observed_exposure = anthropic_row["observed_exposure"]
        rows.append({
            "dimension": "AI Impact", "source": "Anthropic Job Exposure", "soc_code": soc,
            "value": f"{observed_exposure:.3f}",
            "description": (
                f"{observed_exposure:.0%} of this occupation's task content "
                f"shows up in real, observed Claude usage — this is measured "
                f"usage, not a theoretical estimate."
            ),
        })

        gap_value = oecd_row["gap_index_reversed_norm"]
        is_proxy = bool(oecd_row["is_proxy"])
        oecd_description = (
            f"AI's current capabilities cover an estimated {gap_value:.0%} of "
            f"what this occupation demands, based on OECD's forward-looking "
            f"capability assessment."
        )
        if is_proxy:
            oecd_description = (
                "[PROXY — based on an adjacent occupation, not a direct "
                "measurement] " + oecd_description
            )
        rows.append({
            "dimension": "AI Impact", "source": "OECD Capability Gap", "soc_code": soc,
            "value": f"{gap_value:.2f}",
            "description": oecd_description,
        })

        # --- Internal Demand (ID) ---
        req_trend = internal_row["internal_req_volume_trend_pct"]
        req_dir = "increasing" if req_trend > 0 else "decreasing" if req_trend < 0 else "flat"
        rows.append({
            "dimension": "Internal Demand (ID)", "source": "ATS/VMS Reqs (internal)", "soc_code": soc,
            "value": f"{req_trend:+.1f}%",
            "description": (
                f"Internal requisition volume for this occupation is "
                f"{req_dir} ({req_trend:+.1f}% comparing earlier vs. later "
                f"reqs)."
            ),
        })

        # --- Exposure ---
        margin_trend = internal_row["internal_margin_trend_pct"]
        margin_dir = (
            "expanding" if margin_trend > 0 else "compressing" if margin_trend < 0 else "stable"
        )
        rows.append({
            "dimension": "Exposure", "source": "Client Billing (internal)", "soc_code": soc,
            "value": f"{margin_trend:+.1f}%",
            "description": (
                f"Average margin on placements in this occupation is "
                f"{margin_dir} ({margin_trend:+.1f}%) — compression can "
                f"signal commoditization or client pricing pressure."
            ),
        })

        submittal_trend = internal_row["internal_submittal_trend_pct"]
        submittal_dir = (
            "growing" if submittal_trend > 0 else "shrinking" if submittal_trend < 0 else "stable"
        )
        supply_dir = "improving" if submittal_trend > 0 else "tightening"
        rows.append({
            "dimension": "Exposure", "source": "Candidate Pipeline (internal)", "soc_code": soc,
            "value": f"{submittal_trend:+.1f}%",
            "description": (
                f"Candidate submittal volume per req is {submittal_dir} "
                f"({submittal_trend:+.1f}%), reflecting {supply_dir} talent "
                f"supply."
            ),
        })

    return pd.DataFrame(rows, columns=COLUMNS)
