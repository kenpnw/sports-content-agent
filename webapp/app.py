from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from config import APP_HOST, APP_PORT, BASE_DIR, OUTPUT_DIR
from webapp.job_manager import job_manager


app = Flask(__name__, template_folder="templates", static_folder="static")


def _safe_generated_path(raw_path: str) -> Path:
    candidate = Path(raw_path).resolve()
    allowed = Path(OUTPUT_DIR).resolve()
    if not str(candidate).startswith(str(allowed)):
        raise PermissionError("File path is outside generated output.")
    return candidate


@app.get("/")
def index():
    sample_path = BASE_DIR / "data" / "samples" / "nba_postgame_sample.json"
    return render_template(
        "index.html",
        sample_input=str(sample_path),
        api_host=APP_HOST,
        api_port=APP_PORT,
    )


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/jobs")
def list_jobs():
    return jsonify({"jobs": job_manager.list_jobs()})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        abort(404)
    return jsonify(job)


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(force=True, silent=True) or {}
    source = payload.get("source", "fetch_today")
    team = payload.get("team") or ""
    input_path = payload.get("input_path") or ""
    job = job_manager.start_job(source=source, team=team, input_path=input_path)
    return jsonify(job), 202


@app.get("/api/files")
def get_file():
    raw_path = request.args.get("path", "")
    if not raw_path:
        abort(400)
    try:
        path = _safe_generated_path(raw_path)
    except PermissionError:
        abort(403)
    if not path.exists():
        abort(404)
    return send_file(path)


def run() -> None:
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
