"""Rule-based possession boundary detection from basketball play-by-play.

This module is the T-102 bridge between official PBP rows and the Video Scout
pipeline. It is intentionally deterministic: no LLM calls, no vision calls,
and no dependency on realtime.event_detector. The output can be serialized for
evaluation, then converted into VisualObservation objects for demo_runner.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from storage.file_store import ensure_dir, read_json, write_json
from video_scout.models import VisualObservation


DEFAULT_REPLAY_PATH = Path("data/samples/nba_replay_sample.json")
DEFAULT_OBSERVATIONS_OUTPUT = Path("data/samples/auto_observations_from_t102.json")


@dataclass
class PossessionBoundary:
    """One inferred offensive possession window."""

    possession_id: str
    start_event_index: int
    end_event_index: int
    start_clock: str
    end_clock: str
    period: int
    possession_team: str
    end_reason: str
    tactic_hints: list[str] = field(default_factory=list)
    approx_video_start_seconds: float = 0.0
    approx_video_end_seconds: float = 0.0
    event_ids: list[str] = field(default_factory=list)
    event_descriptions: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    salience_category: str = "routine"
    salience: float = 0.1
    score_home: int = 0
    score_away: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage or later evaluation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PossessionBoundary":
        """Deserialize from a saved boundary dict."""
        return cls(
            possession_id=str(payload.get("possession_id", "")),
            start_event_index=int(payload.get("start_event_index", 0)),
            end_event_index=int(payload.get("end_event_index", 0)),
            start_clock=str(payload.get("start_clock", "")),
            end_clock=str(payload.get("end_clock", "")),
            period=int(payload.get("period", 0)),
            possession_team=str(payload.get("possession_team", "")),
            end_reason=str(payload.get("end_reason", "routine")),
            tactic_hints=[str(item) for item in payload.get("tactic_hints", [])],
            approx_video_start_seconds=float(payload.get("approx_video_start_seconds", 0.0) or 0.0),
            approx_video_end_seconds=float(payload.get("approx_video_end_seconds", 0.0) or 0.0),
            event_ids=[str(item) for item in payload.get("event_ids", [])],
            event_descriptions=[str(item) for item in payload.get("event_descriptions", [])],
            players=[str(item) for item in payload.get("players", [])],
            salience_category=str(payload.get("salience_category", "routine")),
            salience=float(payload.get("salience", 0.1) or 0.1),
            score_home=int(payload.get("score_home", 0) or 0),
            score_away=int(payload.get("score_away", 0) or 0),
        )

    def to_observation(self) -> VisualObservation:
        """Convert this boundary into the strict Video Scout observation model."""
        evidence = [
            f"event:{event_id}" for event_id in self.event_ids
        ] + self.event_descriptions[:3]
        return VisualObservation(
            observation_id=self.possession_id,
            timecode_seconds=self.approx_video_end_seconds,
            period=self.period,
            clock=self.end_clock,
            event_description=self.event_descriptions[-1] if self.event_descriptions else "",
            possession_team=self.possession_team,
            defense_team="",
            clip_start_seconds=self.approx_video_start_seconds,
            clip_end_seconds=max(self.approx_video_start_seconds + 1.0, self.approx_video_end_seconds),
            clip_label=f"{self.possession_id}_{self.salience_category}",
            tactic_tags=self.tactic_hints + [self.salience_category, self.end_reason],
            players=self.players,
            court_structure=(
                f"PBP-inferred possession from {self.start_clock} to {self.end_clock}; "
                f"ended by {self.end_reason}."
            ),
            action_summary=" | ".join(self.event_descriptions[-3:]),
            decision_analysis=(
                f"Rule detector marked this as {self.salience_category} with salience "
                f"{self.salience:.2f}; use video review to validate spacing and decision quality."
            ),
            evidence=evidence,
            confidence=min(0.86, max(0.55, self.salience)),
            source="auto_pbp",
        )


class PossessionBoundaryDetector:
    """Infer possession windows from raw PBP rows with simple basketball rules."""

    END_REASON_MADE_SHOT = "made_shot"
    END_REASON_TURNOVER = "turnover"
    END_REASON_DEFENSIVE_REBOUND = "defensive_rebound"
    END_REASON_PERIOD_END = "period_end"
    END_REASON_GAME_END = "game_end"

    def detect(
        self,
        events: list[dict[str, Any]],
        *,
        video_total_seconds: float | None = None,
    ) -> list[PossessionBoundary]:
        boundaries: list[PossessionBoundary] = []
        active_start: int | None = None
        active_team = ""
        missed_shot_team = ""
        recent_points: deque[tuple[str, int]] = deque(maxlen=8)

        for index, event in enumerate(events):
            period = _period(event)
            if _is_period_end(event) or _is_game_end(event):
                if active_start is not None:
                    boundaries.append(
                        self._make_boundary(
                            events=events,
                            start=active_start,
                            end=index,
                            possession_team=active_team,
                            end_reason=self.END_REASON_GAME_END if _is_game_end(event) else self.END_REASON_PERIOD_END,
                            recent_points=recent_points,
                            video_total_seconds=video_total_seconds,
                        )
                    )
                    active_start = None
                    active_team = ""
                    missed_shot_team = ""
                continue

            if active_start is not None and period != _period(events[active_start]):
                boundaries.append(
                    self._make_boundary(
                        events=events,
                        start=active_start,
                        end=max(active_start, index - 1),
                        possession_team=active_team,
                        end_reason=self.END_REASON_PERIOD_END,
                        recent_points=recent_points,
                        video_total_seconds=video_total_seconds,
                    )
                )
                active_start = None
                active_team = ""
                missed_shot_team = ""

            if _is_non_play_event(event):
                if _is_period_end(event) and active_start is not None:
                    boundaries.append(
                        self._make_boundary(
                            events=events,
                            start=active_start,
                            end=index,
                            possession_team=active_team,
                            end_reason=self.END_REASON_PERIOD_END,
                            recent_points=recent_points,
                            video_total_seconds=video_total_seconds,
                        )
                    )
                    active_start = None
                    active_team = ""
                    missed_shot_team = ""
                continue

            team = _team(event) or active_team
            if active_start is None:
                active_start = index
                active_team = team

            end_reason = ""
            possession_team = active_team or team
            if _is_made_shot(event):
                end_reason = self.END_REASON_MADE_SHOT
                possession_team = team
            elif _is_turnover(event):
                end_reason = self.END_REASON_TURNOVER
                possession_team = team
            elif _is_missed_shot(event):
                missed_shot_team = team
            elif _is_rebound(event) and missed_shot_team:
                if team and team != missed_shot_team:
                    end_reason = self.END_REASON_DEFENSIVE_REBOUND
                    possession_team = missed_shot_team
                missed_shot_team = ""
            elif _is_game_end(event):
                end_reason = self.END_REASON_GAME_END

            if end_reason:
                boundary = self._make_boundary(
                    events=events,
                    start=active_start,
                    end=index,
                    possession_team=possession_team,
                    end_reason=end_reason,
                    recent_points=recent_points,
                    video_total_seconds=video_total_seconds,
                )
                boundaries.append(boundary)
                if _points(event) > 0 and team:
                    recent_points.append((team, _points(event)))
                active_start = None
                active_team = ""
                missed_shot_team = ""

        if active_start is not None:
            boundaries.append(
                self._make_boundary(
                    events=events,
                    start=active_start,
                    end=len(events) - 1,
                    possession_team=active_team,
                    end_reason=self.END_REASON_GAME_END,
                    recent_points=recent_points,
                    video_total_seconds=video_total_seconds,
                )
            )
        return [item for item in boundaries if item.period > 0]

    def _make_boundary(
        self,
        *,
        events: list[dict[str, Any]],
        start: int,
        end: int,
        possession_team: str,
        end_reason: str,
        recent_points: Iterable[tuple[str, int]],
        video_total_seconds: float | None,
    ) -> PossessionBoundary:
        window = events[start : end + 1]
        start_event = window[0]
        end_event = window[-1]
        salience_category, salience = _classify_salience(
            event=end_event,
            previous_event=events[end - 1] if end > 0 else None,
            recent_points=list(recent_points),
            end_reason=end_reason,
        )
        tactic_hints = _infer_tactic_hints(window, salience_category)
        event_ids = [_event_id(item) for item in window]
        descriptions = [_description(item) for item in window if _description(item)]
        players = _unique(
            [
                _player_name(item)
                for item in window
                if _player_name(item)
            ]
        )
        start_seconds = _clock_to_absolute_seconds(_period(start_event), _clock(start_event))
        end_seconds = _clock_to_absolute_seconds(_period(end_event), _clock(end_event))
        start_seconds, end_seconds = _map_to_video_seconds(
            start_seconds,
            end_seconds,
            video_total_seconds=video_total_seconds,
        )
        return PossessionBoundary(
            possession_id=f"poss_p{_period(end_event)}_e{_event_id(end_event)}",
            start_event_index=start,
            end_event_index=end,
            start_clock=_clock(start_event),
            end_clock=_clock(end_event),
            period=_period(end_event),
            possession_team=possession_team,
            end_reason=end_reason,
            tactic_hints=tactic_hints,
            approx_video_start_seconds=round(max(0.0, start_seconds - 4.0), 2),
            approx_video_end_seconds=round(max(start_seconds + 1.0, end_seconds + 3.0), 2),
            event_ids=event_ids,
            event_descriptions=descriptions,
            players=players,
            salience_category=salience_category,
            salience=salience,
            score_home=_score_home(end_event),
            score_away=_score_away(end_event),
        )


def boundaries_to_observations(
    boundaries: list[PossessionBoundary],
    *,
    min_salience: float = 0.45,
    max_count: int = 12,
) -> list[VisualObservation]:
    """Select 6-12 high-value possessions and convert them to observations."""
    must_keep = {"clutch_shot", "lead_change", "momentum_swing", "period_end", "game_end"}

    candidates = [
        item
        for item in boundaries
        if item.salience_category != "routine"
        and (item.salience >= min_salience or item.salience_category in must_keep)
    ]
    candidates.sort(
        key=lambda item: (
            0 if item.salience_category in must_keep else 1,
            -item.salience,
            item.period,
            item.end_event_index,
        )
    )
    selected = candidates[:max_count]
    selected.sort(key=lambda item: (item.period, item.start_event_index))
    return [item.to_observation() for item in selected]


def load_replay_events(path: str | Path) -> list[dict[str, Any]]:
    payload = read_json(Path(path))
    events = payload.get("events", [])
    if not isinstance(events, list):
        raise ValueError("Replay JSON must contain an `events` list.")
    return [item for item in events if isinstance(item, dict)]


def summarize_boundaries(boundaries: list[PossessionBoundary]) -> dict[str, Any]:
    lengths = [item.end_event_index - item.start_event_index + 1 for item in boundaries]
    distribution = Counter(item.end_reason for item in boundaries)
    return {
        "boundary_count": len(boundaries),
        "end_reason_distribution": dict(sorted(distribution.items())),
        "average_possession_length_rows": round(sum(lengths) / len(lengths), 2) if lengths else 0.0,
    }


def save_observations(path: str | Path, observations: list[VisualObservation]) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    write_json(
        target,
        {
            "source": "video_scout.possession_boundary_detector",
            "observation_count": len(observations),
            "observations": [item.to_dict() for item in observations],
        },
    )


def _classify_salience(
    *,
    event: dict[str, Any],
    previous_event: dict[str, Any] | None,
    recent_points: list[tuple[str, int]],
    end_reason: str,
) -> tuple[str, float]:
    if _is_game_end(event) or end_reason == PossessionBoundaryDetector.END_REASON_GAME_END:
        return "game_end", 0.99
    if end_reason == PossessionBoundaryDetector.END_REASON_PERIOD_END or _is_period_end(event):
        return "period_end", 0.68
    if _is_made_shot(event):
        if _is_clutch(event):
            return "clutch_shot", 0.96
        if _is_lead_change(event, previous_event):
            return "lead_change", 0.84
        if _is_momentum_swing(event, recent_points):
            return "momentum_swing", 0.78
        if _points(event) >= 3 or "3pt" in _sub_type(event).lower() or "dunk" in _description(event).lower():
            return "key_shot", 0.58
    if end_reason == PossessionBoundaryDetector.END_REASON_TURNOVER:
        return "turnover", 0.50
    if end_reason == PossessionBoundaryDetector.END_REASON_DEFENSIVE_REBOUND:
        return "defensive_stop", 0.46
    return "routine", 0.20


def _infer_tactic_hints(events: list[dict[str, Any]], salience_category: str) -> list[str]:
    text = " ".join(_description(item).lower() for item in events)
    hints: list[str] = []
    if "3pt" in text or "three" in text or "3'" in text:
        hints.append("three_point_creation")
    if "dunk" in text or "layup" in text:
        hints.append("rim_pressure")
    if "turnover" in text or "steal" in text:
        hints.append("ball_security")
    if "rebound" in text:
        hints.append("rebound_control")
    if salience_category in {"clutch_shot", "lead_change"}:
        hints.append("late_game_execution")
    if not hints:
        hints.append("half_court_possession")
    return _unique(hints)


def _clock_to_absolute_seconds(period: int, clock: str) -> float:
    remaining = _remaining_seconds(clock)
    period_len = 720.0 if period <= 4 else 300.0
    elapsed_in_period = max(0.0, period_len - remaining)
    previous = 0.0
    for p in range(1, period):
        previous += 720.0 if p <= 4 else 300.0
    return previous + elapsed_in_period


def _map_to_video_seconds(
    start_seconds: float,
    end_seconds: float,
    *,
    video_total_seconds: float | None,
) -> tuple[float, float]:
    if not video_total_seconds:
        return start_seconds, end_seconds
    regulation_seconds = 48 * 60
    ratio = max(0.01, video_total_seconds / regulation_seconds)
    return start_seconds * ratio, end_seconds * ratio


def _remaining_seconds(clock: str) -> float:
    text = clock.strip().upper()
    if text.startswith("PT"):
        text = text[2:]
        minutes = 0
        seconds = 0.0
        if "M" in text:
            before, text = text.split("M", 1)
            minutes = int(float(before or 0))
        if "S" in text:
            seconds = float(text.split("S", 1)[0] or 0)
        return minutes * 60 + seconds
    if ":" in text:
        left, right = text.split(":", 1)
        return int(left) * 60 + float(right)
    return 0.0


def _is_non_play_event(event: dict[str, Any]) -> bool:
    desc = _description(event).lower()
    action = _action_type(event).lower()
    if "game start" in desc or action in {"", "start"}:
        return not _team(event)
    return False


def _is_made_shot(event: dict[str, Any]) -> bool:
    return _shot_result(event).lower() == "made" or "made shot" in _action_type(event).lower()


def _is_missed_shot(event: dict[str, Any]) -> bool:
    desc = _description(event).lower()
    action = _action_type(event).lower()
    return _shot_result(event).lower() == "missed" or "miss" in desc or "missed shot" in action


def _is_rebound(event: dict[str, Any]) -> bool:
    return "rebound" in _description(event).lower() or "rebound" in _action_type(event).lower()


def _is_turnover(event: dict[str, Any]) -> bool:
    return "turnover" in _description(event).lower() or "turnover" in _action_type(event).lower()


def _is_period_end(event: dict[str, Any]) -> bool:
    text = f"{_description(event)} {_action_type(event)}".lower()
    return "end of" in text and "period" in text


def _is_game_end(event: dict[str, Any]) -> bool:
    text = f"{_description(event)} {_action_type(event)}".lower()
    return "end of game" in text or "final" in text or "game end" in text


def _is_clutch(event: dict[str, Any]) -> bool:
    return _period(event) >= 4 and _remaining_seconds(_clock(event)) <= 300 and abs(_score_home(event) - _score_away(event)) <= 6


def _is_lead_change(event: dict[str, Any], previous_event: dict[str, Any] | None) -> bool:
    if previous_event is None:
        return False
    previous_leader = _leader(previous_event)
    current_leader = _leader(event)
    if not previous_leader or not current_leader:
        return False
    return current_leader != previous_leader


def _is_momentum_swing(event: dict[str, Any], recent_points: list[tuple[str, int]]) -> bool:
    team = _team(event)
    if not team or _points(event) <= 0:
        return False
    totals: dict[str, int] = {}
    for row_team, points in recent_points + [(team, _points(event))]:
        totals[row_team] = totals.get(row_team, 0) + points
    leader_points = totals.get(team, 0)
    other_points = sum(points for row_team, points in totals.items() if row_team != team)
    return leader_points >= 8 and other_points <= 2


def _leader(event: dict[str, Any]) -> str:
    if _score_home(event) > _score_away(event):
        return "HOME"
    if _score_away(event) > _score_home(event):
        return "AWAY"
    return ""


def _period(event: dict[str, Any]) -> int:
    return int(event.get("period", 0) or 0)


def _clock(event: dict[str, Any]) -> str:
    return str(event.get("clock", ""))


def _description(event: dict[str, Any]) -> str:
    return str(event.get("description", ""))


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("actionId", event.get("event_id", "")))


def _team(event: dict[str, Any]) -> str:
    return str(event.get("teamTricode", event.get("team", "")))


def _player_name(event: dict[str, Any]) -> str:
    return str(event.get("playerNameI", event.get("actor", "")))


def _action_type(event: dict[str, Any]) -> str:
    return str(event.get("actionType", ""))


def _sub_type(event: dict[str, Any]) -> str:
    return str(event.get("subType", ""))


def _shot_result(event: dict[str, Any]) -> str:
    return str(event.get("shotResult", ""))


def _points(event: dict[str, Any]) -> int:
    if _shot_result(event).lower() == "made":
        return int(event.get("shotValue", 0) or 0)
    return 0


def _score_home(event: dict[str, Any]) -> int:
    return int(event.get("scoreHome", 0) or 0)


def _score_away(event: dict[str, Any]) -> int:
    return int(event.get("scoreAway", 0) or 0)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _print_summary(boundaries: list[PossessionBoundary], observations: list[VisualObservation]) -> None:
    summary = summarize_boundaries(boundaries)
    print(f"[T-102] boundaries={summary['boundary_count']}")
    print(f"[T-102] end_reason_distribution={summary['end_reason_distribution']}")
    print(f"[T-102] average_possession_length_rows={summary['average_possession_length_rows']}")
    print(f"[T-102] selected_observations={len(observations)}")
    for item in observations[:12]:
        print(
            f"[T-102] observation={item.observation_id} | Q{item.period} {item.clock} | "
            f"tags={','.join(item.tactic_tags[:4])}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infer possession boundaries from PBP.")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY_PATH), help="Replay JSON path.")
    parser.add_argument("--video-total-seconds", type=float, default=0.0, help="Optional source video duration.")
    parser.add_argument("--min-salience", type=float, default=0.45, help="Minimum salience for observation selection.")
    parser.add_argument("--max-count", type=int, default=12, help="Maximum observations to emit.")
    parser.add_argument("--write-observations", default="", help="Optional path for auto observations JSON.")
    parser.add_argument("--write-boundaries", default="", help="Optional path for raw boundaries JSON.")
    return parser.parse_args()


def _self_test() -> None:
    args = parse_args()
    events = load_replay_events(args.replay)
    detector = PossessionBoundaryDetector()
    boundaries = detector.detect(
        events,
        video_total_seconds=args.video_total_seconds or None,
    )
    observations = boundaries_to_observations(
        boundaries,
        min_salience=args.min_salience,
        max_count=args.max_count,
    )
    round_tripped = [PossessionBoundary.from_dict(item.to_dict()) for item in boundaries]
    if [item.to_dict() for item in round_tripped] != [item.to_dict() for item in boundaries]:
        raise SystemExit("PossessionBoundary round-trip serialization failed.")
    if round_tripped:
        _ = round_tripped[0].to_observation()
    _print_summary(boundaries, observations)
    if args.write_boundaries:
        boundary_path = Path(args.write_boundaries)
        ensure_dir(boundary_path.parent)
        write_json(boundary_path, [item.to_dict() for item in boundaries])
        print(f"[T-102] wrote_boundaries={boundary_path.resolve()}")
    if args.write_observations:
        save_observations(args.write_observations, observations)
        print(f"[T-102] wrote_observations={Path(args.write_observations).resolve()}")
    if len(boundaries) < 8:
        raise SystemExit(f"Expected at least 8 boundaries for T-102 self-test; got {len(boundaries)}.")
    if not (1 <= len(observations) <= args.max_count):
        raise SystemExit("Observation selection produced an invalid count.")
    print("[T-102] self-test passed")


if __name__ == "__main__":
    _self_test()
