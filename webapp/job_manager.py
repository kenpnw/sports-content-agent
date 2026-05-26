from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config import BASE_DIR, OUTPUT_DIR
from ingestion.nba_live import fetch_today_nba_postgame_data
from realtime.demo_runner import run_replay_demo
from video_scout.demo_runner import run_video_scout_demo
from workflows.nba_postgame import run_nba_postgame_workflow


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda job: job["created_at"], reverse=True)
        return [self._public_job(job) for job in jobs[:12]]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return self._public_job(job)

    def start_job(self, source: str, team: str | None, input_path: str | None, game_id: str | None = None) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "source": source,
            "team": team or "",
            "input_path": input_path or "",
            "game_id": game_id or "",
            "logs": [],
            "steps": [],
            "result": None,
            "error": "",
        }
        with self._lock:
            self._jobs[job_id] = job
            self._evict_old_jobs()

        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return self.get_job(job_id) or job

    def _log(self, job_id: str, message: str, level: str = "info") -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["logs"].append(
                {
                    "timestamp": _iso_now(),
                    "level": level,
                    "message": message,
                }
            )
            job["updated_at"] = _iso_now()

    def _step(self, job_id: str, stage: str, status: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            existing = next((item for item in job["steps"] if item["stage"] == stage), None)
            step_payload = {
                "stage": stage,
                "status": status,
                "message": message,
                "payload": payload or {},
                "updated_at": _iso_now(),
            }
            if existing:
                existing.update(step_payload)
            else:
                job["steps"].append(step_payload)
            job["updated_at"] = _iso_now()

    def _run_job(self, job_id: str) -> None:
        try:
            with self._lock:
                self._jobs[job_id]["status"] = "running"
                self._jobs[job_id]["updated_at"] = _iso_now()

            with self._lock:
                job = dict(self._jobs[job_id])

            source = job["source"]
            team = job["team"] or None
            input_path = job["input_path"] or None

            if source == "video_scout_demo":
                if not input_path:
                    raise RuntimeError("Observation path is required for video scout demo jobs.")
                if not Path(input_path).is_file():
                    raise RuntimeError(
                        f"Observation file not found: '{input_path}'. "
                        "Please check the path and make sure the JSON exists."
                    )
                replay_path = str(BASE_DIR / "data" / "samples" / "nba_replay_sample.json")
                court_report_path = str(BASE_DIR / "data" / "samples" / "court_ai_report_sample.json")
                self._step(job_id, "load_observations", "running", "Loading video scout observations.")
                self._log(job_id, f"Using video scout observations: {input_path}")
                self._step(job_id, "load_observations", "completed", "Observation file loaded.", {"input_path": input_path})

                self._step(
                    job_id,
                    "video_scout_pipeline",
                    "running",
                    "Running timestamp-grounded tactical analysis.",
                )
                result = run_video_scout_demo(
                    observations_path=input_path,
                    replay_path=replay_path,
                    court_report_path=court_report_path,
                    use_llm=False,
                    use_vision=False,
                )
                self._step(job_id, "video_scout_pipeline", "completed", "Video scout report generated.", result)
                self._log(
                    job_id,
                    f"Video scout generated {result['segment_count']} tactical segments from {result['observation_count']} observations.",
                )
                with self._lock:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["result"] = result
                    self._jobs[job_id]["updated_at"] = _iso_now()
                return

            if source == "replay_demo":
                if not input_path:
                    raise RuntimeError("Replay path is required for realtime replay demo jobs.")
                if not Path(input_path).is_file():
                    raise RuntimeError(
                        f"Replay file not found: '{input_path}'. "
                        "Please check the path and make sure the replay JSON exists."
                    )
                self._step(job_id, "load_replay", "running", "Loading recorded play-by-play replay.")
                self._log(job_id, f"Using replay input: {input_path}")
                self._step(job_id, "load_replay", "completed", "Replay file loaded.", {"input_path": input_path})

                self._step(
                    job_id,
                    "realtime_pipeline",
                    "running",
                    "Running replay, event detection, commentary, and provenance tagging.",
                )
                result = run_replay_demo(
                    replay_path=input_path,
                    style="hupu",
                    speed=100.0,
                    sleep=False,
                    use_llm=False,
                )
                self._step(job_id, "realtime_pipeline", "completed", "Realtime replay transcript generated.", result)
                self._log(
                    job_id,
                    f"Realtime demo generated {result['commentary_count']} commentaries from {result['event_count']} events.",
                )
                with self._lock:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["result"] = {"workflow": "realtime_demo", **result}
                    self._jobs[job_id]["updated_at"] = _iso_now()
                return

            if source == "fetch_today":
                game_id = job.get("game_id") or None
                if game_id:
                    self._step(job_id, "fetch_live", "running", f"Fetching specific game {game_id}.")
                    self._log(job_id, f"Fetching specific game_id={game_id}")
                else:
                    self._step(job_id, "fetch_live", "running", "Fetching official NBA finals and ranking candidates.")
                    self._log(job_id, f"Fetching live NBA input for team filter: {team or 'none'}")
                fetch_result = fetch_today_nba_postgame_data(
                    output_dir=OUTPUT_DIR,
                    team_filter=team,
                    save_input=True,
                    game_id=game_id,
                )
                input_path = fetch_result["input_path"]
                selection_context = fetch_result.get("selection")
                source_mode = fetch_result.get("source_mode", "live")
                self._step(
                    job_id,
                    "fetch_live",
                    "completed",
                    "Official NBA input fetched and ranked." if source_mode == "live" else "Live fetch failed, cached NBA input selected.",
                    {
                        "input_path": input_path,
                        "selection": selection_context or {},
                        "source_mode": source_mode,
                    },
                )
                if source_mode == "live":
                    self._log(job_id, f"Live input saved to {input_path}")
                else:
                    self._log(job_id, f"Using cached input fallback: {input_path}")
                    if selection_context and selection_context.get("fallback_reason"):
                        self._log(job_id, f"Fallback reason: {selection_context['fallback_reason']}", "warning")
                if selection_context:
                    selected_game = selection_context.get("selected_game", {})
                    self._log(
                        job_id,
                        "Topic engine selected "
                        f"{selected_game.get('winner', 'the game')} with score "
                        f"{selected_game.get('global_topic_score', 'n/a')}.",
                    )
            else:
                if not input_path:
                    raise RuntimeError("Input path is required for local input jobs.")
                if not Path(input_path).is_file():
                    raise RuntimeError(
                        f"Input file not found: '{input_path}'. "
                        "Please check the path and make sure the file exists."
                    )
                self._step(job_id, "fetch_live", "completed", "Using local normalized input.", {"input_path": input_path})
                self._log(job_id, f"Using local input: {input_path}")
                selection_context = None

            result = run_nba_postgame_workflow(
                input_path=input_path,
                output_dir=OUTPUT_DIR,
                selection_context=selection_context,
                callback=lambda stage, status, message, payload=None: self._step(job_id, stage, status, message, payload),
            )
            self._log(job_id, "Workflow finished and publish plans are ready.")
            with self._lock:
                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["result"] = result
                self._jobs[job_id]["updated_at"] = _iso_now()
        except Exception as exc:
            self._log(job_id, str(exc), "error")
            with self._lock:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["error"] = str(exc)
                self._jobs[job_id]["updated_at"] = _iso_now()

    _MAX_JOBS = 50  # keep at most this many jobs in memory

    def _evict_old_jobs(self) -> None:
        """Remove oldest completed/failed jobs when the store exceeds _MAX_JOBS. Call with lock held."""
        if len(self._jobs) <= self._MAX_JOBS:
            return
        # Sort by created_at ascending; evict finished jobs first
        finished = sorted(
            [j for j in self._jobs.values() if j["status"] in ("completed", "failed")],
            key=lambda j: j["created_at"],
        )
        for job in finished:
            if len(self._jobs) <= self._MAX_JOBS:
                break
            del self._jobs[job["id"]]

    def _public_job(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job["id"],
            "status": job["status"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "source": job["source"],
            "team": job["team"],
            "input_path": job["input_path"],
            "logs": list(job["logs"]),
            "steps": list(job["steps"]),
            "result": job["result"],
            "error": job["error"],
        }


job_manager = JobManager()
