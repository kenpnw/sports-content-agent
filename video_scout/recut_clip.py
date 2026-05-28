"""Re-cut a single tactical clip with user-adjusted start/end times.

Used by the manual-adjustment UI in webapp/templates/tactical_review.html
to fix clips whose automated alignment ended up on the wrong play.

Stores adjustments in <report_dir>/clip_overrides.json so they survive
reloads and re-runs of the pipeline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def _ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError("ffmpeg not found on PATH")
    return p


def load_overrides(report_dir: Path) -> dict[str, Any]:
    path = report_dir / "clip_overrides.json"
    if not path.exists():
        return {"version": "1", "overrides": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_overrides(report_dir: Path, data: dict[str, Any]) -> None:
    path = report_dir / "clip_overrides.json"
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def extract_single_frame(
    video_path: Path,
    at_seconds: float,
    output_path: Path,
) -> bool:
    """Extract one frame at the given video second. Used for live preview."""
    cmd = [
        _ffmpeg(), "-y",
        "-ss", f"{max(0.0, at_seconds):.2f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-loglevel", "error",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def recut_clip(
    *,
    video_path: Path,
    clips_dir: Path,
    clip_filename: str,
    new_start_seconds: float,
    new_end_seconds: float,
    generate_gif: bool = True,
    gif_fps: int = 10,
    gif_width: int = 480,
) -> dict[str, Any]:
    """Re-cut the given clip (mp4 + gif) at new start/end seconds.

    Returns: {ok: bool, clip_path, gif_path, error?}
    """
    if new_end_seconds <= new_start_seconds + 1.0:
        return {"ok": False, "error": "end must be > start + 1s"}
    duration = new_end_seconds - new_start_seconds

    clip_path = clips_dir / clip_filename
    gif_path = clip_path.with_suffix(".gif")
    frames_dir = clips_dir / f"{clip_path.stem}_frames"

    # Re-cut mp4
    cmd_mp4 = [
        _ffmpeg(), "-y",
        "-ss", f"{new_start_seconds:.2f}",
        "-i", str(video_path),
        "-t", f"{duration:.2f}",
        "-c", "copy",
        str(clip_path),
    ]
    r = subprocess.run(cmd_mp4, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"ok": False, "error": f"mp4 cut failed: {r.stderr[-400:]}"}

    result: dict[str, Any] = {
        "ok": True,
        "clip_path": str(clip_path.relative_to(clips_dir.parent)),
        "gif_path": None,
        "frames_dir": None,
        "duration": duration,
        "recut_at": datetime.now().isoformat(),
    }

    # Re-generate GIF
    if generate_gif:
        cmd_gif = [
            _ffmpeg(), "-y", "-i", str(clip_path),
            "-vf", f"fps={gif_fps},scale={gif_width}:-1:flags=lanczos",
            "-loop", "0", str(gif_path),
        ]
        try:
            g = subprocess.run(cmd_gif, capture_output=True, text=True, timeout=90)
            if g.returncode == 0 and gif_path.exists():
                result["gif_path"] = str(gif_path.relative_to(clips_dir.parent))
        except Exception:
            pass

    # Refresh extracted keyframes (the tactical_review UI uses these)
    if frames_dir.exists():
        try:
            shutil.rmtree(frames_dir)
        except Exception:
            pass
    frames_dir.mkdir(exist_ok=True)
    try:
        # Same 6-keyframe extraction logic as extract_clip_frames.py:
        # evenly spaced at the second half of the clip.
        for i in range(6):
            offset = 0.5 + (i + 0.5) / 12.0  # samples at 54%, 62%, 71%, 79%, 88%, 96%
            frame_t = new_start_seconds + offset * duration
            frame_out = frames_dir / f"frame_{i+1:02d}.jpg"
            extract_single_frame(video_path, frame_t, frame_out)
        result["frames_dir"] = str(frames_dir.relative_to(clips_dir.parent))
    except Exception as exc:
        result["frames_warning"] = str(exc)

    return result


def adjust_clip(
    *,
    report_dir: Path,
    video_path: Path,
    clip_filename: str,
    new_start_seconds: float,
    new_end_seconds: float,
) -> dict[str, Any]:
    """High-level entry: re-cut + persist override."""
    clips_dir = report_dir / "clips"
    if not clips_dir.exists():
        return {"ok": False, "error": f"clips dir missing: {clips_dir}"}

    # 1. Re-cut on disk
    result = recut_clip(
        video_path=video_path,
        clips_dir=clips_dir,
        clip_filename=clip_filename,
        new_start_seconds=new_start_seconds,
        new_end_seconds=new_end_seconds,
    )
    if not result.get("ok"):
        return result

    # 2. Persist the override
    overrides = load_overrides(report_dir)
    overrides.setdefault("overrides", {})
    overrides["overrides"][clip_filename] = {
        "adjusted_start_seconds": new_start_seconds,
        "adjusted_end_seconds": new_end_seconds,
        "duration": new_end_seconds - new_start_seconds,
        "adjusted_at": result["recut_at"],
        "adjusted_by": "manual",
    }
    save_overrides(report_dir, overrides)
    result["override_persisted"] = True
    return result
