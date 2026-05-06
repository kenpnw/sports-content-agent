"""Video scouting pipeline.

The package is intentionally provider-agnostic:
- `frame_sampler` prepares local video frames when OpenCV is available.
- `vision_client` can call an optional OpenAI-compatible vision model.
- `tactic_analyzer` uses the existing DeepSeek text client to turn visual
  observations into a grounded tactical report.
"""

from __future__ import annotations

__all__ = [
    "VideoScoutAnalyzer",
    "run_video_scout_demo",
]


def __getattr__(name: str):
    if name == "VideoScoutAnalyzer":
        from video_scout.tactic_analyzer import VideoScoutAnalyzer

        return VideoScoutAnalyzer
    if name == "run_video_scout_demo":
        from video_scout.demo_runner import run_video_scout_demo

        return run_video_scout_demo
    raise AttributeError(name)
