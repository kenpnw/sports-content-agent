"""Rebuild clip positions using a clean per-period linear PBP map,
then re-cut MP4 + GIF + 6 keyframes for every clip.

Use when the OCR-based time_map snap-collapses multiple distinct events
onto the same video window (e.g., NBA replay overlay freezing the
scoreboard). This script:

  1. Reads observations.normalized.json (the 60 events with PBP timing)
  2. Reads time_map.json's OCR samples (truncation-safe)
  3. Filters samples to LIVE-only (drops 'frozen' runs from replays)
  4. Fits a robust per-period linear video<->game time map
  5. Computes a fresh video position for each event using:
        video_t = period_anchor + game_elapsed * period_ratio
  6. Re-cuts each clip's MP4 + GIF + 6 keyframes at the new position
  7. Updates clip_manifest.json with new start/end seconds (atomic write)

No LLM calls. Runtime: ~5-10 min for 60 clips on a typical laptop.

Usage:
    python -m thesis_scripts.recover_clip_positions \\
        --report data/generated/video_scout/real_game_0042500315_v1 \\
        --video data/videos/sas_okc_wcf.mkv
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Make repo modules importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_pt(pt_str: str) -> float | None:
    """PT9M56.00S -> 596 seconds remaining."""
    m = re.match(r"PT(\d+)M([\d.]+)S", pt_str or "")
    if not m:
        return None
    return float(m.group(1)) * 60.0 + float(m.group(2))


def _read_json_truncation_safe(path: Path) -> dict:
    """Some files may have been left with a partial trailing object
    from a non-atomic write. Take the first valid JSON object."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(raw)
    return obj


def _load_observations(report_dir: Path) -> list[dict]:
    obs_path = report_dir / "observations.normalized.json"
    if not obs_path.exists():
        raise FileNotFoundError(obs_path)
    data = _read_json_truncation_safe(obs_path)
    # observations file is a top-level list
    if isinstance(data, list):
        return data
    return data.get("observations", []) or []


def _load_time_map(video_path: Path) -> dict:
    tmap_path = video_path.with_suffix(".time_map.json")
    if not tmap_path.exists():
        raise FileNotFoundError(tmap_path)
    return _read_json_truncation_safe(tmap_path)


def _cleaned_samples_for_period(
    samples: list[dict],
    period: int,
    anchor: float,
    next_anchor: float | None,
) -> list[dict]:
    """Return OCR samples for a period after dropping replay-frozen runs
    and obvious outliers. Sorted by video_seconds ascending.

    Critical: filter samples to lie within this period's video range
    [anchor, next_anchor). NBA OCR sometimes misreads '1ST' as '4TH'
    or vice versa, polluting one period's sample list with frames
    that actually belong to a different period.
    """
    # Period-range filter: samples must be within this period's video window
    upper = next_anchor if next_anchor else float("inf")
    in_period = [
        s for s in samples
        if s.get("period") == period
        and s.get("clock_remaining_seconds") is not None
        and anchor - 30.0 <= s.get("video_seconds", 0) < upper + 30.0
        # 30s slack on each side to accommodate slightly mis-anchored samples
    ]
    if not in_period:
        return []
    in_period.sort(key=lambda s: s["video_seconds"])

    # Step 1: drop frozen runs (≥3 consecutive samples reading same clock within 5s)
    cleaned: list[dict] = []
    i = 0
    while i < len(in_period):
        j = i + 1
        while j < len(in_period) and abs(
            in_period[j]["clock_remaining_seconds"] - in_period[i]["clock_remaining_seconds"]
        ) <= 5.0:
            j += 1
        run = in_period[i:j]
        if len(run) >= 3:
            cleaned.append(run[0])  # keep first (live game just before freeze)
        else:
            cleaned.extend(run)
        i = j

    # Step 2: enforce monotonic decreasing clock_remaining (events go forward)
    monotonic: list[dict] = [cleaned[0]] if cleaned else []
    for s in cleaned[1:]:
        last = monotonic[-1]
        if s["clock_remaining_seconds"] <= last["clock_remaining_seconds"] + 2.0:
            monotonic.append(s)
        # else: clock went BACKWARDS — almost certainly OCR error, skip
    return monotonic


