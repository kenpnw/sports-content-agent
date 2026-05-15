"""Interactive score-only ROI picker for visual score tracking.

This tool is intentionally separate from `scoreboard_roi_picker`: T-OCR uses
one wide scoreboard crop for period and clock parsing, while T-CV-1A needs two
small crops that contain only the home and away score digits.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def pick_score_rois(
    *,
    video_path: str,
    frame_at_seconds: float = 60.0,
    output_path: str | None = None,
    home_team: str = "OKC",
    away_team: str = "LAL",
    visualize: bool = False,
) -> dict[str, Any]:
    """Let the user select home and away score rectangles on one video frame."""
    cv2 = _import_cv2()
    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"Video file not found: {source}")

    frame, sample_seconds, duration_seconds = _read_frame(cv2, source, frame_at_seconds=frame_at_seconds)
    away_roi = _select_roi(cv2, frame, "Select AWAY score ROI, Enter confirm, ESC cancel")
    home_roi = _select_roi(cv2, frame, "Select HOME score ROI, Enter confirm, ESC cancel")
    if away_roi["w"] <= 0 or away_roi["h"] <= 0 or home_roi["w"] <= 0 or home_roi["h"] <= 0:
        print("[warning] One or more score ROIs are empty; OCR will likely fail.", file=sys.stderr)

    target = Path(output_path) if output_path else _default_output_path(source)
    payload = _build_payload(
        video_path=source,
        frame=frame,
        sample_seconds=sample_seconds,
        duration_seconds=duration_seconds,
        home_score_roi=home_roi,
        away_score_roi=away_roi,
        home_team=home_team,
        away_team=away_team,
    )
    _write_json(target, payload)
    if visualize:
        preview_path = target.with_name(f"{source.stem}.score_roi_preview.png")
        _write_preview(cv2, frame, home_roi, away_roi, preview_path)
        print(f"Score ROI preview saved: {preview_path.resolve()}")
    print(f"Score ROI JSON saved: {target.resolve()}")
    return payload


def _select_roi(cv2: Any, frame: Any, window_name: str) -> dict[str, int]:
    roi_tuple = cv2.selectROI(window_name, frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    return _roi_dict(roi_tuple)


def _read_frame(cv2: Any, source: Path, *, frame_at_seconds: float) -> tuple[Any, float, float]:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {source}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_seconds = frame_count / fps if fps > 0 else 0.0
    sample_seconds = max(0.0, float(frame_at_seconds))
    if duration_seconds > 0 and sample_seconds > duration_seconds:
        sample_seconds = duration_seconds / 2.0
        print(f"[warning] Requested frame is beyond video duration; using {sample_seconds:.2f}s.", file=sys.stderr)
    capture.set(cv2.CAP_PROP_POS_MSEC, sample_seconds * 1000.0)
    ok, frame = capture.read()
    capture.release()
    if not ok or frame is None:
        raise RuntimeError(f"Unable to read frame at {sample_seconds:.2f}s from {source}")
    return frame, sample_seconds, duration_seconds


def _build_payload(
    *,
    video_path: Path,
    frame: Any,
    sample_seconds: float,
    duration_seconds: float,
    home_score_roi: dict[str, int],
    away_score_roi: dict[str, int],
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    height, width = frame.shape[:2]
    return {
        "video_path": str(video_path),
        "video_resolution": [int(width), int(height)],
        "sample_frame_seconds": round(float(sample_seconds), 3),
        "video_duration_seconds": round(float(duration_seconds), 3),
        "home_score_roi": home_score_roi,
        "away_score_roi": away_score_roi,
        "home_team": str(home_team or "HOME").upper(),
        "away_team": str(away_team or "AWAY").upper(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _write_preview(
    cv2: Any,
    frame: Any,
    home_roi: dict[str, int],
    away_roi: dict[str, int],
    output_path: Path,
) -> None:
    preview = frame.copy()
    _draw_roi(cv2, preview, away_roi, (255, 0, 0), "AWAY")
    _draw_roi(cv2, preview, home_roi, (0, 255, 0), "HOME")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), preview):
        raise RuntimeError(f"Unable to save preview: {output_path}")


def _draw_roi(cv2: Any, frame: Any, roi: dict[str, int], color: tuple[int, int, int], label: str) -> None:
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    if w <= 0 or h <= 0:
        return
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 3)
    cv2.putText(frame, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _roi_dict(roi_tuple: tuple[int, int, int, int]) -> dict[str, int]:
    x, y, w, h = [int(value) for value in roi_tuple]
    return {"x": x, "y": y, "w": w, "h": h}


def _default_output_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}.score_roi.json")


def _import_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError("opencv-python is required for score ROI picking.") from exc
    return cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick home/away score digit ROIs for visual score tracking.")
    parser.add_argument("--video", default="", help="Local game video path.")
    parser.add_argument("--frame-at-seconds", type=float, default=60.0, help="Video timestamp used for calibration.")
    parser.add_argument("--output", default="", help="Output score ROI JSON path.")
    parser.add_argument("--home-team", default="OKC", help="Home team tricode.")
    parser.add_argument("--away-team", default="LAL", help="Away team tricode.")
    parser.add_argument("--visualize", action="store_true", help="Save a preview PNG with both score boxes.")
    parser.add_argument("--self-test", action="store_true", help="Run a synthetic payload/preview self-test.")
    return parser.parse_args()


def _self_test() -> None:
    cv2 = _import_cv2()
    import numpy as np

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    home_roi = {"x": 430, "y": 640, "w": 50, "h": 38}
    away_roi = {"x": 330, "y": 640, "w": 50, "h": 38}
    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "synthetic.score_roi.json"
        preview = Path(temp_dir) / "synthetic.score_roi_preview.png"
        payload = _build_payload(
            video_path=Path("synthetic.mp4"),
            frame=frame,
            sample_seconds=10.0,
            duration_seconds=120.0,
            home_score_roi=home_roi,
            away_score_roi=away_roi,
            home_team="OKC",
            away_team="LAL",
        )
        _write_json(target, payload)
        _write_preview(cv2, frame, home_roi, away_roi, preview)
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["home_score_roi"] == home_roi
        assert loaded["away_score_roi"] == away_roi
        assert preview.is_file()
    print("score_roi_picker self-test passed.")


def main() -> None:
    args = parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.video:
        raise SystemExit("--video is required unless --self-test is used.")
    pick_score_rois(
        video_path=args.video,
        frame_at_seconds=args.frame_at_seconds,
        output_path=args.output or None,
        home_team=args.home_team,
        away_team=args.away_team,
        visualize=args.visualize,
    )


if __name__ == "__main__":
    main()
