from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TeamStats:
    points: int
    rebounds: int
    assists: int
    turnovers: int
    three_points_made: int
    three_points_attempted: int


@dataclass
class TeamResult:
    name: str
    short_name: str
    score: int
    record: str
    stats: TeamStats


@dataclass
class PlayerPerformance:
    name: str
    team: str
    points: int
    rebounds: int
    assists: int
    steals: int = 0
    blocks: int = 0
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    three_points_made: int = 0
    three_points_attempted: int = 0
    plus_minus: int = 0
    summary: str = ""


@dataclass
class GameFlowNote:
    quarter: str
    note: str


@dataclass
class NBAInstantAnalysis:
    headline: str
    primary_driver: str = ""
    secondary_driver: str = ""
    key_takeaways: list[str] = field(default_factory=list)
    tactical_observations: list[str] = field(default_factory=list)
    trending_angles: list[str] = field(default_factory=list)
    driver_details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class NBAPostgameData:
    league: str
    game_id: str
    game_date: str
    status: str
    venue: str
    home_team: TeamResult
    away_team: TeamResult
    winner: str
    top_players: list[PlayerPerformance]
    game_flow: list[GameFlowNote]
    notable_context: list[str]
    analysis: NBAInstantAnalysis
    source: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NBAPostgameData":
        def parse_team(team_payload: dict[str, Any]) -> TeamResult:
            stats_payload = team_payload.get("stats", {})
            stats = TeamStats(
                points=int(stats_payload.get("points", team_payload.get("score", 0))),
                rebounds=int(stats_payload.get("rebounds", 0)),
                assists=int(stats_payload.get("assists", 0)),
                turnovers=int(stats_payload.get("turnovers", 0)),
                three_points_made=int(stats_payload.get("three_points_made", 0)),
                three_points_attempted=int(stats_payload.get("three_points_attempted", 0)),
            )
            return TeamResult(
                name=str(team_payload.get("name", "")),
                short_name=str(team_payload.get("short_name", team_payload.get("name", ""))),
                score=int(team_payload.get("score", 0)),
                record=str(team_payload.get("record", "")),
                stats=stats,
            )

        top_players = []
        for item in payload.get("top_players", []):
            top_players.append(
                PlayerPerformance(
                    name=str(item.get("name", "")),
                    team=str(item.get("team", "")),
                    points=int(item.get("points", 0)),
                    rebounds=int(item.get("rebounds", 0)),
                    assists=int(item.get("assists", 0)),
                    steals=int(item.get("steals", 0)),
                    blocks=int(item.get("blocks", 0)),
                    field_goals_made=int(item.get("field_goals_made", 0)),
                    field_goals_attempted=int(item.get("field_goals_attempted", 0)),
                    three_points_made=int(item.get("three_points_made", 0)),
                    three_points_attempted=int(item.get("three_points_attempted", 0)),
                    plus_minus=int(item.get("plus_minus", 0)),
                    summary=str(item.get("summary", "")),
                )
            )

        game_flow = []
        for item in payload.get("game_flow", []):
            game_flow.append(
                GameFlowNote(
                    quarter=str(item.get("quarter", "")),
                    note=str(item.get("note", "")),
                )
            )

        analysis_payload = payload.get("analysis", {})
        analysis = NBAInstantAnalysis(
            headline=str(analysis_payload.get("headline", "")),
            primary_driver=str(analysis_payload.get("primary_driver", "")),
            secondary_driver=str(analysis_payload.get("secondary_driver", "")),
            key_takeaways=[str(x) for x in analysis_payload.get("key_takeaways", [])],
            tactical_observations=[str(x) for x in analysis_payload.get("tactical_observations", [])],
            trending_angles=[str(x) for x in analysis_payload.get("trending_angles", [])],
            driver_details=[
                {
                    "type": str(item.get("type", "")),
                    "label": str(item.get("label", "")),
                    "value": item.get("value", 0),
                }
                for item in analysis_payload.get("driver_details", [])
                if isinstance(item, dict)
            ],
        )

        return cls(
            league=str(payload.get("league", "NBA")),
            game_id=str(payload.get("game_id", "")),
            game_date=str(payload.get("game_date", "")),
            status=str(payload.get("status", "final")),
            venue=str(payload.get("venue", "")),
            home_team=parse_team(payload.get("home_team", {})),
            away_team=parse_team(payload.get("away_team", {})),
            winner=str(payload.get("winner", "")),
            top_players=top_players,
            game_flow=game_flow,
            notable_context=[str(x) for x in payload.get("notable_context", [])],
            analysis=analysis,
            source=str(payload.get("source", "")),
        )