def _video_seconds_for_event(
    period: int,
    clock_remaining_target: float,
    anchors: dict,
    cleaned_samples_by_period: dict[int, list[dict]],
) -> float:
    """Piecewise-linear interpolation between adjacent OCR samples.

    For an event with `clock_remaining_target` seconds left in `period`,
    find the two surrounding samples and linearly interpolate their
    video_seconds. Falls back to anchor-based linear if out of range.
    """
    anchor_raw = anchors.get(str(period), anchors.get(period, 0.0))
    anchor = float(anchor_raw)
    samples = cleaned_samples_by_period.get(period, [])

    if not samples:
        # No usable samples — fall back to global linear assumption
        # (12-min period, no per-period info available)
        return anchor + (720.0 - clock_remaining_target) * 1.5

    # samples are sorted by video_seconds asc, which since
    # clock_remaining DECREASES over time = also sorted by clock_remaining DESC
    # Walk to find bracketing pair
    for i in range(len(samples) - 1):
        s1, s2 = samples[i], samples[i + 1]
        c1 = s1["clock_remaining_seconds"]
        c2 = s2["clock_remaining_seconds"]
        if c1 >= clock_remaining_target >= c2:
            # Interpolate
            span_clock = c1 - c2
            if span_clock < 0.5:
                return s1["video_seconds"]
            t = (c1 - clock_remaining_target) / span_clock
            v1 = s1["video_seconds"]
            v2 = s2["video_seconds"]
            return v1 + t * (v2 - v1)

    # Target is OUTSIDE sample range — extrapolate from nearest end
    first, last = samples[0], samples[-1]
    if clock_remaining_target > first["clock_remaining_seconds"]:
        # event is EARLIER than first sample — extrapolate from anchor
        if len(samples) >= 2:
            # Use the slope between anchor (clock=720) and first sample
            game_elapsed_to_first = 720.0 - first["clock_remaining_seconds"]
            video_offset_to_first = first["video_seconds"] - anchor
            if game_elapsed_to_first > 5:
                local_ratio = video_offset_to_first / game_elapsed_to_first
                return anchor + (720.0 - clock_remaining_target) * local_ratio
        return anchor + (720.0 - clock_remaining_target) * 1.0
    else:
        # event is LATER than last sample — extrapolate from last segment
        if len(samples) >= 2:
            s_prev = samples[-2]
            span_clock = s_prev["clock_remaining_seconds"] - last["clock_remaining_seconds"]
            if span_clock > 0.5:
                local_ratio = (last["video_seconds"] - s_prev["video_seconds"]) / span_clock
                return last["video_seconds"] + (last["clock_remaining_seconds"] - clock_remaining_target) * local_ratio
        return last["video_seconds"] + (last["clock_remaining_seconds"] - clock_remaining_target) * 1.5


def _recut_clip(
    *,
    video_path: Path,
    clip_path: Path,
    new_start: float,
    new_end: float,
    gif_fps: int = 10,
    gif_width: int = 480,
) -> bool:
    """Re-cut MP4 + GIF + 6 keyframes at new times."""
    duration = max(1.0, new_end - new_start)
    gif_path = clip_path.with_suffix(".gif")
    frames_dir = clip_path.parent / f"{clip_path.stem}_frames"

    # MP4
    r = subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{max(0.0, new_start):.2f}",
        "-i", str(video_path),
        "-t", f"{duration:.2f}",
        "-c", "copy",
        str(clip_path),
    ], capture_output=True, timeout=60)
    if r.returncode != 0:
        return False

    # GIF
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(clip_path),
        "-vf", f"fps={gif_fps},scale={gif_width}:-1:flags=lanczos",
        "-loop", "0",
        str(gif_path),
    ], capture_output=True, timeout=60)

    # 6 keyframes (evenly spaced in second half of clip)
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(exist_ok=True)
    for i in range(6):
        offset = 0.5 + (i + 0.5) / 12.0  # 54%, 62%, 71%, 79%, 88%, 96%
        t = new_start + offset * duration
        out = frames_dir / f"frame_{i+1:02d}.jpg"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{max(0.0, t):.2f}",
            "-i", str(video_path),
            "-vframes", "1",
            str(out),
        ], capture_output=True, timeout=30)
    return True


