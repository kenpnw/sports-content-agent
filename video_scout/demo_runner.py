"""CLI runner for the Video Scout Agent."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from storage.file_store import ensure_dir, read_json, timestamp_slug, write_json, write_text
from video_scout.auto_observation_builder import (
    DEFAULT_AUTO_OBSERVATIONS_PATH,
    build_observations_from_pbp,
    save_auto_observations,
)
from video_scout.court_report import CourtReport
from video_scout.event_anchor_refiner import refine_event_anchor
from video_scout.models import FrameSample, VisualObservation, VideoScoutReport
from video_scout.tactic_analyzer import VideoScoutAnalyzer
from video_scout.vision_client import VisionClient


REGULATION_PERIOD_SECONDS = 720.0
DEFAULT_CLIP_BEFORE_SECONDS = 22.0
DEFAULT_CLIP_AFTER_SECONDS = 4.0
REFINEMENT_SOFT_SHIFT_WARNING_SECONDS = 120.0
REFINEMENT_HARD_SHIFT_DROP_SECONDS = 300.0


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
    clip_before_seconds: float = DEFAULT_CLIP_BEFORE_SECONDS,
    clip_after_seconds: float = DEFAULT_CLIP_AFTER_SECONDS,
    generate_gifs: bool = True,
    gif_fps: int = 10,
    gif_width: int = 480,
    video_period_windows: dict[int, tuple[float, float]] | None = None,
    time_map_path: str | None = None,
    apply_time_map: bool = False,
    refine_events: bool = False,
    roi_path: str | None = None,
    play_segments_path: str | None = None,
) -> dict[str, Any]:
    # Load play_segments early so it's available later
    play_segments_payload: dict[str, Any] | None = None
    if play_segments_path:
        try:
            from video_scout.play_segment_detector import load_play_segments_payload
            play_segments_payload = load_play_segments_payload(play_segments_path)
            print(f"[demo_runner] loaded play_segments: {len(play_segments_payload.get('play_segments', []))} play segments, "
                  f"{len(play_segments_payload.get('non_play_segments', []))} non-play")
        except Exception as exc:
            print(f"[demo_runner] WARNING: could not load play_segments from {play_segments_path}: {exc}")
            play_segments_payload = None
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

    time_map_summary = _empty_time_map_summary(time_map_path=time_map_path, requested=apply_time_map)
    time_map_samples: list[dict[str, Any]] = []
    if time_map_path and apply_time_map:
        try:
            time_map = read_json(Path(time_map_path))
            time_map_samples = [
                item for item in time_map.get("samples", []) if isinstance(item, dict)
            ]
            observations, time_map_summary = _apply_time_map(
                observations,
                time_map,
                time_map_path=time_map_path,
                clip_before_seconds=clip_before_seconds,
                clip_after_seconds=clip_after_seconds,
            )
        except Exception as exc:
            print(f"[warning] Failed to apply time map, keeping original clip times: {exc}")
            time_map_summary = _empty_time_map_summary(
                time_map_path=time_map_path,
                requested=apply_time_map,
                error=str(exc),
            )

    refinement_summary = _empty_refinement_summary(requested=refine_events)
    if refine_events:
        try:
            resolved_roi_path = _resolve_refinement_roi_path(video_path=video_path, roi_path=roi_path)
            roi_dict = read_json(resolved_roi_path)
            if not time_map_samples and time_map_path:
                time_map_payload = read_json(Path(time_map_path))
                time_map_samples = [
                    item for item in time_map_payload.get("samples", []) if isinstance(item, dict)
                ]
            print(
                "[refine-events] Long OCR task: using multi-strategy search "
                "(A: ±20s/0.5s, B: ±60s/1s, C: ±120s/2s)."
            )
            observations, refinement_summary = _refine_observation_clips(
                observations,
                video_path=video_path or "",
                roi_dict=roi_dict,
                time_map_samples=time_map_samples,
                clip_before_seconds=clip_before_seconds,
                clip_after_seconds=clip_after_seconds,
            )
            refinement_summary["roi_path"] = str(resolved_roi_path)
            if float(refinement_summary.get("refinement_elapsed_seconds", 0.0) or 0.0) > 2400.0:
                raise RuntimeError("Per-event refinement exceeded 40 minutes.")
        except Exception as exc:
            print(f"[warning] Per-event refinement failed, keeping original clip times: {exc}")
            refinement_summary = _empty_refinement_summary(
                requested=refine_events,
                error=str(exc),
                fallback_clips=len(observations),
            )
            refinement_summary["total_observations"] = len(observations)

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
        play_segments_payload=play_segments_payload,
    )
    clip_manifest.update(
        {
            "time_map_applied": bool(time_map_summary.get("applied", False)),
            "time_map_path": str(time_map_summary.get("path", "")),
            "period_anchors_used": time_map_summary.get("period_anchors_used", {}),
            "events_refined": int(refinement_summary.get("events_refined", 0) or 0),
            "refinement_total_ocr_calls": int(refinement_summary.get("refinement_total_ocr_calls", 0) or 0),
            "refinement_elapsed_seconds": round(
                float(refinement_summary.get("refinement_elapsed_seconds", 0.0) or 0.0),
                3,
            ),
            "refinement_strategy_distribution": refinement_summary.get("strategy_distribution", {}),
            "refinement_warned_shift_count": int(refinement_summary.get("warned_shift_count", 0) or 0),
            "refinement_monotonic_fallbacks": int(refinement_summary.get("monotonic_fallbacks", 0) or 0),
            "refinement_hard_threshold_drops": int(refinement_summary.get("hard_threshold_drops", 0) or 0),
            "refinement_sample_fallbacks": int(refinement_summary.get("sample_fallbacks", 0) or 0),
            "neighbor_interpolation_count": int(refinement_summary.get("neighbor_interpolation_count", 0) or 0),
            "linear_fallback_no_neighbor_count": int(
                refinement_summary.get("linear_fallback_no_neighbor_count", 0) or 0
            ),
        }
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
        "time_map": time_map_summary,
        "event_refinement": refinement_summary,
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
    play_segments_payload: dict[str, Any] | None = None,
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

    # Stats for play-segment snapping
    snap_stats = {"applied": play_segments_payload is not None, "snapped": 0, "kept": 0, "no_nearby": 0, "details": []}

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
            start = max(0.0, float(start))
            end = float(end)

        # ---- play-segment snap ----
        if play_segments_payload is not None:
            from video_scout.play_segment_detector import snap_clip_window, normalize_event_position
            orig_start, orig_end = start, end
            start, end, snap_info = snap_clip_window(
                play_segments_payload, start, end, max_snap_distance=30.0, min_clip_seconds=8.0,
            )
            if snap_info["snapped"]:
                if "inside_play" in snap_info["reason"]:
                    snap_stats["snapped"] += 1
                else:
                    snap_stats["snapped"] += 1
            else:
                snap_stats["no_nearby"] += 1

            # ---- event-position normalization ----
            # Reconstruct event video time from the original (pre-snap) clip window:
            # original was [event - before_seconds, event + after_seconds]
            # so event_video_time = orig_end - after_seconds
            event_video_time = orig_end - after_seconds
            seg = snap_info.get("segment") or {}
            if seg.get("start") is not None and seg.get("end") is not None:
                # Normalize so event lands at 78% through clip (audience sees ~20s build-up + ~6s after)
                norm_start, norm_end = normalize_event_position(
                    clip_start=start, clip_end=end, event_time=event_video_time,
                    target_ratio=0.78,
                    seg_start=seg["start"], seg_end=seg["end"],
                )
                if (norm_end - norm_start) >= 8.0 and (
                    abs(norm_start - start) > 0.5 or abs(norm_end - end) > 0.5
                ):
                    snap_info["normalized"] = True
                    snap_info["pre_norm"] = [round(start, 2), round(end, 2)]
                    start, end = norm_start, norm_end
                    snap_info["adjusted"] = [round(start, 2), round(end, 2)]

            snap_stats["details"].append({
                "index": index,
                "observation_id": observation.observation_id,
                "original": snap_info["original"],
                "adjusted": snap_info["adjusted"],
                "reason": snap_info["reason"] + ("|event_normalized" if snap_info.get("normalized") else ""),
            })
            # Update observation so downstream metadata reflects the actual clip window
            observation.clip_start_seconds = start
            observation.clip_end_seconds = end

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
            "refinement_mode": str(getattr(observation, "refinement_mode", "")),
            "refinement_seed_seconds": _optional_round(getattr(observation, "refinement_seed_seconds", None)),
            "refinement_matched_seconds": _optional_round(getattr(observation, "refinement_matched_seconds", None)),
            "refinement_ocr_calls": int(getattr(observation, "refinement_ocr_calls", 0) or 0),
            "refinement_strategy": str(getattr(observation, "refinement_strategy", "")),
            "refinement_search_attempts": int(getattr(observation, "refinement_search_attempts", 0) or 0),
            "refinement_shift_seconds": _optional_round(getattr(observation, "refinement_shift_seconds", None)),
            "refinement_warning": str(getattr(observation, "refinement_warning", "")),
            "monotonicity_violated": bool(getattr(observation, "monotonicity_violated", False)),
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
        "play_segment_snap": snap_stats,
    }


def _apply_time_map(
    observations: list[VisualObservation],
    time_map_dict: dict[str, Any],
    *,
    time_map_path: str,
    clip_before_seconds: float,
    clip_after_seconds: float,
) -> tuple[list[VisualObservation], dict[str, Any]]:
    """Remap observation clip windows from game time to real video seconds."""
    anchors = _extract_reliable_period_anchors(time_map_dict)
    adjusted = 0
    fallback = 0
    warnings: list[str] = []
    for observation in observations:
        period = int(observation.period or 0)
        anchor = anchors.get(period)
        if anchor is None:
            fallback += 1
            warning = (
                f"Time map fallback for {observation.observation_id or '<unknown>'}: "
                f"period {period} anchor missing or unreliable."
            )
            warnings.append(warning)
            print(f"[warning] {warning}")
            continue
        period_elapsed_seconds = float(observation.timecode_seconds) - (period - 1) * REGULATION_PERIOD_SECONDS
        if period_elapsed_seconds < 0:
            fallback += 1
            warning = (
                f"Time map fallback for {observation.observation_id or '<unknown>'}: "
                f"timecode_seconds={observation.timecode_seconds} is outside period {period}."
            )
            warnings.append(warning)
            print(f"[warning] {warning}")
            continue
        video_event_seconds = float(anchor) + period_elapsed_seconds
        observation.clip_start_seconds = max(0.0, video_event_seconds - clip_before_seconds)
        observation.clip_end_seconds = max(
            observation.clip_start_seconds + 1.0,
            video_event_seconds + clip_after_seconds,
        )
        adjusted += 1
    return observations, {
        "requested": True,
        "applied": adjusted > 0,
        "path": str(time_map_path),
        "period_anchors_used": {str(period): round(value, 3) for period, value in sorted(anchors.items())},
        "adjusted_clips": adjusted,
        "fallback_clips": fallback,
        "warnings": warnings,
        "error": "",
    }


def _extract_reliable_period_anchors(time_map_dict: dict[str, Any]) -> dict[int, float]:
    anchors_payload = time_map_dict.get("period_anchors", {})
    reliability_payload = time_map_dict.get("period_anchors_reliability", {})
    anchors: dict[int, float] = {}
    if not isinstance(anchors_payload, dict):
        return anchors
    for raw_period, raw_anchor in anchors_payload.items():
        try:
            period = int(raw_period)
            reliability = str(reliability_payload.get(str(raw_period), reliability_payload.get(raw_period, "")))
            if reliability and reliability != "reliable":
                continue
            anchors[period] = float(raw_anchor)
        except (TypeError, ValueError):
            continue
    return anchors


def _resolve_refinement_roi_path(*, video_path: str | None, roi_path: str | None) -> Path:
    if roi_path:
        candidate = Path(roi_path)
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"ROI file not found: {roi_path}")
    if not video_path:
        raise FileNotFoundError("--refine-events requires --video and a scoreboard ROI JSON.")
    video = Path(video_path)
    inferred = video.with_suffix(".scoreboard_roi.json")
    if inferred.is_file():
        return inferred
    raise FileNotFoundError(
        "ROI file not found. Pass --roi or place a file next to the video named "
        f"{inferred.name}."
    )


def _refine_observation_clips(
    observations: list[VisualObservation],
    *,
    video_path: str,
    roi_dict: dict[str, Any],
    time_map_samples: list[dict[str, Any]],
    clip_before_seconds: float,
    clip_after_seconds: float,
) -> tuple[list[VisualObservation], dict[str, Any]]:
    """Refine each observation clip window by OCR-checking the nearby scoreboard."""
    started_at = time.perf_counter()
    refined = 0
    fallback = 0
    skipped = 0
    total_ocr_calls = 0
    warnings: list[str] = []
    warned_shift_count = 0
    hard_threshold_drops = 0
    sample_fallbacks = 0
    strategy_distribution = {
        "A": 0,
        "B": 0,
        "C": 0,
        "sample_fallback": 0,
        "linear_fallback": 0,
    }

    for index, observation in enumerate(observations, start=1):
        seed = _event_seed_from_clip(observation)
        expected_clock = _expected_clock_remaining(observation)
        if seed is None or expected_clock is None:
            fallback += 1
            skipped += 1
            _mark_refinement(
                observation,
                mode="fallback",
                seed=seed,
                matched=None,
                ocr_calls=0,
                strategy="linear_fallback",
                search_attempts=0,
                shift=0.0,
                warning="",
                monotonicity_violated=False,
            )
            strategy_distribution["linear_fallback"] += 1
            continue

        result = refine_event_anchor(
            video_path=video_path,
            roi_dict=roi_dict,
            expected_period=int(observation.period),
            expected_clock_remaining_seconds=expected_clock,
            seed_video_seconds=seed,
            time_map_samples=time_map_samples,
        )
        total_ocr_calls += int(result.ocr_calls_made)
        strategy = _normalize_refinement_strategy(result.strategy_used)
        strategy_distribution[strategy] = strategy_distribution.get(strategy, 0) + 1
        if result.mode == "ocr_refined":
            shift = abs(float(result.video_seconds) - float(result.seed_video_seconds))
            warning = ""
            if shift > REFINEMENT_HARD_SHIFT_DROP_SECONDS:
                hard_threshold_drops += 1
                fallback_seconds = float(result.seed_video_seconds)
                observation.clip_start_seconds = max(0.0, fallback_seconds - clip_before_seconds)
                observation.clip_end_seconds = max(
                    observation.clip_start_seconds + 1.0,
                    fallback_seconds + clip_after_seconds,
                )
                _mark_refinement(
                    observation,
                    mode="fallback",
                    seed=float(result.seed_video_seconds),
                    matched=None,
                    ocr_calls=result.ocr_calls_made,
                    strategy=result.strategy_used,
                    search_attempts=result.search_attempts,
                    shift=shift,
                    warning="shift > 300s dropped to seed",
                    monotonicity_violated=False,
                )
                fallback += 1
                print(
                    f"[refine-events] {index}/{len(observations)} "
                    f"{observation.observation_id or '<unknown>'}: fallback "
                    f"strategy={result.strategy_used} seed={result.seed_video_seconds:.1f} "
                    f"shift={shift:.1f}s hard_drop ocr_calls={result.ocr_calls_made}"
                )
                continue
            if shift > REFINEMENT_SOFT_SHIFT_WARNING_SECONDS:
                warning = "shift > 120s but accepted"
                warnings.append(f"{observation.observation_id or '<unknown>'}: {warning} ({shift:.1f}s)")
                warned_shift_count += 1
            observation.clip_start_seconds = max(0.0, float(result.video_seconds) - clip_before_seconds)
            observation.clip_end_seconds = max(
                observation.clip_start_seconds + 1.0,
                float(result.video_seconds) + clip_after_seconds,
            )
            _mark_refinement(
                observation,
                mode="ocr_refined",
                seed=seed,
                matched=float(result.video_seconds),
                ocr_calls=result.ocr_calls_made,
                strategy=result.strategy_used,
                search_attempts=result.search_attempts,
                shift=shift,
                warning=warning,
                monotonicity_violated=False,
            )
            refined += 1
        else:
            fallback += 1
            if result.strategy_used == "sample_fallback":
                sample_fallbacks += 1
                observation.clip_start_seconds = max(0.0, float(result.video_seconds) - clip_before_seconds)
                observation.clip_end_seconds = max(
                    observation.clip_start_seconds + 1.0,
                    float(result.video_seconds) + clip_after_seconds,
                )
            shift = abs(float(result.video_seconds) - float(result.seed_video_seconds))
            _mark_refinement(
                observation,
                mode="fallback",
                seed=float(result.seed_video_seconds),
                matched=float(result.video_seconds) if result.strategy_used == "sample_fallback" else None,
                ocr_calls=result.ocr_calls_made,
                strategy=result.strategy_used,
                search_attempts=result.search_attempts,
                shift=shift,
                warning="",
                monotonicity_violated=False,
            )

        print(
            f"[refine-events] {index}/{len(observations)} "
            f"{observation.observation_id or '<unknown>'}: {getattr(observation, 'refinement_mode', '')} "
            f"strategy={result.strategy_used} seed={result.seed_video_seconds:.1f} "
            f"ocr_calls={result.ocr_calls_made}"
        )

    neighbor_interpolation_count = _interpolate_linear_fallbacks_from_neighbors(
        observations,
        clip_before_seconds=clip_before_seconds,
        clip_after_seconds=clip_after_seconds,
    )
    monotonic_fallbacks = _enforce_refinement_monotonicity(
        observations,
        clip_before_seconds=clip_before_seconds,
        clip_after_seconds=clip_after_seconds,
    )
    final_refined = sum(1 for item in observations if getattr(item, "refinement_mode", "") == "ocr_refined")
    final_neighbor = sum(
        1
        for item in observations
        if getattr(item, "refinement_strategy", "") == "neighbor_interpolation"
        and getattr(item, "refinement_mode", "") == "neighbor_interpolation"
    )
    final_linear = sum(
        1
        for item in observations
        if getattr(item, "refinement_strategy", "") == "linear_fallback"
        and getattr(item, "refinement_mode", "") == "fallback"
    )
    final_fallback = len(observations) - final_refined - final_neighbor

    elapsed = time.perf_counter() - started_at
    return observations, {
        "requested": True,
        "events_refined": final_refined,
        "fallback_clips": final_fallback,
        "skipped_clips": skipped,
        "warned_shift_count": warned_shift_count,
        "monotonic_fallbacks": monotonic_fallbacks,
        "neighbor_interpolation_count": final_neighbor,
        "linear_fallback_no_neighbor_count": final_linear,
        "sample_fallbacks": sample_fallbacks,
        "hard_threshold_drops": hard_threshold_drops,
        "total_observations": len(observations),
        "refinement_total_ocr_calls": total_ocr_calls,
        "refinement_elapsed_seconds": round(elapsed, 3),
        "strategy_distribution": strategy_distribution,
        "warnings": warnings,
        "error": "",
        "roi_path": "",
    }


def _event_seed_from_clip(observation: VisualObservation) -> float | None:
    start = observation.clip_start_seconds
    end = observation.clip_end_seconds
    if start is None or end is None:
        return None
    return (float(start) + float(end)) / 2.0 + 8.0


def _expected_clock_remaining(observation: VisualObservation) -> float | None:
    period = int(observation.period or 0)
    if period <= 0:
        return None
    elapsed_in_period = float(observation.timecode_seconds) - (period - 1) * REGULATION_PERIOD_SECONDS
    if elapsed_in_period < 0 or elapsed_in_period > REGULATION_PERIOD_SECONDS:
        return None
    return REGULATION_PERIOD_SECONDS - elapsed_in_period


def _mark_refinement(
    observation: VisualObservation,
    *,
    mode: str,
    seed: float | None,
    matched: float | None,
    ocr_calls: int,
    strategy: str,
    search_attempts: int,
    shift: float | None,
    warning: str,
    monotonicity_violated: bool,
) -> None:
    observation.refinement_mode = mode
    observation.refinement_seed_seconds = seed
    observation.refinement_matched_seconds = matched
    observation.refinement_ocr_calls = int(ocr_calls)
    observation.refinement_strategy = strategy
    observation.refinement_search_attempts = int(search_attempts)
    observation.refinement_shift_seconds = shift
    observation.refinement_warning = warning
    observation.monotonicity_violated = bool(monotonicity_violated)


def _interpolate_linear_fallbacks_from_neighbors(
    observations: list[VisualObservation],
    *,
    clip_before_seconds: float,
    clip_after_seconds: float,
) -> int:
    accepted = [
        item
        for item in observations
        if getattr(item, "refinement_mode", "") == "ocr_refined"
        and getattr(item, "refinement_matched_seconds", None) is not None
    ]
    if not accepted:
        return 0

    converted = 0
    for item in observations:
        if getattr(item, "refinement_strategy", "") != "linear_fallback":
            continue
        if getattr(item, "refinement_mode", "") != "fallback":
            continue
        estimated = _estimate_from_refined_neighbors(item, accepted)
        if estimated is None:
            continue
        seed = getattr(item, "refinement_seed_seconds", None)
        shift = abs(float(estimated) - float(seed)) if seed is not None else 0.0
        item.clip_start_seconds = max(0.0, float(estimated) - clip_before_seconds)
        item.clip_end_seconds = max(item.clip_start_seconds + 1.0, float(estimated) + clip_after_seconds)
        item.refinement_mode = "neighbor_interpolation"
        item.refinement_strategy = "neighbor_interpolation"
        item.refinement_matched_seconds = round(float(estimated), 3)
        item.refinement_shift_seconds = round(float(shift), 3)
        item.refinement_warning = str(getattr(item, "refinement_warning", "") or "")
        item.monotonicity_violated = False
        converted += 1
    return converted


def _estimate_from_refined_neighbors(
    target: VisualObservation,
    accepted: list[VisualObservation],
) -> float | None:
    period = int(target.period or 0)
    target_game = float(target.timecode_seconds)
    same_period = [item for item in accepted if int(item.period or 0) == period]
    if not same_period:
        return None
    previous = [
        item for item in same_period if float(item.timecode_seconds) < target_game
    ]
    following = [
        item for item in same_period if float(item.timecode_seconds) > target_game
    ]
    prev_item = max(previous, key=lambda item: float(item.timecode_seconds), default=None)
    next_item = min(following, key=lambda item: float(item.timecode_seconds), default=None)
    if prev_item is not None and next_item is not None:
        prev_game = float(prev_item.timecode_seconds)
        next_game = float(next_item.timecode_seconds)
        if abs(next_game - prev_game) < 1e-6:
            return None
        ratio = (target_game - prev_game) / (next_game - prev_game)
        prev_video = float(getattr(prev_item, "refinement_matched_seconds"))
        next_video = float(getattr(next_item, "refinement_matched_seconds"))
        return prev_video + ratio * (next_video - prev_video)
    if next_item is not None:
        next_game = float(next_item.timecode_seconds)
        next_video = float(getattr(next_item, "refinement_matched_seconds"))
        return next_video + (target_game - next_game)
    if prev_item is not None:
        prev_game = float(prev_item.timecode_seconds)
        prev_video = float(getattr(prev_item, "refinement_matched_seconds"))
        return prev_video + (target_game - prev_game)
    return None


def _enforce_refinement_monotonicity(
    observations: list[VisualObservation],
    *,
    clip_before_seconds: float,
    clip_after_seconds: float,
) -> int:
    fallbacks = 0
    changed = True
    while changed:
        changed = False
        for left, right in zip(observations, observations[1:]):
            left_seconds = _refinement_event_seconds(left)
            right_seconds = _refinement_event_seconds(right)
            if left_seconds is None or right_seconds is None or left_seconds < right_seconds:
                continue
            left_shift = abs(float(getattr(left, "refinement_shift_seconds", 0.0) or 0.0))
            right_shift = abs(float(getattr(right, "refinement_shift_seconds", 0.0) or 0.0))
            victim = left if left_shift >= right_shift else right
            if bool(getattr(victim, "monotonicity_violated", False)):
                continue
            seed = getattr(victim, "refinement_seed_seconds", None)
            if seed is None:
                continue
            _fallback_observation_to_seed(
                victim,
                float(seed),
                clip_before_seconds=clip_before_seconds,
                clip_after_seconds=clip_after_seconds,
            )
            fallbacks += 1
            changed = True
            break
    return fallbacks


def _refinement_event_seconds(observation: VisualObservation) -> float | None:
    matched = getattr(observation, "refinement_matched_seconds", None)
    if matched is not None:
        try:
            return float(matched)
        except (TypeError, ValueError):
            pass
    start = observation.clip_start_seconds
    end = observation.clip_end_seconds
    if start is None or end is None:
        return None
    return (float(start) + float(end)) / 2.0 + 9.0


def _fallback_observation_to_seed(
    observation: VisualObservation,
    seed: float,
    *,
    clip_before_seconds: float,
    clip_after_seconds: float,
) -> None:
    observation.clip_start_seconds = max(0.0, float(seed) - clip_before_seconds)
    observation.clip_end_seconds = max(observation.clip_start_seconds + 1.0, float(seed) + clip_after_seconds)
    observation.refinement_mode = "fallback"
    observation.refinement_matched_seconds = None
    observation.monotonicity_violated = True
    previous_warning = str(getattr(observation, "refinement_warning", "") or "")
    suffix = "monotonicity violation fallback to seed"
    observation.refinement_warning = f"{previous_warning}; {suffix}" if previous_warning else suffix


def _normalize_refinement_strategy(strategy: str) -> str:
    if strategy in {"A", "B", "C", "sample_fallback", "linear_fallback"}:
        return strategy
    if strategy == "sample_interpolation":
        return "sample_fallback"
    return "linear_fallback"


def _empty_refinement_summary(
    *,
    requested: bool,
    error: str = "",
    fallback_clips: int = 0,
) -> dict[str, Any]:
    return {
        "requested": bool(requested),
        "events_refined": 0,
        "fallback_clips": int(fallback_clips),
        "skipped_clips": 0,
        "warned_shift_count": 0,
        "monotonic_fallbacks": 0,
        "neighbor_interpolation_count": 0,
        "linear_fallback_no_neighbor_count": 0,
        "sample_fallbacks": 0,
        "hard_threshold_drops": 0,
        "total_observations": 0,
        "refinement_total_ocr_calls": 0,
        "refinement_elapsed_seconds": 0.0,
        "strategy_distribution": {
            "A": 0,
            "B": 0,
            "C": 0,
            "sample_fallback": 0,
            "linear_fallback": 0,
        },
        "warnings": [],
        "error": error,
        "roi_path": "",
    }


def _optional_round(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _empty_time_map_summary(
    *,
    time_map_path: str | None,
    requested: bool,
    error: str = "",
) -> dict[str, Any]:
    return {
        "requested": bool(requested),
        "applied": False,
        "path": str(time_map_path or ""),
        "period_anchors_used": {},
        "adjusted_clips": 0,
        "fallback_clips": 0,
        "warnings": [],
        "error": error,
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
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("observations", [])
    else:
        raise ValueError("Observations file must be a list or a dict with an `observations` key.")
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


def _print_time_map_status(summary: dict[str, Any]) -> None:
    time_map = summary.get("time_map", {})
    if not isinstance(time_map, dict) or not time_map.get("requested"):
        return
    anchors = {
        int(period): float(anchor)
        for period, anchor in time_map.get("period_anchors_used", {}).items()
    }
    print("\n" + "=" * 60)
    print("Time Map Applied")
    print("-" * 60)
    print(f"Source:           {time_map.get('path', '')}")
    print(f"Anchors used:     {anchors}")
    print(
        f"Adjusted clips:   {int(time_map.get('adjusted_clips', 0) or 0)} / "
        f"{int(summary.get('observation_count', 0) or 0)}"
    )
    print(f"Fallback clips:   {int(time_map.get('fallback_clips', 0) or 0)}")
    if time_map.get("error"):
        print(f"Error:            {time_map.get('error')}")
    print("=" * 60)


def _print_refinement_status(summary: dict[str, Any]) -> None:
    refinement = summary.get("event_refinement", {})
    if not isinstance(refinement, dict) or not refinement.get("requested"):
        return
    total = int(refinement.get("total_observations", 0) or summary.get("observation_count", 0) or 0)
    refined = int(refinement.get("events_refined", 0) or 0)
    fallback = int(refinement.get("fallback_clips", 0) or 0)
    neighbor = int(refinement.get("neighbor_interpolation_count", 0) or 0)
    linear_no_neighbor = int(refinement.get("linear_fallback_no_neighbor_count", 0) or 0)
    ocr_calls = int(refinement.get("refinement_total_ocr_calls", 0) or 0)
    elapsed = float(refinement.get("refinement_elapsed_seconds", 0.0) or 0.0)
    rate = (refined / total) if total else 0.0
    print("\n" + "=" * 60)
    print("Per-Event Refinement")
    print("-" * 60)
    print(f"Refined:           {refined} / {total}   ({rate:.1%})")
    print(f"Fallback:          {fallback} / {total}")
    print(f"Total OCR calls:   {ocr_calls}")
    print(f"Total elapsed:     {_format_elapsed(elapsed)}")
    if refinement.get("error"):
        print(f"Error:             {refinement.get('error')}")
    print("=" * 60)
    distribution = refinement.get("strategy_distribution", {})
    if isinstance(distribution, dict):
        print("\nPer-Event Refinement Strategy Distribution")
        print("-" * 60)
        print(f"Strategy A (precise):    {int(distribution.get('A', 0) or 0)}")
        print(f"Strategy B (medium):     {int(distribution.get('B', 0) or 0)}")
        print(f"Strategy C (wide):       {int(distribution.get('C', 0) or 0)}")
        print(f"Sample fallback:         {int(distribution.get('sample_fallback', 0) or 0)}")
        print(f"Linear fallback:         {int(distribution.get('linear_fallback', 0) or 0)}")
    print("\n" + "=" * 60)
    print("Per-Event Refinement Summary")
    print("-" * 60)
    print(f"Refined (accepted):           {refined} / {total}")
    print(f"Neighbor interpolated:        {neighbor} / {total}")
    print(f"Linear fallback (no neighbor): {linear_no_neighbor} / {total}")
    print(f"Monotonic fallbacks:          {int(refinement.get('monotonic_fallbacks', 0) or 0)}")
    print(f"Hard threshold drops:         {int(refinement.get('hard_threshold_drops', 0) or 0)} (shift > 300s)")
    print("=" * 60)


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    minutes, sec = divmod(total, 60)
    if minutes:
        return f"{minutes} min {sec} sec"
    return f"{sec} sec"


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
    parser.add_argument("--time-map", default="", help="Optional video_time_map.json path from T-OCR-3.")
    parser.add_argument("--apply-time-map", action="store_true", help="Explicitly remap clip windows using --time-map anchors.")
    parser.add_argument("--refine-events", action="store_true", help="OCR-refine each event around its seeded clip timestamp.")
    parser.add_argument("--roi", default="", help="Optional scoreboard ROI JSON for --refine-events.")
    parser.add_argument("--play-segments", default="", help="Optional play_segments.json from play_segment_detector; if provided, clip windows snap to play segments.")
    parser.add_argument(
        "--period-video-windows",
        default="",
        help="Optional per-period video windows, e.g. 1:900-2300,2:2500-3900,3:4300-5700,4:5900-7100.",
    )
    parser.add_argument("--target-chars", type=int, default=2000, help="Target Chinese character count for the report.")
    parser.add_argument("--use-reasoner", action="store_true", help="Use the slower reasoning model for deeper analysis.")
    parser.add_argument("--clip-before", type=float, default=DEFAULT_CLIP_BEFORE_SECONDS, help="Seconds before each event to include in tactical clips.")
    parser.add_argument("--clip-after", type=float, default=DEFAULT_CLIP_AFTER_SECONDS, help="Seconds after each event to include in tactical clips.")
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
        time_map_path=args.time_map or None,
        apply_time_map=args.apply_time_map,
        refine_events=args.refine_events,
        roi_path=args.roi or None,
        play_segments_path=args.play_segments or None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _print_llm_pipeline_status(summary)
    _print_time_map_status(summary)
    _print_refinement_status(summary)


if __name__ == "__main__":
    main()
