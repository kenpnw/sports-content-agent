"""CLI runner for the Video Scout Agent."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from storage.file_store import ensure_dir, read_json, timestamp_slug, write_json, write_text
from video_scout.auto_observation_builder import (
    DEFAULT_AUTO_OBSERVATIONS_PATH,
    build_observations_from_pbp,
    save_auto_observations,
)
from video_scout.court_report import CourtReport
from video_scout.models import FrameSample, VisualObservation, VideoScoutReport
from video_scout.tactic_analyzer import VideoScoutAnalyzer
from video_scout.vision_client import VisionClient


def run_video_scout_demo(
    *,
    video_path: str | None = None,
    observations_path: str | None = None,
    frame_manifest_path: str | None = None,
    replay_path: str | None = None,
    court_report_path: str | None = None,
    output_dir: str | None = None,
    use_llm: bool = False,
    use_vision: bool = False,
    target_chars: int = 2000,
    use_reasoner: bool = False,
    auto_observations: bool = False,
    video_total_seconds: float | None = None,
    auto_periods: set[int] | None = None,
    clip_before_seconds: float = 14.0,
    clip_after_seconds: float = 5.0,
    generate_gifs: bool = True,
    gif_fps: int = 10,
    gif_width: int = 480,
    video_period_windows: dict[int, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Run the scouting pipeline and write report artifacts."""
    game_context: dict[str, Any] = {}
    play_by_play_context: list[dict[str, Any]] = []
    court_report_context: dict[str, Any] = {}
    if replay_path:
        replay_payload = read_json(Path(replay_path))
        game_context.update(
            {
                "game_id": replay_payload.get("game_id", ""),
                "home_team": replay_payload.get("home_team", ""),
                "away_team": replay_payload.get("away_team", ""),
                "matchup": f"{replay_payload.get('away_team', '')} @ {replay_payload.get('home_team', '')}".strip(),
            }
        )
        play_by_play_context = list(replay_payload.get("events", []))
    if court_report_path:
        court_report = CourtReport.from_file(court_report_path)
        court_report_context = court_report.to_prompt_context()
        game_context.update(
            {
                "game_id": court_report.game_id or game_context.get("game_id", ""),
                "title": court_report.title,
                "home_team": court_report.home_team or game_context.get("home_team", ""),
                "away_team": court_report.away_team or game_context.get("away_team", ""),
                "final_score": court_report.final_score,
                "mvp": court_report.mvp,
            }
        )

    observations_source = "none"
    if auto_observations:
        if not replay_path:
            raise RuntimeError("--auto-observations requires --replay.")
        observations = build_observations_from_pbp(
            replay_path,
            court_report_path=court_report_path or None,
            video_total_seconds=video_total_seconds,
            video_period_windows=video_period_windows,
            periods=auto_periods,
        )
        save_auto_observations(DEFAULT_AUTO_OBSERVATIONS_PATH, observations)
        observations_source = "auto_pbp"
    else:
        observations = _load_observations(observations_path) if observations_path else []
        observations_source = "manual_file" if observations_path else "none"
    if not observations and frame_manifest_path:
        observations = _observations_from_frame_manifest(
            frame_manifest_path,
            game_context=game_context,
            use_vision=use_vision,
        )
        observations_source = "frame_manifest"
    if not observations:
        raise RuntimeError(
            "No observations available. Provide --observations, or provide "
            "--frame-manifest with --use-vision after configuring VISION_API_KEY."
        )

    analyzer = VideoScoutAnalyzer(enable_llm=use_llm)
    report = analyzer.analyze(
        observations,
        game_context=game_context,
        play_by_play_context=play_by_play_context,
        court_report_context=court_report_context,
        use_reasoning_model=use_reasoner,
        target_chars=target_chars,
    )

    output_base = Path(output_dir) if output_dir else Path("data") / "generated" / "video_scout" / timestamp_slug()
    ensure_dir(output_base)
    clip_manifest = _build_tactical_clips(
        video_path=video_path,
        observations=observations,
        output_dir=output_base / "clips",
        before_seconds=clip_before_seconds,
        after_seconds=clip_after_seconds,
        generate_gifs=generate_gifs,
        gif_fps=gif_fps,
        gif_width=gif_width,
    )
    write_json(output_base / "observations.normalized.json", [item.to_dict() for item in observations])
    write_json(output_base / "clip_manifest.json", clip_manifest)
    write_json(output_base / "report.json", report.to_dict())
    write_text(output_base / "report.md", _render_markdown(report, clip_manifest=clip_manifest))
    llm_steps_summary = _summarize_llm_steps(report.metadata.get("llm_steps", []))

    return {
        "workflow": "video_scout",
        "video_path": video_path or "",
        "observations_path": observations_path or "",
        "observations_source": observations_source,
        "auto_observations": auto_observations,
        "auto_observations_path": str(DEFAULT_AUTO_OBSERVATIONS_PATH.resolve()) if auto_observations else "",
        "frame_manifest_path": frame_manifest_path or "",
        "replay_path": replay_path or "",
        "court_report_path": court_report_path or "",
        "use_llm": use_llm,
        "use_vision": use_vision,
        "target_chars": target_chars,
        "use_reasoner": use_reasoner,
        "observation_count": len(observations),
        "segment_count": len(report.key_segments),
        "clip_count": len(clip_manifest.get("clips", [])),
        "clip_status": clip_manifest.get("status", ""),
        "gif_enabled": generate_gifs,
        "video_period_windows": {
            str(period): [round(window[0], 2), round(window[1], 2)]
            for period, window in (video_period_windows or {}).items()
        },
        "auto_periods": sorted(auto_periods) if auto_periods else [],
        "llm_used_successfully": bool(report.metadata.get("llm_used_successfully", False)),
        "llm_steps_summary": llm_steps_summary,
        "output_dir": str(output_base.resolve()),
        "title": report.title,
    }


