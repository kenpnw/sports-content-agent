"""Per-event OCR refinement for video clip anchors.

This module is a narrow T-OCR-6 patch on top of video_time_map anchors:
demo_runner already has a seed video timestamp for each event, and this
refiner checks nearby scoreboard frames to find the frame whose real game
clock matches the expected play-by-play clock.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_scout.scoreboard_ocr import ScoreboardOCR
from video_scout.video_time_mapper import _repair_clock_for_time_mapping


@dataclass
class RefinementResult:
    """Result of refining one event timestamp using scoreboard OCR."""

    video_seconds: float
    mode: str
    confidence: float
    ocr_calls_made: int
    elapsed_seconds: float
    strategy_used: str
    seed_video_seconds: float
    search_attempts: int


def refine_event_anchor(
    *,
    video_path: str | Path,
    roi_dict: dict[str, Any],
    expected_period: int,
    expected_clock_remaining_seconds: float,
    seed_video_seconds: float | None,
    time_map_samples: list[dict[str, Any]],
    search_window_seconds: float = 30.0,
    sample_interval: float = 1.0,
    tolerance_seconds: float = 2.0,
) -> RefinementResult:
    """Find the nearest OCR-confirmed video timestamp for one PBP event.

    The function never raises for ordinary video/OCR failures. If no usable
    seed or no matching scoreboard frame is found, it returns a fallback result
    so demo_runner can keep the existing clip window.
    """
    started_at = time.perf_counter()
    estimated_seed, seed_strategy = _estimate_seed_from_samples(
        int(expected_period),
        float(expected_clock_remaining_seconds),
        time_map_samples,
    )
    if estimated_seed is None:
        estimated_seed = float(seed_video_seconds) if seed_video_seconds is not None else None
        seed_strategy = "linear_fallback"
    if estimated_seed is None:
        return RefinementResult(
            video_seconds=0.0,
            mode="skipped_no_seed",
            confidence=0.0,
            ocr_calls_made=0,
            elapsed_seconds=0.0,
            strategy_used="linear_fallback",
            seed_video_seconds=0.0,
            search_attempts=0,
        )

    seed = float(estimated_seed)
    ocr_calls = 0
    search_attempts = 0
    capture = None
    try:
        cv2 = _import_cv2()
        source = Path(video_path)
        if not source.is_file():
            return _fallback(seed, "fallback_no_match", ocr_calls, started_at, seed_strategy, 0)

        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            return _fallback(seed, "fallback_no_match", ocr_calls, started_at, seed_strategy, 0)

        ocr = ScoreboardOCR(roi_dict, use_gpu=False)
        strategies = [
            ("A", 20.0, 2.0, 0.5),
            ("B", 60.0, 5.0, 1.0),
            ("C", 120.0, 10.0, 2.0),
        ]
        for strategy_name, window, tolerance, interval in strategies:
            matched, calls = _run_search_strategy(
                capture,
                cv2,
                ocr,
                seed=seed,
                expected_period=int(expected_period),
                expected_clock_remaining_seconds=float(expected_clock_remaining_seconds),
                window_seconds=window,
                tolerance_seconds=tolerance,
                sample_interval=interval,
            )
            ocr_calls += calls
            search_attempts += 1
            if matched is not None:
                return RefinementResult(
                    video_seconds=round(float(matched), 3),
                    mode="ocr_refined",
                    confidence=1.0,
                    ocr_calls_made=ocr_calls,
                    elapsed_seconds=round(time.perf_counter() - started_at, 3),
                    strategy_used=strategy_name,
                    seed_video_seconds=round(float(seed), 3),
                    search_attempts=search_attempts,
                )
    except Exception:
        return _fallback(seed, "fallback_no_match", ocr_calls, started_at, seed_strategy, search_attempts)
    finally:
        if capture is not None:
            capture.release()

    fallback_seed, fallback_strategy = _nearest_sample_seed(
        int(expected_period),
        float(expected_clock_remaining_seconds),
        time_map_samples,
    )
    if fallback_seed is None:
        fallback_seed = seed
        fallback_strategy = "linear_fallback"
    return _fallback(fallback_seed, "fallback_no_match", ocr_calls, started_at, fallback_strategy, search_attempts)


def _run_search_strategy(
    capture: Any,
    cv2: Any,
    ocr: ScoreboardOCR,
    *,
    seed: float,
    expected_period: int,
    expected_clock_remaining_seconds: float,
    window_seconds: float,
    tolerance_seconds: float,
    sample_interval: float,
) -> tuple[float | None, int]:
    start_seconds = max(0.0, seed - max(0.0, float(window_seconds)))
    end_seconds = max(start_seconds, seed + max(0.0, float(window_seconds)))
    candidates: list[float] = []
    ocr_calls = 0
    for video_seconds in _build_sample_points(start_seconds, end_seconds, sample_interval):
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, video_seconds) * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            reading = ocr.read_frame(frame)
            ocr_calls += 1
        except Exception:
            continue

        if reading.period != int(expected_period):
            continue
        clock_remaining = _repair_clock_for_time_mapping(reading)
        if clock_remaining is None:
            continue
        if abs(float(clock_remaining) - float(expected_clock_remaining_seconds)) < float(tolerance_seconds):
            candidates.append(float(video_seconds))
    if not candidates:
        return None, ocr_calls
    return min(candidates, key=lambda item: abs(item - seed)), ocr_calls


def _fallback(
    seed: float,
    mode: str,
    ocr_calls: int,
    started_at: float,
    strategy_used: str,
    search_attempts: int,
) -> RefinementResult:
    return RefinementResult(
        video_seconds=round(float(seed), 3),
        mode=mode,
        confidence=0.0,
        ocr_calls_made=ocr_calls,
        elapsed_seconds=round(time.perf_counter() - started_at, 3),
        strategy_used=strategy_used,
        seed_video_seconds=round(float(seed), 3),
        search_attempts=search_attempts,
    )


def _estimate_seed_from_samples(
    period: int,
    target_clock_remaining: float,
    samples: list[dict[str, Any]],
) -> tuple[float | None, str]:
    period_samples = _valid_period_samples(period, samples)
    if len(period_samples) < 2:
        return _nearest_sample_seed(period, target_clock_remaining, samples)

    above = [
        item for item in period_samples if float(item["clock_remaining_seconds"]) >= float(target_clock_remaining)
    ]
    below = [
        item for item in period_samples if float(item["clock_remaining_seconds"]) <= float(target_clock_remaining)
    ]
    high = min(above, key=lambda item: abs(float(item["clock_remaining_seconds"]) - target_clock_remaining)) if above else None
    low = min(below, key=lambda item: abs(float(item["clock_remaining_seconds"]) - target_clock_remaining)) if below else None
    if high is None or low is None:
        return _nearest_sample_seed(period, target_clock_remaining, samples)
    high_clock = float(high["clock_remaining_seconds"])
    low_clock = float(low["clock_remaining_seconds"])
    high_video = float(high["video_seconds"])
    low_video = float(low["video_seconds"])
    if abs(high_clock - low_clock) < 1e-6:
        return ((high_video + low_video) / 2.0, "sample_fallback")
    ratio = (float(target_clock_remaining) - high_clock) / (low_clock - high_clock)
    estimated = high_video + ratio * (low_video - high_video)
    return round(float(estimated), 3), "sample_interpolation"


def _nearest_sample_seed(
    period: int,
    target_clock_remaining: float,
    samples: list[dict[str, Any]],
) -> tuple[float | None, str]:
    period_samples = _valid_period_samples(period, samples)
    if not period_samples:
        return None, "linear_fallback"
    nearest = min(
        period_samples,
        key=lambda item: abs(float(item["clock_remaining_seconds"]) - float(target_clock_remaining)),
    )
    return round(float(nearest["video_seconds"]), 3), "sample_fallback"


def _valid_period_samples(period: int, samples: list[dict[str, Any]]) -> list[dict[str, float]]:
    valid: list[dict[str, float]] = []
    for sample in samples:
        try:
            if int(sample.get("period")) != int(period):
                continue
            if bool(sample.get("is_outlier", False)):
                continue
            clock = float(sample.get("clock_remaining_seconds"))
            video_seconds = float(sample.get("video_seconds"))
        except (TypeError, ValueError):
            continue
        valid.append({"clock_remaining_seconds": clock, "video_seconds": video_seconds})
    valid.sort(key=lambda item: float(item["video_seconds"]))
    return valid


def _build_sample_points(start_seconds: float, end_seconds: float, interval: float) -> list[float]:
    points: list[float] = []
    cursor = float(start_seconds)
    limit = float(end_seconds) + 1e-6
    while cursor <= limit:
        points.append(round(cursor, 3))
        cursor += float(interval)
    return points


def _import_cv2() -> Any:
    try:
        import cv2  # type: ignore

        return cv2
    except Exception as exc:
        raise RuntimeError("opencv-python is required for per-event refinement.") from exc


def _self_test() -> None:
    result = refine_event_anchor(
        video_path="missing.mp4",
        roi_dict={"roi": {"x": 0, "y": 0, "w": 10, "h": 10}},
        expected_period=1,
        expected_clock_remaining_seconds=700.0,
        seed_video_seconds=42.0,
        time_map_samples=[],
    )
    assert result.mode == "fallback_no_match"
    assert result.video_seconds == 42.0
    assert result.strategy_used == "linear_fallback"
    skipped = refine_event_anchor(
        video_path="missing.mp4",
        roi_dict={"roi": {"x": 0, "y": 0, "w": 10, "h": 10}},
        expected_period=1,
        expected_clock_remaining_seconds=700.0,
        seed_video_seconds=None,
        time_map_samples=[],
    )
    assert skipped.mode == "skipped_no_seed"
    seed, strategy = _estimate_seed_from_samples(
        1,
        660.0,
        [
            {"period": 1, "clock_remaining_seconds": 690, "video_seconds": 100},
            {"period": 1, "clock_remaining_seconds": 630, "video_seconds": 190},
        ],
    )
    assert strategy == "sample_interpolation"
    assert seed == 145.0
    print("event_anchor_refiner self-test passed.")


if __name__ == "__main__":
    _self_test()
