from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from config import DATA_DIR, KNOWLEDGE_DB_PATH
from core.models import NBAPostgameData
from storage.file_store import ensure_dir, read_json


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _season_label(game_date: str) -> str:
    try:
        parsed = datetime.fromisoformat(game_date)
    except ValueError:
        parsed = datetime.now()
    start_year = parsed.year if parsed.month >= 10 else parsed.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


class FactStore:
    def __init__(self, db_path: str = KNOWLEDGE_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        ensure_dir(self.db_path.parent)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY,
                    league TEXT NOT NULL,
                    season TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    source TEXT NOT NULL,
                    home_team_code TEXT NOT NULL,
                    home_team_name TEXT NOT NULL,
                    away_team_code TEXT NOT NULL,
                    away_team_name TEXT NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    winner_code TEXT NOT NULL,
                    winner_name TEXT NOT NULL,
                    inserted_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_game_stats (
                    game_id TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    season TEXT NOT NULL,
                    team_code TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    opponent_code TEXT NOT NULL,
                    opponent_name TEXT NOT NULL,
                    is_home INTEGER NOT NULL,
                    win INTEGER NOT NULL,
                    points INTEGER NOT NULL,
                    rebounds INTEGER NOT NULL,
                    assists INTEGER NOT NULL,
                    turnovers INTEGER NOT NULL,
                    three_points_made INTEGER NOT NULL,
                    three_points_attempted INTEGER NOT NULL,
                    point_margin INTEGER NOT NULL,
                    PRIMARY KEY (game_id, team_code)
                );
                CREATE INDEX IF NOT EXISTS idx_team_game_stats_team_date
                    ON team_game_stats(team_code, game_date DESC);
                CREATE INDEX IF NOT EXISTS idx_team_game_stats_opponent
                    ON team_game_stats(team_code, opponent_code, game_date DESC);

                CREATE TABLE IF NOT EXISTS player_game_stats (
                    game_id TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    season TEXT NOT NULL,
                    team_code TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    points INTEGER NOT NULL,
                    rebounds INTEGER NOT NULL,
                    assists INTEGER NOT NULL,
                    steals INTEGER NOT NULL,
                    blocks INTEGER NOT NULL,
                    field_goals_made INTEGER NOT NULL,
                    field_goals_attempted INTEGER NOT NULL,
                    three_points_made INTEGER NOT NULL,
                    three_points_attempted INTEGER NOT NULL,
                    plus_minus INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    PRIMARY KEY (game_id, player_name, team_code)
                );
                CREATE INDEX IF NOT EXISTS idx_player_game_stats_lookup
                    ON player_game_stats(player_name, team_code, game_date DESC);

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    doc_id TEXT PRIMARY KEY,
                    sport TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def bootstrap_from_workspace(self, exclude_paths: set[str] | None = None) -> int:
        exclude = {str(Path(path).resolve()) for path in (exclude_paths or set())}
        ingested = 0
        candidate_paths = []
        generated_root = DATA_DIR / "generated" / "nba_postgame"
        if generated_root.exists():
            candidate_paths.extend(generated_root.rglob("nba_postgame_*.json"))

        for path in candidate_paths:
            resolved = str(path.resolve())
            if resolved in exclude:
                continue
            try:
                payload = read_json(path)
                if str(payload.get("league", "")).upper() != "NBA":
                    continue
                game = NBAPostgameData.from_dict(payload)
            except Exception:
                continue
            self.ingest_postgame(game)
            ingested += 1
        return ingested

    def ingest_postgame(self, game: NBAPostgameData) -> None:
        season = _season_label(game.game_date)
        winner_code = game.home_team.short_name if game.home_team.score >= game.away_team.score else game.away_team.short_name
        winner_name = game.home_team.name if game.home_team.score >= game.away_team.score else game.away_team.name

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO games (
                    game_id, league, season, game_date, status, venue, source,
                    home_team_code, home_team_name, away_team_code, away_team_name,
                    home_score, away_score, winner_code, winner_name, inserted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game.game_id,
                    game.league,
                    season,
                    game.game_date,
                    game.status,
                    game.venue,
                    game.source,
                    game.home_team.short_name,
                    game.home_team.name,
                    game.away_team.short_name,
                    game.away_team.name,
                    game.home_team.score,
                    game.away_team.score,
                    winner_code,
                    winner_name,
                    _iso_now(),
                ),
            )
            conn.execute("DELETE FROM team_game_stats WHERE game_id = ?", (game.game_id,))
            conn.execute("DELETE FROM player_game_stats WHERE game_id = ?", (game.game_id,))
            self._insert_team_rows(conn, game, season)
            self._insert_player_rows(conn, game, season)

    def build_game_context(self, game: NBAPostgameData) -> dict[str, Any]:
        home_context = self.team_snapshot(game.home_team.short_name, fallback_name=game.home_team.name)
        away_context = self.team_snapshot(game.away_team.short_name, fallback_name=game.away_team.name)
        head_to_head = self.head_to_head(
            game.home_team.short_name,
            game.away_team.short_name,
            home_name=game.home_team.name,
            away_name=game.away_team.name,
        )
        player_context = []
        for player in game.top_players[:4]:
            player_context.append(
                self.player_snapshot(
                    player.name,
                    player.team,
                    fallback_team_name=game.home_team.name if player.team == game.home_team.short_name else game.away_team.name,
                )
            )
        return {
            "home_team": home_context,
            "away_team": away_context,
            "head_to_head": head_to_head,
            "top_players": player_context,
        }

    def team_snapshot(self, team_code: str, fallback_name: str = "", limit: int = 8) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT game_id, game_date, team_name, opponent_code, opponent_name, win,
                       points, rebounds, assists, turnovers, three_points_made, point_margin
                FROM team_game_stats
                WHERE team_code = ?
                ORDER BY game_date DESC, game_id DESC
                LIMIT ?
                """,
                (team_code, limit),
            ).fetchall()

        team_name = rows[0]["team_name"] if rows else fallback_name or team_code
        if not rows:
            return {
                "team_code": team_code,
                "team_name": team_name,
                "tracked_games": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "recent_form": "",
                "averages": {},
                "recent_games": [],
                "summary": f"{team_name} 目前还没有可复用的历史样本。",
            }

        wins = sum(int(row["win"]) for row in rows)
        tracked_games = len(rows)
        recent_games = [
            {
                "game_id": row["game_id"],
                "game_date": row["game_date"],
                "opponent_code": row["opponent_code"],
                "opponent_name": row["opponent_name"],
                "win": bool(row["win"]),
                "point_margin": int(row["point_margin"]),
                "points": int(row["points"]),
            }
            for row in rows
        ]
        averages = {
            "points": round(sum(int(row["points"]) for row in rows) / tracked_games, 1),
            "rebounds": round(sum(int(row["rebounds"]) for row in rows) / tracked_games, 1),
            "assists": round(sum(int(row["assists"]) for row in rows) / tracked_games, 1),
            "turnovers": round(sum(int(row["turnovers"]) for row in rows) / tracked_games, 1),
            "three_points_made": round(sum(int(row["three_points_made"]) for row in rows) / tracked_games, 1),
        }
        recent_form = "".join("W" if row["win"] else "L" for row in rows)
        return {
            "team_code": team_code,
            "team_name": team_name,
            "tracked_games": tracked_games,
            "wins": wins,
            "losses": tracked_games - wins,
            "win_rate": round(wins / tracked_games, 3),
            "recent_form": recent_form,
            "averages": averages,
            "recent_games": recent_games,
            "summary": (
                f"{team_name} 在已入库的最近 {tracked_games} 场里打出 "
                f"{wins} 胜 {tracked_games - wins} 负，场均 {averages['points']} 分。"
            ),
        }

    def head_to_head(
        self,
        home_code: str,
        away_code: str,
        home_name: str = "",
        away_name: str = "",
        limit: int = 6,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT game_id, game_date, team_name, opponent_name, win, point_margin, points
                FROM team_game_stats
                WHERE team_code = ? AND opponent_code = ?
                ORDER BY game_date DESC, game_id DESC
                LIMIT ?
                """,
                (home_code, away_code, limit),
            ).fetchall()

        if not rows:
            return {
                "home_team_code": home_code,
                "away_team_code": away_code,
                "tracked_games": 0,
                "home_wins": 0,
                "away_wins": 0,
                "average_margin": 0.0,
                "recent_results": [],
                "summary": f"{home_name or home_code} 和 {away_name or away_code} 还没有可复用的交手样本。",
            }

        recent_results = [
            {
                "game_id": row["game_id"],
                "game_date": row["game_date"],
                "home_win_view": bool(row["win"]),
                "point_margin": int(row["point_margin"]),
                "points": int(row["points"]),
            }
            for row in rows
        ]
        home_wins = sum(1 for row in rows if row["win"])
        tracked_games = len(rows)
        average_margin = round(sum(int(row["point_margin"]) for row in rows) / tracked_games, 1)
        home_team_name = rows[0]["team_name"] if rows else home_name or home_code
        away_team_name = rows[0]["opponent_name"] if rows else away_name or away_code
        return {
            "home_team_code": home_code,
            "away_team_code": away_code,
            "tracked_games": tracked_games,
            "home_wins": home_wins,
            "away_wins": tracked_games - home_wins,
            "average_margin": average_margin,
            "recent_results": recent_results,
            "summary": (
                f"{home_team_name} 和 {away_team_name} 已入库交手 {tracked_games} 场，"
                f"{home_team_name} 视角下 {home_wins} 胜 {tracked_games - home_wins} 负。"
            ),
        }

    def player_snapshot(self, player_name: str, team_code: str, fallback_team_name: str = "", limit: int = 8) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT game_id, game_date, team_name, points, rebounds, assists, steals, blocks,
                       field_goals_made, field_goals_attempted, three_points_made,
                       three_points_attempted, plus_minus
                FROM player_game_stats
                WHERE player_name = ? AND team_code = ?
                ORDER BY game_date DESC, game_id DESC
                LIMIT ?
                """,
                (player_name, team_code, limit),
            ).fetchall()

        team_name = rows[0]["team_name"] if rows else fallback_team_name or team_code
        if not rows:
            return {
                "player_name": player_name,
                "team_code": team_code,
                "team_name": team_name,
                "tracked_games": 0,
                "averages": {},
                "summary": f"{player_name} 目前还没有历史样本。",
            }

        tracked_games = len(rows)
        averages = {
            "points": round(sum(int(row["points"]) for row in rows) / tracked_games, 1),
            "rebounds": round(sum(int(row["rebounds"]) for row in rows) / tracked_games, 1),
            "assists": round(sum(int(row["assists"]) for row in rows) / tracked_games, 1),
            "steals": round(sum(int(row["steals"]) for row in rows) / tracked_games, 1),
            "blocks": round(sum(int(row["blocks"]) for row in rows) / tracked_games, 1),
        }
        latest = rows[0]
        return {
            "player_name": player_name,
            "team_code": team_code,
            "team_name": team_name,
            "tracked_games": tracked_games,
            "averages": averages,
            "latest_game": {
                "game_id": latest["game_id"],
                "game_date": latest["game_date"],
                "points": int(latest["points"]),
                "rebounds": int(latest["rebounds"]),
                "assists": int(latest["assists"]),
                "plus_minus": int(latest["plus_minus"]),
            },
            "summary": (
                f"{player_name} 在已入库的最近 {tracked_games} 场里场均 "
                f"{averages['points']} 分 {averages['rebounds']} 板 {averages['assists']} 助。"
            ),
        }

    def store_document(
        self,
        doc_id: str,
        sport: str,
        source_type: str,
        title: str,
        body: str,
        uri: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_documents (
                    doc_id, sport, source_type, title, body, uri, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    sport,
                    source_type,
                    title,
                    body,
                    uri,
                    json.dumps(
                        asdict(metadata) if hasattr(metadata, "__dataclass_fields__") else (metadata or {}),
                        ensure_ascii=False,
                    ),
                    _iso_now(),
                ),
            )

    def _insert_team_rows(self, conn: sqlite3.Connection, game: NBAPostgameData, season: str) -> None:
        rows = [
            (
                game.game_id,
                game.game_date,
                season,
                game.home_team.short_name,
                game.home_team.name,
                game.away_team.short_name,
                game.away_team.name,
                1,
                1 if game.home_team.score >= game.away_team.score else 0,
                game.home_team.stats.points,
                game.home_team.stats.rebounds,
                game.home_team.stats.assists,
                game.home_team.stats.turnovers,
                game.home_team.stats.three_points_made,
                game.home_team.stats.three_points_attempted,
                game.home_team.score - game.away_team.score,
            ),
            (
                game.game_id,
                game.game_date,
                season,
                game.away_team.short_name,
                game.away_team.name,
                game.home_team.short_name,
                game.home_team.name,
                0,
                1 if game.away_team.score >= game.home_team.score else 0,
                game.away_team.stats.points,
                game.away_team.stats.rebounds,
                game.away_team.stats.assists,
                game.away_team.stats.turnovers,
                game.away_team.stats.three_points_made,
                game.away_team.stats.three_points_attempted,
                game.away_team.score - game.home_team.score,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO team_game_stats (
                game_id, game_date, season, team_code, team_name, opponent_code, opponent_name,
                is_home, win, points, rebounds, assists, turnovers,
                three_points_made, three_points_attempted, point_margin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _insert_player_rows(self, conn: sqlite3.Connection, game: NBAPostgameData, season: str) -> None:
        rows = [
            (
                game.game_id,
                game.game_date,
                season,
                player.team,
                game.home_team.name if player.team == game.home_team.short_name else game.away_team.name,
                player.name,
                player.points,
                player.rebounds,
                player.assists,
                player.steals,
                player.blocks,
                player.field_goals_made,
                player.field_goals_attempted,
                player.three_points_made,
                player.three_points_attempted,
                player.plus_minus,
                player.summary,
            )
            for player in game.top_players
        ]
        conn.executemany(
            """
            INSERT INTO player_game_stats (
                game_id, game_date, season, team_code, team_name, player_name,
                points, rebounds, assists, steals, blocks,
                field_goals_made, field_goals_attempted,
                three_points_made, three_points_attempted,
                plus_minus, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