def _build_tactical_clips(
    *,
    video_path: str | None,
    observations: list[VisualObservation],
    output_dir: Path,
    before_seconds: float,
    after_seconds: float,
    generate_gifs: bool,
    gif_fps: int,
    gif_width: int,
) -> dict[str, Any]:
    clips = []
    ffmpeg_path = shutil.which("ffmpeg")
    source_video = Path(video_path).resolve() if video_path else None
    can_cut = bool(ffmpeg_path and source_video and source_video.is_file())
    status = "cut" if can_cut else "plan_only"
    reason = ""
    if not video_path:
        reason = "No --video provided; generated a tactical clip plan only."
    elif not source_video or not source_video.is_file():
        reason = f"Video file not found: {video_path}; generated a tactical clip plan only."
    elif not ffmpeg_path:
        reason = "ffmpeg is not installed or not on PATH; generated a tactical clip plan only."

    ensure_dir(output_dir)
    for index, observation in enumerate(observations, start=1):
        start = observation.clip_start_seconds
        end = observation.clip_end_seconds
        if start is None and end is None:
            start = max(0.0, observation.timecode_seconds - before_seconds)
            end = max(start + 1.0, observation.timecode_seconds + after_seconds)
        elif start is None:
            end = float(end)
            start = max(0.0, end - before_seconds)
        elif end is None:
            start = max(0.0, float(start) - before_seconds)
            end = max(start + 1.0, observation.timecode_seconds + after_seconds)
        else:
            start = max(0.0, float(start) - before_seconds)
            end = float(end) + after_seconds
        duration = max(1.0, end - start)
        label = observation.clip_label or observation.observation_id or f"clip_{index:03d}"
        safe_label = _safe_filename(label)
        output_path = output_dir / f"{index:03d}_{safe_label}.mp4"
        gif_path = output_dir / f"{index:03d}_{safe_label}.gif"
        clip = {
            "index": index,
            "observation_id": observation.observation_id,
            "label": label,
            "period": observation.period,
            "clock": observation.clock,
            "event_description": observation.event_description,
            "tactic_tags": observation.tactic_tags,
            "players": observation.players,
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "duration_seconds": round(duration, 2),
            "output_path": str(output_path.resolve()),
            "gif_path": str(gif_path.resolve()),
            "status": "planned",
            "gif_status": "planned" if generate_gifs else "disabled",
            "error": "",
            "gif_error": "",
        }
        if can_cut and source_video is not None:
            command = [
                str(ffmpeg_path),
                "-y",
                "-ss",
                f"{start:.2f}",
                "-i",
                str(source_video),
                "-t",
                f"{duration:.2f}",
                "-c",
                "copy",
                str(output_path),
            ]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
                if completed.returncode == 0 and output_path.exists():
                    clip["status"] = "cut"
                else:
                    clip["status"] = "failed"
                    clip["error"] = (completed.stderr or completed.stdout)[-1000:]
            except Exception as exc:
                clip["status"] = "failed"
                clip["error"] = str(exc)
            if generate_gifs:
                gif_command = [
                    str(ffmpeg_path),
                    "-y",
                    "-ss",
                    f"{start:.2f}",
                    "-i",
                    str(source_video),
                    "-t",
                    f"{duration:.2f}",
                    "-vf",
                    f"fps={gif_fps},scale={gif_width}:-1:flags=lanczos",
                    "-loop",
                    "0",
                    str(gif_path),
                ]
                try:
                    completed = subprocess.run(gif_command, capture_output=True, text=True, timeout=90)
                    if completed.returncode == 0 and gif_path.exists():
                        clip["gif_status"] = "generated"
                    else:
                        clip["gif_status"] = "failed"
                        clip["gif_error"] = (completed.stderr or completed.stdout)[-1000:]
                except Exception as exc:
                    clip["gif_status"] = "failed"
                    clip["gif_error"] = str(exc)
        clips.append(clip)

    return {
        "status": status,
        "reason": reason,
        "video_path": str(source_video) if source_video else "",
        "ffmpeg_path": ffmpeg_path or "",
        "clip_before_seconds": before_seconds,
        "clip_after_seconds": after_seconds,
        "generate_gifs": generate_gifs,
        "gif_fps": gif_fps,
        "gif_width": gif_width,
        "clips": clips,
    }


