"""Detect when the broadcast scoreboard is visible in each video frame.

Uses fast template matching against a known reference frame (Q1 start, where the
scoreboard is guaranteed to be visible) to classify each sampled frame as
scoreboard-visible (live play) or scoreboard-hidden (replay/closeup/commercial).

This is a much sharper signal than scene+audio because:
  * NBA broadcasts overlay the scoreboard during live play
  * Replays, commercials, slow-mo, and player closeups REMOVE the scoreboard
  * Template match against the reference is fast (~3ms per frame on CPU)

Output:
  visibility_timeline.json with per-second classification + merged segments.

Usage:
    python -m video_scout.scoreboard_visibility_detector \\
        --video data/videos/nba_demo.MKV \\
        --roi data/videos/nba_demo.score_roi.json \\
        --reference-time 1052.0 \\
        --output data/videos/nba_demo.scoreboard_visibility.json \\
        --sample-fps 1.0
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# ---------- Defaults ----------
DEFAULT_SAMPLE_FPS = 1.0       # sample 1 frame per second of video
DEFAULT_MATCH_THRESHOLD = 0.55  # normalized correlation; lower = more permissive
DEFAULT_MIN_SEGMENT_SECONDS = 4.0
DEFAULT_REFERENCE_TIME = None   # if None, auto-pick using period anchors or center of video


@dataclass
class Segment:
    start: float
    end: float
    label: str        # "visible" | "hidden"
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "duration": round(self.end - self.start, 2),
            "label": self.label,
            "confidence": round(self.confidence, 3),
        }


def load_roi(path: Path) -> dict[str, Any]:
    """Load ROI JSON. Supports either combined roi (x,y,w,h) or home/away pair."""
    data = json.loads(path.read_text(encoding="utf-8"))
    # If we have both home and away score ROIs, merge into a bounding box that covers both
    if "home_score_roi" in data and "away_score_roi" in data:
        h = data["home_score_roi"]
        a = data["away_score_roi"]
        x = min(h["x"], a["x"])
        y = min(h["y"], a["y"])
        right = max(h["x"] + h["w"], a["x"] + a["w"])
        bottom = max(h["y"] + h["h"], a["y"] + a["h"])
        # Expand slightly to grab surrounding scoreboard chrome
        pad_x = int((right - x) * 0.3)
        pad_y = int((bottom - y) * 0.3)
        return {
            "x": max(0, x - pad_x),
            "y": max(0, y - pad_y),
            "w": (right - x) + 2 * pad_x,
            "h": (bottom - y) + 2 * pad_y,
        }
    if "roi" in data:
        return data["roi"]
    return data


def crop_roi(frame: np.ndarray, roi: dict[str, int]) -> np.ndarray:
    x, y, w, h = int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])
    H, W = frame.shape[:2]
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return frame[y:y + h, x:x + w]


def grab_frame_at(video_path: str, seconds: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    return frame


def collect_reference_templates(
    video_path: str,
    roi: dict[str, int],
    reference_times: list[float],
) -> list[np.ndarray]:
    """Build a list of reference templates by sampling known-visible moments."""
    templates: list[np.ndarray] = []
    for t in reference_times:
        frame = grab_frame_at(video_path, t)
        if frame is None:
            continue
        cropped = crop_roi(frame, roi)
        # Convert to grayscale and equalize histogram to be robust to brightness differences
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        templates.append(gray)
    return templates


def score_visibility(roi_crop: np.ndarray, templates: list[np.ndarray]) -> float:
    """Compute the best normalized correlation score between roi_crop and any template."""
    if not templates:
        return 0.0
    gray = cv2.cvtColor(roi_crop, cv2.COLOR_BGR2GRAY) if roi_crop.ndim == 3 else roi_crop
    best = 0.0
    for tpl in templates:
        # Match must be sized so tpl fits inside gray. Resize tpl to match gray size if needed.
        if tpl.shape != gray.shape:
            try:
                tpl_resized = cv2.resize(tpl, (gray.shape[1], gray.shape[0]))
            except cv2.error:
                continue
        else:
            tpl_resized = tpl
        try:
            res = cv2.matchTemplate(gray, tpl_resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best:
                best = max_val
        except cv2.error:
            continue
    return float(best)


def detect_visibility(
    video_path: Path,
    roi: dict[str, int],
    reference_times: list[float],
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    progress_step: int = 600,
) -> tuple[list[tuple[float, float, bool]], dict[str, Any]]:
    """Sample the video and classify each sample using STREAMING ffmpeg pipe (fast).

    Returns:
        samples: list of (time_seconds, score, is_visible)
        meta: dict with stats
    """
    print(f"[visibility] building {len(reference_times)} reference templates …")
    templates = collect_reference_templates(str(video_path), roi, reference_times)
    if not templates:
        raise RuntimeError("Failed to extract any reference template; check reference_times and ROI.")
    print(f"[visibility] got {len(templates)} valid templates, shape={templates[0].shape}")

    # Probe duration quickly via ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=False,
    )
    try:
        duration = float(probe.stdout.strip())
    except (TypeError, ValueError):
        duration = 0.0
    print(f"[visibility] video duration: {duration:.1f}s")

    x, y, w, h = int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])

    # ffmpeg pipe: decode at sample_fps, crop ROI server-side, output raw BGR24
    # This is dramatically faster than OpenCV per-frame seeking on MKV files.
    ffmpeg_cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps={sample_fps},crop={w}:{h}:{x}:{y}",
        "-pix_fmt", "bgr24",
        "-f", "rawvideo", "-",
    ]
    frame_bytes = w * h * 3
    sample_interval = 1.0 / sample_fps
    samples: list[tuple[float, float, bool]] = []
    count_visible = 0
    count_total = 0

    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10 * 1024 * 1024)
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            cropped = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
            t = count_total * sample_interval
            score = score_visibility(cropped, templates)
            is_visible = score >= match_threshold
            samples.append((t, score, is_visible))
            count_total += 1
            if is_visible:
                count_visible += 1
            if count_total % progress_step == 0:
                pct = count_visible / max(count_total, 1) * 100
                print(f"[visibility]   t={t:6.1f}s  ({count_total} samples, {pct:.1f}% visible so far)")
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()

    meta = {
        "video_duration_seconds": round(duration, 2),
        "sample_fps": sample_fps,
        "total_samples": count_total,
        "visible_samples": count_visible,
        "visible_ratio": round(count_visible / max(count_total, 1), 3),
        "match_threshold": match_threshold,
        "reference_count": len(templates),
        "reference_times": reference_times,
    }
    print(f"[visibility] done: {count_visible}/{count_total} visible ({meta['visible_ratio']*100:.1f}%)")
    return samples, meta


def merge_into_segments(
    samples: list[tuple[float, float, bool]],
    sample_interval: float,
    min_segment_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
) -> list[Segment]:
    if not samples:
        return []
    segments: list[Segment] = []
    cur_label = None
    cur_start = 0.0
    cur_scores: list[float] = []
    for i, (t, score, vis) in enumerate(samples):
        label = "visible" if vis else "hidden"
        if cur_label is None:
            cur_label = label
            cur_start = t
            cur_scores = [score]
        elif label != cur_label:
            avg = sum(cur_scores) / max(len(cur_scores), 1)
            conf = avg if cur_label == "visible" else max(0.05, 1.0 - avg)
            segments.append(Segment(start=cur_start, end=t, label=cur_label, confidence=conf))
            cur_label = label
            cur_start = t
            cur_scores = [score]
        else:
            cur_scores.append(score)
    # close
    final_end = samples[-1][0] + sample_interval
    if cur_label is not None:
        avg = sum(cur_scores) / max(len(cur_scores), 1)
        conf = avg if cur_label == "visible" else max(0.05, 1.0 - avg)
        segments.append(Segment(start=cur_start, end=final_end, label=cur_label, confidence=conf))

    # Absorb tiny opposite-label gaps (shorter than min_segment_seconds) into surrounding majority
    cleaned: list[Segment] = []
    for seg in segments:
        if (seg.end - seg.start) < min_segment_seconds and cleaned:
            prev = cleaned[-1]
            cleaned[-1] = Segment(start=prev.start, end=seg.end, label=prev.label, confidence=prev.confidence)
        else:
            cleaned.append(seg)

    # Second pass: merge adjacent same-label
    merged: list[Segment] = []
    for seg in cleaned:
        if merged and merged[-1].label == seg.label:
            prev = merged[-1]
            merged[-1] = Segment(start=prev.start, end=seg.end, label=prev.label,
                                 confidence=(prev.confidence + seg.confidence) / 2)
        else:
            merged.append(seg)
    return merged


def auto_reference_times(time_map_path: str | None, duration: float) -> list[float]:
    """Pick reference times for the templates: prefer period anchors, fallback to evenly spaced."""
    if time_map_path:
        try:
            tm = json.loads(Path(time_map_path).read_text(encoding="utf-8"))
            anchors = tm.get("period_anchors", {})
            refs = []
            for p in sorted(anchors):
                t = float(anchors[p])
                # Sample 1 second after the anchor to skip score-graphic animation
                refs.append(t + 1.0)
            if refs:
                return refs
        except Exception:
            pass
    # Fallback: 4 evenly spaced inside the middle 80% of the video
    a = duration * 0.2
    b = duration * 0.8
    return [a, a + (b - a) / 3.0, a + 2 * (b - a) / 3.0, b]


def run(
    video_path: Path,
    roi: dict[str, int],
    output_path: Path,
    time_map_path: str | None = None,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    min_segment_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
    reference_times: list[float] | None = None,
) -> dict[str, Any]:
    # Probe duration via OpenCV (faster than ffprobe; we already need cv2 anyway)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1.0)
    cap.release()

    if reference_times is None:
        reference_times = auto_reference_times(time_map_path, duration)

    samples, meta = detect_visibility(
        video_path=video_path,
        roi=roi,
        reference_times=reference_times,
        sample_fps=sample_fps,
        match_threshold=match_threshold,
    )

    sample_interval = 1.0 / sample_fps
    segments = merge_into_segments(samples, sample_interval, min_segment_seconds)

    play_segments = [s.to_dict() for s in segments if s.label == "visible"]
    non_play_segments = [s.to_dict() for s in segments if s.label == "hidden"]
    play_total = sum(s.end - s.start for s in segments if s.label == "visible")
    non_play_total = sum(s.end - s.start for s in segments if s.label == "hidden")

    payload = {
        "video_path": str(video_path),
        "duration_seconds": round(duration, 2),
        "method": "scoreboard_template_match_v1",
        "params": {
            "sample_fps": sample_fps,
            "match_threshold": match_threshold,
            "min_segment_seconds": min_segment_seconds,
            "roi": roi,
            "reference_times": reference_times,
        },
        "meta": meta,
        "summary": {
            "total_segments": len(segments),
            "play_segments": len(play_segments),
            "non_play_segments": len(non_play_segments),
            "play_total_seconds": round(play_total, 1),
            "non_play_total_seconds": round(non_play_total, 1),
            "play_ratio": round(play_total / max(duration, 1), 3),
        },
        # Use the same keys as play_segment_detector.py so it's a drop-in replacement
        "play_segments": play_segments,
        "non_play_segments": non_play_segments,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[visibility] wrote {output_path}")
    print(f"[visibility] play (scoreboard-visible): {payload['summary']['play_total_seconds']}s ({payload['summary']['play_ratio']*100:.1f}%)")
    print(f"[visibility] non-play (scoreboard-hidden): {payload['summary']['non_play_total_seconds']}s")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect scoreboard visibility timeline.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--roi", required=True, help="Path to score_roi.json (or scoreboard_roi.json).")
    parser.add_argument("--output", required=True)
    parser.add_argument("--time-map", default="", help="Optional time_map.json to pick reference anchors.")
    parser.add_argument("--sample-fps", type=float, default=DEFAULT_SAMPLE_FPS)
    parser.add_argument("--match-threshold", type=float, default=DEFAULT_MATCH_THRESHOLD)
    parser.add_argument("--min-segment", type=float, default=DEFAULT_MIN_SEGMENT_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    roi = load_roi(Path(args.roi))
    run(
        video_path=Path(args.video),
        roi=roi,
        output_path=Path(args.output),
        time_map_path=args.time_map or None,
        sample_fps=args.sample_fps,
        match_threshold=args.match_threshold,
        min_segment_seconds=args.min_segment,
    )


if __name__ == "__main__":
    main()
