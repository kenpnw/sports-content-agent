"""Adapter for basketball-court AI stat reports.

Many smart-court systems export a postgame report with player box scores and
an MVP. This adapter turns that structured report into context the Video Scout
Agent can use together with timestamped video observations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from storage.file_store import read_json


@dataclass
class CourtPlayerStat:
    player_id: str
    name: str
    team: str
    minutes: float = 0.0
    points: int = 0
    shot_attempts: int = 0
    shots_made: int = 0
    three_attempts: int = 0
    threes_made: int = 0
    free_throw_attempts: int = 0
    free_throws_made: int = 0
    rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    fouls: int = 0
    plus_minus: int = 0
    mvp_score: float = 0.0
    role_tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CourtPlayerStat":
        return cls(
            player_id=str(payload.get("player_id", payload.get("id", ""))),
            name=str(payload.get("name", "")),
            team=str(payload.get("team", "")),
            minutes=float(payload.get("minutes", 0.0) or 0.0),
            points=int(payload.get("points", 0) or 0),
            shot_attempts=int(payload.get("shot_attempts", payload.get("fga", 0)) or 0),
            shots_made=int(payload.get("shots_made", payload.get("fgm", 0)) or 0),
            three_attempts=int(payload.get("three_attempts", payload.get("tpa", 0)) or 0),
            threes_made=int(payload.get("threes_made", payload.get("tpm", 0)) or 0),
            free_throw_attempts=int(payload.get("free_throw_attempts", payload.get("fta", 0)) or 0),
            free_throws_made=int(payload.get("free_throws_made", payload.get("ftm", 0)) or 0),
            rebounds=int(payload.get("rebounds", 0) or 0),
            assists=int(payload.get("assists", 0) or 0),
            steals=int(payload.get("steals", 0) or 0),
            blocks=int(payload.get("blocks", 0) or 0),
            turnovers=int(payload.get("turnovers", 0) or 0),
            fouls=int(payload.get("fouls", 0) or 0),
            plus_minus=int(payload.get("plus_minus", 0) or 0),
            mvp_score=float(payload.get("mvp_score", 0.0) or 0.0),
            role_tags=[str(item) for item in payload.get("role_tags", [])],
        )

    @property
    def field_goal_pct(self) -> float:
        return round(self.shots_made / self.shot_attempts, 3) if self.shot_attempts else 0.0

    @property
    def usage_events(self) -> int:
        return self.shot_attempts + self.assists + self.turnovers + self.free_throw_attempts

    @property
    def tactical_initiation_score(self) -> float:
        # Not a basketball truth claim; this is an explainable product metric.
        return round(
            self.assists * 3.0
            + self.shot_attempts * 1.3
            + self.free_throw_attempts * 0.7
            + self.turnovers * 0.9
            + max(self.plus_minus, 0) * 0.2,
            2,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["field_goal_pct"] = self.field_goal_pct
        payload["usage_events"] = self.usage_events
        payload["tactical_initiation_score"] = self.tactical_initiation_score
        return payload


@dataclass
class CourtReport:
    game_id: str
    title: str
    home_team: str
    away_team: str
    final_score: str
    source: str = "court_ai"
    mvp: str = ""
    players: list[CourtPlayerStat] = field(default_factory=list)
    team_stats: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "CourtReport":
        payload = read_json(Path(path))
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CourtReport":
        players_payload = payload.get("players", [])
        return cls(
            game_id=str(payload.get("game_id", "")),
            title=str(payload.get("title", payload.get("matchup", "Smart Court Game Report"))),
            home_team=str(payload.get("home_team", "")),
            away_team=str(payload.get("away_team", "")),
            final_score=str(payload.get("final_score", "")),
            source=str(payload.get("source", "court_ai")),
            mvp=str(payload.get("mvp", "")),
            players=[CourtPlayerStat.from_dict(item) for item in players_payload if isinstance(item, dict)],
            team_stats=dict(payload.get("team_stats", {})),
            metadata=dict(payload.get("metadata", {})),
        )

    def top_players(self, limit: int = 8) -> list[CourtPlayerStat]:
        return sorted(
            self.players,
            key=lambda item: (
                item.mvp_score,
                item.points + item.rebounds + item.assists + item.steals + item.blocks,
                item.plus_minus,
            ),
            reverse=True,
        )[:limit]

    def tactical_initiators(self, limit: int = 6) -> list[CourtPlayerStat]:
        return sorted(self.players, key=lambda item: item.tactical_initiation_score, reverse=True)[:limit]

    def to_analysis_context(self) -> dict[str, Any]:
        top_players = [player.to_dict() for player in self.top_players()]
        initiators = [self._initiator_summary(player) for player in self.tactical_initiators()]
        mvp_player = next((player for player in self.players if player.name == self.mvp), None)
        return {
            "game_id": self.game_id,
            "title": self.title,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "final_score": self.final_score,
            "source": self.source,
            "mvp": self.mvp,
            "mvp_player": mvp_player.to_dict() if mvp_player else {},
            "team_stats": self.team_stats,
            "top_players": top_players,
            "tactical_initiators": initiators,
            "metric_note": (
                "tactical_initiation_score = assists*3.0 + shot_attempts*1.3 "
                "+ free_throw_attempts*0.7 + turnovers*0.9 + positive_plus_minus*0.2"
            ),
        }

    def to_prompt_context(self, *, top_limit: int = 6, initiator_limit: int = 6) -> dict[str, Any]:
        """Smaller context optimized for LLM prompts."""
        mvp_player = next((player for player in self.players if player.name == self.mvp), None)
        return {
            "game_id": self.game_id,
            "title": self.title,
            "final_score": self.final_score,
            "mvp": self.mvp,
            "mvp_line": self._compact_player_line(mvp_player) if mvp_player else "",
            "team_stats": self.team_stats,
            "top_players": [self._compact_player(player) for player in self.top_players(top_limit)],
            "tactical_initiators": [
                self._initiator_summary(player)
                for player in self.tactical_initiators(initiator_limit)
            ],
            "metric_note": "initiation_score explains usage burden, not official basketball truth.",
        }

    def _compact_player(self, player: CourtPlayerStat) -> dict[str, Any]:
        return {
            "name": player.name,
            "team": player.team,
            "line": self._compact_player_line(player),
            "role_tags": player.role_tags,
            "initiation_score": player.tactical_initiation_score,
        }

    def _compact_player_line(self, player: CourtPlayerStat | None) -> str:
        if not player:
            return ""
        return (
            f"{player.name} {player.points}分 {player.shots_made}/{player.shot_attempts}投 "
            f"三分{player.threes_made}/{player.three_attempts} "
            f"{player.rebounds}板 {player.assists}助 {player.blocks}帽 "
            f"{player.turnovers}失误 正负值{player.plus_minus:+d}"
        )

    def _initiator_summary(self, player: CourtPlayerStat) -> dict[str, Any]:
        return {
            "player": player.name,
            "team": player.team,
            "score": player.tactical_initiation_score,
            "usage_events": player.usage_events,
            "line": (
                f"{player.name}: {player.points}分, {player.shot_attempts}次出手, "
                f"{player.assists}助攻, {player.turnovers}失误, 正负值{player.plus_minus:+d}"
            ),
            "interpretation": _infer_player_role(player),
            "evidence": [
                f"shot_attempts={player.shot_attempts}",
                f"assists={player.assists}",
                f"turnovers={player.turnovers}",
                f"plus_minus={player.plus_minus}",
            ],
        }


def _infer_player_role(player: CourtPlayerStat) -> str:
    if player.assists >= 6 and player.shot_attempts >= 10:
        return "主要战术发起点，既承担持球组织，也承担一定终结压力。"
    if player.assists >= 6:
        return "偏组织型发起点，主要价值在于串联和创造队友机会。"
    if player.shot_attempts >= 16:
        return "高使用率终结点，战术更多围绕其出手质量展开。"
    if player.rebounds >= 10 or player.blocks >= 3:
        return "内线结构点，更多影响篮板保护、护框和二次进攻。"
    if player.three_attempts >= 6:
        return "空间牵制点，其站位会影响持球人突破和协防选择。"
    return "轮换功能点，需要结合视频回合判断其具体战术职责。"
