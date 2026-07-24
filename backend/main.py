"""
FastAPI backend — REST + SSE API (PROJECT_SPEC.md, Section 5) plus the
server-rendered HTML frontend (Jinja2 templates + plain CSS, a handful of
vanilla-JS lines only where a static page truly can't do the job: consuming
the pipeline's SSE stream live). One process, one service — no separate
frontend framework.

Data flow: ai_risk_framework.py reads its tables from input/*.csv.
Running the pipeline (Agent Run Panel) computes all 6 agents (Signal
Intelligence runs first, independent of reconciliation) and writes each
one's result table to output/agents/*.csv, plus both Excel reports to
output/reports/. Dashboard, Insights & Recommendations, and Export never
compute anything themselves — they only read those output files, and show
an empty state if the pipeline hasn't produced them yet.
"""

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import StreamingResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import ai_risk_framework  # imported as a module, not `from ... import SOC_REF` —
# SOC_REF is reassigned by load_all_data() on every pipeline run, and a
# bare `from` import would freeze a stale copy from server startup.
from backend import agents
from backend import charting
from backend import storage
from backend.patterns import classify_pattern
from backend.job_roles import build_all_job_roles
from backend.annotations import load_annotations, get_annotation, save_annotation
from backend.excel_export import build_extended_workbook, build_views_workbook
from backend import llm

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="AI Risk Framework")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

PIPELINE_NOT_RUN_DETAIL = "Pipeline has not been run yet. Run it from the Agent Run Panel first."


def _df_records(df):
    """Convert a DataFrame to JSON-safe records (handles numpy dtypes/NaN
    correctly via pandas' own JSON encoder, unlike a plain .to_dict())."""
    return json.loads(df.to_json(orient="records"))


# =====================================================================
# Persisting agent output to output/agents/*.csv and the final report
# to output/reports/ — the single place that turns a completed agent's
# in-memory result into the file that everything else reads back.
# =====================================================================

def _persist_agent_output(name, payload):
    if name == agents.SIGNAL_INTELLIGENCE_NAME:
        storage.write_agent_csv("signal-ledger", payload["signal_ledger"])
        storage.write_agent_csv("risk-action-matrix", payload["risk_matrix_comparison"])
        storage.write_agent_csv("risk-action-matrix-reference", payload["risk_matrix_reference"])
    elif name == agents.AGENT_NAMES[0]:
        storage.write_agent_csv("reconciliation", agents.reconciliation_to_frame(payload["reconciliation"]))
    elif name == agents.AGENT_NAMES[1]:
        storage.write_agent_csv("market-demand", agents.market_demand_to_frame(payload["results"]))
    elif name == agents.AGENT_NAMES[2]:
        storage.write_agent_csv("ai-impact", agents.ai_impact_to_frame(payload["results"]))
    elif name == agents.AGENT_NAMES[3]:
        storage.write_agent_csv("internal-exposure", agents.internal_exposure_to_frame(payload["results"]))
        storage.write_agent_csv("job-roles", build_all_job_roles(list(payload["results"].keys())))
    elif name == agents.AGENT_NAMES[4]:
        storage.write_agent_csv("recommendation", agents.recommendation_to_frame(payload["results"]))
        build_extended_workbook(str(storage.report_path()))
        build_views_workbook(str(storage.views_report_path()))


# =====================================================================
# Reading pipeline results back from output/agents/*.csv — reconstructs
# the same shape the agents originally returned, entirely from disk.
# Returns None if the pipeline hasn't produced output yet.
# =====================================================================

