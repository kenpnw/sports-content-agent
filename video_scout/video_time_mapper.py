"""Full-video OCR sampling and period anchor reconstruction.

T-OCR-3 extends the single-frame ScoreboardOCR reader into a video-level
time mapper. It samples one frame at a fixed interval, reads the scoreboard,
fits period clock anchors, and writes a `video_time_map.json` artifact for
downstream video clipping.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from video_scout.scoreboard_ocr import ScoreboardOCR, ScoreboardReading, load_roi_json


EXPECTED_REGULATION_PERIODS = (1, 2, 3, 4)
REGULATION_PERIOD_SECONDS = 720.0
OVERTIME_PERIOD_SECONDS = 300.0
OUTLIER_RESIDUAL_SECONDS = 30.0
MIN_RELIABLE_SAMPLES = 5


@dataclass
class TimeMapSample:
    """One sampled video timestamp and its OCR result."""

    video_seconds: float
    period: int | None
    clock_remaining_seconds: float | None
    confidence: float
    extraction_mode: str
    raw_text: str
    is_outlier: bool = False
    error_reason: str = ""
    ocr_box_count: int = 0

    @classmethod
    def from_reading(cls, video_seconds: float, reading: ScoreboardReading) -> "TimeMapSample":
        repaired_clock = _repair_clock_for_time_mapping(reading)
        return cls(
            video_seconds=round(float(video_seconds), 3),
            period=reading.period,
            clock_remaining_seconds=repaired_clock,
            confidence=round(float(reading.confidence), 4),
            extraction_mode=reading.extraction_mode,
            raw_text=reading.raw_text,
            error_reason=reading.error_reason,
            ocr_box_count=reading.ocr_box_count,
        )

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["error_reason"]:
            payload.pop("error_reason")
        if not payload["ocr_box_count"]:
            payload.pop("ocr_box_count")
        return payload


@dataclass
class PeriodFit:
    """Linear fit result for one period."""

    period: int
    anchor_seconds: float | None
    reliability: str
    slope: float | None = None
    intercept: float | None = None
    samples_used: int = 0
    samples_seen: int = 0
    outlier_indices: list[int] | None = None
    reason: str = ""


def build_time_map(
    *,
    video_path: Path,
    roi_path: Path,
    sample_interval_seconds: float,
    output_path: Path,
    start_seconds: float = 0.0,
    end_seconds: float = 0.0,
    progress_every: int = 20,
    visualize: bool = False,
) -> dict[str, Any]:
    """Sample a video, reconstruct period anchors, and write the time map."""
    cv2 = _import_cv2()
    video_duration = _probe_video_duration(cv2, video_path)
    effective_end = video_duration if end_seconds <= 0 else min(float(end_seconds), video_duration)
    if effective_end < start_seconds:
        raise ValueError("--end-seconds must be greater than or equal to --start-seconds")

    timestamps = _build_sample_timestamps(float(start_seconds), effective_end, float(sample_interval_seconds))
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频文件：{video_path}")

    ocr = ScoreboardOCR(load_roi_json(roi_path), use_gpu=False)
    samples: list[TimeMapSample] = []
    started_at = time.perf_counter()

    try:
        for index, video_seconds in enumerate(timestamps, start=1):
            reading = _read_sample(capture, cv2, ocr, video_seconds)
            samples.append(TimeMapSample.from_reading(video_seconds, reading))
            if progress_every > 0 and (index % progress_every == 0 or index == len(timestamps)):
                _print_progress(index, len(timestamps), samples)
    except KeyboardInterrupt:
        print("\n收到 Ctrl-C，正在保存已采样结果...", file=sys.stderr)
    finally:
        capture.release()

    result = _assemble_time_map(
        video_path=video_path,
        video_duration=video_duration,
        sample_interval_seconds=sample_interval_seconds,
        samples=samples,
    )
    _write_json(output_path, result)
    if visualize:
        _write_timeline_visualization(output_path, result)

    elapsed = time.perf_counter() - started_at
    average = elapsed / len(samples) if samples else 0.0
    print(f"Total elapsed seconds: {elapsed:.2f}", file=sys.stderr)
    print(f"Average seconds per sampled frame: {average:.2f}", file=sys.stderr)
    _print_summary(result, output_path)
    return result


def _read_sample(capture: Any, cv2: Any, ocr: ScoreboardOCR, video_seconds: float) -> ScoreboardReading:
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(video_seconds)) * 1000.0)
        ok, frame = capture.read()
        if not ok or frame is None:
            return _failed_reading(f"frame_read_failed_at_{video_seconds:.3f}")
        return ocr.read_frame(frame)
    except Exception as exc:
        return _failed_reading(f"sample_failed_at_{video_seconds:.3f}: {exc}")


def _repair_clock_for_time_mapping(reading: ScoreboardReading) -> float | None:
    """Repair common no-colon clock OCR strings without changing ScoreboardOCR."""
    if reading.period is None or not reading.raw_text:
        return reading.clock_remaining_seconds
    text = str(reading.raw_text).upper().replace("O", "0")
    period_match = re.search(r"\b(?:1ST|2ND|3RD|4TH|Q[1-4]|OT)\b", text)
    if not period_match:
        return reading.clock_remaining_seconds
    before_period = text[: period_match.start()]
    digit_tokens = re.findall(r"\d+", before_period)
    if not digit_tokens:
        return reading.clock_remaining_seconds
    candidates = _clock_candidates_from_digits(digit_tokens[-1])
    if not candidates:
        return reading.clock_remaining_seconds
    repaired = candidates[0]
    if reading.clock_remaining_seconds is None:
        return repaired
    if abs(repaired - float(reading.clock_remaining_seconds)) >= 45.0:
        return repaired
    return float(reading.clock_remaining_seconds)


def _clock_candidates_from_digits(digits: str) -> list[float]:
    candidates: list[tuple[int, float]] = []
    clean = re.sub(r"\D+", "", digits)
    if len(clean) >= 5:
        for drop_index in range(len(clean)):
            repaired = clean[:drop_index] + clean[drop_index + 1 :]
            for priority, value in _parse_digit_clock_variants(repaired):
                candidates.append((priority + 2, value))
    for priority, value in _parse_digit_clock_variants(clean):
        candidates.append((priority, value))
    deduped: dict[float, int] = {}
    for priority, value in candidates:
        deduped[value] = min(priority, deduped.get(value, priority))
    return [value for value, _ in sorted(deduped.items(), key=lambda item: (item[1], -item[0]))]


def _parse_digit_clock_variants(digits: str) -> list[tuple[int, float]]:
    values: list[tuple[int, float]] = []
    if len(digits) == 4:
        minute = int(digits[:2])
        second = int(digits[2:])
        if 0 <= minute <= 12 and 0 <= second < 60:
            values.append((0, float(minute * 60 + second)))
        minute = int(digits[0])
        second = int(digits[2:])
        if 0 <= minute <= 9 and 0 <= second < 60:
            values.append((1, float(minute * 60 + second)))
    if len(digits) == 3:
        minute = int(digits[0])
        second = int(digits[1:])
        if 0 <= minute <= 9 and 0 <= second < 60:
            values.append((0, float(minute * 60 + second)))
    return values


def _assemble_time_map(
    *,
    video_path: Path,
    video_duration: float,
    sample_interval_seconds: float,
    samples: list[TimeMapSample],
) -> dict[str, Any]:
    fits = _reconstruct_period_anchors(samples)
    fit_by_period = {fit.period: fit for fit in fits}
    for fit in fits:
        for sample_index in fit.outlier_indices or []:
            if 0 <= sample_index < len(samples):
                samples[sample_index].is_outlier = True

    reliability: dict[str, str] = {}
    anchors: dict[str, float] = {}
    for period in EXPECTED_REGULATION_PERIODS:
        fit = fit_by_period.get(period)
        if fit and fit.anchor_seconds is not None:
            anchors[str(period)] = round(fit.anchor_seconds, 3)
            reliability[str(period)] = fit.reliability
        else:
            reliability[str(period)] = "missing"

    extra_periods = sorted(period for period in fit_by_period if period not in EXPECTED_REGULATION_PERIODS)
    for period in extra_periods:
        fit = fit_by_period[period]
        if fit.anchor_seconds is not None:
            anchors[str(period)] = round(fit.anchor_seconds, 3)
            reliability[str(period)] = fit.reliability

    total_samples = len(samples)
    ocr_success = sum(1 for item in samples if item.period is not None)
    outliers = sum(1 for item in samples if item.is_outlier)
    anchors_detected = sum(1 for value in reliability.values() if value != "missing")
    anchors_reliable = sum(1 for value in reliability.values() if value == "reliable")

    return {
        "video_path": str(video_path),
        "video_duration_seconds": round(float(video_duration), 3),
        "sample_interval_seconds": float(sample_interval_seconds),
        "period_anchors": anchors,
        "period_anchors_reliability": reliability,
        "samples": [sample.to_public_dict() for sample in samples],
        "stats": {
            "total_samples": total_samples,
            "ocr_success": ocr_success,
            "ocr_success_rate": round(ocr_success / total_samples, 4) if total_samples else 0.0,
            "outliers_dropped": outliers,
            "anchors_detected": anchors_detected,
            "anchors_reliable": anchors_reliable,
        },
        "fit_details": {
            str(fit.period): {
                "slope": fit.slope,
                "intercept": fit.intercept,
                "samples_seen": fit.samples_seen,
                "samples_used": fit.samples_used,
                "reason": fit.reason,
            }
            for fit in fits
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _reconstruct_period_anchors(samples: list[TimeMapSample]) -> list[PeriodFit]:
    """Fit `video_seconds -> clock_remaining` lines and derive period starts."""
    grouped: dict[int, list[tuple[int, TimeMapSample]]] = {}
    for index, sample in enumerate(samples):
        if sample.period is None or sample.clock_remaining_seconds is None:
            continue
        grouped.setdefault(int(sample.period), []).append((index, sample))

    fits: list[PeriodFit] = []
    for period, items in sorted(grouped.items()):
        items.sort(key=lambda pair: pair[1].video_seconds)
        points = [(sample.video_seconds, float(sample.clock_remaining_seconds)) for _, sample in items]
        initial = _robust_line(points) or _linear_regression(points)
        if initial is None:
            fits.append(
                PeriodFit(
                    period=period,
                    anchor_seconds=None,
                    reliability="unreliable",
                    samples_seen=len(items),
                    samples_used=0,
                    outlier_indices=[],
                    reason="not_enough_distinct_points",
                )
            )
            continue

        slope, intercept = initial
        kept: list[tuple[int, TimeMapSample]] = []
        outlier_indices: list[int] = []
        for original_index, sample in items:
            predicted = slope * sample.video_seconds + intercept
            residual = abs(float(sample.clock_remaining_seconds) - predicted)
            if residual > OUTLIER_RESIDUAL_SECONDS:
                outlier_indices.append(original_index)
            else:
                kept.append((original_index, sample))

        target_clock = _period_length(period)
        anchor = _anchor_from_high_clock_samples(period, items)
        if anchor is None:
            refit_points = [(sample.video_seconds, float(sample.clock_remaining_seconds)) for _, sample in kept]
            refit = _linear_regression(refit_points) if len(refit_points) >= 2 else initial
            slope, intercept = refit if refit is not None else initial
            anchor = _anchor_from_fit(slope, intercept, target_clock)
        else:
            slope = -1.0
            intercept = target_clock + anchor
        reliability = _fit_reliability(anchor, slope, len(items), len(kept))
        reason = _fit_reason(anchor, slope, len(items), len(kept))
        fits.append(
            PeriodFit(
                period=period,
                anchor_seconds=anchor,
                reliability=reliability,
                slope=round(slope, 6),
                intercept=round(intercept, 6),
                samples_seen=len(items),
                samples_used=len(kept),
                outlier_indices=outlier_indices,
                reason=reason,
            )
        )
    return fits


def _linear_regression(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if math.isclose(denominator, 0.0):
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    intercept = mean_y - slope * mean_x
    return float(slope), float(intercept)


def _anchor_from_high_clock_samples(period: int, items: list[tuple[int, TimeMapSample]]) -> float | None:
    """Estimate period start from the highest-clock samples before stoppage drift."""
    target_clock = _period_length(period)
    usable = [
        sample
        for _, sample in items
        if sample.clock_remaining_seconds is not None
        and 0 <= float(sample.clock_remaining_seconds) <= target_clock
    ]
    if len(usable) < 2:
        return None
    top = sorted(usable, key=lambda sample: float(sample.clock_remaining_seconds), reverse=True)[:5]
    if len(top) < 2:
        return None
    estimates = sorted(
        sample.video_seconds - (target_clock - float(sample.clock_remaining_seconds))
        for sample in top
    )
    index = max(0, len(estimates) // 2 - 1)
    return float(estimates[index])


def _robust_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Return a median-slope line for first-pass outlier detection."""
    if len(points) < 2:
        return None
    slopes: list[float] = []
    for left_index, left in enumerate(points):
        for right in points[left_index + 1 :]:
            dx = right[0] - left[0]
            if not math.isclose(dx, 0.0):
                slopes.append((right[1] - left[1]) / dx)
    if not slopes:
        return None
    slope = float(median(slopes))
    intercept = float(median([y - slope * x for x, y in points]))
    return slope, intercept


