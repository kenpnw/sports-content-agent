"""Extract keyframes from clip MP4 files for the tactical_review frontend.

For each MP4 in a `clips/` directory, extract N evenly-spaced JPG frames
and save them next to the MP4 in a sibling `<basename>_frames/` directory.

Usage:
    python -m video_scout.extract_clip_frames --report-dir data/generated/video_scout/real_okc_lal_g1_v3_neighbor
    python -m video_scout.extract_clip_frames --report-dir <dir> --frames 8
    python -m video_scout.extract_clip_frames --all   # process all reports

Requires `ffmpeg` and `ffprobe` to be installed and on PATH.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


DEFAULT_FRAME_COUNT = 6
DEFAULT_QUALITY = 2  # ffmpeg -q:v (lower=better, 2 is near-lossless JPEG)


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH. Please install ffmpeg first.")
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found on PATH. Please install ffmpeg first.")


def probe_duration_seconds(mp4_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return 0.0


def extract_one(mp4_path: Path, frames: int, quality: int, force: bool) -> dict:
    duration = probe_duration_seconds(mp4_path)
    out_dir = mp4_path.parent / f"{mp4_path.stem}_frames"

    if out_dir.exists() and not force:
        existing = sorted(out_dir.glob("frame_*.jpg"))
        if len(existing) >= frames:
            return {
                "clip": mp4_path.name,
                "frames": [p.name for p in existing],
                "duration": duration,
                "status": "skipped (already extracted)",
            }

    out_dir.mkdir(parents=True, exist_ok=True)
    if duration <= 0:
        return {
            "clip": mp4_path.name,
            "frames": [],
            "duration": duration,
            "status": "skipped (zero duration)",
        }

    # Sampling strategy:
    # - Bias toward the second half of the clip (action concentration)
    # - First frame at 10% of clip, then evenly spaced through 95%
    timestamps = []
    start_frac, end_frac = 0.10, 0.95
    if frames <= 1:
        timestamps = [duration * 0.5]
    else:
        step = (end_frac - start_frac) / (frames - 1)
        timestamps = [duration * (start_frac + i * step) for i in range(frames)]

    saved = []
    for idx, ts in enumerate(timestamps, start=1):
        out_path = out_dir / f"frame_{idx:02d}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(mp4_path),
                "-frames:v",
                "1",
                "-q:v",
                str(quality),
                "-y",
                str(out_path),
            ],
            capture_output=True,
            check=False,
        )
        if out_path.exists():
            saved.append(out_path.name)

    return {
        "clip": mp4_path.name,
        "frames": saved,
        "duration": duration,
        "status": "ok" if saved else "failed",
    }


def find_clip_dirs(report_dir: Path) -> Iterable[Path]:
    clips_dir = report_dir / "clips"
    if not clips_dir.exists():
        return []
    return [clips_dir]


def process_report_dir(report_dir: Path, frames: int, quality: int, force: bool) -> dict:
    summary = {"report_dir": str(report_dir), "clips_processed": []}
    for clips_dir in find_clip_dirs(report_dir):
        for mp4_path in sorted(clips_dir.glob("*.mp4")):
            info = extract_one(mp4_path, frames=frames, quality=quality, force=force)
            summary["clips_processed"].append(info)
    return summary


def list_all_reports(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if (p / "clips").exists())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract keyframes from clip MP4 files.")
    parser.add_argument(
        "--report-dir",
        help="Path to a single report directory (e.g. data/generated/video_scout/<id>).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every report under data/generated/video_scout/",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=DEFAULT_FRAME_COUNT,
        help=f"Number of frames per clip (default: {DEFAULT_FRAME_COUNT}).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"JPEG quality 2-31, lower=better (default: {DEFAULT_QUALITY}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if frames already exist.",
    )
    parser.add_argument(
        "--video-scout-root",
        default="data/generated/video_scout",
        help="Root directory for video_scout reports (default: data/generated/video_scout).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_ffmpeg()

    targets: list[Path] = []
    if args.report_dir:
        targets.append(Path(args.report_dir).resolve())
    if args.all:
        targets.extend(list_all_reports(Path(args.video_scout_root).resolve()))

    if not targets:
        raise SystemExit("No report directory provided. Use --report-dir or --all.")

    overall = []
    for report_dir in targets:
        if not report_dir.exists():
            print(f"[skip] {report_dir} does not exist")
            continue
        summary = process_report_dir(
            report_dir, frames=args.frames, quality=args.quality, force=args.force
        )
        overall.append(summary)
        print(f"[ok] {report_dir.name}: processed {len(summary['clips_processed'])} clips")
        for info in summary["clips_processed"]:
            print(f"     - {info['clip']}: {info['status']} ({len(info['frames'])} frames)")

    print()
    print(json.dumps(overall, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
