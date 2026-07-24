"""
Small server-side helpers that turn numbers into inline CSS (bar heights,
heatmap cell colors) so the dashboard's charts are plain HTML/CSS — no
charting library, no client-side JS required to render them.
"""


def _lerp(a, b, t):
    return a + (b - a) * t


def heatmap_color(value, vmin=0.0, vmax=100.0):
    """Deep teal (low) -> amber (mid) -> deep red (high), as an rgb()
    string — a muted, corporate-BI-style diverging scale rather than
    primary green/amber/red."""
    t = 0.0 if vmax == vmin else max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
    stops = [
        (0.0, (15, 118, 110)),   # teal-700
        (0.5, (217, 119, 6)),    # amber-600
        (1.0, (185, 28, 28)),    # red-700
    ]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t0 <= t <= t1:
            local_t = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            r = round(_lerp(c0[0], c1[0], local_t))
            g = round(_lerp(c0[1], c1[1], local_t))
            b = round(_lerp(c0[2], c1[2], local_t))
            return f"rgb({r}, {g}, {b})"
    return "rgb(148, 163, 184)"


UP_COLOR = "#0f766e"     # teal-700 — growth / expansion
DOWN_COLOR = "#b91c1c"   # red-700 — decline / compression
ANTHROPIC_COLOR = "#4f46e5"  # indigo-600
OECD_COLOR = "#0891b2"       # cyan-600


def signed_bar(value, vmin=-20.0, vmax=20.0):
    """Return {height_pct, direction, color} for a baseline-centered CSS
    bar representing a signed percentage value clamped to [vmin, vmax]."""
    clamped = max(vmin, min(vmax, value))
    half_range = max(abs(vmin), abs(vmax))
    height_pct = round(abs(clamped) / half_range * 100, 1) if half_range else 0.0
    direction = "up" if clamped >= 0 else "down"
    color = UP_COLOR if clamped >= 0 else DOWN_COLOR
    return {"height_pct": height_pct, "direction": direction, "color": color, "value": value}


def unsigned_bar(value, vmax=1.0, color="#0b3554"):
    """Return {width_pct, color} for a simple 0..vmax CSS bar."""
    width_pct = round(max(0.0, min(vmax, value)) / vmax * 100, 1) if vmax else 0.0
    return {"width_pct": width_pct, "color": color, "value": value}


RISK_BADGE_CLASS = {"HIGH": "badge-high", "MODERATE": "badge-moderate", "LOW": "badge-low"}

PATTERN_BADGE_CLASS = {
    "Structural Displacement Risk": "badge-high",
    "AI-Augmented Recomposition": "badge-moderate",
    "External Demand Down + Internal Revenue Down": "badge-high",
    "External Demand Down + Internal Revenue Stable": "badge-moderate",
    "Execution Gap": "badge-moderate",
    "Invest and Scale": "badge-low",
    "Mixed Signal / No Dominant Pattern": "badge-neutral",
}
