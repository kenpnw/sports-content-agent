"""Generate a contact-sheet poster of all clips in a report for fast visual QA.

Each thumbnail shows the middle frame, sorted by quality score (high to low),
with a colored border indicating quality tier and labels for snap status + tactic.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path

import cv2
import numpy as np


def quality_score(snap_info, clip):
    score = 50
    snap_label = "—"
    if snap_info:
        o, a = snap_info["original"], snap_info["adjusted"]
        if o == a: score += 20; snap_label = "OK"
        elif o[0] != a[0]: score += 15; snap_label = "SHIFT"
        else: score += 5; snap_label = "TRIM"
    dur = clip["end_seconds"] - clip["start_seconds"]
    if 22 <= dur <= 28: score += 15
    elif dur >= 15: score += 5
    else: score -= 10
    tags = ",".join(clip.get("tactic_tags") or [])
    if "lead_change" in tags: score += 10
    elif "key_shot" in tags or "three_point_creation" in tags: score += 8
    elif "rim_pressure" in tags: score += 6
    elif "turnover" in tags: score += 3
    elif "period_end" in tags: score -= 5
    return max(0, min(100, score)), snap_label


def quality_color(score):
    if score >= 70: return (183, 231, 110)   # green
    if score >= 50: return (36, 191, 251)    # amber
    return (184, 163, 148)                    # gray


def build_poster(report_dir: Path, out_path: Path | None = None, cols: int = 6) -> Path:
    m = json.loads((report_dir / "clip_manifest.json").read_text(encoding="utf-8"))
    clips = m["clips"]
    snap_by_obs = {d["observation_id"]: d for d in m.get("play_segment_snap", {}).get("details", [])}

    indexed = []
    for i, c in enumerate(clips):
        s, snap_label = quality_score(snap_by_obs.get(c["observation_id"]), c)
        indexed.append((i, c, quality_color(s), s, snap_label))
    indexed.sort(key=lambda x: -x[3])

    n = len(indexed)
    rows = (n + cols - 1) // cols
    THUMB_W, THUMB_H = 320, 180
    GAP = 8
    LABEL_H = 44
    poster_w = cols * THUMB_W + (cols + 1) * GAP
    poster_h = 50 + rows * (THUMB_H + LABEL_H) + (rows + 1) * GAP
    poster = np.full((poster_h, poster_w, 3), 14, dtype=np.uint8)

    cv2.rectangle(poster, (0, 0), (poster_w, 50), (24, 32, 50), -1)
    cv2.putText(poster, f"{report_dir.name}  -  {n} clips sorted by quality (green=hi)",
                (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (110, 231, 183), 1, cv2.LINE_AA)

    for pos, (orig_idx, clip, color, score, snap_label) in enumerate(indexed):
        row, col = pos // cols, pos % cols
        x = GAP + col * (THUMB_W + GAP)
        y = 50 + GAP + row * (THUMB_H + LABEL_H + GAP)
        label = os.path.splitext(os.path.basename(clip.get("gif_path", "")))[0]
        for ftry in ("frame_04.jpg", "frame_03.jpg", "frame_02.jpg", "frame_05.jpg", "frame_01.jpg"):
            fpath = report_dir / "clips" / f"{label}_frames" / ftry
            if fpath.exists():
                thumb = cv2.imread(str(fpath))
                if thumb is not None:
                    poster[y:y+THUMB_H, x:x+THUMB_W] = cv2.resize(thumb, (THUMB_W, THUMB_H))
                    break
        cv2.rectangle(poster, (x-2, y-2), (x+THUMB_W+2, y+THUMB_H+2), color, 3)
        label_y = y + THUMB_H + 4
        cv2.rectangle(poster, (x, label_y), (x+THUMB_W, label_y+LABEL_H-4), (24, 32, 50), -1)
        text = f"#{orig_idx+1:02d}  Q{clip['period']} {clip['clock'][:7].replace('PT','')}  Q{score}  [{snap_label}]"
        cv2.putText(poster, text, (x+6, label_y+18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        desc = (clip.get("event_description","") or "")[:38]
        cv2.putText(poster, desc, (x+6, label_y+34), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 200, 200), 1, cv2.LINE_AA)

    out = out_path or (report_dir / "clip_overview_poster.jpg")
    cv2.imwrite(str(out), poster, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"wrote {out}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report-dir", required=True)
    p.add_argument("--output", default="")
    p.add_argument("--cols", type=int, default=6)
    args = p.parse_args()
    build_poster(Path(args.report_dir), Path(args.output) if args.output else None, cols=args.cols)


if __name__ == "__main__":
    main()