def _anchor_from_fit(slope: float, intercept: float, target_clock: float) -> float | None:
    if math.isclose(slope, 0.0):
        return None
    return float((target_clock - intercept) / slope)


def _fit_reliability(anchor: float | None, slope: float, seen: int, kept: int) -> str:
    if anchor is None:
        return "unreliable"
    if seen < MIN_RELIABLE_SAMPLES or kept < MIN_RELIABLE_SAMPLES:
        return "unreliable"
    if slope >= -0.05:
        return "unreliable"
    return "reliable"


def _fit_reason(anchor: float | None, slope: float, seen: int, kept: int) -> str:
    if anchor is None:
        return "flat_or_unfit_line"
    if seen < MIN_RELIABLE_SAMPLES:
        return f"only_{seen}_samples"
    if kept < MIN_RELIABLE_SAMPLES:
        return f"only_{kept}_inlier_samples"
    if slope >= -0.05:
        return "clock_not_decreasing"
    return "ok"


def _write_timeline_visualization(output_path: Path, result: dict[str, Any]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"无法生成 timeline 图：缺少 matplotlib 或后端不可用：{exc}", file=sys.stderr)
        return

    image_path = Path(f"{output_path}.timeline.png")
    samples = result.get("samples", [])
    success_x: list[float] = []
    success_y: list[float] = []
    outlier_x: list[float] = []
    outlier_y: list[float] = []
    for sample in samples:
        period = sample.get("period")
        clock = sample.get("clock_remaining_seconds")
        if period is None or clock is None:
            continue
        y_value = _game_elapsed_from_clock(int(period), float(clock))
        if sample.get("is_outlier"):
            outlier_x.append(float(sample["video_seconds"]))
            outlier_y.append(y_value)
        else:
            success_x.append(float(sample["video_seconds"]))
            success_y.append(y_value)

    fig, ax = plt.subplots(figsize=(12, 6))
    if success_x:
        ax.scatter(success_x, success_y, s=18, color="#2563eb", label="OCR success")
    if outlier_x:
        ax.scatter(outlier_x, outlier_y, s=24, color="#dc2626", label="Outlier")

    fit_details = result.get("fit_details", {})
    anchors = result.get("period_anchors", {})
    for period_text, details in fit_details.items():
        period = int(period_text)
        slope = details.get("slope")
        intercept = details.get("intercept")
        if slope is None or intercept is None:
            continue
        period_samples = [
            sample
            for sample in samples
            if sample.get("period") == period and sample.get("clock_remaining_seconds") is not None
        ]
        if not period_samples:
            continue
        xs = [float(sample["video_seconds"]) for sample in period_samples]
        if period_text in anchors:
            xs.append(float(anchors[period_text]))
        x0, x1 = min(xs), max(xs)
        line_x = [x0, x1]
        line_y = [_game_elapsed_from_clock(period, slope * x + intercept) for x in line_x]
        ax.plot(line_x, line_y, linewidth=2, label=f"Q{period} fit")

    for period_text, anchor in anchors.items():
        ax.axvline(float(anchor), color="#64748b", linestyle="--", linewidth=1)
        ax.text(float(anchor), 40, f"Q{period_text}", rotation=90, va="bottom", ha="right", fontsize=9)

    ax.set_xlim(0, max(float(result.get("video_duration_seconds", 0.0)), 1.0))
    ax.set_ylim(0, 2880)
    ax.set_xlabel("video_seconds")
    ax.set_ylabel("game_seconds_elapsed")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    image_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(image_path, dpi=160)
    plt.close(fig)
    print(f"Timeline visualization saved to: {image_path}", file=sys.stderr)