def _load_pipeline_data():
    if not storage.pipeline_has_run():
        return None

    reconciliation_df = storage.read_agent_csv("reconciliation")
    market_df = storage.read_agent_csv("market-demand")
    ai_df = storage.read_agent_csv("ai-impact")
    internal_df = storage.read_agent_csv("internal-exposure")
    rec_df = storage.read_agent_csv("recommendation")
    job_roles_df = storage.read_agent_csv("job-roles")
    signal_ledger_df = storage.read_agent_csv("signal-ledger")
    risk_matrix_comparison_df = storage.read_agent_csv("risk-action-matrix")
    risk_matrix_reference_df = storage.read_agent_csv("risk-action-matrix-reference")

    market = {
        row["soc_code"]: {
            "demand_growth_index": row["demand_growth_index"],
            "direction": row["direction"],
            "narrative": row["narrative"],
        }
        for _, row in market_df.iterrows()
    }
    ai_impact = {
        row["soc_code"]: {
            "composite_ai_exposure": row["composite_ai_exposure"],
            "exposure_band": row["exposure_band"],
            "agreement_note": row["agreement_note"],
            "narrative": row["narrative"],
        }
        for _, row in ai_df.iterrows()
    }
    internal = {}
    for _, row in internal_df.iterrows():
        soc = row["soc_code"]
        if job_roles_df is not None and not job_roles_df.empty:
            job_roles = job_roles_df[job_roles_df["soc_code"] == soc].drop(columns=["soc_code"]).reset_index(drop=True)
        else:
            job_roles = pd.DataFrame()
        internal[soc] = {
            "internal_demand_index": row["internal_demand_index"],
            "direction": row["direction"],
            "narrative": row["narrative"],
            "job_roles": job_roles,
        }
    recommendation = {}
    for _, row in rec_df.iterrows():
        recommendation[row["soc_code"]] = {
            "risk_rating": row["risk_rating"],
            "narrative": row["narrative"],
            "used_llm": bool(row["used_llm"]),
        }

    return {
        "reconciliation_df": reconciliation_df,
        "market": market,
        "ai_impact": ai_impact,
        "internal": internal,
        "recommendation": recommendation,
        "signal_ledger_df": signal_ledger_df,
        "risk_matrix_comparison_df": risk_matrix_comparison_df,
        "risk_matrix_reference_df": risk_matrix_reference_df,
    }


def _require_pipeline_data():
    data = _load_pipeline_data()
    if data is None:
        raise HTTPException(status_code=409, detail=PIPELINE_NOT_RUN_DETAIL)
    return data


@app.get("/api/socs")
def get_socs():
    return _df_records(ai_risk_framework.SOC_REF)


@app.get("/api/llm-status")
def get_llm_status():
    return {"configured": llm.is_configured()}


@app.post("/api/run-pipeline")
def run_pipeline():
    def event_stream():
        # Clear output/ first so a run never leaves behind stale files from
        # a previous run (e.g. an agent that no longer produces a given
        # file, or a renamed slug) alongside the fresh ones.
        storage.clear_outputs()
        for name, status, summary, payload in agents.run_full_pipeline():
            if status == "done":
                _persist_agent_output(name, payload)
            event = {"agent_name": name, "status": status, "output_summary": summary}
            yield f"data: {json.dumps(event)}\n\n"
            if status == "running":
                time.sleep(0.35)  # brief pause so the UI's spinner is visible
        yield "data: {\"agent_name\": \"__pipeline__\", \"status\": \"complete\", \"output_summary\": \"Pipeline finished.\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/reset-pipeline")
def reset_pipeline():
    """Deletes every file under output/agents/ and output/reports/ (the
    Agent Run Panel's "Reset" button) — the same clear used automatically
    at the start of a pipeline run, exposed on demand so a user can clear
    results without immediately re-running the pipeline."""
    storage.clear_outputs()
    return {"status": "ok"}


@app.get("/api/reconciliation")
def get_reconciliation():
    data = _require_pipeline_data()
    return _df_records(data["reconciliation_df"])


@app.get("/api/reconciliation/{soc_code}")
def get_reconciliation_one(soc_code: str):
    data = _require_pipeline_data()
    df = data["reconciliation_df"]
    match = df[df["soc_code"] == soc_code]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Unknown soc_code: {soc_code}")
    return _df_records(match)[0]


@app.get("/api/job-roles/{soc_code}")
def get_job_roles(soc_code: str):
    data = _require_pipeline_data()
    if soc_code not in data["internal"]:
        raise HTTPException(status_code=404, detail=f"Unknown soc_code: {soc_code}")
    return _df_records(data["internal"][soc_code]["job_roles"])


