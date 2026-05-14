"""Build a demo court report from normalized official NBA PBP.

NBA does not expose the project's target venue-AI report format. For demo
alignment, this module derives a compatible court report from official PBP and
marks the output metadata honestly as PBP-derived.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("data/court_reports")
TEAM_NAMES_ZH = {
    "OKC": "雷霆",
    "LAL": "湖人",
    "GSW": "勇士",
    "BOS": "凯尔特人",
    "NYK": "尼克斯",
    "PHI": "76人",
    "CLE": "骑士",
    "DET": "活塞",
    "MIN": "森林狼",
    "SAS": "马刺",
}


@dataclass
class PlayerLine:
    """Accumulated player box score derived from PBP events."""

    name: str
    team: str
    player_id: str = ""
    points: int = 0
    shot_attempts: int = 0
    shots_made: int = 0
    three_attempts: int = 0
    threes_made: int = 0
    free_throw_attempts: int = 0
    free_throws_made: int = 0
    rebounds: int = 0
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    fouls: int = 0
    plus_minus: int = 0
    role_tags: list[str] = field(default_factory=list)

    @property
    def mvp_score(self) -> float:
        return round(
            self.points * 1.0
            + self.assists * 1.5
            + self.rebounds * 1.0
            + self.blocks * 2.0
            + self.steals * 2.0
            - self.turnovers * 1.0,
            2,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id or _safe_player_id(self.team, self.name),
            "name": self.name,
            "team": self.team,
            "minutes": 0.0,
            "points": self.points,
            "shot_attempts": self.shot_attempts,
            "shots_made": self.shots_made,
            "three_attempts": self.three_attempts,
            "threes_made": self.threes_made,
            "free_throw_attempts": self.free_throw_attempts,
            "free_throws_made": self.free_throws_made,
            "rebounds": self.rebounds,
            "offensive_rebounds": self.offensive_rebounds,
            "defensive_rebounds": self.defensive_rebounds,
            "assists": self.assists,
            "steals": self.steals,
            "blocks": self.blocks,
            "turnovers": self.turnovers,
            "fouls": self.fouls,
            "plus_minus": self.plus_minus,
            "mvp_score": self.mvp_score,
            "role_tags": self.role_tags or _infer_role_tags(self),
        }


def build_court_report(replay_path: str | Path) -> dict[str, Any]:
    """Read normalized replay JSON and emit a court-report-compatible dict."""
    replay = json.loads(Path(replay_path).read_text(encoding="utf-8"))
    events = replay.get("events", [])
    if not isinstance(events, list):
        raise ValueError("Replay JSON must contain an events list.")

    players: dict[tuple[str, str], PlayerLine] = {}
    team_stats = _blank_team_stats(replay)
    final_home, final_away = 0, 0

    for event in events:
        if not isinstance(event, dict):
            continue
        team = str(event.get("teamTricode", ""))
        if team and team not in team_stats:
            team_stats[team] = _empty_team_line()
        final_home = _safe_int(event.get("scoreHome"), final_home)
        final_away = _safe_int(event.get("scoreAway"), final_away)
        player = _player_line(players, event)
        action = str(event.get("actionType", "")).lower()
        shot_result = str(event.get("shotResult", "")).lower()
        sub_type = str(event.get("subType", ""))

        if action in {"2pt", "3pt"} and player:
            shot_value = 3 if action == "3pt" or sub_type == "3PT" else 2
            player.shot_attempts += 1
            team_stats[team]["shot_attempts"] += 1
            if shot_value == 3:
                player.three_attempts += 1
                team_stats[team]["three_attempts"] += 1
            if shot_result == "made":
                player.shots_made += 1
                player.points += shot_value
                team_stats[team]["shots_made"] += 1
                team_stats[team]["points"] += shot_value
                if shot_value == 3:
                    player.threes_made += 1
                    team_stats[team]["threes_made"] += 1
        elif action == "freethrow" and player:
            player.free_throw_attempts += 1
            team_stats[team]["free_throw_attempts"] += 1
            if shot_result == "made":
                player.free_throws_made += 1
                player.points += 1
                team_stats[team]["free_throws_made"] += 1
                team_stats[team]["points"] += 1
        elif action == "rebound" and player:
            player.rebounds += 1
            team_stats[team]["rebounds"] += 1
            if sub_type == "OffReb":
                player.offensive_rebounds += 1
                team_stats[team]["offensive_rebounds"] += 1
            else:
                player.defensive_rebounds += 1
                team_stats[team]["defensive_rebounds"] += 1
        elif action == "turnover" and player:
            player.turnovers += 1
            team_stats[team]["turnovers"] += 1
        elif action == "steal" and player:
            player.steals += 1
            team_stats[team]["steals"] += 1
        elif action == "block" and player:
            player.blocks += 1
            team_stats[team]["blocks"] += 1
        elif action == "foul" and player:
            player.fouls += 1
            team_stats[team]["fouls"] += 1

        assist_name = str(event.get("assistPlayerNameInitial", ""))
        if assist_name:
            assist_player = _player_line(
                players,
                {"playerNameI": assist_name, "teamTricode": team, "personId": event.get("assistPersonId", "")},
            )
            if assist_player:
                assist_player.assists += 1
                team_stats[team]["assists"] += 1

    player_lines = sorted(
        [line for line in players.values() if _has_box_score(line)],
        key=lambda item: (item.mvp_score, item.points, item.assists + item.rebounds),
        reverse=True,
    )
    mvp = player_lines[0].name if player_lines else ""
    home_team = str(replay.get("home_team", ""))
    away_team = str(replay.get("away_team", ""))
    return {
        "game_id": str(replay.get("game_id", "")),
        "title": _title_for_game(replay),
        "home_team": home_team,
        "away_team": away_team,
        "final_score": f"{home_team} {final_home} - {final_away} {away_team}",
        "source": "court_ai_derived_from_pbp",
        "mvp": mvp,
        "players": [line.to_dict() for line in player_lines],
        "team_stats": team_stats,
        "metadata": {
            "derivation_note": (
                "Court report derived from official NBA PBP for demo. "
                "Real venue AI integration is future work."
            ),
            "plus_minus_note": "plus_minus is set to 0 because on-court lineup simulation is outside this demo derivation.",
            "event_count": len(events),
        },
    }


def save_court_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _player_line(players: dict[tuple[str, str], PlayerLine], event: dict[str, Any]) -> PlayerLine | None:
    name = str(event.get("playerNameI", "")).strip()
    team = str(event.get("teamTricode", "")).strip()
    if not name or not team or name.lower() in {"team", "unknown"}:
        return None
    key = (team, name)
    if key not in players:
        person_id = str(event.get("personId", "") or "")
        players[key] = PlayerLine(name=name, team=team, player_id=person_id)
    return players[key]


def _blank_team_stats(replay: dict[str, Any]) -> dict[str, dict[str, int]]:
    teams = [str(replay.get("home_team", "")), str(replay.get("away_team", ""))]
    return {team: _empty_team_line() for team in teams if team}


def _empty_team_line() -> dict[str, int]:
    return {
        "points": 0,
        "shot_attempts": 0,
        "shots_made": 0,
        "three_attempts": 0,
        "threes_made": 0,
        "free_throw_attempts": 0,
        "free_throws_made": 0,
        "rebounds": 0,
        "offensive_rebounds": 0,
        "defensive_rebounds": 0,
        "assists": 0,
        "turnovers": 0,
        "blocks": 0,
        "steals": 0,
        "fouls": 0,
    }


def _title_for_game(replay: dict[str, Any]) -> str:
    home = str(replay.get("home_team", ""))
    away = str(replay.get("away_team", ""))
    if {home, away} == {"OKC", "LAL"} and str(replay.get("game_id", "")).endswith("1"):
        return "OKC 雷霆 vs LAL 湖人 — 2026 西部半决赛 G1"
    return f"{home} {_team_zh(home)} vs {away} {_team_zh(away)} — NBA Playoffs"


def _team_zh(code: str) -> str:
    return TEAM_NAMES_ZH.get(code, "")


def _infer_role_tags(player: PlayerLine) -> list[str]:
    tags: list[str] = []
    if player.shot_attempts >= 15:
        tags.append("primary scorer")
    if player.assists >= 6:
        tags.append("creator")
    if player.rebounds >= 8:
        tags.append("rebounder")
    if player.blocks >= 2:
        tags.append("rim protector")
    if player.three_attempts >= 6:
        tags.append("floor spacer")
    return tags or ["rotation contributor"]


def _safe_player_id(team: str, name: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in name).strip("_")
    return f"{team.lower()}_{slug}"


def _has_box_score(line: PlayerLine) -> bool:
    return any(
        [
            line.points,
            line.shot_attempts,
            line.rebounds,
            line.assists,
            line.steals,
            line.blocks,
            line.turnovers,
            line.fouls,
        ]
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build demo court report from normalized NBA PBP.")
    parser.add_argument("--replay", required=True, help="Normalized replay JSON from ingestion.nba_pbp_fetcher.")
    parser.add_argument("--output", default="", help="Output court report JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_court_report(args.replay)
    output = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{report['game_id']}_court_report.json"
    save_court_report(output, report)
    print(
        json.dumps(
            {
                "game_id": report["game_id"],
                "players": len(report["players"]),
                "mvp": report["mvp"],
                "final_score": report["final_score"],
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
