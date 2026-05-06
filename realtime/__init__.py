"""Real-time sports content generation module.

This package extends the existing `sports_agent` codebase with real-time
event-driven content generation, fact verification, and visualization.

Sub-modules
-----------
- `models`            : Play-by-play event data classes
- `llm_client`        : DeepSeek (OpenAI-compatible) client wrapper with
                        prompt-contract enforcement
- `replay_simulator`  : Replays a recorded play-by-play feed at real-time
                        speed (path-of-least-risk for thesis defense demo)
- `event_detector`    : Classifies play-by-play events into commentary
                        triggers (key shot / turnover / momentum swing / ...)
- `live_commentator`  : Produces single-event commentary using LLM under
                        prompt-contract supervision
- `provenance`        : Sentence-level fact attribution (✓ / ⚠ / ○)

The package is designed to coexist with the existing post-game workflow.
Original modules (`workflows/`, `analysis/`, `content/`, `review/`, etc.)
are NOT modified.
"""

from realtime.models import (
    PlayByPlayEvent,
    DetectedEvent,
    Commentary,
    ProvenanceTag,
)

__all__ = [
    "PlayByPlayEvent",
    "DetectedEvent",
    "Commentary",
    "ProvenanceTag",
    "LiveCommentator",
    "LiveCommentaryPolicy",
]


def __getattr__(name: str):
    if name in {"LiveCommentator", "LiveCommentaryPolicy"}:
        from realtime.live_commentator import LiveCommentator, LiveCommentaryPolicy

        mapping = {
            "LiveCommentator": LiveCommentator,
            "LiveCommentaryPolicy": LiveCommentaryPolicy,
        }
        return mapping[name]
    raise AttributeError(f"module 'realtime' has no attribute {name!r}")
