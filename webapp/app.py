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
    game_id = payload.get("game_id") or ""
    job = job_manager.start_job(source=source, team=team, input_path=input_path, game_id=game_id)
    return jsonify(job), 202


@app.get("/api/nba/recent_games")
def list_recent_nba_games():
    """Return finished NBA games from the last N days (default 30) for UI picker."""
    from ingestion.nba_live import list_recent_finals
    try:
        days = int(request.args.get("days", "30"))
    except ValueError:
        days = 30
    days = max(1, min(days, 90))
    try:
        games = list_recent_finals(lookback_days=days)
        return jsonify({"games": games, "lookback_days": days, "count": len(games)})
    except RuntimeError as exc:
        return jsonify({"games": [], "lookback_days": days, "count": 0, "error": str(exc)}), 200


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


def _clip_basename_from_filename(clip_filename: str) -> str:
    """Get the basename without extension for frame folder lookup.

    Frames are stored next to the MP4 in a sibling `<basename>_frames/` directory,
    where `<basename>` is the MP4/GIF filename without extension.
    """
    return Path(clip_filename).stem


@app.get("/api/tactical/clip/<report_id>/<path:clip_filename>/frames")
def list_clip_frames(report_id: str, clip_filename: str):
    """Return the list of pre-extracted keyframes for a given clip.

    Frames live at: <report_dir>/clips/<basename>_frames/frame_XX.jpg
    """
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)

    clips_dir = (report_dir / "clips").resolve()
    basename = _clip_basename_from_filename(clip_filename)
    frames_dir = (clips_dir / f"{basename}_frames").resolve()

    # Defensive: ensure frames_dir is inside clips_dir
    try:
        frames_dir.relative_to(clips_dir)
    except ValueError:
        abort(403)

    if not frames_dir.exists() or not frames_dir.is_dir():
        return jsonify({"frames": [], "basename": basename, "frames_dir_exists": False})

    frames = sorted(
        p.name for p in frames_dir.glob("frame_*.jpg") if p.is_file()
    )
    return jsonify(
        {
            "frames": frames,
            "basename": basename,
            "frames_dir_exists": True,
        }
    )


@app.get("/static-frames/<report_id>/<basename>/<frame_filename>")
def get_tactical_frame(report_id: str, basename: str, frame_filename: str):
    """Serve a single pre-extracted keyframe image."""
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)

    # basename and frame_filename must not contain path separators
    if "/" in basename or "\\" in basename or ".." in basename:
        abort(403)
    if "/" in frame_filename or "\\" in frame_filename or ".." in frame_filename:
        abort(403)

    clips_dir = (report_dir / "clips").resolve()
    frames_dir = (clips_dir / f"{basename}_frames").resolve()
    try:
        frames_dir.relative_to(clips_dir)
    except ValueError:
        abort(403)

    frame_path = (frames_dir / frame_filename).resolve()
    try:
        frame_path.relative_to(frames_dir)
    except ValueError:
        abort(403)

    if not frame_path.exists() or not frame_path.is_file():
        abort(404)
    return send_file(frame_path)


# ---------- Manual clip adjustment (P0-A) ----------

def _source_video_for_report(report_dir: Path) -> Path | None:
    """Find the source MKV/MP4 referenced by this report's clip_manifest."""
    manifest_path = report_dir / "clip_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = _read_json_file(manifest_path)
    except Exception:
        return None
    raw = manifest.get("video_path") or manifest.get("source_video")
    if not raw:
        # Also check report.json metadata
        rep = report_dir / "report.json"
        if rep.exists():
            try:
                data = _read_json_file(rep)
                raw = (data.get("metadata") or {}).get("video_path") or data.get("video_path")
            except Exception:
                pass
    if not raw:
        return None
    p = Path(raw)
    return p if p.exists() else None


@app.get("/api/tactical/<report_id>/overrides")
def get_clip_overrides(report_id: str):
    """Return the user-saved clip adjustments for this report."""
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)
    from video_scout.recut_clip import load_overrides
    return jsonify(load_overrides(report_dir))


@app.get("/api/tactical/<report_id>/preview-frame")
def get_preview_frame(report_id: str):
    """Extract a single frame at the given video second. Used by the
    manual-adjust modal to live-preview where the slider will cut.

    Query param: ?second=<float>
    """
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)
    try:
        second = float(request.args.get("second", "0"))
    except (TypeError, ValueError):
        abort(400)
    if second < 0 or second > 36000:  # sanity: 10h cap
        abort(400)
    video = _source_video_for_report(report_dir)
    if not video:
        abort(404, "source video not found")
    # Write to a per-report ephemeral preview file (overwritten on each call)
    preview = report_dir / "_preview_frame.jpg"
    from video_scout.recut_clip import extract_single_frame
    ok = extract_single_frame(video, second, preview)
    if not ok:
        abort(500, "ffmpeg frame extract failed")
    return send_file(preview, mimetype="image/jpeg")


@app.post("/api/tactical/<report_id>/clip/<path:clip_filename>/adjust")
def adjust_clip_endpoint(report_id: str, clip_filename: str):
    """Save user-adjusted start/end seconds for a clip, then re-cut MP4 + GIF.

    Body JSON: {start_seconds: float, end_seconds: float}
    """
    try:
        report_dir = _safe_tactical_report_dir(report_id)
    except PermissionError:
        abort(403)
    if "/" in clip_filename or "\\" in clip_filename or ".." in clip_filename:
        abort(403)
    try:
        payload = request.get_json(force=True) or {}
        start = float(payload.get("start_seconds"))
        end = float(payload.get("end_seconds"))
    except (TypeError, ValueError, KeyError):
        abort(400, "body must include start_seconds and end_seconds")
    if end - start < 1.0 or end - start > 60.0:
        abort(400, "clip duration must be between 1 and 60 seconds")
    video = _source_video_for_report(report_dir)
    if not video:
        abort(404, "source video not found for this report")

    from video_scout.recut_clip import adjust_clip
    result = adjust_clip(
        report_dir=report_dir,
        video_path=video,
        clip_filename=clip_filename,
        new_start_seconds=start,
        new_end_seconds=end,
    )
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


def run() -> None:
    app.run(host=APP_HOST, port=APP_PORT, debug=False)


if __name__ == "__main__":
    run()
