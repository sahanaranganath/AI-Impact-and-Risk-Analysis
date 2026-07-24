"""
Pattern-interpretation library (PROJECT_SPEC.md, Section 3).

Sits on top of the existing `build_reconciliation()` output and classifies
each SOC into a named pattern with a plain-English meaning and a recommended
leadership action, in addition to the numeric HIGH/MODERATE/LOW risk rating
already produced by `classify_risk()`.

Threshold choices
------------------
All numeric cutoffs below are imported from `ai_risk_framework.py`'s
shared business-logic threshold section (not redefined here), so this
library, `classify_risk()`, the AI Impact Agent, and the Risk & Action
Matrix all agree on what "weak growth" or "high AI exposure" means:
- "external demand low/declining" / "strong" reuse the exact thresholds
  already used by `classify_risk()`: weak growth is
  `bls_emp_change_pct < WEAK_GROWTH_THRESHOLD` (8), strong growth is
  `>= STRONG_GROWTH_THRESHOLD` (10). Values in the 8-9.99 gap between the
  two don't count as clearly "weak" or "strong" and fall through to the
  catch-all pattern below (see `_DEFAULT_PATTERN`).
- "high AI exposure" reuses classify_risk()'s high-exposure cutoff,
  `composite_ai_exposure >= AI_EXPOSURE_HIGH_MIN` (0.60) — see
  `ai_risk_framework.py` for why this is calibrated to the composite
  metric's real achievable range rather than a generic 0-1 scale.
- The two AI-exposure patterns (Reposition / Structural Displacement) use a
  wider band for "sharply declining" vs. "roughly flat/stable" than the
  plain `< 0` / `>= 0` split used for the market 2x2, since the spec
  describes them in qualitative terms ("sharply declining", "roughly
  flat/stable") rather than a hard zero threshold:
    - sharply declining:  internal_req_volume_trend_pct <= INTERNAL_SHARP_DECLINE_MAX (-10)
    - flat/stable:        -INTERNAL_TREND_FLAT_BAND < internal_req_volume_trend_pct < INTERNAL_TREND_FLAT_BAND (+/-10)

Evaluation order
----------------
This is an AI risk framework, so the two AI-exposure-driven patterns
(Structural Displacement, AI-Augmented Recomposition) are checked BEFORE the
generic external/internal market 2x2 (patterns 1-4) — they are the more
specific, more actionable signal when AI exposure is high, and structural
displacement (the most severe pattern) is checked first among the two.
Only when neither AI-exposure pattern fires do we fall through to the
external-vs-internal demand quadrant.
"""

from ai_risk_framework import (
    AI_EXPOSURE_HIGH_MIN as HIGH_EXPOSURE_THRESHOLD,
    WEAK_GROWTH_THRESHOLD,
    STRONG_GROWTH_THRESHOLD,
    INTERNAL_SHARP_DECLINE_MAX as SHARP_DECLINE_THRESHOLD,
    INTERNAL_TREND_FLAT_BAND as STABLE_BAND,
)

STRUCTURAL_DISPLACEMENT = "Structural Displacement Risk"
AI_AUGMENTED_RECOMPOSITION = "AI-Augmented Recomposition"
EXTERNAL_DOWN_INTERNAL_DOWN = "External Demand Down + Internal Revenue Down"
EXTERNAL_DOWN_INTERNAL_STABLE = "External Demand Down + Internal Revenue Stable"
EXECUTION_GAP = "Execution Gap"
INVEST_AND_SCALE = "Invest and Scale"
MIXED_SIGNAL = "Mixed Signal / No Dominant Pattern"


