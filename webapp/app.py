from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from config import APP_HOST, APP_PORT, BASE_DIR, OUTPUT_DIR
from webapp.job_manager import job_manager


app = Flask(__name__, template_folder="templates", static_folder="static")

TACTICAL_OUTPUT_DIR = BASE_DIR / "data" / "generated" / "video_scout"


def _safe_generated_path(raw_path: str) -> Path:
    candidate = Path(raw_path).resolve()
    allowed = Path(OUTPUT_DIR).resolve()
    if not str(candidate).startswith(str(allowed)):
        raise PermissionError("File path is outside generated output.")
    return candidate


def _safe_tactical_report_dir(report_id: str) -> Path:
    if not report_id or "/" in report_id or "\\" in report_id or ".." in report_id:
        raise PermissionError("Invalid tactical report id.")

    base = TACTICAL_OUTPUT_DIR.resolve()
    candidate = (base / report_id).resolve()
    if candidate.parent != base:
        raise PermissionError("Tactical report path is outside generated output.")
    return candidate


def _read_json_file(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@app.get("/")
def index():
    sample_path = BASE_DIR / "data" / "samples" / "nba_postgame_sample.json"
    sample_replay_path = BASE_DIR / "data" / "samples" / "nba_replay_sample.json"
    sample_video_scout_path = BASE_DIR / "data" / "samples" / "video_scout_observations_sample.json"
    return render_template(
        "index.html",
        sample_input=str(sample_path),
        sample_replay=str(sample_replay_path),
        sample_video_scout=str(sample_video_scout_path),
        api_host=APP_HOST,
        api_port=APP_PORT,
    )


@app.get("/tactical")
def tactical_review():
    return render_template("tactical_review.html")


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


@app.get("/api/tactical/list")
def list_tactical_reports():
    reports = []
    if TACTICAL_OUTPUT_DIR.exists():
        for report_path in TACTICAL_OUTPUT_DIR.glob("*/report.json"):
            report_dir = report_path.parent
            try:
                report = _read_json_file(report_path)
            except (OSError, json.JSONDecodeError):
                continue

            manifest_path = report_dir / "clip_manifest.json"
            clip_count = 0
            if manifest_path.exists():
                try:
                    manifest = _read_json_file(manifest_path)
                    clip_count = len(manifest.get("clips", []))
                except (OSError, json.JSONDecodeError):
                    clip_count = 0

            modified_at = report_path.stat().st_mtime
            reports.append(
                {
                    "report_id": report_dir.name,
                    "title": report.get("title") or report_dir.name,
                    "created_at": report.get("created_at") or report.get("generated_at") or "",
                    "modified_at": modified_at,
                    "clip_count": clip_count,
                    "segment_count": len(report.get("key_segments", [])),
                }
            )

    reports.sort(key=lambda item: item.get("modified_at", 0), reverse=True)
    return jsonify(
        [
            {
                "report_id": item["report_id"],
                "title": item["title"],
                "created_at": item["created_at"],
                "clip_count": item["clip_count"],
                "segment_count": item["segment_count"],
            }
            for item in reports
        ]
    )


@app.get("/api/tactical/report/<report_id>")
def get_tactical_report(report_id: str):
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)

    report_path = report_dir / "report.json"
    manifest_path = report_dir / "clip_manifest.json"
    if not report_path.exists():
        abort(404)

    try:
        report = _read_json_file(report_path)
        clip_manifest = _read_json_file(manifest_path) if manifest_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        abort(500)

    return jsonify({"report": report, "clip_manifest": clip_manifest})


@app.get("/static-clips/<report_id>/<path:clip_filename>")
def get_tactical_clip(report_id: str, clip_filename: str):
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)

    clips_dir = (report_dir / "clips").resolve()
    clip_path = (clips_dir / Path(clip_filename).name).resolve()
    if clip_path.parent != clips_dir:
        abort(403)
    if not clip_path.exists():
        abort(404)
    return send_file(clip_path)


def run() -> None:
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