@app.get("/api/pattern/{soc_code}")
def get_pattern(soc_code: str):
    data = _require_pipeline_data()
    df = data["reconciliation_df"]
    match = df[df["soc_code"] == soc_code]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Unknown soc_code: {soc_code}")
    return classify_pattern(match.iloc[0].to_dict())


@app.get("/api/insights/{soc_code}")
def get_insights(soc_code: str):
    data = _require_pipeline_data()
    rec = data["recommendation"]
    if soc_code not in rec:
        raise HTTPException(status_code=404, detail=f"Unknown soc_code: {soc_code}")
    out = dict(rec[soc_code])
    out["soc_code"] = soc_code
    return out


@app.get("/api/heatmap")
def get_heatmap():
    """Data shaped for the SOC x [AI Impact, Demand Shift, Organizational
    Exposure] 3-dimension heatmap."""
    data = _require_pipeline_data()
    df = data["reconciliation_df"]
    market = data["market"]
    internal = data["internal"]

    rows = []
    for row in df.itertuples():
        rows.append({
            "soc_code": row.soc_code,
            "soc_title": row.soc_title,
            "ai_impact": round(row.composite_ai_exposure * 100, 1),
            "demand_shift": market[row.soc_code]["demand_growth_index"],
            "organizational_exposure": internal[row.soc_code]["internal_demand_index"],
            "risk_rating": row.risk_rating,
        })
    return rows


class AnnotationIn(BaseModel):
    soc_code: str
    note: str = ""
    include_in_report: bool = True


@app.get("/api/annotations")
def get_annotations():
    return _df_records(load_annotations())


@app.get("/api/annotations/{soc_code}")
def get_annotation_one(soc_code: str):
    return get_annotation(soc_code)


@app.post("/api/annotations")
def post_annotation(annotation: AnnotationIn):
    if annotation.soc_code not in ai_risk_framework.SOC_REF["soc_code"].tolist():
        raise HTTPException(status_code=404, detail=f"Unknown soc_code: {annotation.soc_code}")
    return save_annotation(annotation.soc_code, annotation.note, annotation.include_in_report)