def _safe_filename(value: str) -> str:
    keep = []
    for char in value.strip():
        if char.isalnum() or char in {"-", "_"}:
            keep.append(char)
        elif char.isspace():
            keep.append("_")
    return "".join(keep)[:80] or "clip"


def _load_observations(path: str) -> list[VisualObservation]:
    payload = read_json(Path(path))
    raw_items = payload.get("observations", payload if isinstance(payload, list) else [])
    if not isinstance(raw_items, list):
        raise ValueError("Observations file must be a list or contain an `observations` list.")
    return [VisualObservation.from_dict(item) for item in raw_items if isinstance(item, dict)]


def _summarize_llm_steps(raw_steps: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return []
    summary: list[dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "step": str(item.get("step", "")),
                "model": str(item.get("model", "")),
                "status": str(item.get("status", "")),
                "latency_seconds": float(item.get("latency_seconds", 0.0) or 0.0),
                "fallback_reason": str(item.get("fallback_reason", "")),
            }
        )
    return summary


def _print_llm_pipeline_status(summary: dict[str, Any]) -> None:
    steps = summary.get("llm_steps_summary", [])
    print("\nLLM Pipeline Status")
    print("-------------------")
    print(f"llm_used_successfully: {bool(summary.get('llm_used_successfully', False))}")
    if not isinstance(steps, list) or not steps:
        print("No LLM step metadata recorded.")
        return
    for item in steps:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("fallback_reason", ""))
        suffix = f" | fallback_reason={reason}" if reason else ""
        print(
            f"- {item.get('step', '')}: {item.get('status', '')} "
            f"| model={item.get('model', '')} "
            f"| latency={float(item.get('latency_seconds', 0.0) or 0.0):.2f}s"
            f"{suffix}"
        )


def _observations_from_frame_manifest(
    frame_manifest_path: str,
    *,
    game_context: dict[str, Any],
    use_vision: bool,
) -> list[VisualObservation]:
    manifest = read_json(Path(frame_manifest_path))
    frames = [
        FrameSample(**item)
        for item in manifest.get("frames", [])
        if isinstance(item, dict)
    ]
    if not use_vision:
        return [
            VisualObservation(
                observation_id=frame.frame_id,
                timecode_seconds=frame.timecode_seconds,
                period=frame.period,
                clock=frame.clock,
                frame_path=frame.image_path,
                event_description=frame.linked_event_description,
                tactic_tags=["unlabeled_frame"],
                action_summary="已抽取关键帧，但尚未配置视觉模型或人工标注。",
                decision_analysis="该帧需要视觉模型或人工标注后才能进入正式战术判断。",
                evidence=[frame.image_path],
                confidence=0.35,
                source="frame_manifest",
            )
            for frame in frames
        ]
    client = VisionClient.from_env()
    return [client.analyze_frame(frame, game_context=game_context) for frame in frames]


