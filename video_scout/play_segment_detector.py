"""Detect "real play" vs "non-play" (replay/commercial/closeup) segments in NBA broadcast video.

Combines two cheap signals from ffmpeg:
  1. Scene-change density — rapid cuts indicate replays/montages, sustained shots indicate live play.
  2. Audio RMS — sustained mid/high RMS indicates crowd noise (play), low RMS indicates commercial/silence.

Outputs a JSON file with two lists:
  - play_segments: ranges of video time considered live game action
  - non_play_segments: ranges considered to be non-play (replay/ad/closeup/pregame)

Downstream consumers (e.g., event_anchor_refiner) constrain their search to play_segments only.

Usage:
    python -m video_scout.play_segment_detector --video data/videos/nba_demo.MKV --output data/videos/nba_demo.play_segments.json

Tunables:
    --scene-threshold     ffmpeg scene-change detection threshold (default 0.3, range 0.0-1.0; lower = more cuts)
    --bucket-seconds      width of analysis window in seconds (default 1.0)
    --min-segment         shortest segment kept (default 4 seconds; smaller fragments are merged into neighbors)
    --rms-threshold-db    RMS dB below which audio is considered "quiet" (default -40)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------- Tunable defaults ----------
DEFAULT_SCENE_THRESHOLD = 0.30
DEFAULT_BUCKET_SECONDS = 1.0
DEFAULT_MIN_SEGMENT_SECONDS = 4.0
DEFAULT_RMS_THRESHOLD_DB = -40.0
DEFAULT_RAPID_CUT_PER_5S = 3   # >= this many cuts in a 5s window = "rapid cut" (replay/montage)
DEFAULT_SUSTAINED_SHOT_SECONDS = 4.0  # shot longer than this is "sustained" (likely play)


@dataclass
class Segment:
    start: float
    end: float
    label: str       # "play" | "non_play"
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "duration": round(self.end - self.start, 2),
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
        }


def ensure_tools() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg / ffprobe not found on PATH. Install ffmpeg first.")


def probe_duration_seconds(video_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return 0.0


def extract_scene_cuts(video_path: Path, threshold: float) -> list[float]:
    """Run ffmpeg scene-change detection and return list of cut timestamps (seconds)."""
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info",
        "-i", str(video_path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    cuts: list[float] = []
    pat = re.compile(r"pts_time:([\d.]+)")
    for line in proc.stderr.splitlines():
        if "showinfo" in line:
            m = pat.search(line)
            if m:
                try:
                    cuts.append(float(m.group(1)))
                except ValueError:
                    pass
    return cuts


def extract_audio_rms(video_path: Path, bucket_seconds: float, duration_seconds: float) -> list[float]:
    """Return RMS dB per bucket of bucket_seconds width.

    We aggregate ffmpeg's astats output (which fires at arbitrary frame intervals)
    into fixed-width buckets keyed off pts_time.

    Output index = bucket k covers [k*bucket_seconds, (k+1)*bucket_seconds).
    """
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info",
        "-i", str(video_path),
        "-vn",
        "-ac", "1", "-ar", "8000",
        "-af", "astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    # Parse interleaved metadata lines:
    #   frame:N  pts:X  pts_time:T.SSS
    #   lavfi.astats.Overall.RMS_level=-23.45
    frame_pat = re.compile(r"pts_time:([\d.]+)")
    rms_pat = re.compile(r"RMS_level=(-?[\d.]+|-inf|inf)")
    samples: list[tuple[float, float]] = []  # (time_seconds, rms_db)
    pending_time: float | None = None
    for line in proc.stderr.splitlines():
        m = frame_pat.search(line)
        if m:
            try:
                pending_time = float(m.group(1))
            except ValueError:
                pending_time = None
            continue
        m = rms_pat.search(line)
        if m and pending_time is not None:
            token = m.group(1)
            if token == "-inf":
                rms = -90.0
            elif token == "inf":
                rms = 0.0
            else:
                try:
                    rms = float(token)
                except ValueError:
                    pending_time = None
                    continue
            samples.append((pending_time, rms))
            pending_time = None

    # Aggregate to buckets
    num_buckets = max(int(duration_seconds / bucket_seconds) + 1, 1)
    bucket_sums = [0.0] * num_buckets
    bucket_counts = [0] * num_buckets
    for t, rms in samples:
        k = int(t / bucket_seconds)
        if 0 <= k < num_buckets:
            bucket_sums[k] += rms
            bucket_counts[k] += 1

    rms_per_bucket: list[float] = []
    for k in range(num_buckets):
        if bucket_counts[k] > 0:
            rms_per_bucket.append(bucket_sums[k] / bucket_counts[k])
        else:
            rms_per_bucket.append(-90.0)
    return rms_per_bucket


def classify_buckets(
    duration_seconds: float,
    cuts: list[float],
    rms_buckets: list[float],
    bucket_seconds: float,
    rms_threshold_db: float,
    rapid_cut_per_5s: int,
    sustained_shot_seconds: float,
) -> list[tuple[str, float, str]]:
    """For each bucket return (label, confidence, reason)."""
    num_buckets = max(int(duration_seconds / bucket_seconds), len(rms_buckets))
    # Pad RMS if short
    rms_buckets = rms_buckets + [-90.0] * max(0, num_buckets - len(rms_buckets))

    # Pre-compute scene-cut times sorted
    cuts_sorted = sorted(cuts)

    def cuts_in_window(start_s: float, end_s: float) -> int:
        # Binary search via simple loop (cuts is usually small)
        lo = 0
        for i, c in enumerate(cuts_sorted):
            if c < start_s:
                lo = i + 1
            else:
                break
        hi = lo
        for i in range(lo, len(cuts_sorted)):
            if cuts_sorted[i] <= end_s:
                hi = i + 1
            else:
                break
        return hi - lo

    def time_since_last_cut(t: float) -> float:
        last = 0.0
        for c in cuts_sorted:
            if c <= t:
                last = c
            else:
                break
        return t - last

    def time_until_next_cut(t: float) -> float:
        for c in cuts_sorted:
            if c > t:
                return c - t
        return duration_seconds - t

    classifications: list[tuple[str, float, str]] = []
    for k in range(num_buckets):
        center_t = (k + 0.5) * bucket_seconds
        rms = rms_buckets[k] if k < len(rms_buckets) else -90.0

        # Feature: cuts in surrounding 5s window
        c_5s = cuts_in_window(center_t - 2.5, center_t + 2.5)

        # Feature: current shot length
        prev_cut_gap = time_since_last_cut(center_t)
        next_cut_gap = time_until_next_cut(center_t)
        current_shot_len = prev_cut_gap + next_cut_gap

        # Decision logic
        is_quiet = rms < rms_threshold_db
        is_rapid_cut = c_5s >= rapid_cut_per_5s
        is_sustained = current_shot_len >= sustained_shot_seconds

        if is_quiet:
            # Very low audio = commercial/silence/intro
            label = "non_play"
            conf = min(0.95, 0.55 + (rms_threshold_db - rms) / 20.0)
            reason = f"low_audio_rms={rms:.1f}dB"
        elif is_rapid_cut:
            label = "non_play"
            conf = min(0.85, 0.5 + (c_5s - rapid_cut_per_5s) * 0.1)
            reason = f"rapid_cuts={c_5s}_in_5s"
        elif is_sustained and rms >= rms_threshold_db:
            label = "play"
            conf = min(0.95, 0.55 + (current_shot_len - sustained_shot_seconds) * 0.05)
            reason = f"sustained_shot={current_shot_len:.1f}s+audio={rms:.1f}dB"
        else:
            # Ambiguous — short-medium shot with mid audio
            # Default to play with low confidence (better to include than exclude)
            label = "play"
            conf = 0.45
            reason = f"ambiguous_shot={current_shot_len:.1f}s_rms={rms:.1f}dB"

        classifications.append((label, conf, reason))
    return classifications


def merge_segments(
    classifications: list[tuple[str, float, str]],
    bucket_seconds: float,
    min_segment_seconds: float,
) -> list[Segment]:
    """Merge consecutive same-label buckets, then drop tiny segments by reassigning to neighbors."""
    if not classifications:
        return []

    segments: list[Segment] = []
    cur_label, cur_conf_sum, cur_count, cur_reasons = None, 0.0, 0, []
    cur_start = 0.0

    for k, (label, conf, reason) in enumerate(classifications):
        bucket_start = k * bucket_seconds
        if label != cur_label:
            if cur_label is not None:
                segments.append(Segment(
                    start=cur_start,
                    end=bucket_start,
                    label=cur_label,
                    confidence=cur_conf_sum / max(cur_count, 1),
                    reason=most_common(cur_reasons),
                ))
            cur_label = label
            cur_conf_sum = conf
            cur_count = 1
            cur_start = bucket_start
            cur_reasons = [reason]
        else:
            cur_conf_sum += conf
            cur_count += 1
            cur_reasons.append(reason)

    # close last
    final_end = len(classifications) * bucket_seconds
    if cur_label is not None:
        segments.append(Segment(
            start=cur_start,
            end=final_end,
            label=cur_label,
            confidence=cur_conf_sum / max(cur_count, 1),
            reason=most_common(cur_reasons),
        ))

    # Drop tiny segments by absorbing into the longer neighbor
    cleaned: list[Segment] = []
    for seg in segments:
        if (seg.end - seg.start) < min_segment_seconds and cleaned:
            # absorb into previous segment (extend its end)
            prev = cleaned[-1]
            cleaned[-1] = Segment(
                start=prev.start,
                end=seg.end,
                label=prev.label,
                confidence=prev.confidence,
                reason=prev.reason + f"|absorbed_short_{seg.label}",
            )
        else:
            cleaned.append(seg)

    # Second pass: merge adjacent same-label after absorption
    merged: list[Segment] = []
    for seg in cleaned:
        if merged and merged[-1].label == seg.label:
            prev = merged[-1]
            merged[-1] = Segment(
                start=prev.start,
                end=seg.end,
                label=prev.label,
                confidence=(prev.confidence + seg.confidence) / 2,
                reason=prev.reason,
            )
        else:
            merged.append(seg)

    return merged


def most_common(items: list[str]) -> str:
    if not items:
        return ""
    counts: dict[str, int] = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def run_detection(
    video_path: Path,
    output_path: Path,
    scene_threshold: float = DEFAULT_SCENE_THRESHOLD,
    bucket_seconds: float = DEFAULT_BUCKET_SECONDS,
    min_segment_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
    rms_threshold_db: float = DEFAULT_RMS_THRESHOLD_DB,
    rapid_cut_per_5s: int = DEFAULT_RAPID_CUT_PER_5S,
    sustained_shot_seconds: float = DEFAULT_SUSTAINED_SHOT_SECONDS,
) -> dict[str, Any]:
    ensure_tools()
    duration = probe_duration_seconds(video_path)
    if duration <= 0:
        raise RuntimeError(f"Could not probe duration of {video_path}")

    print(f"[detector] video duration: {duration:.1f}s ({duration/60:.1f} min)")
    print(f"[detector] extracting scene cuts (threshold={scene_threshold})…")
    cuts = extract_scene_cuts(video_path, threshold=scene_threshold)
    print(f"[detector] extracted {len(cuts)} scene cuts")

    print(f"[detector] extracting audio RMS per {bucket_seconds}s bucket…")
    rms_buckets = extract_audio_rms(video_path, bucket_seconds=bucket_seconds, duration_seconds=duration)
    print(f"[detector] extracted {len(rms_buckets)} RMS buckets")

    classifications = classify_buckets(
        duration_seconds=duration,
        cuts=cuts,
        rms_buckets=rms_buckets,
        bucket_seconds=bucket_seconds,
        rms_threshold_db=rms_threshold_db,
        rapid_cut_per_5s=rapid_cut_per_5s,
        sustained_shot_seconds=sustained_shot_seconds,
    )

    segments = merge_segments(
        classifications=classifications,
        bucket_seconds=bucket_seconds,
        min_segment_seconds=min_segment_seconds,
    )

    play_segments = [s.to_dict() for s in segments if s.label == "play"]
    non_play_segments = [s.to_dict() for s in segments if s.label == "non_play"]
    play_total = sum(s.end - s.start for s in segments if s.label == "play")
    non_play_total = sum(s.end - s.start for s in segments if s.label == "non_play")

    payload = {
        "video_path": str(video_path),
        "duration_seconds": round(duration, 2),
        "method": "scene+audio_rms_v1",
        "params": {
            "scene_threshold": scene_threshold,
            "bucket_seconds": bucket_seconds,
            "min_segment_seconds": min_segment_seconds,
            "rms_threshold_db": rms_threshold_db,
            "rapid_cut_per_5s": rapid_cut_per_5s,
            "sustained_shot_seconds": sustained_shot_seconds,
        },
        "summary": {
            "total_segments": len(segments),
            "play_segments": len(play_segments),
            "non_play_segments": len(non_play_segments),
            "play_total_seconds": round(play_total, 1),
            "non_play_total_seconds": round(non_play_total, 1),
            "play_ratio": round(play_total / max(duration, 1), 3),
        },
        "play_segments": play_segments,
        "non_play_segments": non_play_segments,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[detector] wrote {output_path}")
    print(f"[detector] play: {payload['summary']['play_total_seconds']}s ({payload['summary']['play_ratio']*100:.1f}%)  |  non-play: {payload['summary']['non_play_total_seconds']}s")
    return payload


def find_play_segment_for_time(payload: dict[str, Any], video_seconds: float) -> dict[str, Any] | None:
    """Helper for downstream code: given a video timestamp, return the play_segment containing it, or None."""
    for seg in payload.get("play_segments", []):
        if seg["start"] <= video_seconds <= seg["end"]:
            return seg
    return None


def snap_clip_window(
    payload: dict[str, Any],
    clip_start: float,
    clip_end: float,
    max_snap_distance: float = 25.0,
    min_clip_seconds: float = 6.0,
) -> tuple[float, float, dict[str, Any]]:
    """Adjust [clip_start, clip_end] to align with play_segments.

    Returns (new_start, new_end, info_dict).

    Logic:
      1. If midpoint already inside a play_segment: trim the window to stay within that segment.
      2. If midpoint in non_play but a play_segment is within max_snap_distance: shift the window
         center to land in that segment and trim.
      3. Otherwise: keep original window, mark info["snapped"]=False.

    `info_dict` contains: snapped (bool), original (tuple), adjusted (tuple), reason (str),
    segment (dict or None).
    """
    mid = (clip_start + clip_end) / 2.0
    play_segments = payload.get("play_segments", [])

    def trim_to_segment(seg, start, end):
        new_start = max(start, seg["start"])
        new_end = min(end, seg["end"])
        # If trimmed too narrow, expand around midpoint within the segment
        if (new_end - new_start) < min_clip_seconds:
            seg_dur = seg["end"] - seg["start"]
            if seg_dur >= min_clip_seconds:
                center = (new_start + new_end) / 2.0
                half = min_clip_seconds / 2.0
                new_start = max(seg["start"], center - half)
                new_end = min(seg["end"], center + half)
                if (new_end - new_start) < min_clip_seconds:
                    # snap to segment start or end based on which side has more room
                    if center - seg["start"] < seg["end"] - center:
                        new_start = seg["start"]
                        new_end = min(seg["end"], seg["start"] + min_clip_seconds)
                    else:
                        new_end = seg["end"]
                        new_start = max(seg["start"], seg["end"] - min_clip_seconds)
        return new_start, new_end

    # Step 1: midpoint inside a play_segment?
    inside = find_play_segment_for_time(payload, mid)
    if inside:
        new_start, new_end = trim_to_segment(inside, clip_start, clip_end)
        info = {
            "snapped": True,
            "original": [round(clip_start, 2), round(clip_end, 2)],
            "adjusted": [round(new_start, 2), round(new_end, 2)],
            "reason": "midpoint_inside_play",
            "segment": inside,
        }
        return new_start, new_end, info

    # Step 2: find nearest play_segment within max_snap_distance
    best_seg = None
    best_dist = float("inf")
    for seg in play_segments:
        if mid < seg["start"]:
            dist = seg["start"] - mid
        elif mid > seg["end"]:
            dist = mid - seg["end"]
        else:
            dist = 0
        if dist < best_dist:
            best_dist = dist
            best_seg = seg

    if best_seg and best_dist <= max_snap_distance:
        # Shift window to center on segment's center if segment is short, or trim if long
        seg_dur = best_seg["end"] - best_seg["start"]
        orig_dur = clip_end - clip_start
        if seg_dur < orig_dur:
            new_start = best_seg["start"]
            new_end = best_seg["end"]
        else:
            # Place original-length window inside segment, biased toward segment center
            seg_center = (best_seg["start"] + best_seg["end"]) / 2.0
            new_start = max(best_seg["start"], seg_center - orig_dur / 2.0)
            new_end = min(best_seg["end"], new_start + orig_dur)
            if (new_end - new_start) < orig_dur:
                new_start = max(best_seg["start"], new_end - orig_dur)
        info = {
            "snapped": True,
            "original": [round(clip_start, 2), round(clip_end, 2)],
            "adjusted": [round(new_start, 2), round(new_end, 2)],
            "reason": f"snapped_to_nearest_play_dist={best_dist:.1f}s",
            "segment": best_seg,
        }
        return new_start, new_end, info

    # Step 3: no snap, keep original
    return clip_start, clip_end, {
        "snapped": False,
        "original": [round(clip_start, 2), round(clip_end, 2)],
        "adjusted": [round(clip_start, 2), round(clip_end, 2)],
        "reason": "no_nearby_play_segment",
        "segment": None,
    }


def load_play_segments_payload(path: str | Path) -> dict[str, Any]:
    """Load a play_segments JSON file. Returns the parsed dict."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"play_segments file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def snap_to_nearest_play_segment(
    payload: dict[str, Any], video_seconds: float, max_distance: float = 30.0
) -> tuple[float, dict[str, Any]] | None:
    """If video_seconds falls inside a play segment, return (t, seg).
    Otherwise return the nearest play segment within max_distance; if none, return None.
    """
    inside = find_play_segment_for_time(payload, video_seconds)
    if inside:
        return video_seconds, inside

    best_seg = None
    best_dist = float("inf")
    best_t = None
    for seg in payload.get("play_segments", []):
        if video_seconds < seg["start"]:
            dist = seg["start"] - video_seconds
            candidate_t = seg["start"]
        else:
            dist = video_seconds - seg["end"]
            candidate_t = seg["end"]
        if dist < best_dist:
            best_dist = dist
            best_seg = seg
            best_t = candidate_t

    if best_seg and best_dist <= max_distance:
        return best_t, best_seg
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect play vs non-play segments in NBA broadcast video.")
    parser.add_argument("--video", required=True, help="Input video file path.")
    parser.add_argument("--output", required=True, help="Output JSON path for play_segments.")
    parser.add_argument("--scene-threshold", type=float, default=DEFAULT_SCENE_THRESHOLD)
    parser.add_argument("--bucket-seconds", type=float, default=DEFAULT_BUCKET_SECONDS)
    parser.add_argument("--min-segment", type=float, default=DEFAULT_MIN_SEGMENT_SECONDS)
    parser.add_argument("--rms-threshold-db", type=float, default=DEFAULT_RMS_THRESHOLD_DB)
    parser.add_argument("--rapid-cut-per-5s", type=int, default=DEFAULT_RAPID_CUT_PER_5S)
    parser.add_argument("--sustained-shot-seconds", type=float, default=DEFAULT_SUSTAINED_SHOT_SECONDS)
    parser.add_argument("--game-window-start", type=float, default=0.0,
                        help="If set, everything before this time is forced non-play (pregame).")
    parser.add_argument("--game-window-end", type=float, default=0.0,
                        help="If set, everything after this time is forced non-play (postgame).")
    parser.add_argument("--reclassify-from", default="",
                        help="Optional: path to existing play_segments JSON; reuse its cached cuts+RMS, re-run classification only.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_detection(
        video_path=Path(args.video),
        output_path=Path(args.output),
        scene_threshold=args.scene_threshold,
        bucket_seconds=args.bucket_seconds,
        min_segment_seconds=args.min_segment,
        rms_threshold_db=args.rms_threshold_db,
        rapid_cut_per_5s=args.rapid_cut_per_5s,
        sustained_shot_seconds=args.sustained_shot_seconds,
    )


if __name__ == "__main__":
    main()
