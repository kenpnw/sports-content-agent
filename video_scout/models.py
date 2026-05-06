"""Data models for video-based basketball scouting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FrameSample:
    """One sampled frame from a local game video."""

    frame_id: str
    image_path: str
    timecode_seconds: float
    period: int = 0
    clock: str = ""
    linked_event_id: str = ""
    linked_event_description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisualObservation:
    """One tactical observation anchored to a timestamp or frame."""

    observation_id: str
    timecode_seconds: float
    period: int
    clock: str
    frame_path: str = ""
    event_description: str = ""
    possession_team: str = ""
    defense_team: str = ""
    clip_start_seconds: float | None = None
    clip_end_seconds: float | None = None
    clip_label: str = ""
    tactic_tags: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    court_structure: str = ""
    action_summary: str = ""
    decision_analysis: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.75
    source: str = "manual"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualObservation":
        return cls(
            observation_id=str(payload.get("observation_id", payload.get("id", ""))),
            timecode_seconds=float(payload.get("timecode_seconds", 0.0)),
            period=int(payload.get("period", 0)),
            clock=str(payload.get("clock", "")),
            frame_path=str(payload.get("frame_path", "")),
            event_description=str(payload.get("event_description", "")),
            possession_team=str(payload.get("possession_team", "")),
            defense_team=str(payload.get("defense_team", "")),
            clip_start_seconds=_optional_float(payload.get("clip_start_seconds")),
            clip_end_seconds=_optional_float(payload.get("clip_end_seconds")),
            clip_label=str(payload.get("clip_label", "")),
            tactic_tags=[str(item) for item in payload.get("tactic_tags", [])],
            players=[str(item) for item in payload.get("players", [])],
            court_structure=str(payload.get("court_structure", "")),
            action_summary=str(payload.get("action_summary", "")),
            decision_analysis=str(payload.get("decision_analysis", "")),
            evidence=[str(item) for item in payload.get("evidence", [])],
            confidence=float(payload.get("confidence", 0.75)),
            source=str(payload.get("source", "manual")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TacticalSegment:
    """One report segment produced by the scout analyzer."""

    timecode: str
    period: int
    clock: str
    tactic_type: str
    observation: str
    decision_analysis: str
    win_loss_impact: str
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.75

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoScoutReport:
    """Full tactical report for one game or one video clip."""

    title: str
    executive_summary: str
    full_analysis: str = ""
    key_segments: list[TacticalSegment] = field(default_factory=list)
    tactical_themes: list[str] = field(default_factory=list)
    quarter_flow: list[str] = field(default_factory=list)
    deciding_factors: list[str] = field(default_factory=list)
    mvp_analysis: str = ""
    player_tactical_profiles: list[dict[str, Any]] = field(default_factory=list)
    player_decision_notes: list[str] = field(default_factory=list)
    content_angles: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence_index: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["key_segments"] = [segment.to_dict() for segment in self.key_segments]
        return payload


def seconds_to_timecode(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
