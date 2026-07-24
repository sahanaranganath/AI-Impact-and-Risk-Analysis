"""
File-backed storage for pipeline results.

`input/` (read by ai_risk_framework.py) and `output/` (written here) are
the actual source of truth for "has the pipeline been run" — not
in-memory state. This means:
  - Dashboard / Insights / Export only ever show data that exists as a
    real file on disk, produced by an actual agent run.
  - Results survive a server restart.
  - Adding a new SOC only requires editing the input/*.csv files —
    nothing here, or in ai_risk_framework.py, hardcodes a SOC list.
"""

from pathlib import Path
import shutil

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
AGENTS_DIR = OUTPUT_DIR / "agents"
REPORTS_DIR = OUTPUT_DIR / "reports"

# Every file an agent run produces under output/agents/. "job-roles" isn't
# one of the 5 named agents, but it's a result table used by the
# Dashboard's drill-down and the Excel export, produced alongside the
# Internal Exposure Agent's own output.
AGENT_FILENAMES = {
    "reconciliation": "data_reconciliation_agent.csv",
    "market-demand": "market_demand_agent.csv",
    "ai-impact": "ai_impact_agent.csv",
    "internal-exposure": "internal_exposure_agent.csv",
    "recommendation": "recommendation_agent.csv",
    "job-roles": "job_roles_by_soc.csv",
    "signal-ledger": "signal_ledger.csv",
    "risk-action-matrix": "risk_action_matrix.csv",
    "risk-action-matrix-reference": "risk_action_matrix_reference.csv",
}

REPORT_FILENAME = "AI_Risk_Framework_SETT.xlsx"
VIEWS_REPORT_FILENAME = "Signal_Intelligence_Report.xlsx"


def ensure_dirs():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def agent_csv_path(slug):
    return AGENTS_DIR / AGENT_FILENAMES[slug]


def write_agent_csv(slug, df):
    ensure_dirs()
    df.to_csv(agent_csv_path(slug), index=False)


def read_agent_csv(slug):
    path = agent_csv_path(slug)
    if not path.exists():
        return None
    return pd.read_csv(path)


def pipeline_has_run():
    """True once every agent (including the job-roles table) has written
    its output file — i.e. a full pipeline run has completed at least
    once since output/ was last cleared."""
    return all(agent_csv_path(slug).exists() for slug in AGENT_FILENAMES)


def report_path():
    return REPORTS_DIR / REPORT_FILENAME


def report_exists():
    return report_path().exists()


def views_report_path():
    return REPORTS_DIR / VIEWS_REPORT_FILENAME


def views_report_exists():
    return views_report_path().exists()


def clear_outputs():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    ensure_dirs()
