"""Automatically detect the scoreboard ROI in an NBA broadcast video.

No manual setup required: samples several frames from the middle of the video and
uses image processing heuristics to find the most likely scoreboard region.

Strategy:
  1. Sample 12 frames evenly through the middle 60% of the video (likely live play).
  2. For each frame, look in the bottom 35% (typical scoreboard placement).
  3. Find connected dark-on-light regions with high text-like edge density.
  4. Run OCR on candidate regions; keep regions containing digits + ':' (scoreboard text).
  5. Take the most consistent region across frames (mode of bounding boxes).
  6. Output ROI compatible with score_roi.json (with home_score_roi and away_score_roi).

Usage:
    python -m video_scout.auto_roi_detector \\
        --video data/videos/<game>.MKV \\
        --output data/videos/<game>.score_roi.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class Candidate:
    x: int
    y: int
    w: int
    h: int
    text: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "text": self.text, "score": round(self.score, 3)}


def probe_video(video_path: Path) -> tuple[float, int, int]:
    # Stream-level for dimensions
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "default=noprint_wrappers=1", str(video_path)],
        capture_output=True, text=True, check=False,
    )
    width = height = 0
    for line in result.stdout.splitlines():
        if line.startswith("width="):
            try: width = int(line.split("=")[1])
            except: pass
        elif line.startswith("height="):
            try: height = int(line.split("=")[1])
            except: pass
    # Container-level for duration (MKV often has duration only at container level)
    result2 = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=False,
    )
    try:
        duration = float(result2.stdout.strip())
    except (TypeError, ValueError):
        duration = 0.0
    return duration, width, height


def sample_frames(video_path: Path, num_samples: int = 12) -> list[tuple[float, np.ndarray]]:
    duration, w, h = probe_video(video_path)
    if duration <= 0:
        raise RuntimeError(f"Cannot probe video {video_path}")
    # Sample in the middle 60% (avoid pregame/postgame)
    start = duration * 0.20
    end = duration * 0.80
    step = (end - start) / max(num_samples - 1, 1)
    timestamps = [start + i * step for i in range(num_samples)]
    frames: list[tuple[float, np.ndarray]] = []
    for t in timestamps:
        # Use ffmpeg pipe (avoids slow MKV seeking)
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-ss", f"{t:.2f}", "-i", str(video_path),
             "-frames:v", "1", "-pix_fmt", "bgr24", "-f", "rawvideo",
             "-hide_banner", "-loglevel", "error", "-"],
            capture_output=True, check=False, timeout=10,
        )
        if proc.returncode != 0 or len(proc.stdout) < w * h * 3:
            continue
        frame = np.frombuffer(proc.stdout[:w*h*3], dtype=np.uint8).reshape(h, w, 3)
        frames.append((t, frame))
    return frames


def find_candidate_regions(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Return bounding boxes of candidate scoreboard rectangles in the bottom 18% of frame."""
    H, W = frame.shape[:2]
    # Scoreboard typically lives in the bottom 8-18% of the broadcast (above the lower border ads)
    search_top = int(H * 0.78)
    search_bottom = int(H * 0.97)
    region = frame[search_top:search_bottom, :]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

    # Find text-like edges
    edges = cv2.Canny(gray, 50, 150)

    # Dilate to merge nearby text characters
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # NBA scoreboard is typically wide (200-700px) and short (30-90px)
        if w < 150 or w > 800:
            continue
        if h < 25 or h > 120:
            continue
        # Aspect ratio: scoreboard graphic is wide
        if w / h < 2.0 or w / h > 12.0:
            continue
        candidates.append((x, y + search_top, w, h))
    return candidates