def _render_markdown(report: VideoScoutReport, *, clip_manifest: dict[str, Any] | None = None) -> str:
    lines = [
        f"# {report.title}",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
        "## Full Tactical Analysis",
        "",
        report.full_analysis or "No long-form analysis was generated.",
        "",
        "## Key Tactical Segments",
        "",
    ]
    if clip_manifest:
        lines.extend(
            [
                "## Tactical Clip Manifest",
                "",
                f"- Status: `{clip_manifest.get('status', '')}`",
                f"- Reason: {clip_manifest.get('reason', '')}",
                f"- Video: `{clip_manifest.get('video_path', '')}`",
                f"- GIF: `{clip_manifest.get('generate_gifs', False)}` / fps={clip_manifest.get('gif_fps', '')} / width={clip_manifest.get('gif_width', '')}",
                "",
            ]
        )
        for clip in clip_manifest.get("clips", []):
            lines.append(
                f"- `{clip.get('label', '')}` | Q{clip.get('period', '')} {clip.get('clock', '')} | "
                f"{clip.get('start_seconds', '')}-{clip.get('end_seconds', '')}s | {clip.get('status', '')} | "
                f"{clip.get('output_path', '')} | gif={clip.get('gif_status', '')} | {clip.get('gif_path', '')}"
            )
        lines.append("")
    for index, segment in enumerate(report.key_segments, start=1):
        lines.extend(
            [
                f"### {index}. Q{segment.period} {segment.clock} | {segment.timecode}",
                "",
                f"- Tactic: `{segment.tactic_type}`",
                f"- Observation: {segment.observation}",
                f"- Decision: {segment.decision_analysis}",
                f"- Win/Loss Impact: {segment.win_loss_impact}",
                f"- Confidence: `{segment.confidence:.2f}`",
                "- Evidence:",
            ]
        )
        for item in segment.evidence:
            lines.append(f"  - {item}")
        lines.append("")

    lines.extend(["## Tactical Themes", ""])
    lines.extend([f"- {item}" for item in report.tactical_themes])
    lines.extend(["", "## Quarter / Flow Reading", ""])
    lines.extend([f"- {item}" for item in report.quarter_flow])
    lines.extend(["## Deciding Factors", ""])
    lines.extend([f"- {item}" for item in report.deciding_factors])
    lines.extend(["", "## MVP Analysis", ""])
    lines.append(report.mvp_analysis or "No MVP analysis was generated.")
    lines.extend(["", "## Player Tactical Profiles", ""])
    for profile in report.player_tactical_profiles:
        lines.extend(
            [
                f"### {profile.get('player', '')} / {profile.get('team', '')}",
                "",
                f"- Role: {profile.get('role', '')}",
                f"- Tactical Read: {profile.get('tactical_read', '')}",
                "- Stat Evidence:",
            ]
        )
        for item in profile.get("stat_evidence", []):
            lines.append(f"  - {item}")
        lines.append("- Video Evidence:")
        for item in profile.get("video_evidence", []):
            lines.append(f"  - {item}")
        lines.append(f"- Confidence: `{float(profile.get('confidence', 0.0) or 0.0):.2f}`")
        lines.append("")
    lines.extend(["", "## Player Decision Notes", ""])
    lines.extend([f"- {item}" for item in report.player_decision_notes])
    lines.extend(["", "## Content Angles", ""])
    lines.extend([f"- {item}" for item in report.content_angles])
    lines.extend(["", "## Limitations", ""])
    lines.extend([f"- {item}" for item in report.limitations])
    lines.extend(["", "## Evidence Index", ""])
    for item in report.evidence_index:
        lines.append(
            f"- `{item.get('id', '')}` | {item.get('timecode', '')} | "
            f"{item.get('source', '')} | {item.get('value', '')}"
        )
    lines.append("")
    return "\n".join(lines)