def _game_elapsed_from_clock(period: int, clock_remaining: float) -> float:
    period_length = _period_length(period)
    if period <= 4:
        return (period - 1) * REGULATION_PERIOD_SECONDS + (period_length - float(clock_remaining))
    return 4 * REGULATION_PERIOD_SECONDS + (period - 5) * OVERTIME_PERIOD_SECONDS + (
        period_length - float(clock_remaining)
    )


def _period_length(period: int) -> float:
    return OVERTIME_PERIOD_SECONDS if period >= 5 else REGULATION_PERIOD_SECONDS


def _build_sample_timestamps(start_seconds: float, end_seconds: float, interval_seconds: float) -> list[float]:
    if interval_seconds <= 0:
        raise ValueError("--sample-interval-seconds must be greater than 0")
    timestamps: list[float] = []
    current = max(0.0, float(start_seconds))
    while current <= end_seconds + 1e-6:
        timestamps.append(round(current, 3))
        current += interval_seconds
    return timestamps


def _probe_video_duration(cv2: Any, video_path: Path) -> float:
    if not video_path.is_file():
        raise FileNotFoundError(f"视频文件不存在：{video_path}")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频文件：{video_path}")
    try:
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        duration = frame_count / fps if frame_count > 0 and fps > 0 else 0.0
        if duration <= 0:
            duration = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
        if duration <= 0:
            raise RuntimeError("无法读取视频时长。")
        return float(duration)
    finally:
        capture.release()


