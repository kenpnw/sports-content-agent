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
    extraction_mode: str

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
        processed = _preprocess(cv2, crop)
        processed_reading = self._read_crop(processed)
        if processed_reading.confidence >= 0.6:
            return processed_reading
        color_reading = self._read_crop(crop)
        return color_reading if color_reading.confidence > processed_reading.confidence else processed_reading

    def _read_crop(self, crop_image: Any) -> ScoreboardReading:
        """Run EasyOCR on one cropped image and parse its text."""
        results = self._reader.readtext(
            crop_image,
            detail=1,
            allowlist="0123456789:QSTNDRHO",
            text_threshold=0.5,
            paragraph=False,
        )
        if not results:
            return _error_reading("no_text_detected")

        texts = [str(item[1]).strip() for item in results if len(item) >= 2 and str(item[1]).strip()]
        confidences = [float(item[2]) for item in results if len(item) >= 3]
        raw_text = " ".join(texts).strip()
        raw_confidence = _mean(confidences)
        period, clock_seconds, extraction_mode = parse_scoreboard_text(raw_text)
        if period is None and clock_seconds is None:
            return ScoreboardReading(
                raw_text=raw_text,
                period=None,
                clock_remaining_seconds=None,
                confidence=raw_confidence,
                error_reason=f"parse_failed: {raw_text}",
                ocr_box_count=len(results),
                extraction_mode="failed",
            )
        return ScoreboardReading(
            raw_text=raw_text,
            period=period,
            clock_remaining_seconds=clock_seconds,
            confidence=raw_confidence,
            error_reason="" if period is not None and clock_seconds is not None else f"partial_parse: {raw_text}",
            ocr_box_count=len(results),
            extraction_mode=extraction_mode,
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


@dataclass
class _ClockCandidate:
    """Candidate clock recovered from noisy OCR text."""

    seconds: float
    start: int
    end: int
    used_positions: set[int]
    minute: int
    second: int
    priority: int


def parse_scoreboard_text(raw_text: str) -> tuple[int | None, float | None, str]:
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
            return period, seconds, "strict"
    clock_candidate = _extract_clock_candidate_from_garbled(text)
    clock_seconds = clock_candidate.seconds if clock_candidate else None
    period = _extract_period_from_garbled(text, clock_candidate=clock_candidate)
    if period is not None or clock_seconds is not None:
        return period, clock_seconds, "smart"
    return None, None, "failed"


def _extract_clock_from_garbled(text: str) -> float | None:
    """Recover MM:SS from OCR strings where the colon may be missing."""
    candidate = _extract_clock_candidate_from_garbled(_normalize_ocr_text(text))
    return candidate.seconds if candidate else None


def _extract_clock_candidate_from_garbled(text: str) -> _ClockCandidate | None:
    candidates: list[_ClockCandidate] = []
    for match in re.finditer(r"\d+", text):
        digits = match.group(0)
        base = match.start()
        for offset in range(0, max(0, len(digits) - 4 + 1)):
            chunk = digits[offset : offset + 4]
            candidate = _clock_candidate_from_digits(
                chunk,
                start=base + offset,
                used_positions={base + offset + index for index in range(4)},
                priority=0,
            )
            if candidate:
                candidates.append(candidate)
        if len(digits) >= 5:
            for offset in range(0, len(digits) - 5 + 1):
                chunk = digits[offset : offset + 5]
                for drop_index in range(5):
                    repaired = chunk[:drop_index] + chunk[drop_index + 1 :]
                    used = {
                        base + offset + index
                        for index in range(5)
                        if index != drop_index
                    }
                    candidate = _clock_candidate_from_digits(
                        repaired,
                        start=base + offset,
                        used_positions=used,
                        priority=-2 if drop_index == 2 else -1,
                    )
                    if candidate:
                        candidates.append(candidate)
        for offset in range(0, max(0, len(digits) - 3 + 1)):
            chunk = digits[offset : offset + 3]
            minute = int(chunk[0])
            second = int(chunk[1:])
            if 0 <= minute <= 9 and 0 <= second < 60:
                candidates.append(
                    _ClockCandidate(
                        seconds=float(minute * 60 + second),
                        start=base + offset,
                        end=base + offset + 3,
                        used_positions={base + offset + index for index in range(3)},
                        minute=minute,
                        second=second,
                        priority=1,
                    )
                )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            item.start,
            item.priority,
            0 if 1 <= item.minute <= 12 else 1,
            item.second,
        )
    )
    return candidates[0]


def _clock_candidate_from_digits(
    digits: str,
    *,
    start: int,
    used_positions: set[int],
    priority: int,
) -> _ClockCandidate | None:
    if len(digits) != 4:
        return None
    minute = int(digits[:2])
    second = int(digits[2:])
    if 0 <= minute <= 12 and 0 <= second < 60:
        return _ClockCandidate(
            seconds=float(minute * 60 + second),
            start=start,
            end=start + len(digits),
            used_positions=used_positions,
            minute=minute,
            second=second,
            priority=priority,
        )
    return None


def _extract_period_from_garbled(
    text: str,
    *,
    clock_candidate: _ClockCandidate | None = None,
) -> int | None:
    normalized = _normalize_ocr_text(text)
    strict_patterns = [
        r"\bQ\s*([1-6])\b",
        r"\b([1-4])\s*(?:ST|ND|RD|TH)\b",
        r"\b([1-3])\s*OT\b",
    ]
    for pattern in strict_patterns:
        match = re.search(pattern, normalized)
        if match:
            value = int(match.group(1))
            return 4 + value if "OT" in pattern else value
    if re.search(r"\bOT\b|0T|O7", normalized):
        return 5
    if re.search(r"\b(?:T8R|T8|78|7B)\b", normalized):
        return 1

    excluded = clock_candidate.used_positions if clock_candidate else set()
    for match in re.finditer(r"[1-4]", normalized):
        index = match.start()
        if any(abs(index - used) <= 1 for used in excluded):
            continue
        return int(match.group(0))
    return None


def _parse_q_period_clock(text: str) -> tuple[int | None, float | None]:
    match = re.search(r"\bQ\s*([1-4])\s*([0-9]{1,2}[:.][0-9]{2}(?:\.[0-9])?)\b", text)
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
    match = re.search(r"\b([2-9])?\s*OT\s*([0-9]{1,2}[:.][0-9]{2}(?:\.[0-9])?)\b", text)
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


def _preprocess(cv2: Any, crop_bgr: Any) -> Any:
    """Enhance scoreboard clock text before EasyOCR reads the ROI."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


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
        extraction_mode="failed",
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

    parser_cases = [
        ("11853 78 T8r", 1, 713.0, "smart"),
        ("Q4 0:08 24", 4, 8.0, "strict"),
        ("OT 4:30 14", 5, 270.0, "strict"),
        ("", None, None, "failed"),
    ]
    for raw_text, expected_period, expected_clock, expected_mode in parser_cases:
        period, clock, mode = parse_scoreboard_text(raw_text)
        assert period == expected_period, (raw_text, period, expected_period)
        assert mode == expected_mode, (raw_text, mode, expected_mode)
        if expected_clock is None:
            assert clock is None, (raw_text, clock)
        else:
            assert clock is not None and abs(clock - expected_clock) <= 0.1, (raw_text, clock, expected_clock)

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
        assert reading.extraction_mode in {"strict", "smart"}, reading

    blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
    blank_reading = ocr.read_frame(blank)
    assert blank_reading.error_reason == "no_text_detected", blank_reading
    assert blank_reading.extraction_mode == "failed", blank_reading
    print("[T-OCR-2.5] self-test passed")


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
