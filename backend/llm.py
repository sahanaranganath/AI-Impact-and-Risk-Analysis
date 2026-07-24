"""
Azure OpenAI GPT-4o wrapper — used ONLY by the Recommendation Agent
(PROJECT_SPEC.md, Section 4.5). Every other agent is pure rule-based logic
and never touches this module.

Grounding rule: the prompt includes ONLY the already-computed structured
numeric/pattern outputs. The system prompt explicitly forbids the model
from introducing outside claims about the occupation, AI capabilities, or
the labor market beyond what's provided.
"""

import os
import json

SYSTEM_PROMPT = (
    "You are a labor-market risk analyst writing a short internal briefing "
    "note. You will be given ONLY a JSON object of already-computed "
    "numeric scores, index values, and a named pattern classification for "
    "one occupation. Turn that structured data into ONE fluent narrative "
    "paragraph ending in a concrete recommendation. Do not introduce any "
    "fact, statistic, or claim about the occupation, AI capabilities, or "
    "the labor market that is not present in the JSON provided — no "
    "outside knowledge, no speculation beyond what the numbers say. If the "
    "JSON marks a value as a proxy or an assumption, mention that caveat "
    "plainly rather than ignoring it. If the JSON includes a "
    "`risk_action_matrix` object, your concluding recommendation MUST name "
    "its `recommended_action` value explicitly (verbatim) and explain it "
    "using its `rationale` — do not just restate the risk rating and "
    "pattern classification independently of it."
)


def is_configured():
    return bool(
        os.environ.get("AZURE_OPENAI_API_KEY")
        and os.environ.get("AZURE_OPENAI_ENDPOINT")
        and os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    )


def generate_recommendation_narrative(structured_payload: dict) -> str:
    """Call Azure OpenAI GPT-4o with only `structured_payload` as grounding.

    Raises on any failure (missing config, network error, API error) — the
    caller (RecommendationAgent) is responsible for catching and falling
    back to the templated narrative. Never call this without a try/except
    around it.
    """
    if not is_configured():
        raise RuntimeError("Azure OpenAI is not configured (missing env vars).")

    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
    )

    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(structured_payload, default=str)},
        ],
        temperature=0.3,
        max_tokens=400,
    )
    text = response.choices[0].message.content
    if not text or not text.strip():
        raise RuntimeError("Azure OpenAI returned an empty response.")
    return text.strip()