@app.get("/api/report/excel")
def get_report_excel():
    if not storage.report_exists():
        raise HTTPException(status_code=409, detail=PIPELINE_NOT_RUN_DETAIL)
    return FileResponse(
        path=storage.report_path(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=storage.REPORT_FILENAME,
    )


@app.get("/api/report/views-excel")
def get_views_report_excel():
    """Standalone workbook with only the Signal Ledger / Risk & Action
    Matrix sheets — same 409-until-generated behavior as the full report
    above."""
    if not storage.views_report_exists():
        raise HTTPException(status_code=409, detail=PIPELINE_NOT_RUN_DETAIL)
    return FileResponse(
        path=storage.views_report_path(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=storage.VIEWS_REPORT_FILENAME,
    )


# ---------------------------------------------------------------------
# Per-agent CSV downloads — serves the persisted output/agents/*.csv
# file directly. 409 if that agent hasn't produced output yet (the UI
# already hides the download button until then; this is the safety net).
# ---------------------------------------------------------------------

DOWNLOADABLE_AGENT_SLUGS = {m["slug"] for m in agents.AGENT_METADATA}
for _m in agents.AGENT_METADATA:
    DOWNLOADABLE_AGENT_SLUGS.update(extra["slug"] for extra in _m["extra_downloads"])


@app.get("/api/agents/{slug}/csv")
def download_agent_csv(slug: str):
    if slug not in DOWNLOADABLE_AGENT_SLUGS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {slug}")
    path = storage.agent_csv_path(slug)
    if not path.exists():
        raise HTTPException(status_code=409, detail="This agent has not been run yet.")
    return FileResponse(path=path, media_type="text/csv", filename=path.name)


# =====================================================================
# Server-rendered HTML frontend (Jinja2 + plain CSS). Screens 1-4 from
# PROJECT_SPEC.md section 6, minus a JS-based charting/frontend framework —
# charts are plain CSS bars/heatmap cells computed in backend/charting.py.
# =====================================================================

def _selected_socs(request: Request):
    """A single-SOC dropdown filter: query param `soc` is either empty/
    missing ("All SOCs") or one valid soc_code."""
    all_codes = ai_risk_framework.SOC_REF["soc_code"].tolist()
    raw = request.query_params.get("soc", "")
    return [raw] if raw in all_codes else all_codes


def _soc_titles():
    return dict(zip(ai_risk_framework.SOC_REF["soc_code"], ai_risk_framework.SOC_REF["soc_title"]))


def _soc_options(request: Request):
    titles = _soc_titles()
    selected = request.query_params.get("soc", "")
    return {
        "selected": selected,
        "options": [
            {"value": c, "label": f"{c} — {titles[c]}"}
            for c in ai_risk_framework.SOC_REF["soc_code"].tolist()
        ],
    }


def _build_soc_views(selected_codes, data):
    df = data["reconciliation_df"]
    market = data["market"]
    ai_impact = data["ai_impact"]
    internal = data["internal"]
    recommendation = data["recommendation"]
    annotations = load_annotations()

    views = []
    for row in df.itertuples():
        if row.soc_code not in selected_codes:
            continue
        pattern = classify_pattern(row._asdict())
        job_roles_df = internal[row.soc_code]["job_roles"]

        ann_match = annotations[annotations["soc_code"] == row.soc_code]
        if not ann_match.empty:
            ann_row = ann_match.iloc[-1]
            note = "" if pd.isna(ann_row["note"]) else ann_row["note"]
            include_in_report = bool(ann_row["include_in_report"])
        else:
            note, include_in_report = "", True

        views.append({
            "soc_code": row.soc_code,
            "soc_title": row.soc_title,
            "risk_rating": row.risk_rating,
            "risk_badge_class": charting.RISK_BADGE_CLASS.get(row.risk_rating, "badge-neutral"),
            "pattern": pattern,
            "pattern_badge_class": charting.PATTERN_BADGE_CLASS.get(
                pattern["pattern_name"], "badge-neutral"
            ),
            "heatmap": {
                "ai_impact": round(row.composite_ai_exposure * 100, 1),
                "ai_impact_color": charting.heatmap_color(row.composite_ai_exposure * 100),
                "demand_shift": market[row.soc_code]["demand_growth_index"],
                "demand_shift_color": charting.heatmap_color(
                    market[row.soc_code]["demand_growth_index"]
                ),
                "org_exposure": internal[row.soc_code]["internal_demand_index"],
                "org_exposure_color": charting.heatmap_color(
                    internal[row.soc_code]["internal_demand_index"]
                ),
            },
            "bars": {
                "external_growth": charting.signed_bar(row.bls_emp_change_pct),
                "internal_req_trend": charting.signed_bar(row.internal_req_volume_trend_pct),
                "anthropic_exposure": charting.unsigned_bar(
                    row.anthropic_observed_exposure, vmax=1.0, color=charting.ANTHROPIC_COLOR
                ),
                "oecd_exposure": charting.unsigned_bar(
                    row.oecd_gap_index_reversed_norm, vmax=1.0, color=charting.OECD_COLOR
                ),
                "margin_trend": charting.signed_bar(row.internal_margin_trend_pct),
            },
            "market": market[row.soc_code],
            "ai_impact_agent": ai_impact[row.soc_code],
            "internal_exposure": internal[row.soc_code],
            "job_roles": _df_records(job_roles_df),
            "recommendation": recommendation.get(row.soc_code),
            "annotation_note": note,
            "annotation_include": include_in_report,
            "oecd_is_proxy": bool(row.oecd_is_proxy),
        })
    return views


SIGNAL_LEDGER_DIMENSION_ORDER = ["External Demand (ED)", "AI Impact", "Internal Demand (ID)", "Exposure"]


def _risk_matrix_join_key(ai_level):
    return "HIGH" if ai_level in ("HIGH", "MODERATE") else "LOW"


def _build_view_sections(request: Request, data, selected_codes):
    """Dashboard-only context for the Signal Ledger and Risk & Action Matrix
    sections (produced together by the Signal Intelligence Agent) — filtered
    by the same ?soc= selection as the rest of the page, plus a Signal
    Ledger-only ?dimension= filter."""
    signal_ledger_df = data["signal_ledger_df"]
    risk_matrix_comparison_df = data["risk_matrix_comparison_df"]
    risk_matrix_reference_df = data["risk_matrix_reference_df"]

    selected_dimension = request.query_params.get("dimension", "")

    ledger_filtered = signal_ledger_df[signal_ledger_df["soc_code"].isin(selected_codes)]
    if selected_dimension:
        ledger_filtered = ledger_filtered[ledger_filtered["dimension"] == selected_dimension]

    signal_ledger_groups = [
        {"dimension": d, "rows": _df_records(ledger_filtered[ledger_filtered["dimension"] == d])}
        for d in SIGNAL_LEDGER_DIMENSION_ORDER
        if not ledger_filtered[ledger_filtered["dimension"] == d].empty
    ]

    comparison_filtered = risk_matrix_comparison_df[risk_matrix_comparison_df["soc_code"].isin(selected_codes)]
    resolved_keys = {
        (row.ed_direction, row.id_direction, _risk_matrix_join_key(row.ai_level))
        for row in comparison_filtered.itertuples()
    }
    risk_matrix_reference_rows = [
        {
            "ed": row.ed, "id": row.id, "ai": row.ai,
            "recommended_action": row.recommended_action,
            "rationale": row.rationale,
            "is_resolved": (row.ed, row.id, row.ai) in resolved_keys,
        }
        for row in risk_matrix_reference_df.itertuples()
    ]

    return {
        "signal_ledger_groups": signal_ledger_groups,
        "dimension_options": SIGNAL_LEDGER_DIMENSION_ORDER,
        "selected_dimension": selected_dimension,
        "risk_matrix_rows": _df_records(comparison_filtered),
        "risk_matrix_reference_rows": risk_matrix_reference_rows,
    }


@app.get("/")
def page_index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "agents_meta": agents.AGENT_METADATA,
        "qs": request.url.query,
    })


