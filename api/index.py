from __future__ import annotations

import os
from typing import Any

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/")
def root() -> Any:
    return jsonify(
        {
            "service": "GeoQA Agent",
            "status": "ok",
            "mode": "vercel_api_scaffold",
            "notes": [
                "This Vercel deployment currently exposes API health/config endpoints.",
                "Run full Streamlit UX on a stateful host (container or VM) for production flows.",
            ],
            "endpoints": ["/", "/health", "/config"],
        }
    )


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "healthy"})


@app.get("/config")
def config() -> Any:
    return jsonify(
        {
            "agent_report_enabled": os.getenv("GEOQA_AGENT_REPORT_ENABLED", "true"),
            "has_openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
            "llm_model": os.getenv("GEOQA_LLM_MODEL"),
            "output_root": os.getenv("GEOQA_OUTPUT_ROOT", "outputs"),
        }
    )


# Vercel Python runtime expects a WSGI callable named `app`.
