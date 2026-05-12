"""Build Video Scout observations automatically from PBP plus court reports.

T-103 sits above the T-102 possession detector. It does not re-implement
possession splitting; instead it enriches the selected PBP-derived observations
with smart-court player stat evidence so the final report has a stronger
multi-source evidence chain.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from storage.file_store import ensure_dir, write_json
from video_scout.court_report import CourtPlayerStat, CourtReport
from video_scout.models import VisualObservation
from video_scout.possession_boundary_detector import (
    PossessionBoundaryDetector,
    boundaries_to_observations,
    load_replay_events,
)


DEFAULT_AUTO_OBSERVATIONS_PATH = Path("data/samples/auto_observations_demo.json")


def build_observations_from_pbp(
    pbp_path: str | Path,
    *,
    court_report_path: str | Path | None = None,
    video_total_seconds: float | None = None,
    video_period_windows: dict[int, tuple[float, float]] | None = None,
    periods: set[int] | None = None,
    min_salience: float = 0.45,
    max_count: int = 12,
) -> list[VisualObservation]:
    """Create observations from PBP and optionally enrich with court stats."""
    events = load_replay_events(pbp_path)
    detector = PossessionBoundaryDetector()
    boundaries = detector.detect(
        events,
        video_total_seconds=video_total_seconds,
        video_period_windows=video_period_windows,
    )
    if periods:
        boundaries = [item for item in boundaries if item.period in periods]
    observations = boundaries_to_observations(
        boundaries,
        min_salience=min_salience,
        max_count=max_count,
    )
    court_report = CourtReport.from_file(court_report_path) if court_report_path else None
    if court_report:
        observations = _enrich_observations_with_court_report(
            observations=observations,
            events=events,
            court_report=court_report,
        )
    return observations


def normalize_player_name(name: str, court_report: CourtReport | None) -> str:
    """Normalize short or full PBP player names against court-report players.

    Examples:
        S. Curry -> S. Curry
        Stephen Curry -> S. Curry
    """
    raw = " ".join(str(name or "").replace(".", ". ").split()).replace(". ", ". ")
    if not raw or not court_report:
        return str(name or "")

    direct = {player.name.lower(): player.name for player in court_report.players}
    if raw.lower() in direct:
        return direct[raw.lower()]

    raw_key = _initial_last_key(raw)
    for player in court_report.players:
        if _initial_last_key(player.name) == raw_key:
            return player.name

    raw_last = _last_name(raw)
    matches = [player.name for player in court_report.players if _last_name(player.name) == raw_last]
    return matches[0] if len(matches) == 1 else str(name or "")


def save_auto_observations(path: str | Path, observations: list[VisualObservation]) -> None:
    """Persist auto observations in the same shape accepted by demo_runner."""
    target = Path(path)
    ensure_dir(target.parent)
    write_json(
        target,
        {
            "source": "video_scout.auto_observation_builder",
            "observation_count": len(observations),
            "observations": [item.to_dict() for item in observations],
        },
    )


def _enrich_observations_with_court_report(
    *,
    observations: list[VisualObservation],
    events: list[dict],
    court_report: CourtReport,
) -> list[VisualObservation]:
    events_by_id = {_event_id(event): event for event in events}
    players_by_name = {player.name: player for player in court_report.players}

    for observation in observations:
        event_ids = _event_ids_from_evidence(observation.evidence)
        raw_players = [
            str(events_by_id[event_id].get("playerNameI", ""))
            for event_id in event_ids
            if event_id in events_by_id and events_by_id[event_id].get("playerNameI")
        ]
        normalized_players = _unique(
            normalize_player_name(player_name, court_report)
            for player_name in [*observation.players, *raw_players]
            if player_name
        )
        observation.players = normalized_players

        stat_lines = [
            _player_stat_line(players_by_name[player_name])
            for player_name in normalized_players
            if player_name in players_by_name
        ]
        for line in stat_lines:
            if line and line not in observation.evidence:
                observation.evidence.append(line)
        if stat_lines:
            observation.confidence = min(0.92, observation.confidence + 0.04)
    return observations


def _player_stat_line(player: CourtPlayerStat) -> str:
    return (
        f"{player.name} {player.points}分 "
        f"{player.shot_attempts}投{player.shots_made}中 "
        f"三分{player.threes_made}/{player.three_attempts} "
        f"{player.rebounds}板{player.assists}助 "
        f"{player.steals}断{player.blocks}帽 "
        f"正负值{player.plus_minus:+d}"
    )


def _event_ids_from_evidence(evidence: Iterable[str]) -> list[str]:
    ids: list[str] = []
    for item in evidence:
        text = str(item)
        if text.startswith("event:"):
            ids.append(text.split("event:", 1)[1])
    return ids


def _event_id(event: dict) -> str:
    return str(event.get("actionId", event.get("event_id", "")))


def _initial_last_key(name: str) -> str:
    parts = _name_parts(name)
    if not parts:
        return ""
    first = parts[0][0].lower() if parts[0] else ""
    return f"{first}.{parts[-1].lower()}"


def _last_name(name: str) -> str:
    parts = _name_parts(name)
    return parts[-1].lower() if parts else ""


def _name_parts(name: str) -> list[str]:
    cleaned = str(name or "").replace(".", " ")
    return [part for part in cleaned.split() if part]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Video Scout observations from PBP.")
    parser.add_argument("--replay", default="data/samples/nba_replay_sample.json", help="Replay JSON path.")
    parser.add_argument("--court-report", default="", help="Optional smart-court report JSON.")
    parser.add_argument("--video-total-seconds", type=float, default=0.0, help="Optional source video duration.")
    parser.add_argument("--periods", default="", help="Optional comma-separated periods, e.g. 1 or 1,2.")
    parser.add_argument("--output", default=str(DEFAULT_AUTO_OBSERVATIONS_PATH), help="Output observation JSON path.")
    parser.add_argument("--min-salience", type=float, default=0.45, help="Minimum salience for selected observations.")
    parser.add_argument("--max-count", type=int, default=12, help="Maximum selected observations.")
    return parser.parse_args()


def _self_test() -> None:
    args = parse_args()
    observations = build_observations_from_pbp(
        args.replay,
        court_report_path=args.court_report or None,
        video_total_seconds=args.video_total_seconds or None,
        periods=_parse_periods(args.periods),
        min_salience=args.min_salience,
        max_count=args.max_count,
    )
    save_auto_observations(args.output, observations)
    stat_evidence_count = sum(
        1
        for item in observations
        if any("分" in evidence and "投" in evidence and "正负值" in evidence for evidence in item.evidence)
    )
    print(
        json.dumps(
            {
                "observation_count": len(observations),
                "stat_evidence_count": stat_evidence_count,
                "output": str(Path(args.output).resolve()),
                "first_players": observations[0].players if observations else [],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_periods(value: str) -> set[int] | None:
    """Parse optional comma-separated period filters."""
    text = str(value or "").strip()
    if not text:
        return None
    periods = {int(item.strip()) for item in text.split(",") if item.strip()}
    if any(period <= 0 for period in periods):
        raise ValueError("--periods values must be positive integers.")
    return periods


if __name__ == "__main__":
    _self_test()
