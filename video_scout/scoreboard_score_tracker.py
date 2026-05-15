"""Track visual scoring changes from score-only OCR crops.

T-CV-1A keeps this module independent from demo_runner: it samples the video,
reads only the two score digit ROIs, and emits a visual score-change timeline
that can later be reconciled against official play-by-play.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


CONFIRM_THRESHOLD = 3
MAX_DELTA = 3


@dataclass
class ScoreEvent:
    """One visual score change detected from the broadcast scoreboard."""

    video_seconds: float
    team: str
    points_delta: int
    home_score: int
    away_score: int
    ocr_confidence: float
    raw_home_text: str
    raw_away_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreReading:
    """Score OCR result for one sampled frame."""

    home_score: int | None
    away_score: int | None
    confidence: float
    raw_home_text: str
    raw_away_text: str
    error_reason: str = ""


@dataclass
class ScoreState:
    """Confirmed score plus a pending candidate awaiting stable repeats."""

    confirmed_home: int
    confirmed_away: int
    confirmed_at_video_seconds: float
    pending_home: int | None = None
    pending_away: int | None = None
    pending_consecutive_count: int = 0
    pending_first_seen_at: float = 0.0

    def reset_pending(self) -> None:
        self.pending_home = None
        self.pending_away = None
        self.pending_consecutive_count = 0
        self.pending_first_seen_at = 0.0


class ScoreTracker:
    """Sequential score OCR scanner with multi-frame score confirmation."""

    _reader_cache: Any = None

    def __init__(
        self,
        score_roi_path: str | Path,
        sample_interval: float = 2.0,
        confirm_threshold: int = CONFIRM_THRESHOLD,
    ) -> None:
        self.score_roi_path = Path(score_roi_path)
        self.roi_payload = _load_json(self.score_roi_path)
        self.home_roi = _extract_roi(self.roi_payload, "home_score_roi")
        self.away_roi = _extract_roi(self.roi_payload, "away_score_roi")
        self.sample_interval = max(0.1, float(sample_interval))
        self.confirm_threshold = max(1, int(confirm_threshold))
        self._reader = self._get_reader()

    def scan_video(
        self,
        video_path: str | Path,
        *,
        start_seconds: float = 0.0,
        end_seconds: float = 0.0,
        progress_every: int = 100,
    ) -> dict[str, Any]:
        """Sample the video sequentially and return confirmed score-change events."""
        cv2 = _import_cv2()
        source = Path(video_path)
        if not source.is_file():
            raise FileNotFoundError(f"Video file not found: {source}")
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open video: {source}")

        started_at = time.perf_counter()
        duration = _video_duration_seconds(cv2, capture)
        effective_start = max(0.0, float(start_seconds))
        effective_end = duration if end_seconds <= 0 else min(float(end_seconds), duration)
        timestamps = _sample_points(effective_start, effective_end, self.sample_interval)
        events: list[ScoreEvent] = []
        state: ScoreState | None = None
        total_samples = 0
        ocr_success = 0
        skipped_negative = 0
        skipped_large = 0
        skipped_double_change = 0
        pending_abandoned = 0

        try:
            for index, video_seconds in enumerate(timestamps, start=1):
                total_samples += 1
                reading = self._read_at(capture, cv2, video_seconds)
                if reading.home_score is None or reading.away_score is None:
                    pending_abandoned += _abandon_pending(state)
                    _print_progress(index, len(timestamps), events, ocr_success, progress_every)
                    continue
                ocr_success += 1
                home_score = int(reading.home_score)
                away_score = int(reading.away_score)
                if state is None:
                    state = ScoreState(home_score, away_score, float(video_seconds))
                    _print_progress(index, len(timestamps), events, ocr_success, progress_every)
                    continue

                event, skipped_reason, abandoned = _update_score_state(
                    state,
                    home_score=home_score,
                    away_score=away_score,
                    video_seconds=float(video_seconds),
                    reading=reading,
                    confirm_threshold=self.confirm_threshold,
                )
                pending_abandoned += abandoned
                if skipped_reason == "negative":
                    skipped_negative += 1
                elif skipped_reason == "large":
                    skipped_large += 1
                elif skipped_reason == "double_change":
                    skipped_double_change += 1
                if event is not None:
                    events.append(event)
                _print_progress(index, len(timestamps), events, ocr_success, progress_every)
        except KeyboardInterrupt:
            print("\nReceived Ctrl-C; saving sampled score events so far.", file=sys.stderr)
        finally:
            capture.release()

        elapsed = time.perf_counter() - started_at
        return {
            "video_path": str(source),
            "score_roi_path": str(self.score_roi_path),
            "sample_interval_seconds": float(self.sample_interval),
            "confirm_threshold": int(self.confirm_threshold),
            "max_delta_per_change": MAX_DELTA,
            "start_seconds": round(effective_start, 3),
            "end_seconds": round(effective_end, 3),
            "home_team": str(self.roi_payload.get("home_team", "HOME")),
            "away_team": str(self.roi_payload.get("away_team", "AWAY")),
            "events": [event.to_dict() for event in events],
            "stats": {
                "total_samples": total_samples,
                "ocr_success": ocr_success,
                "ocr_success_rate": round(ocr_success / total_samples, 4) if total_samples else 0.0,
                "score_changes_detected": len(events),
                "confirmed_score_events": len(events),
                "pending_abandoned": pending_abandoned,
                "negative_changes_skipped": skipped_negative,
                "large_changes_skipped": skipped_large,
                "double_changes_skipped": skipped_double_change,
                "elapsed_seconds": round(elapsed, 3),
                "average_seconds_per_sample": round(elapsed / total_samples, 3) if total_samples else 0.0,
            },
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _read_at(self, capture: Any, cv2: Any, video_seconds: float) -> ScoreReading:
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(video_seconds)) * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                return ScoreReading(None, None, 0.0, "", "", "frame_read_failed")
            home_text, home_conf = self._read_roi(cv2, frame, self.home_roi)
            away_text, away_conf = self._read_roi(cv2, frame, self.away_roi)
            home_score = _parse_score_text(home_text)
            away_score = _parse_score_text(away_text)
            confidence = _mean([home_conf, away_conf])
            error = "" if home_score is not None and away_score is not None else "score_parse_failed"
            return ScoreReading(home_score, away_score, confidence, home_text, away_text, error)
        except Exception as exc:
            return ScoreReading(None, None, 0.0, "", "", f"read_failed: {exc}")

    def _read_roi(self, cv2: Any, frame: Any, roi: dict[str, int]) -> tuple[str, float]:
        crop = _crop_roi(frame, roi)
        if crop is None:
            return "", 0.0
        processed = _preprocess_score_crop(cv2, crop)
        results = self._reader.readtext(
            processed,
            detail=1,
            allowlist="0123456789",
            text_threshold=0.4,
            paragraph=False,
        )
        if not results:
            results = self._reader.readtext(crop, detail=1, allowlist="0123456789", text_threshold=0.4, paragraph=False)
        texts = [str(item[1]).strip() for item in results if len(item) >= 2 and str(item[1]).strip()]
        confidences = [float(item[2]) for item in results if len(item) >= 3]
        return " ".join(texts), _mean(confidences)

    @classmethod
    def _get_reader(cls) -> Any:
        if cls._reader_cache is None:
            easyocr = _import_easyocr()
            cls._reader_cache = easyocr.Reader(["en"], gpu=False)
        return cls._reader_cache


def _update_score_state(
    state: ScoreState,
    *,
    home_score: int,
    away_score: int,
    video_seconds: float,
    reading: ScoreReading,
    confirm_threshold: int,
) -> tuple[ScoreEvent | None, str, int]:
    if home_score == state.confirmed_home and away_score == state.confirmed_away:
        abandoned = _abandon_pending(state)
        return None, "", abandoned

    home_delta = int(home_score) - int(state.confirmed_home)
    away_delta = int(away_score) - int(state.confirmed_away)
    if home_delta < 0 or away_delta < 0:
        abandoned = _abandon_pending(state)
        return None, "negative", abandoned
    if home_delta > MAX_DELTA or away_delta > MAX_DELTA:
        abandoned = _abandon_pending(state)
        return None, "large", abandoned
    if home_delta > 0 and away_delta > 0:
        abandoned = _abandon_pending(state)
        return None, "double_change", abandoned

    abandoned = 0
    if state.pending_home == home_score and state.pending_away == away_score:
        state.pending_consecutive_count += 1
    else:
        if state.pending_home is not None or state.pending_away is not None:
            abandoned = 1
        state.pending_home = int(home_score)
        state.pending_away = int(away_score)
        state.pending_consecutive_count = 1
        state.pending_first_seen_at = float(video_seconds)

    if state.pending_consecutive_count < max(1, int(confirm_threshold)):
        return None, "", abandoned

    points_delta = home_delta if home_delta > 0 else away_delta
    team = "HOME" if home_delta > 0 else "AWAY"
    event = ScoreEvent(
        video_seconds=round(float(state.pending_first_seen_at), 3),
        team=team,
        points_delta=int(points_delta),
        home_score=int(home_score),
        away_score=int(away_score),
        ocr_confidence=round(float(reading.confidence), 4),
        raw_home_text=reading.raw_home_text,
        raw_away_text=reading.raw_away_text,
    )
    state.confirmed_home = int(home_score)
    state.confirmed_away = int(away_score)
    state.confirmed_at_video_seconds = float(video_seconds)
    state.reset_pending()
    return event, "", abandoned


def _abandon_pending(state: ScoreState | None) -> int:
    if state is None:
        return 0
    if state.pending_home is None and state.pending_away is None:
        return 0
    state.reset_pending()
    return 1


def save_score_events(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_score_text(raw_text: str) -> int | None:
    digits = re.sub(r"\D+", "", str(raw_text or ""))
    if not digits:
        return None
    if len(digits) > 3:
        digits = digits[-3:]
    try:
        value = int(digits)
    except ValueError:
        return None
    return value if 0 <= value <= 200 else None


def _preprocess_score_crop(cv2: Any, crop: Any) -> Any:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = 3 if min(gray.shape[:2]) < 40 else 2
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def _crop_roi(frame: Any, roi: dict[str, int]) -> Any | None:
    height, width = frame.shape[:2]
    x = max(0, int(roi.get("x", 0)))
    y = max(0, int(roi.get("y", 0)))
    w = max(0, int(roi.get("w", 0)))
    h = max(0, int(roi.get("h", 0)))
    if w <= 0 or h <= 0 or x >= width or y >= height:
        return None
    return frame[y : min(height, y + h), x : min(width, x + w)]


def _extract_roi(payload: dict[str, Any], key: str) -> dict[str, int]:
    roi = payload.get(key)
    if not isinstance(roi, dict):
        raise ValueError(f"score ROI JSON missing `{key}`.")
    return {name: int(roi.get(name, 0) or 0) for name in ("x", "y", "w", "h")}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _video_duration_seconds(cv2: Any, capture: Any) -> float:
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    return frame_count / fps if fps > 0 else 0.0


def _sample_points(start_seconds: float, end_seconds: float, interval: float) -> list[float]:
    points: list[float] = []
    cursor = float(start_seconds)
    limit = float(end_seconds) + 1e-6
    while cursor <= limit:
        points.append(round(cursor, 3))
        cursor += float(interval)
    return points


def _print_progress(index: int, total: int, events: list[ScoreEvent], ocr_success: int, progress_every: int) -> None:
    if progress_every <= 0:
        return
    if index % progress_every != 0 and index != total:
        return
    rate = ocr_success / index if index else 0.0
    print(f"[score-tracker] {index}/{total} samples, OCR success={rate:.1%}, confirmed_events={len(events)}")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _import_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError("opencv-python is required for score tracking.") from exc
    return cv2


def _import_easyocr() -> Any:
    try:
        import easyocr  # type: ignore
    except Exception as exc:
        raise RuntimeError("easyocr is required for score tracking.") from exc
    return easyocr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track broadcast score changes using score-only OCR ROIs.")
    parser.add_argument("--video", required=False, default="", help="Local video path.")
    parser.add_argument("--score-roi", required=False, default="", help="Score ROI JSON from score_roi_picker.")
    parser.add_argument("--sample-interval", type=float, default=2.0, help="Seconds between score OCR samples.")
    parser.add_argument("--confirm-threshold", type=int, default=CONFIRM_THRESHOLD, help="Identical new scores required before confirming a score event.")
    parser.add_argument("--start-seconds", type=float, default=0.0, help="Optional scan start.")
    parser.add_argument("--end-seconds", type=float, default=0.0, help="Optional scan end; 0 means video end.")
    parser.add_argument("--progress-every", type=int, default=100, help="Print progress every N samples.")
    parser.add_argument("--output", default="", help="Output score_events.json path.")
    parser.add_argument("--self-test", action="store_true", help="Run parser/change-detection self-test without OCR.")
    return parser.parse_args()


def _self_test() -> None:
    assert _parse_score_text("31") == 31
    assert _parse_score_text(" 1 0 5 ") == 105
    assert _parse_score_text("abc") is None
    state = ScoreState(0, 0, 0.0)
    reading = ScoreReading(3, 0, 0.9, "3", "0")
    event, reason, abandoned = _update_score_state(state, home_score=3, away_score=0, video_seconds=10.0, reading=reading, confirm_threshold=3)
    assert event is None and reason == "" and abandoned == 0
    event, reason, abandoned = _update_score_state(state, home_score=2, away_score=0, video_seconds=12.0, reading=reading, confirm_threshold=3)
    assert event is None and reason == "" and abandoned == 1
    _update_score_state(state, home_score=3, away_score=0, video_seconds=14.0, reading=reading, confirm_threshold=3)
    event, reason, _ = _update_score_state(state, home_score=3, away_score=0, video_seconds=16.0, reading=reading, confirm_threshold=3)
    assert event is None and reason == ""
    event, reason, _ = _update_score_state(state, home_score=3, away_score=0, video_seconds=18.0, reading=reading, confirm_threshold=3)
    assert event is not None and event.points_delta == 3
    print("scoreboard_score_tracker self-test passed.")


def main() -> None:
    args = parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.video or not args.score_roi:
        raise SystemExit("--video and --score-roi are required unless --self-test is used.")
    tracker = ScoreTracker(args.score_roi, sample_interval=args.sample_interval, confirm_threshold=args.confirm_threshold)
    payload = tracker.scan_video(
        args.video,
        start_seconds=args.start_seconds,
        end_seconds=args.end_seconds,
        progress_every=args.progress_every,
    )
    output = Path(args.output) if args.output else Path(args.video).with_name(f"{Path(args.video).stem}.score_events.json")
    save_score_events(output, payload)
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))
    print(f"Score events saved to: {output.resolve()}")


if __name__ == "__main__":
    main()