def _failed_reading(reason: str) -> ScoreboardReading:
    return ScoreboardReading(
        raw_text="",
        period=None,
        clock_remaining_seconds=None,
        confidence=0.0,
        error_reason=reason,
        ocr_box_count=0,
        extraction_mode="failed",
    )


def _print_progress(done: int, total: int, samples: list[TimeMapSample]) -> None:
    success = sum(1 for item in samples if item.period is not None)
    rate = success / len(samples) if samples else 0.0
    print(
        f"[video_time_mapper] sampled {done}/{total}; OCR success {success}/{len(samples)} ({rate:.1%})",
        file=sys.stderr,
    )


def _print_summary(result: dict[str, Any], output_path: Path) -> None:
    stats = result["stats"]
    anchors = result["period_anchors"]
    reliability = result["period_anchors_reliability"]
    print("=" * 60, file=sys.stderr)
    print("Video Time Mapping Complete", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    print(f"Total samples:        {stats['total_samples']}", file=sys.stderr)
    print(f"OCR success rate:     {stats['ocr_success_rate'] * 100:.1f}%", file=sys.stderr)
    print(f"Anchors detected:     {stats['anchors_detected']} / 4 expected", file=sys.stderr)
    for period in EXPECTED_REGULATION_PERIODS:
        anchor = anchors.get(str(period))
        if anchor is None:
            print(f"Q{period} starts at video:   missing ({reliability.get(str(period), 'missing')})", file=sys.stderr)
        else:
            print(
                f"Q{period} starts at video:   {anchor:.1f}s ({_format_hms(anchor)})",
                file=sys.stderr,
            )
    print(f"Output saved to:      {output_path}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def _format_hms(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _import_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 opencv-python，无法执行视频采样。") from exc
    return cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全视频比分牌 OCR 采样与时间映射构建。")
    parser.add_argument("--video", required=True, help="本地比赛视频路径。")
    parser.add_argument("--roi", required=True, help="T-OCR-1 生成的 scoreboard_roi.json。")
    parser.add_argument("--sample-interval-seconds", type=float, default=30.0, help="采样间隔秒数，默认 30。")
    parser.add_argument("--output", required=True, help="输出 video_time_map.json 路径。")
    parser.add_argument("--start-seconds", type=float, default=0.0, help="采样起点秒数，默认 0。")
    parser.add_argument("--end-seconds", type=float, default=0.0, help="采样终点秒数，0 表示视频末尾。")
    parser.add_argument("--progress-every", type=int, default=20, help="每多少个采样点输出一次进度。")
    parser.add_argument("--visualize", action="store_true", help="生成 <output>.timeline.png 时间线图。")
    return parser.parse_args()


def _self_test() -> None:
    samples = [
        TimeMapSample(100.0, 1, 720.0, 0.9, "strict", "Q1 12:00"),
        TimeMapSample(160.0, 1, 660.0, 0.9, "strict", "Q1 11:00"),
        TimeMapSample(220.0, 1, 600.0, 0.9, "strict", "Q1 10:00"),
        TimeMapSample(280.0, 1, 540.0, 0.9, "strict", "Q1 9:00"),
        TimeMapSample(340.0, 1, 480.0, 0.9, "strict", "Q1 8:00"),
        TimeMapSample(400.0, 1, 200.0, 0.9, "strict", "Q1 bad"),
    ]
    fits = _reconstruct_period_anchors(samples)
    assert len(fits) == 1
    assert fits[0].anchor_seconds is not None and abs(fits[0].anchor_seconds - 100.0) < 0.01
    assert fits[0].reliability == "reliable"
    assert fits[0].outlier_indices == [5]
    print("video_time_mapper self-test passed.")


def main() -> None:
    args = parse_args()
    build_time_map(
        video_path=Path(args.video),
        roi_path=Path(args.roi),
        sample_interval_seconds=args.sample_interval_seconds,
        output_path=Path(args.output),
        start_seconds=args.start_seconds,
        end_seconds=args.end_seconds,
        progress_every=args.progress_every,
        visualize=args.visualize,
    )


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.argv.remove("--self-test")
        _self_test()
    else:
        main()
