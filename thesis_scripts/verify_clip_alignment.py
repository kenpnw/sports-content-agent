"""Independent ground-truth verification of clip alignment.

For each clip in a generated report:
  1. Use ffmpeg to extract a single frame at the *center* of the clip window
     (i.e., where the event is supposed to be visible).
  2. OCR the scoreboard ROI on that frame.
  3. Compare the extracted clock to the labeled clock from the PBP.
  4. Categorize the diff into buckets.

Output:
  - Per-clip CSV: clip_id, period, label_clock, ocr_clock, diff_seconds, verdict
  - Summary: how many clips are within 0/2/5/15/60+ seconds of the label

Crucially, this is independent of the per-event refinement's self-report,
so it gives the *real* user-visible alignment accuracy.

Run from repo root (needs ffmpeg + EasyOCR + the .scoreboard_roi.json):

    python -m thesis_scripts.verify_clip_alignment \\
        --report data/generated/video_scout/real_game_0042500315_v1 \\
        --video data/videos/sas_okc_wcf.mkv \\
        --roi data/videos/sas_okc_wcf.scoreboard_roi.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        import os
        os.environ.setdefault(k, v)


CLOCK_PATTERNS = [
    re.compile(r"(\d{1,2})[:.](\d{2})"),    # MM:SS or M.SS
    re.compile(r"(\d{1,2})[ ]+(\d{2})"),     # MM  SS (sometimes OCR splits)
]


def _parse_pt_clock(pt_str: str) -> float | None:
    """Parse 'PT9M56.00S' -> 9*60+56 = 596 seconds remaining."""
    if not pt_str:
        return None
    m = re.match(r"PT(\d+)M([\d.]+)S", pt_str)
    if not m:
        return None
    try:
        return float(m.group(1)) * 60.0 + float(m.group(2))
    except ValueError:
        return None


def _parse_clock_from_text(text: str) -> tuple[int, int] | None:
    """Find MM:SS in raw OCR text. Returns (minutes, seconds) or None."""
    text = text.replace("|", "1").replace("l", "1").replace("O", "0").replace("o", "0")
    for pat in CLOCK_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                mm = int(m.group(1))
                ss = int(m.group(2))
                if 0 <= mm <= 12 and 0 <= ss <= 59:
                    return (mm, ss)
            except ValueError:
                continue
    return None


def _extract_frame(video: Path, second: float, out_path: Path) -> bool:
    """Use ffmpeg to dump a single frame at the given second."""
    cmd = [
        "ffmpeg", "-y", "-ss", str(second), "-i", str(video),
        "-vframes", "1", "-loglevel", "error", str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0


def _crop_roi(frame_path: Path, roi: dict, out_path: Path) -> bool:
    from PIL import Image
    try:
        im = Image.open(frame_path)
        x, y, w, h = int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])
        crop = im.crop((x, y, x + w, y + h))
        crop.save(out_path)
        return True
    except Exception as exc:
        print(f"  crop failed: {exc}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="Report dir (contains report.json + clip_manifest.json)")
    ap.add_argument("--video", required=True, help="Source video file")
    ap.add_argument("--roi", required=True, help="ROI JSON file")
    ap.add_argument("--output", default="", help="CSV output path (default: <report>/clip_alignment_verification.csv)")
    ap.add_argument("--limit", type=int, default=0, help="Only verify first N clips (for quick test)")
    args = ap.parse_args()

    _load_env()
    report_dir = Path(args.report)
    video_path = Path(args.video)
    roi_path = Path(args.roi)
    for p in (report_dir, video_path, roi_path):
        if not p.exists():
            print(f"[ERROR] missing: {p}")
            sys.exit(1)

    roi = json.loads(roi_path.read_text(encoding="utf-8")).get("roi") or {}
    if not all(k in roi for k in ("x", "y", "w", "h")):
        print("[ERROR] ROI JSON missing x/y/w/h")
        sys.exit(1)

    manifest = json.loads((report_dir / "clip_manifest.json").read_text(encoding="utf-8"))
    clips = manifest.get("clips") or []
    if args.limit > 0:
        clips = clips[: args.limit]
    print(f"[info] verifying {len(clips)} clips")

    try:
        import easyocr
    except ImportError:
        print("[ERROR] pip install easyocr")
        sys.exit(1)
    reader = easyocr.Reader(["en"], gpu=False)

    out_csv = Path(args.output) if args.output else (report_dir / "clip_alignment_verification.csv")
    out_csv.write_text("idx,clip_id,period,label_clock,center_video_sec,ocr_text,ocr_clock,diff_seconds,verdict\n", encoding="utf-8")

    bucket_count = Counter()
    bucket_thresholds = [(2, "perfect"), (5, "good"), (15, "off"), (60, "bad"), (10_000, "very_bad")]

    work_dir = Path(tempfile.mkdtemp(prefix="verify_"))
    print(f"[info] temp dir: {work_dir}")

    for i, clip in enumerate(clips, 1):
        clip_id = clip.get("clip_id") or clip.get("clip_label") or f"clip_{i}"
        period = int(clip.get("period", 0) or 0)
        label_clock_pt = clip.get("clock") or clip.get("label_clock") or ""
        label_seconds = _parse_pt_clock(label_clock_pt)
        # Clip cut window: extract frame at CENTER (where the event should be)
        start = float(clip.get("start_seconds") or clip.get("clip_start_seconds") or 0)
        end = float(clip.get("end_seconds") or clip.get("clip_end_seconds") or start + 26)
        # Per design, event at ~78% of clip (8s lead, 2s follow on default 10s window)
        # But generic safe: take center frame
        center = (start + end) / 2.0
        if center <= 0:
            print(f"[warn] clip {i} {clip_id}: bad start/end times")
            continue

        # Extract + crop + OCR
        frame_full = work_dir / f"f_{i:03d}.png"
        frame_roi = work_dir / f"r_{i:03d}.png"
        if not _extract_frame(video_path, center, frame_full):
            verdict = "extract_failed"
            ocr_text = ""
            ocr_clock = ""
            diff = ""
        elif not _crop_roi(frame_full, roi, frame_roi):
            verdict = "crop_failed"
            ocr_text = ""
            ocr_clock = ""
            diff = ""
        else:
            ocr_results = reader.readtext(str(frame_roi))
            ocr_text = " | ".join(t[1] for t in ocr_results)
            parsed = _parse_clock_from_text(ocr_text)
            if parsed is None:
                verdict = "ocr_no_clock"
                ocr_clock = ""
                diff = ""
            else:
                mm, ss = parsed
                ocr_seconds = mm * 60 + ss
                ocr_clock = f"{mm}:{ss:02d}"
                if label_seconds is None:
                    verdict = "no_label"
                    diff = ""
                else:
                    diff_s = abs(ocr_seconds - label_seconds)
                    diff = f"{diff_s:.1f}"
                    verdict = next(name for limit, name in bucket_thresholds if diff_s <= limit)
        bucket_count[verdict] += 1

        # Print live
        label_disp = f"{label_seconds:.0f}s" if label_seconds is not None else "?"
        print(f"  [{i:2d}/{len(clips)}] Q{period} label={label_disp:>5} ocr={ocr_clock or '?':>5} diff={diff:>5} -> {verdict}")
        # CSV row
        with out_csv.open("a", encoding="utf-8") as f:
            f.write(f"{i},{clip_id},{period},{label_clock_pt},{center:.1f},{ocr_text.replace(',', ' ')},{ocr_clock},{diff},{verdict}\n")

    print()
    print("=" * 60)
    print("Verification Summary")
    print("-" * 60)
    total = sum(bucket_count.values())
    for bucket in ("perfect", "good", "off", "bad", "very_bad", "ocr_no_clock", "crop_failed", "extract_failed"):
        n = bucket_count.get(bucket, 0)
        pct = (100.0 * n / total) if total else 0
        print(f"  {bucket:<18} {n:>3}  ({pct:5.1f}%)")
    print("-" * 60)
    perfect_or_good = bucket_count.get("perfect", 0) + bucket_count.get("good", 0)
    pog_pct = (100.0 * perfect_or_good / total) if total else 0
    print(f"  TRUE ALIGNMENT (perfect+good, <=5s): {perfect_or_good}/{total} = {pog_pct:.1f}%")
    print("=" * 60)
    print(f"[saved] {out_csv}")


if __name__ == "__main__":
    main()
