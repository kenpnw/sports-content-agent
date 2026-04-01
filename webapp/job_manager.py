from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from ingestion.nba_live import fetch_today_nba_postgame_data
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

    def start_job(self, source: str, team: str | None, input_path: str | None) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "source": source,
            "team": team or "",
            "input_path": input_path or "",
            "logs": [],
            "steps": [],
            "result": None,
            "error": "",
        }
        with self._lock:
            self._jobs[job_id] = job

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

            if source == "fetch_today":
                self._step(job_id, "fetch_live", "running", "Fetching latest completed NBA game from official feed.")
                self._log(job_id, f"Fetching live NBA input for team filter: {team or 'none'}")
                input_path = fetch_today_nba_postgame_data(
                    output_dir=OUTPUT_DIR,
                    team_filter=team,
                    save_input=True,
                )
                self._step(job_id, "fetch_live", "completed", "Official NBA input fetched.", {"input_path": input_path})
                self._log(job_id, f"Live input saved to {input_path}")
            else:
                if not input_path:
                    raise RuntimeError("Input path is required for local input jobs.")
                self._step(job_id, "fetch_live", "completed", "Using local normalized input.", {"input_path": input_path})
                self._log(job_id, f"Using local input: {input_path}")

            result = run_nba_postgame_workflow(
                input_path=input_path,
                output_dir=OUTPUT_DIR,
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
