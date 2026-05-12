"""Single-frame scoreboard OCR and clock parser.

T-OCR-2 consumes the T-OCR-1 ROI JSON fields:
`roi.x`, `roi.y`, `roi.w`, `roi.h`, plus optional `video_resolution`.
It reads only one frame at a requested timestamp, crops the scoreboard ROI,
runs EasyOCR, and parses period + game clock. It does not sample full videos
or rebuild video-to-PBP time mapping.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class ScoreboardReading:
    """Structured OCR result for one scoreboard frame."""

    raw_text: str
    period: int | None
    clock_remaining_seconds: float | None
    confidence: float
    error_reason: str
    ocr_box_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScoreboardOCR:
    """OCR reader bound to one T-OCR-1 scoreboard ROI JSON payload."""

    _reader_cache: dict[tuple[tuple[str, ...], bool], Any] = {}

    def __init__(
        self,
        roi_dict: dict[str, Any],
        languages: list[str] | None = None,
        use_gpu: bool = False,
    ) -> None:
        self.roi_payload = roi_dict
        self.roi = _extract_roi(roi_dict)
        self.languages = languages or ["en"]
        self.use_gpu = bool(use_gpu)
        self._reader = self._get_reader(self.languages, self.use_gpu)

    def read_frame(self, frame_bgr_numpy: Any) -> ScoreboardReading:
        """Crop ROI from a BGR frame and return parsed scoreboard text."""
        cv2 = _import_cv2()
        if frame_bgr_numpy is None:
            return _error_reading("empty_frame")
        crop = _crop_roi(frame_bgr_numpy, self.roi)
        if crop is None:
            return _error_reading("invalid_or_empty_roi")
        prepared = _prepare_for_ocr(cv2, crop)
        results = self._reader.readtext(
            prepared,
            detail=1,
            paragraph=False,
            allowlist="0123456789QqTtRrSsNnDdHhOo:. ",
        )
        if not results:
            return _error_reading("no_text_detected")

        texts = [str(item[1]).strip() for item in results if len(item) >= 2 and str(item[1]).strip()]
        confidences = [float(item[2]) for item in results if len(item) >= 3]
        raw_text = " ".join(texts).strip()
        raw_confidence = _mean(confidences)
        period, clock_seconds = parse_scoreboard_text(raw_text)
        if period is None or clock_seconds is None:
            return ScoreboardReading(
                raw_text=raw_text,
                period=None,
                clock_remaining_seconds=None,
                confidence=raw_confidence,
                error_reason=f"parse_failed: {raw_text}",
                ocr_box_count=len(results),
            )
        return ScoreboardReading(
            raw_text=raw_text,
            period=period,
            clock_remaining_seconds=clock_seconds,
            confidence=raw_confidence,
            error_reason="",
            ocr_box_count=len(results),
        )

    def read_video_at(self, video_path: str | Path, video_seconds: float) -> ScoreboardReading:
        """Read one frame from a video at `video_seconds`, then call read_frame."""
        cv2 = _import_cv2()
        source = Path(video_path)
        if not source.is_file():
            raise FileNotFoundError(f"视频文件不存在：{source}")
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise RuntimeError(f"无法打开视频文件：{source}")
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(video_seconds)) * 1000.0)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return _error_reading(f"frame_read_failed_at_{video_seconds}")
        return self.read_frame(frame)

    @classmethod
    def _get_reader(cls, languages: list[str], use_gpu: bool) -> Any:
        key = (tuple(languages), bool(use_gpu))
        if key not in cls._reader_cache:
            easyocr = _import_easyocr()
            cls._reader_cache[key] = easyocr.Reader(list(languages), gpu=use_gpu)
        return cls._reader_cache[key]


def parse_scoreboard_text(raw_text: str) -> tuple[int | None, float | None]:
    """Parse common NBA scoreboard period-clock formats."""
    text = _normalize_ocr_text(raw_text)
    parsers: list[Callable[[str], tuple[int | None, float | None]]] = [
        _parse_q_period_clock,
        _parse_ordinal_period_clock,
        _parse_qtr_period_clock,
        _parse_overtime_clock,
    ]
    for parser in parsers:
        period, seconds = parser(text)
        if period is not None and seconds is not None:
            return period, seconds
    return None, None


def _parse_q_period_clock(text: str) -> tuple[int | None, float | None]:
    match = re.search(r"\bQ\s*([1-4])\s+([0-9]{1,2}[:.][0-9]{2}(?:\.[0-9])?)\b", text)
    if not match:
        return None, None
    return int(match.group(1)), _clock_to_seconds(match.group(2))


def _parse_ordinal_period_clock(text: str) -> tuple[int | None, float | None]:
    match = re.search(r"\b([1-4])\s*(ST|ND|RD|TH)\s+([0-9]{1,2}[:.][0-9]{2}(?:\.[0-9])?)\b", text)
    if not match:
        return None, None
    return int(match.group(1)), _clock_to_seconds(match.group(3))


def _parse_qtr_period_clock(text: str) -> tuple[int | None, float | None]:
    match = re.search(r"\bQTR\s*([1-4])\s+([0-9]{1,2}[:.][0-9]{2}(?:\.[0-9])?)\b", text)
    if not match:
        return None, None
    return int(match.group(1)), _clock_to_seconds(match.group(2))


def _parse_overtime_clock(text: str) -> tuple[int | None, float | None]:
    match = re.search(r"\b([2-9])?\s*OT\s+([0-9]{1,2}[:.][0-9]{2}(?:\.[0-9])?)\b", text)
    if not match:
        return None, None
    overtime_number = int(match.group(1) or 1)
    return 4 + overtime_number, _clock_to_seconds(match.group(2))


def _normalize_ocr_text(raw_text: str) -> str:
    text = str(raw_text or "").upper()
    replacements = {
        "IST": "1ST",
        "LST": "1ST",
        "QTRI": "QTR 1",
        "QTRL": "QTR 1",
        "O T": "OT",
        "|": "1",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[^0-9A-Z:. ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\bQ\s+([1-4])\b", r"Q\1", text)
    return text


def _clock_to_seconds(value: str) -> float | None:
    match = re.fullmatch(r"([0-9]{1,2})[:.]([0-9]{2})(?:\.([0-9]))?", value)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    tenths = float(f"0.{match.group(3)}") if match.group(3) else 0.0
    if seconds >= 60:
        return None
    return float(minutes * 60 + seconds) + tenths


def _extract_roi(payload: dict[str, Any]) -> dict[str, int]:
    roi = payload.get("roi", payload)
    if not isinstance(roi, dict):
        raise ValueError("ROI JSON must contain `roi` object.")
    result = {key: int(float(roi.get(key, 0) or 0)) for key in ("x", "y", "w", "h")}
    return result


def _crop_roi(frame: Any, roi: dict[str, int]) -> Any | None:
    height, width = frame.shape[:2]
    x = max(0, min(width, roi["x"]))
    y = max(0, min(height, roi["y"]))
    w = max(0, roi["w"])
    h = max(0, roi["h"])
    x2 = max(x, min(width, x + w))
    y2 = max(y, min(height, y + h))
    if x2 <= x or y2 <= y:
        return None
    return frame[y:y2, x:x2]


def _prepare_for_ocr(cv2: Any, crop: Any) -> Any:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = 3 if min(gray.shape[:2]) < 120 else 2
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(enlarged, cv2.COLOR_GRAY2BGR)


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _error_reading(reason: str) -> ScoreboardReading:
    return ScoreboardReading(
        raw_text="",
        period=None,
        clock_remaining_seconds=None,
        confidence=0.0,
        error_reason=reason,
        ocr_box_count=0,
    )


def _import_cv2() -> Any:
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 opencv-python，无法读取视频帧。") from exc
    return cv2


def _import_easyocr() -> Any:
    try:
        import easyocr  # type: ignore
    except Exception as exc:
        raise RuntimeError("缺少 easyocr，无法执行比分牌 OCR。") from exc
    return easyocr


def load_roi_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="单帧比分牌 OCR 测试。")
    parser.add_argument("--video", default="", help="本地比赛视频路径。")
    parser.add_argument("--roi", default="", help="T-OCR-1 生成的 scoreboard_roi.json。")
    parser.add_argument("--frame-at-seconds", type=float, default=60.0, help="读取视频帧的秒数。")
    parser.add_argument("--gpu", action="store_true", help="允许 EasyOCR 使用 GPU。默认 CPU。")
    parser.add_argument("--self-test", action="store_true", help="运行合成图 OCR 自测。")
    return parser.parse_args()


def _self_test() -> None:
    cv2 = _import_cv2()
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    roi_payload = {
        "video_path": "synthetic_scoreboard.mp4",
        "video_resolution": [1920, 1080],
        "sample_frame_seconds": 60.0,
        "roi": {"x": 120, "y": 950, "w": 520, "h": 90},
        "broadcaster_hint": "",
        "created_at": "2026-05-07T00:00:00",
    }
    ocr = ScoreboardOCR(roi_payload, use_gpu=False)
    cases = [
        ("Q1 11:42", 1, 702.0),
        ("Q4 0:08", 4, 8.0),
        ("OT 4:30", 5, 270.0),
        ("3RD 3:55", 3, 235.0),
    ]
    for text, expected_period, expected_clock in cases:
        frame = _synthetic_scoreboard_frame(text, roi_payload, Image, ImageDraw, ImageFont, np, cv2)
        reading = ocr.read_frame(frame)
        assert reading.period == expected_period, reading
        assert reading.clock_remaining_seconds is not None, reading
        assert abs(reading.clock_remaining_seconds - expected_clock) <= 0.6, reading

    blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
    blank_reading = ocr.read_frame(blank)
    assert blank_reading.error_reason == "no_text_detected", blank_reading
    print("[T-OCR-2] self-test passed")


def _synthetic_scoreboard_frame(
    text: str,
    roi_payload: dict[str, Any],
    image_module: Any,
    draw_module: Any,
    font_module: Any,
    np_module: Any,
    cv2: Any,
) -> Any:
    frame = image_module.new("RGB", (1920, 1080), color=(0, 0, 0))
    draw = draw_module.Draw(frame)
    roi = roi_payload["roi"]
    draw.rectangle(
        [roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]],
        outline=(255, 255, 255),
        width=4,
    )
    font = _load_test_font(font_module, 64)
    draw.text((roi["x"] + 28, roi["y"] + 10), text, fill=(255, 255, 255), font=font)
    rgb = np_module.array(frame)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _load_test_font(font_module: Any, size: int) -> Any:
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return font_module.truetype(path, size)
    return font_module.load_default()


def main() -> None:
    args = parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.video or not args.roi:
        raise SystemExit("--video and --roi are required unless --self-test is used.")
    try:
        ocr = ScoreboardOCR(load_roi_json(args.roi), use_gpu=args.gpu)
        reading = ocr.read_video_at(args.video, args.frame_at_seconds)
        print(json.dumps(reading.to_dict(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"[T-OCR-2] OCR 失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
