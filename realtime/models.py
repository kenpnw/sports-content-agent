"""Real-time event data models.

These models represent the play-by-play event stream and the downstream
artifacts produced by the live commentary pipeline.

Notation
--------
- A `PlayByPlayEvent` is one raw event from the data feed (one made shot,
  one turnover, one timeout, etc.).
- A `DetectedEvent` is a `PlayByPlayEvent` after classification by
  `event_detector`, augmented with category and salience score.
- A `Commentary` is the final LLM-generated text for a `DetectedEvent`,
  with provenance tags for visual fact verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Raw play-by-play event
# ---------------------------------------------------------------------------


@dataclass
class PlayByPlayEvent:
    """One raw event from the play-by-play feed.

    The schema is intentionally permissive: data sources differ across leagues
    and adapters. Only `event_id`, `clock`, `period`, and `description` are
    strictly required for downstream processing.
    """

    event_id: str
    period: int                       # 1, 2, 3, 4 (5+ for OT)
    clock: str                        # e.g. "PT11M42S" or "11:42"
    description: str                  # natural-language event line
    home_score: int = 0
    away_score: int = 0
    actor_player: str = ""            # primary player involved
    secondary_player: str = ""        # assister, blocker, etc.
    actor_team: str = ""              # team short_name
    action_type: str = ""             # "MADE_SHOT" | "MISS" | "TURNOVER" | ...
    sub_type: str = ""                # "3PT" | "DUNK" | "STEAL" | ...
    points: int = 0                   # points scored on this event
    elapsed_seconds_in_period: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_nba_official(cls, payload: dict[str, Any]) -> "PlayByPlayEvent":
        """Build from NBA official live PBP feed payload.

        NBA's CDN feed (`stats.nba.com/.../playbyplay`) uses these fields:
            actionId, period, clock, description, scoreHome, scoreAway,
            playerNameI, actionType, subType
        """
        return cls(
            event_id=str(payload.get("actionId", payload.get("event_id", ""))),
            period=int(payload.get("period", 1)),
            clock=str(payload.get("clock", "")),
            description=str(payload.get("description", "")),
            home_score=int(payload.get("scoreHome", 0)),
            away_score=int(payload.get("scoreAway", 0)),
            actor_player=str(payload.get("playerNameI", payload.get("actor", ""))),
            secondary_player=str(payload.get("assistPlayerNameInitial", "")),
            actor_team=str(payload.get("teamTricode", payload.get("team", ""))),
            action_type=str(payload.get("actionType", "")),
            sub_type=str(payload.get("subType", "")),
            points=int(payload.get("shotValue", 0))
                if payload.get("shotResult") == "Made" else 0,
            raw=dict(payload),
        )


# ---------------------------------------------------------------------------
# Detected (classified) event
# ---------------------------------------------------------------------------

# Canonical event categories used by the commentary pipeline.
# These map to commentary templates and prompt-contract source_scope.
EVENT_CATEGORY_KEY_SHOT = "key_shot"             # impactful made basket
EVENT_CATEGORY_CLUTCH_SHOT = "clutch_shot"       # late-game decisive shot
EVENT_CATEGORY_TURNOVER = "turnover"             # costly turnover
EVENT_CATEGORY_MOMENTUM_SWING = "momentum_swing" # run, lead change, big swing
EVENT_CATEGORY_LEAD_CHANGE = "lead_change"       # lead crossed
EVENT_CATEGORY_TIMEOUT = "timeout"               # tactical timeout
EVENT_CATEGORY_INJURY_NOTE = "injury_note"       # player departure/injury
EVENT_CATEGORY_PERIOD_END = "period_end"         # quarter / half end
EVENT_CATEGORY_GAME_END = "game_end"             # final buzzer
EVENT_CATEGORY_ROUTINE = "routine"               # not commentary-worthy


ALL_EVENT_CATEGORIES = (
    EVENT_CATEGORY_KEY_SHOT,
    EVENT_CATEGORY_CLUTCH_SHOT,
    EVENT_CATEGORY_TURNOVER,
    EVENT_CATEGORY_MOMENTUM_SWING,
    EVENT_CATEGORY_LEAD_CHANGE,
    EVENT_CATEGORY_TIMEOUT,
    EVENT_CATEGORY_INJURY_NOTE,
    EVENT_CATEGORY_PERIOD_END,
    EVENT_CATEGORY_GAME_END,
    EVENT_CATEGORY_ROUTINE,
)


@dataclass
class DetectedEvent:
    """A play-by-play event after classification.

    `salience` is in [0, 1] — events below the configured threshold are
    suppressed by the commentary scheduler.
    """

    raw_event: PlayByPlayEvent
    category: str
    salience: float
    rationale: str = ""               # why this category / salience was assigned
    context_snapshot: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generated commentary
# ---------------------------------------------------------------------------


@dataclass
class ProvenanceTag:
    """Sentence-level fact provenance.

    `state` is one of:
        - "verified" (✓): every numeric / proper-noun claim is grounded
                          in the Fact Store snapshot
        - "narrative" (○): no factual claim, pure stylistic phrasing
        - "speculative" (⚠): contains an inferred claim with traceable
                             source but not strictly verified
    """

    text: str
    state: str                        # "verified" | "narrative" | "speculative"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    notes: str = ""


@dataclass
class Commentary:
    """One LLM-generated commentary attached to a detected event.

    The whole pipeline's output is a stream of `Commentary` objects ordered
    by `produced_at_seconds`.
    """

    event: DetectedEvent
    style: str                        # "hupu" | "academic" | "douyin"
    raw_text: str                     # full commentary as one string
    provenance: list[ProvenanceTag]   # sentence-level breakdown
    produced_at_seconds: float = 0.0  # T+ relative to game start
    latency_seconds: float = 0.0      # LLM call latency for telemetry
    prompt_contract_id: str = ""      # which contract gated this output
    model: str = ""                   # e.g. "deepseek-chat"
    metadata: dict[str, Any] = field(default_factory=dict)