@app.get("/dashboard")
def page_dashboard(request: Request):
    data = _load_pipeline_data()
    selected = _selected_socs(request)
    context = {
        "pipeline_ready": data is not None,
        "views": _build_soc_views(selected, data) if data else [],
        "soc_filter": _soc_options(request),
        "qs": request.url.query,
        "dimension": request.query_params.get("dimension", ""),
    }
    if data:
        context.update(_build_view_sections(request, data, selected))
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/insights")
def page_insights(request: Request):
    data = _load_pipeline_data()
    selected = _selected_socs(request)
    return templates.TemplateResponse(request, "insights.html", {
        "pipeline_ready": data is not None,
        "views": _build_soc_views(selected, data) if data else [],
        "soc_filter": _soc_options(request),
        "qs": request.url.query,
        "saved_soc": request.query_params.get("saved"),
        "dimension": "",
    })


@app.post("/insights/annotations/{soc_code}")
def page_post_annotation(
    soc_code: str,
    request: Request,
    existing_note: str = Form(""),
    include_in_report: str = Form(None),
):
    if soc_code not in ai_risk_framework.SOC_REF["soc_code"].tolist():
        raise HTTPException(status_code=404, detail=f"Unknown soc_code: {soc_code}")
    save_annotation(soc_code, existing_note, include_in_report == "on")

    params = parse_qs(request.url.query)
    params.pop("saved", None)
    params["saved"] = [soc_code]
    return RedirectResponse(url=f"/insights?{urlencode(params, doseq=True)}", status_code=303)


@app.get("/export")
def page_export(request: Request):
    data = _load_pipeline_data()
    selected = _selected_socs(request)
    return templates.TemplateResponse(request, "export.html", {
        "pipeline_ready": data is not None,
        "report_ready": storage.report_exists(),
        "views_report_ready": storage.views_report_exists(),
        "views": _build_soc_views(selected, data) if data else [],
        "soc_filter": _soc_options(request),
        "qs": request.url.query,
        "dimension": "",
    })
