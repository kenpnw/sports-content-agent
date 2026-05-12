"""Interactive scoreboard ROI picker for OCR time alignment.

This T-OCR-1 tool only calibrates the scoreboard rectangle on a sampled video
frame. It does not call OCR engines and does not perform time mapping.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def pick_scoreboard_roi(
    *,
    video_path: str,
    frame_at_seconds: float = 60.0,
    output_path: str | None = None,
    visualize: bool = False,
) -> dict[str, Any]:
    """Open a video frame, let the user select scoreboard ROI, then save JSON."""
    cv2 = _import_cv2()
    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"视频文件不存在：{source}")

    frame, sample_seconds, duration_seconds = _read_frame(
        cv2,
        source,
        frame_at_seconds=frame_at_seconds,
    )
    roi_tuple = cv2.selectROI(
        "拖选比分牌 ROI，Enter 确认，ESC 取消",
        frame,
        showCrosshair=True,
        fromCenter=False,
    )
    cv2.destroyWindow("拖选比分牌 ROI，Enter 确认，ESC 取消")
    roi = _roi_dict(roi_tuple)
    if roi["w"] <= 0 or roi["h"] <= 0:
        print("未选择 ROI：将保存空 ROI，后续可重新标定。", file=sys.stderr)

    target = Path(output_path) if output_path else _default_output_path(source)
    payload = _build_payload(
        video_path=source,
        frame=frame,
        sample_seconds=sample_seconds,
        roi=roi,
        duration_seconds=duration_seconds,
    )
    _write_json(target, payload)
    if visualize:
        preview_path = target.with_name(f"{source.stem}.scoreboard_roi_preview.png")
        _write_preview(cv2, frame, roi, preview_path)
        print(f"ROI 预览图已保存：{preview_path.resolve()}")
    print(f"ROI JSON 已保存：{target.resolve()}")
    return payload


def _read_frame(
    cv2: Any,
    source: Path,
    *,
    frame_at_seconds: float,
) -> tuple[Any, float, float]:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频文件：{source}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_seconds = frame_count / fps if fps > 0 else 0.0
    sample_seconds = max(0.0, float(frame_at_seconds))
    if duration_seconds > 0 and sample_seconds > duration_seconds:
        fallback = duration_seconds / 2.0
        print(
            f"--frame-at-seconds={sample_seconds:.2f} 超出视频时长 "
            f"{duration_seconds:.2f}s，已退到中点 {fallback:.2f}s。",
            file=sys.stderr,
        )
        sample_seconds = fallback

    capture.set(cv2.CAP_PROP_POS_MSEC, sample_seconds * 1000.0)
    ok, frame = capture.read()
    capture.release()
    if not ok or frame is None:
        raise RuntimeError(f"无法在 {sample_seconds:.2f}s 读取视频帧：{source}")
    return frame, sample_seconds, duration_seconds


def _build_payload(
    *,
    video_path: Path,
    frame: Any,
    sample_seconds: float,
    roi: dict[str, int],
    duration_seconds: float = 0.0,
) -> dict[str, Any]:
    height, width = frame.shape[:2]
    return {
        "video_path": str(video_path),
        "video_resolution": [int(width), int(height)],
        "sample_frame_seconds": float(round(sample_seconds, 3)),
        "roi": roi,
        "broadcaster_hint": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _write_preview(cv2: Any, frame: Any, roi: dict[str, int], output_path: Path) -> None:
    preview = frame.copy()
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    if w > 0 and h > 0:
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 0, 255), 3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), preview):
        raise RuntimeError(f"无法保存 ROI 预览图：{output_path}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _roi_dict(roi_tuple: tuple[int, int, int, int]) -> dict[str, int]:
    x, y, w, h = [int(value) for value in roi_tuple]
    return {"x": x, "y": y, "w": w, "h": h}


def _default_output_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}.scoreboard_roi.json")


def _import_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "缺少 opencv-python。请先运行："
            ".\\.venv\\Scripts\\python.exe -m pip install opencv-python"
        ) from exc
    return cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="交互式选择比分牌 ROI，用于后续 OCR 时间对齐。")
    parser.add_argument("--video", default="", help="本地比赛视频路径。")
    parser.add_argument("--frame-at-seconds", type=float, default=60.0, help="抽取用于标定的帧时间。")
    parser.add_argument("--output", default="", help="ROI JSON 输出路径。")
    parser.add_argument("--visualize", action="store_true", help="保存带红框的 ROI 预览图。")
    parser.add_argument("--self-test", action="store_true", help="运行合成图自测，不弹出 selectROI。")
    return parser.parse_args()


def _self_test() -> None:
    cv2 = _import_cv2()
    import numpy as np

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    roi = {"x": 120, "y": 950, "w": 480, "h": 80}
    cv2.rectangle(frame, (roi["x"], roi["y"]), (roi["x"] + roi["w"], roi["y"] + roi["h"]), (255, 255, 255), -1)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        output = temp / "synthetic.scoreboard_roi.json"
        preview = temp / "synthetic.scoreboard_roi_preview.png"
        payload = _build_payload(
            video_path=Path("synthetic_scoreboard.mp4"),
            frame=frame,
            sample_seconds=60.0,
            roi=roi,
            duration_seconds=120.0,
        )
        _write_json(output, payload)
        _write_preview(cv2, frame, roi, preview)
        loaded = _load_json(output)
        assert loaded["video_resolution"] == [1920, 1080]
        assert loaded["sample_frame_seconds"] == 60.0
        assert loaded["roi"] == roi
        assert loaded["broadcaster_hint"] == ""
        assert "created_at" in loaded
        assert preview.is_file()
    print("[T-OCR-1] self-test passed")


def main() -> None:
    args = parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.video:
        raise SystemExit("--video is required unless --self-test is used.")
    try:
        pick_scoreboard_roi(
            video_path=args.video,
            frame_at_seconds=args.frame_at_seconds,
            output_path=args.output or None,
            visualize=args.visualize,
        )
    except Exception as exc:
        print(f"[T-OCR-1] ROI 标定失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