def _render_markdown(report: VideoScoutReport, *, clip_manifest: dict[str, Any] | None = None) -> str:
    lines = [
        f"# {report.title}",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
        "## Full Tactical Analysis",
        "",
        _sanitize_markdown_body(report.full_analysis) or "No long-form analysis was generated.",
        "",
        "## Tactical Clip Manifest",
        "",
    ]
    if clip_manifest:
        lines.extend(
            [
                f"- Status: `{clip_manifest.get('status', '')}`",
                f"- Reason: {clip_manifest.get('reason', '')}",
                f"- Video: `{clip_manifest.get('video_path', '')}`",
                f"- GIF: `{clip_manifest.get('generate_gifs', False)}` / fps={clip_manifest.get('gif_fps', '')} / width={clip_manifest.get('gif_width', '')}",
                "",
            ]
        )
        for clip in clip_manifest.get("clips", []):
            lines.append(
                f"- `{clip.get('label', '')}` | Q{clip.get('period', '')} {clip.get('clock', '')} | "
                f"{clip.get('start_seconds', '')}-{clip.get('end_seconds', '')}s | {clip.get('status', '')} | "
                f"{clip.get('output_path', '')} | gif={clip.get('gif_status', '')} | {clip.get('gif_path', '')}"
            )
        lines.append("")
    else:
        lines.extend(["No tactical clip manifest was generated.", ""])

    lines.extend(["## Key Tactical Segments", ""])
    for index, segment in enumerate(report.key_segments, start=1):
        lines.extend(
            [
                f"### {index}. Q{segment.period} {segment.clock} | {segment.timecode}",
                "",
                f"- Tactic: `{segment.tactic_type}`",
                f"- Observation: {segment.observation}",
                f"- Decision: {segment.decision_analysis}",
                f"- Win/Loss Impact: {segment.win_loss_impact}",
                f"- Confidence: `{segment.confidence:.2f}`",
                "- Evidence:",
            ]
        )
        for item in segment.evidence:
            lines.append(f"  - {item}")
        lines.append("")

    lines.extend(["## Tactical Themes", ""])
    lines.extend([f"- {item}" for item in report.tactical_themes] or ["- No tactical themes were generated."])
    lines.extend(["", "## Quarter Flow", ""])
    lines.extend([f"- {item}" for item in report.quarter_flow] or ["- No quarter flow reading was generated."])
    lines.extend(["", "## Deciding Factors", ""])
    lines.extend([f"- {item}" for item in report.deciding_factors] or ["- No deciding factors were generated."])
    lines.extend(["", "## MVP Analysis", ""])
    lines.append(report.mvp_analysis or "No MVP analysis was generated.")
    lines.extend(["", "## Player Tactical Profiles", ""])
    if report.player_tactical_profiles:
        for profile in report.player_tactical_profiles:
            lines.extend(
                [
                    f"### {profile.get('player', '')} / {profile.get('team', '')}",
                    "",
                    f"- Role: {profile.get('role', '')}",
                    f"- Tactical Read: {profile.get('tactical_read', '')}",
                    "- Stat Evidence:",
                ]
            )
            for item in profile.get("stat_evidence", []):
                lines.append(f"  - {item}")
            lines.append("- Video Evidence:")
            for item in profile.get("video_evidence", []):
                lines.append(f"  - {item}")
            lines.append(f"- Confidence: `{float(profile.get('confidence', 0.0) or 0.0):.2f}`")
            lines.append("")
    else:
        lines.extend(["No player tactical profiles were generated.", ""])

    lines.extend(["## Limitations", ""])
    lines.extend([f"- {item}" for item in report.limitations] or ["- No limitations were generated."])
    lines.extend(["", "## Evidence Index", ""])
    for item in report.evidence_index:
        lines.append(
            f"- `{item.get('id', '')}` | {item.get('timecode', '')} | "
            f"{item.get('source', '')} | {item.get('value', '')}"
        )
    lines.append("")
    return "\n".join(lines)


