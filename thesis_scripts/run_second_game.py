"""End-to-end pipeline for a SECOND game (generalization evidence for the thesis).

Run this AFTER you've downloaded the video and know the NBA game_id.

Usage (PowerShell from repo root):

    # Step 1: pull PBP from NBA Live API (uses the game_id)
    python -m thesis_scripts.run_second_game `
        --video-path "data/videos/<your_game>.mkv" `
        --game-id 0042400321 `
        --slug ind_cle_g3

Behaviour:
    1. Fetches PBP via ingestion.nba_live (writes data/generated/.../pbp.json)
    2. Tries auto_roi_detector first; if quality too low, asks user to manually
       set ROI (writes <slug>.scoreboard_roi.json and exits)
    3. Runs scoreboard_visibility_detector (v2 dense templates)
    4. Runs video_time_mapper to build OCR time_map
    5. Runs video_scout/demo_runner with --use-llm --apply-time-map --play-segments
    6. Output:
        data/generated/video_scout/real_<slug>_g1_v1/
            report.json, report.md, clips/, clip_manifest.json
    7. Prints summary table for thesis Chapter 5 generalization section.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        print("[ERROR] .env not found.")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--video-path", required=True, help="Path to the downloaded .mkv/.mp4 file"
    )
    parser.add_argument(
        "--game-id", required=True, help="NBA game_id like 0042400321"
    )
    parser.add_argument(
        "--slug",
        required=True,
        help="Short identifier for output folder, e.g. ind_cle_g3",
    )
    parser.add_argument(
        "--skip-roi", action="store_true", help="Skip auto-ROI detector; use existing roi file"
    )
    args = parser.parse_args()

    _load_env()

    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"[ERROR] video not found: {video_path}")
        sys.exit(1)

    out_root = Path(f"data/generated/video_scout/real_{args.slug}_v1")
    out_root.mkdir(parents=True, exist_ok=True)

    # ---- Stage 1: PBP fetch ----
    print(f"\n[1/5] Fetching PBP for game {args.game_id}...")
    pbp_path = out_root / "pbp.json"
    cmd = [
        sys.executable,
        "-m",
        "ingestion.nba_pbp_fetcher",
        "--game-id",
        args.game_id,
        "--output",
        str(pbp_path),
    ]
    print("   $", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("[ERROR] PBP fetch failed:")
        print(r.stderr[-2000:])
        sys.exit(1)
    print(f"   ok -> {pbp_path}")

    # ---- Stage 2: ROI ----
    roi_path = video_path.with_suffix(".scoreboard_roi.json")
    if not args.skip_roi and not roi_path.exists():
        print(f"\n[2/5] Auto-ROI detection on {video_path.name}...")
        cmd = [
            sys.executable,
            "-m",
            "video_scout.auto_roi_detector",
            "--video",
            str(video_path),
            "--output",
            str(roi_path),
        ]
        print("   $", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("[WARN] auto-ROI failed; you may need to set ROI manually")
            print(r.stderr[-1000:])
        else:
            print(f"   ok -> {roi_path}")
    else:
        print(f"\n[2/5] Reusing existing ROI: {roi_path}")

    # ---- Stage 3: Visibility detector v2 ----
    print(f"\n[3/5] Scoreboard visibility detector (dense v2)...")
    vis_path = video_path.with_suffix(".scoreboard_visibility_v2.json")
    cmd = [
        sys.executable,
        "-m",
        "video_scout.scoreboard_visibility_detector",
        "--video",
        str(video_path),
        "--roi",
        str(roi_path),
        "--output",
        str(vis_path),
        "--mode",
        "dense_v2",
    ]
    print("   $", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("[WARN] visibility detector failed; will fall back to no-snap")
        print(r.stderr[-1000:])

    # ---- Stage 4: time_map ----
    print(f"\n[4/5] Building OCR time_map...")
    tmap_path = video_path.with_suffix(".time_map.json")
    cmd = [
        sys.executable,
        "-m",
        "video_scout.video_time_mapper",
        "--video",
        str(video_path),
        "--roi",
        str(roi_path),
        "--output",
        str(tmap_path),
    ]
    print("   $", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("[WARN] time_map failed")
        print(r.stderr[-1000:])
    else:
        print(f"   ok -> {tmap_path}")

    # ---- Stage 5: end-to-end demo_runner ----
    print(f"\n[5/5] Running full tactical pipeline (DeepSeek)...")
    t0 = time.time()
    cmd = [
        sys.executable,
        "-m",
        "video_scout.demo_runner",
        "--video",
        str(video_path),
        "--replay",
        str(pbp_path),
        "--auto-observations",
        "--auto-periods",
        "1,2,3,4",
        "--use-llm",
        "--apply-time-map",
        "--time-map",
        str(tmap_path),
        "--refine-events",
        "--roi",
        str(roi_path),
        "--output-dir",
        str(out_root),
    ]
    if vis_path.exists():
        cmd.extend(["--play-segments", str(vis_path)])
    print("   $", " ".join(cmd))
    r = subprocess.run(cmd)
    elapsed = time.time() - t0
    if r.returncode != 0:
        print(f"[ERROR] demo_runner failed (rc={r.returncode})")
        sys.exit(1)

    print(f"\n[done] Full pipeline in {elapsed:.1f}s")
    print(f"        Output:      {out_root}")
    print(f"        Inspect:     report.json / report.md / clips/")
    print(f"        Use as v1 of '{args.slug}' for thesis Chapter 5 generalization.")


if __name__ == "__main__":
    main()
