"""Sample frames from local basketball video files.

OpenCV is optional. The rest of the project can run without it, which keeps the
main dependency set light for thesis/demo work. If the user wants direct video
sampling, install `opencv-python` in the venv.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from storage.file_store import ensure_dir, write_json
from video_scout.models import FrameSample


def sample_video_frames(
    video_path: str,
    output_dir: str,
    *,
    every_seconds: float = 8.0,
    max_frames: int = 80,
    jpeg_quality: int = 90,
) -> dict[str, Any]:
    """Extract frames from a local video and write a manifest JSON.

    Returns a manifest with frame paths and timecodes. If OpenCV is missing,
    raises a friendly RuntimeError instead of breaking imports globally.
    """
    try:
        import cv2  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "OpenCV is not installed. Install it only if you need video frame "
            "extraction: .\\.venv\\Scripts\\python.exe -m pip install opencv-python"
        ) from exc

    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    out = ensure_dir(Path(output_dir))
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video file: {video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_seconds = frame_count / fps if fps > 0 else 0.0
    step = max(1, int(round((fps or 25.0) * every_seconds)))

    samples: list[FrameSample] = []
    frame_index = 0
    sample_index = 0
    while sample_index < max_frames:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            break
        timecode_seconds = frame_index / fps if fps > 0 else sample_index * every_seconds
        frame_id = f"frame_{sample_index + 1:04d}"
        image_path = out / f"{frame_id}.jpg"
        cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
        samples.append(
            FrameSample(
                frame_id=frame_id,
                image_path=str(image_path.resolve()),
                timecode_seconds=round(timecode_seconds, 2),
                metadata={"source_video": str(source.resolve()), "frame_index": frame_index},
            )
        )
        sample_index += 1
        frame_index += step
        if frame_count and frame_index >= frame_count:
            break
    capture.release()

    manifest = {
        "video_path": str(source.resolve()),
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": round(duration_seconds, 2),
        "every_seconds": every_seconds,
        "sample_count": len(samples),
        "frames": [sample.to_dict() for sample in samples],
    }
    write_json(out / "frame_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample frames from a local basketball video.")
    parser.add_argument("--video", required=True, help="Local video path.")
    parser.add_argument("--output-dir", required=True, help="Output folder for sampled frames.")
    parser.add_argument("--every-seconds", type=float, default=8.0)
    parser.add_argument("--max-frames", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = sample_video_frames(
        args.video,
        args.output_dir,
        every_seconds=args.every_seconds,
        max_frames=args.max_frames,
    )
    print(manifest)


if __name__ == "__main__":
    main()