def classify_pattern(row, low_adjacency=None):
    """
    Classify one reconciliation row (a dict-like / pandas Series with the
    fields produced by `build_reconciliation()`) into a named pattern.

    Parameters
    ----------
    row : mapping
        Must provide `bls_emp_change_pct`, `internal_req_volume_trend_pct`,
        `internal_margin_trend_pct`, `composite_ai_exposure`.
    low_adjacency : bool or None
        Whether few/no adjacent, lower-exposure roles exist nearby in the
        SOC hierarchy for this occupation. ASSUMPTION: this reconciliation
        only covers 3 SOCs and no sibling-SOC / adjacency data is modeled
        yet, so this defaults to True (i.e. "assume low adjacency, flag as
        unimplemented") per the spec's explicit instruction, until real
        adjacency data is added. Callers may override once that data
        exists.

    Returns
    -------
    dict with keys: pattern_name, meaning, recommended_action, assumptions
    (a list of strings — empty unless an unimplemented input was assumed).
    """
    if low_adjacency is None:
        low_adjacency = True
        adjacency_assumed = True
    else:
        adjacency_assumed = False

    ai_exposure = row["composite_ai_exposure"]
    bls_growth = row["bls_emp_change_pct"]
    req_trend = row["internal_req_volume_trend_pct"]
    margin_trend = row["internal_margin_trend_pct"]

    high_exposure = ai_exposure >= HIGH_EXPOSURE_THRESHOLD
    weak_growth = bls_growth < WEAK_GROWTH_THRESHOLD
    strong_growth = bls_growth >= STRONG_GROWTH_THRESHOLD
    sharply_declining = req_trend <= SHARP_DECLINE_THRESHOLD
    stable_demand = -STABLE_BAND < req_trend < STABLE_BAND
    margin_declining = margin_trend < 0
    req_declining = req_trend < 0
    req_growing = req_trend > 0

    if high_exposure and sharply_declining and low_adjacency:
        assumptions = (
            ["low_adjacency defaulted to True — no sibling-SOC adjacency "
             "data is modeled in this build; treat this pattern trigger as "
             "a documented assumption, not a verified structural finding."]
            if adjacency_assumed else []
        )
        return {
            "pattern_name": STRUCTURAL_DISPLACEMENT,
            "meaning": (
                "Structural displacement risk — the combination of high AI "
                "exposure and shrinking internal demand, with nowhere "
                "adjacent to redeploy people, is the most serious pattern "
                "in this library."
            ),
            "recommended_action": "Step Back or Harvest with a client transition plan.",
            "assumptions": assumptions,
        }

    if high_exposure and stable_demand:
        return {
            "pattern_name": AI_AUGMENTED_RECOMPOSITION,
            "meaning": (
                "The role is being recomposed (tasks changing, augmented by "
                "AI) rather than eliminated outright."
            ),
            "recommended_action": (
                "Reposition into an AI-augmented archetype — retrain/"
                "rebrand the role rather than reduce headcount."
            ),
            "assumptions": [],
        }

    if weak_growth and margin_declining:
        return {
            "pattern_name": EXTERNAL_DOWN_INTERNAL_DOWN,
            "meaning": (
                "Market decline is flowing into the business — not just a "
                "national trend, it's showing up in our own book."
            ),
            "recommended_action": "High risk: prioritize Harvest, Reposition, or Step Back.",
            "assumptions": [],
        }

    if weak_growth and not margin_declining:
        return {
            "pattern_name": EXTERNAL_DOWN_INTERNAL_STABLE,
            "meaning": (
                "Current account demand may be protected for now, but "
                "future pipeline could weaken as the broader market "
                "softens."
            ),
            "recommended_action": (
                "Watch-list: protect renewals and reposition proactively "
                "before erosion sets in."
            ),
            "assumptions": [],
        }

    if strong_growth and req_declining:
        return {
            "pattern_name": EXECUTION_GAP,
            "meaning": (
                "The market is growing, but the firm isn't capturing its "
                "share of that growth."
            ),
            "recommended_action": (
                "Investigate sales, sourcing, pricing, or capability "
                "issues — this isn't a market problem, it's an internal "
                "one."
            ),
            "assumptions": [],
        }

    if strong_growth and req_growing:
        return {
            "pattern_name": INVEST_AND_SCALE,
            "meaning": "Both the market and the internal book support growth.",
            "recommended_action": "Invest and scale.",
            "assumptions": [],
        }

    return {
        "pattern_name": MIXED_SIGNAL,
        "meaning": (
            "External growth is moderate (neither clearly weak nor clearly "
            "strong by our thresholds) and/or internal demand and AI "
            "exposure signals don't line up with any named pattern above."
        ),
        "recommended_action": (
            "No dominant pattern — treat as a watch-list item and re-check "
            "next cycle."
        ),
        "assumptions": [],
    }