def crop_for_ocr(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    pad = 4
    H, W = frame.shape[:2]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(W, x + w + pad)
    y1 = min(H, y + h + pad)
    return frame[y0:y1, x0:x1]


def has_scoreboard_text(text: str) -> bool:
    """Heuristic: scoreboard text contains digits, often a colon for clock."""
    has_digit = bool(re.search(r'\d', text))
    has_clock_or_score = bool(re.search(r'\d:\d|\d{2,3}', text))
    return has_digit and has_clock_or_score


def run_ocr_on_crop(crop: np.ndarray) -> str:
    """Run easyocr (heavy) or fallback to a heuristic 'has-text' check."""
    try:
        import easyocr
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        results = reader.readtext(crop)
        return " ".join(r[1] for r in results)
    except Exception:
        # Fallback: just check if there's enough "text-like" content
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        edges = cv2.Canny(gray, 50, 150)
        density = edges.sum() / (crop.shape[0] * crop.shape[1] * 255)
        return f"<EDGE_DENSITY:{density:.3f}>" if density > 0.05 else ""


def normalize_box(box: tuple[int, int, int, int], snap: int = 10) -> tuple[int, int, int, int]:
    """Round box coordinates to nearest `snap` pixels for clustering across frames."""
    x, y, w, h = box
    return (x // snap * snap, y // snap * snap, w // snap * snap, h // snap * snap)


def detect_scoreboard_roi(
    video_path: Path,
    num_samples: int = 12,
    use_ocr: bool = True,
) -> dict[str, Any]:
    print(f"[auto_roi] sampling {num_samples} frames from {video_path.name} …")
    samples = sample_frames(video_path, num_samples=num_samples)
    print(f"[auto_roi] got {len(samples)} valid frames")

    all_candidates: list[Candidate] = []
    for t, frame in samples:
        boxes = find_candidate_regions(frame)
        kept_in_this_frame = 0
        for box in boxes:
            crop = crop_for_ocr(frame, box)
            text = ""
            if use_ocr:
                text = run_ocr_on_crop(crop)
                if not has_scoreboard_text(text):
                    continue
            else:
                # Edge-density filter as proxy for "text-like"
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
                edges = cv2.Canny(gray, 50, 150)
                density = edges.sum() / max(crop.shape[0] * crop.shape[1] * 255, 1)
                if density < 0.04:  # too few edges = not text
                    continue
                text = f"<EDGE_DENSITY:{density:.3f}>"
            x, y, w, h = box
            all_candidates.append(Candidate(x=x, y=y, w=w, h=h, text=text, score=1.0))
            kept_in_this_frame += 1
        print(f"[auto_roi]   t={t:6.1f}s: {len(boxes)} candidates, {kept_in_this_frame} kept")

    if not all_candidates:
        raise RuntimeError("No scoreboard-like regions detected; manual ROI calibration required.")

    # Cluster candidates by their normalized position
    cluster_counts = Counter()
    for c in all_candidates:
        key = normalize_box((c.x, c.y, c.w, c.h), snap=20)
        cluster_counts[key] += 1

    # Pick the most common cluster as the scoreboard region
    top_key, top_count = cluster_counts.most_common(1)[0]
    matching = [c for c in all_candidates if normalize_box((c.x, c.y, c.w, c.h), snap=20) == top_key]
    avg_x = int(np.mean([c.x for c in matching]))
    avg_y = int(np.mean([c.y for c in matching]))
    avg_w = int(np.mean([c.w for c in matching]))
    avg_h = int(np.mean([c.h for c in matching]))

    print(f"[auto_roi] top scoreboard cluster: {avg_x},{avg_y} {avg_w}x{avg_h} (matched in {top_count}/{len(all_candidates)} samples)")
    print(f"[auto_roi] sample OCR text: {matching[0].text[:80]}")

    duration, width, height = probe_video(video_path)
    # Compose output compatible with existing score_roi.json schema
    # Split the wide scoreboard area into "home" and "away" score halves
    # (rough heuristic: equal halves)
    half = avg_w // 2
    home_roi = {"x": avg_x + half, "y": avg_y, "w": half, "h": avg_h}
    away_roi = {"x": avg_x, "y": avg_y, "w": half, "h": avg_h}

    return {
        "video_path": str(video_path),
        "video_resolution": [width, height],
        "video_duration_seconds": duration,
        "auto_detected": True,
        "scoreboard_bbox": {"x": avg_x, "y": avg_y, "w": avg_w, "h": avg_h},
        "home_score_roi": home_roi,
        "away_score_roi": away_roi,
        "detection": {
            "frames_sampled": len(samples),
            "candidate_count": len(all_candidates),
            "cluster_match_count": top_count,
            "cluster_match_ratio": round(top_count / max(len(all_candidates), 1), 3),
            "ocr_text_sample": matching[0].text[:200],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-detect scoreboard ROI in NBA broadcast video.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR (faster but less reliable; uses edge density only).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    roi = detect_scoreboard_roi(
        video_path=Path(args.video),
        num_samples=args.samples,
        use_ocr=not args.no_ocr,
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(roi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[auto_roi] wrote {args.output}")
    print(f"[auto_roi] home_score_roi: {roi['home_score_roi']}")
    print(f"[auto_roi] away_score_roi: {roi['away_score_roi']}")


if __name__ == "__main__":
    main()
