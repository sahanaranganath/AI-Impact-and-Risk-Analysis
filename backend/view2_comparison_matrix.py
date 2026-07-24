"""
View 2 — Comparison + Risk & Mitigation Matrix (additive feature, on top of
the existing 5-agent pipeline).

Hard constraint: `build_view2()` never takes `reconciliation_df` and never
reads `output/agents/*.csv` — it loads and computes everything straight from
input/*.csv (via `ai_risk_framework.load_all_data()` and the shared
`compute_composite_ai_exposure()` helper), so it works even before the Data
Reconciliation Agent has run and always agrees with it on the composite
exposure number.

Every LOW/MODERATE/HIGH and UP/DOWN cutoff below is imported from
`ai_risk_framework.py`'s shared business-logic threshold section — the
same numbers `classify_risk()` and `backend/patterns.py` use — so "HIGH AI
exposure" or "the market is growing" mean the same thing here as they do
in Insights & Recommendations. See that module for the business reasoning
behind each cutoff.
"""

import pandas as pd

import ai_risk_framework

# The fixed 8-scenario reference matrix. Never derived from data — this is
# the framework's judgment table, keyed on (ed, id, ai) direction/level.
MATRIX_ROWS = [
    {"ed": "UP", "id": "UP", "ai": "LOW",
     "recommended_action": "Invest",
     "rationale": "Market and internal book both growing, low AI disruption risk"},
    {"ed": "UP", "id": "UP", "ai": "HIGH",
     "recommended_action": "Focus More / Reposition into AI-augmented archetype",
     "rationale": "Growth is real, but role is being reshaped by AI — capture growth while adapting the role"},
    {"ed": "UP", "id": "DOWN", "ai": "LOW",
     "recommended_action": "Execution Gap",
     "rationale": "Market's growing but we're not capturing share — a sales/sourcing problem, not a market or AI problem"},
    {"ed": "UP", "id": "DOWN", "ai": "HIGH",
     "recommended_action": "Reposition",
     "rationale": "Market growing, but our book shrinking and AI-exposed — investigate whether AI is displacing our roles faster than the market overall"},
    {"ed": "DOWN", "id": "UP", "ai": "LOW",
     "recommended_action": "Maintain / Protect Renewals",
     "rationale": "Market softening but our book still growing — watch closely, don't over-invest"},
    {"ed": "DOWN", "id": "UP", "ai": "HIGH",
     "recommended_action": "Reposition (urgent)",
     "rationale": "Book growing now, but sitting on a declining, AI-exposed market — likely to reverse; act before it does"},
    {"ed": "DOWN", "id": "DOWN", "ai": "LOW",
     "recommended_action": "Watch-list",
     "rationale": "Broad decline, but not AI-driven — likely a general market/execution issue"},
    {"ed": "DOWN", "id": "DOWN", "ai": "HIGH",
     "recommended_action": "Harvest / Step Back",
     "rationale": "Everything points the same direction — the clearest, highest-confidence risk pattern"},
]

MATRIX_COLUMNS = ["ed", "id", "ai", "recommended_action", "rationale"]


def _matrix_df():
    return pd.DataFrame(MATRIX_ROWS, columns=MATRIX_COLUMNS)


def _lookup_matrix(ed_direction, id_direction, ai_level_for_matrix_join):
    for row in MATRIX_ROWS:
        if (row["ed"], row["id"], row["ai"]) == (ed_direction, id_direction, ai_level_for_matrix_join):
            return row["recommended_action"], row["rationale"]
    raise ValueError(
        f"No matrix entry for (ed={ed_direction}, id={id_direction}, "
        f"ai={ai_level_for_matrix_join})"
    )


def build_view2():
    """Return (comparison_df, matrix_df). `comparison_df` has one row per
    SOC; `matrix_df` is always the full, fixed 8-row reference table."""
    ai_risk_framework.load_all_data()

    soc_ref = ai_risk_framework.SOC_REF
    bls_projections = ai_risk_framework.BLS_PROJECTIONS
    anthropic = ai_risk_framework.ANTHROPIC_JOB_EXPOSURE
    oecd = ai_risk_framework.OECD_CAPABILITY_GAP
    internal_summary = ai_risk_framework.build_internal_summary()
    composite = ai_risk_framework.compute_composite_ai_exposure(anthropic, oecd)

    rows = []
    for soc in soc_ref["soc_code"]:
        emp_change_pct = bls_projections.loc[bls_projections["soc_code"] == soc, "emp_change_pct"].iloc[0]
        req_trend = internal_summary.loc[
            internal_summary["soc_code"] == soc, "internal_req_volume_trend_pct"
        ].iloc[0]
        composite_ai_exposure = composite.loc[composite["soc_code"] == soc, "composite_ai_exposure"].iloc[0]

        # UP requires clearing the same "faster/stronger than baseline noise"
        # bar used everywhere else in the app (ai_risk_framework.py), not
        # just a positive sign — a role at +2% growth or a +3% internal
        # wobble isn't a real "UP" story, it's economy-wide/sample noise.
        ed_direction = "UP" if emp_change_pct >= ai_risk_framework.WEAK_GROWTH_THRESHOLD else "DOWN"
        id_direction = "UP" if req_trend > ai_risk_framework.INTERNAL_TREND_FLAT_BAND else "DOWN"

        if composite_ai_exposure < ai_risk_framework.AI_EXPOSURE_LOW_MAX:
            ai_level = "LOW"
        elif composite_ai_exposure >= ai_risk_framework.AI_EXPOSURE_HIGH_MIN:
            ai_level = "HIGH"
        else:
            ai_level = "MODERATE"
        # The matrix's AI axis is strictly LOW/HIGH (no MODERATE row exists),
        # so MODERATE must resolve to one side. It folds to LOW, not HIGH:
        # a "mixed signal" reading shouldn't trigger the same AI-reshaping
        # action as a clearly HIGH one — only a clearly HIGH exposure should.
        ai_level_for_matrix_join = "HIGH" if ai_level == "HIGH" else "LOW"

        if ed_direction == "UP" and id_direction == "UP":
            ed_id_relationship = "Aligned (both growing)"
        elif ed_direction == "DOWN" and id_direction == "DOWN":
            ed_id_relationship = "Aligned (both declining)"
        else:
            ed_id_relationship = "Diverging"

        ai_ed_relationship = (
            f"{'Growing' if ed_direction == 'UP' else 'Weak'} market, "
            f"{ai_level.lower()} AI exposure"
        )
        ai_id_relationship = (
            f"Internal demand {'growing' if id_direction == 'UP' else 'declining'} "
            f"{'despite' if ai_level == 'HIGH' else 'alongside'} {ai_level.lower()} AI exposure"
        )

        recommended_action, rationale = _lookup_matrix(
            ed_direction, id_direction, ai_level_for_matrix_join
        )

        rows.append({
            "soc_code": soc,
            "ed_direction": ed_direction,
            "id_direction": id_direction,
            "ai_level": ai_level,
            "ed_id_relationship": ed_id_relationship,
            "ai_ed_relationship": ai_ed_relationship,
            "ai_id_relationship": ai_id_relationship,
            "recommended_action": recommended_action,
            "rationale": rationale,
        })

    comparison_df = pd.DataFrame(rows, columns=[
        "soc_code", "ed_direction", "id_direction", "ai_level",
        "ed_id_relationship", "ai_ed_relationship", "ai_id_relationship",
        "recommended_action", "rationale",
    ])
    return comparison_df, _matrix_df()
