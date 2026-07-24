"""
Job-role-level drill-down (PROJECT_SPEC.md, Section 2).

Builds the job-title-level breakdown within one SOC, joining
`ATS_VMS_REQS` / `CLIENT_BILLING` / `CANDIDATE_PIPELINE` directly — no new
data, no reimplementation of the SOC-level reconciliation logic.
"""

import pandas as pd

# Imported as a module (not `from ai_risk_framework import ATS_VMS_REQS, ...`)
# so every lookup below sees whatever `ai_risk_framework.load_all_data()`
# most recently loaded, instead of a stale snapshot copied at import time.
import ai_risk_framework


def build_job_role_breakdown(soc_code):
    """Return one row per job title within `soc_code`, with req count,
    fill status, days-to-fill, bill/pay rate, and margin — pulled straight
    from the existing ATS/VMS, billing, and pipeline tables."""

    ats_vms_reqs = ai_risk_framework.ATS_VMS_REQS
    client_billing = ai_risk_framework.CLIENT_BILLING
    candidate_pipeline = ai_risk_framework.CANDIDATE_PIPELINE

    reqs = ats_vms_reqs[ats_vms_reqs["soc_code"] == soc_code].copy()
    if reqs.empty:
        return pd.DataFrame(columns=[
            "job_title", "req_count", "open_reqs", "filled_reqs",
            "avg_days_to_fill", "avg_bill_rate", "avg_pay_rate", "avg_margin",
            "avg_submittals", "req_ids",
        ])

    merged = reqs.merge(client_billing.drop(columns=["soc_code"]), on="req_id", how="left")
    merged = merged.merge(candidate_pipeline.drop(columns=["soc_code"]), on="req_id", how="left")

    rows = []
    for job_title, grp in merged.groupby("job_title", sort=False):
        rows.append({
            "job_title": job_title,
            "req_count": len(grp),
            "open_reqs": int((grp["fill_status"] == "Open").sum()),
            "filled_reqs": int((grp["fill_status"] == "Filled").sum()),
            "avg_days_to_fill": round(grp["days_to_fill"].mean(skipna=True), 1)
            if grp["days_to_fill"].notna().any() else None,
            "avg_bill_rate": round(grp["bill_rate"].mean(), 1),
            "avg_pay_rate": round(grp["pay_rate"].mean(), 1),
            "avg_margin": round(grp["margin"].mean(), 1),
            "avg_submittals": round(grp["submittals"].mean(), 1),
            "req_ids": ", ".join(grp["req_id"].tolist()),
        })

    # Preserve original open_date ordering (earliest req first per title).
    order = reqs.sort_values("open_date")["job_title"].drop_duplicates().tolist()
    df = pd.DataFrame(rows)
    df["job_title"] = pd.Categorical(df["job_title"], categories=order, ordered=True)
    return df.sort_values("job_title").reset_index(drop=True)


def build_all_job_roles(soc_codes):
    """Concatenate the job-role breakdown for every SOC in `soc_codes`
    into one flat table (soc_code prepended), for the Excel export and
    the output/agents/job_roles_by_soc.csv result file."""
    frames = []
    for soc in soc_codes:
        breakdown = build_job_role_breakdown(soc).copy()
        breakdown.insert(0, "soc_code", soc)
        frames.append(breakdown)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