def _sanitize_markdown_body(text: str) -> str:
    """Keep generated prose from breaking the fixed outer report structure."""
    cleaned = []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            cleaned.append("### " + line[3:])
        else:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def _parse_period_video_windows(value: str) -> dict[int, tuple[float, float]]:
    """Parse period-to-video-time anchors from the CLI."""
    windows: dict[int, tuple[float, float]] = {}
    text = str(value or "").strip()
    if not text:
        return windows
    for chunk in text.split(","):
        item = chunk.strip()
        if not item:
            continue
        if ":" not in item or "-" not in item:
            raise ValueError(
                "Invalid --period-video-windows item. Expected format like 1:900-2300."
            )
        period_text, range_text = item.split(":", 1)
        start_text, end_text = range_text.split("-", 1)
        period = int(period_text)
        start = float(start_text)
        end = float(end_text)
        if period <= 0 or end <= start:
            raise ValueError(
                "Invalid --period-video-windows values. Period must be positive and end must be greater than start."
            )
        windows[period] = (start, end)
    return windows


def _parse_periods(value: str) -> set[int] | None:
    """Parse optional comma-separated period filters."""
    text = str(value or "").strip()
    if not text:
        return None
    periods = {int(item.strip()) for item in text.split(",") if item.strip()}
    if any(period <= 0 for period in periods):
        raise ValueError("--auto-periods values must be positive integers.")
    return periods


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Video Scout tactical analysis.")
    parser.add_argument("--video", default="", help="Optional full-game or highlight video path.")
    parser.add_argument("--observations", default="", help="Observation JSON file.")
    parser.add_argument("--frame-manifest", default="", help="Frame manifest from frame_sampler.")
    parser.add_argument("--replay", default="", help="Optional play-by-play replay JSON.")
    parser.add_argument("--court-report", default="", help="Optional smart-court AI report JSON.")
    parser.add_argument("--output-dir", default="", help="Optional output folder.")
    parser.add_argument("--use-llm", action="store_true", help="Use DeepSeek for tactical report.")
    parser.add_argument("--use-vision", action="store_true", help="Use configured vision model for frames.")
    parser.add_argument("--auto-observations", action="store_true", help="Build observations from --replay automatically.")
    parser.add_argument("--auto-periods", default="", help="Optional comma-separated periods for auto observations, e.g. 1 or 1,2.")
    parser.add_argument("--video-total-seconds", type=float, default=0.0, help="Optional source video duration for PBP-to-video mapping.")
    parser.add_argument(
        "--period-video-windows",
        default="",
        help="Optional per-period video windows, e.g. 1:900-2300,2:2500-3900,3:4300-5700,4:5900-7100.",
    )
    parser.add_argument("--target-chars", type=int, default=2000, help="Target Chinese character count for the report.")
    parser.add_argument("--use-reasoner", action="store_true", help="Use the slower reasoning model for deeper analysis.")
    parser.add_argument("--clip-before", type=float, default=14.0, help="Seconds before each event to include in tactical clips.")
    parser.add_argument("--clip-after", type=float, default=5.0, help="Seconds after each event to include in tactical clips.")
    parser.add_argument("--no-gif", action="store_true", help="Disable GIF generation for tactical clips.")
    parser.add_argument("--gif-fps", type=int, default=10, help="GIF frame rate when ffmpeg is available.")
    parser.add_argument("--gif-width", type=int, default=480, help="GIF output width when ffmpeg is available.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_video_scout_demo(
        video_path=args.video or None,
        observations_path=args.observations or None,
        frame_manifest_path=args.frame_manifest or None,
        replay_path=args.replay or None,
        court_report_path=args.court_report or None,
        output_dir=args.output_dir or None,
        use_llm=args.use_llm,
        use_vision=args.use_vision,
        target_chars=args.target_chars,
        use_reasoner=args.use_reasoner,
        auto_observations=args.auto_observations,
        video_total_seconds=args.video_total_seconds or None,
        auto_periods=_parse_periods(args.auto_periods),
        clip_before_seconds=args.clip_before,
        clip_after_seconds=args.clip_after,
        generate_gifs=not args.no_gif,
        gif_fps=args.gif_fps,
        gif_width=args.gif_width,
        video_period_windows=_parse_period_video_windows(args.period_video_windows),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _print_llm_pipeline_status(summary)


if __name__ == "__main__":
    main()