def _atomic_write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="Report dir")
    ap.add_argument("--video", required=True, help="Source video")
    ap.add_argument("--clip-before", type=float, default=8.0, help="seconds before event (default 8)")
    ap.add_argument("--clip-after", type=float, default=8.0, help="seconds after event (default 8)")
    ap.add_argument("--dry-run", action="store_true", help="Compute new positions but don't re-cut")
    ap.add_argument("--manifest-only", action="store_true",
                    help="Skip re-cutting; only rewrite clip_manifest.json with new positions. "
                    "Use when clips were already re-cut by a prior run that crashed before manifest write.")
    args = ap.parse_args()

    report_dir = Path(args.report).resolve()
    video_path = Path(args.video).resolve()
    for p in (report_dir, video_path):
        if not p.exists():
            print(f"[error] missing: {p}", file=sys.stderr)
            sys.exit(1)

    # ---- Load ----
    print(f"[info] loading observations from {report_dir}")
    observations = _load_observations(report_dir)
    print(f"[info] {len(observations)} observations")

    print(f"[info] loading time_map from {video_path.with_suffix('.time_map.json')}")
    tmap = _load_time_map(video_path)
    anchors = tmap.get("period_anchors") or {}
    samples = tmap.get("samples") or []
    print(f"[info] {len(samples)} OCR samples; anchors: {anchors}")

    # ---- Build cleaned per-period sample lists (frozen-run filter + monotonicity + range) ----
    sorted_anchors = sorted(((int(p), float(v)) for p, v in anchors.items()), key=lambda x: x[1])
    cleaned_by_period: dict[int, list[dict]] = {}
    print(f"\n[info] per-period sample cleaning:")
    for idx, (period, anchor) in enumerate(sorted_anchors):
        next_anchor = sorted_anchors[idx + 1][1] if idx + 1 < len(sorted_anchors) else None
        all_in_period = [s for s in samples if s.get("period") == period and s.get("clock_remaining_seconds") is not None]
        cleaned = _cleaned_samples_for_period(samples, period, anchor, next_anchor)
        cleaned_by_period[period] = cleaned
        print(f"  Q{period}: anchor={anchor:.0f}s, raw_samples={len(all_in_period)}, cleaned={len(cleaned)} "
              f"(replay+outlier filter)")
        if cleaned:
            first, last = cleaned[0], cleaned[-1]
            game_span = first["clock_remaining_seconds"] - last["clock_remaining_seconds"]
            video_span = last["video_seconds"] - first["video_seconds"]
            avg_ratio = video_span / game_span if game_span > 5 else 0
            print(f"       span: clock {first['clock_remaining_seconds']:.0f}->{last['clock_remaining_seconds']:.0f} "
                  f"({game_span:.0f}s game), video {first['video_seconds']:.0f}->{last['video_seconds']:.0f} "
                  f"({video_span:.0f}s), avg ratio={avg_ratio:.2f}")

    # ---- Compute new positions via piecewise interpolation ----
    clip_before = args.clip_before
    clip_after = args.clip_after
    new_positions = []
    for i, obs in enumerate(observations, 1):
        period = int(obs.get("period", 0) or 0)
        clock_pt = obs.get("clock") or ""
        clock_rem = _parse_pt(clock_pt)
        if not period or clock_rem is None:
            new_positions.append(None)
            continue
        video_t = _video_seconds_for_event(period, clock_rem, anchors, cleaned_by_period)
        new_start = max(0.0, video_t - clip_before)
        new_end = video_t + clip_after
        new_positions.append({"start": new_start, "end": new_end, "event_t": video_t})

    print(f"\n[info] new positions (first 20):")
    print(f"  {'#':<3} {'period':<3} {'clock':<10} {'old_start':>9} {'new_start':>9} {'shift':>8}")
    clip_manifest_path = report_dir / "clip_manifest.json"
    old_manifest = _read_json_truncation_safe(clip_manifest_path) if clip_manifest_path.exists() else {"clips": []}
    old_clips = old_manifest.get("clips", []) or []
    for i in range(min(20, len(observations))):
        obs = observations[i]
        np = new_positions[i]
        if np is None:
            print(f"  {i+1:<3} ??       skipped (no clock)")
            continue
        old_start = old_clips[i].get("start_seconds", 0) if i < len(old_clips) else 0
        shift = np["start"] - old_start
        print(f"  {i+1:<3} Q{obs.get('period')}  {obs.get('clock', '')[:10]:<10} {old_start:>9.1f} {np['start']:>9.1f} {shift:>+8.1f}")

    if args.dry_run:
        print("\n[dry-run] not re-cutting clips. Re-run without --dry-run to apply.")
        return

    # ---- Re-cut each clip ----
    print(f"\n[info] re-cutting {len(old_clips)} clips...")
    clips_dir = report_dir / "clips"
    if not clips_dir.exists():
        print(f"[error] clips dir missing: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    ok_count = fail_count = 0
    for i, clip in enumerate(old_clips):
        if i >= len(new_positions) or new_positions[i] is None:
            continue
        np = new_positions[i]
        clip_filename = Path(clip.get("output_path") or clip.get("gif_path", "")).name
        if not clip_filename:
            fail_count += 1
            continue
        clip_path = clips_dir / (clip_filename if clip_filename.endswith(".mp4") else Path(clip_filename).stem + ".mp4")
        if args.manifest_only:
            # Skip re-cutting — just patch the manifest entry
            clip["start_seconds"] = np["start"]
            clip["end_seconds"] = np["end"]
            clip["recut_by_recover_positions"] = True
            ok_count += 1
            continue
        if not clip_path.exists():
            print(f"  [{i+1}/60] clip mp4 not found: {clip_path.name}")
            fail_count += 1
            continue
        ok = _recut_clip(
            video_path=video_path,
            clip_path=clip_path,
            new_start=np["start"],
            new_end=np["end"],
        )
        if ok:
            ok_count += 1
            clip["start_seconds"] = np["start"]
            clip["end_seconds"] = np["end"]
            clip["recut_by_recover_positions"] = True
        else:
            fail_count += 1
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(old_clips)}] re-cut {ok_count} OK, {fail_count} failed")

    print(f"\n[info] writing updated clip_manifest.json (atomic)")
    old_manifest["recover_positions_at"] = datetime.now().isoformat()
    old_manifest["recover_positions_summary"] = {
        "ok": ok_count,
        "failed": fail_count,
        "total": len(old_clips),
        "cleaned_samples_per_period": {
            str(p): len(cleaned_by_period.get(p, [])) for p, _ in sorted_anchors
        },
    }
    _atomic_write_json(clip_manifest_path, old_manifest)

    print()
    print("=" * 60)
    print(f"Done: {ok_count}/{len(old_clips)} clips re-cut successfully")
    print(f"      {fail_count} failed")
    print(f"      manifest updated at {clip_manifest_path}")
    print(f"      cleaned samples per period: {[(p, len(cleaned_by_period.get(p, []))) for p, _ in sorted_anchors]}")
    print("=" * 60)
    print("\nNext: reload the tactical_review webapp page (Ctrl+F5).")
    print("Verify with: python -m thesis_scripts.verify_clip_alignment ...")


if __name__ == "__main__":
    main()
