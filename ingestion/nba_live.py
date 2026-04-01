from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from analysis.nba_postgame_rules import build_nba_postgame_analysis
from analysis.nba_postgame_rules import display_team_name
from config import OUTPUT_DIR
from storage.file_store import ensure_dir, timestamp_slug, write_json


SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
BOXSCORE_URL_TEMPLATE = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
REQUEST_HEADERS = {
    "User-Agent": "sports-content-agent/0.1",
    "Accept": "application/json",
}


def _http_get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_record(team_payload: dict[str, Any]) -> str:
    wins = team_payload.get("wins")
    losses = team_payload.get("losses")
    if wins is None or losses is None:
        return ""
    return f"{wins}-{losses}"


def _team_matches(team_payload: dict[str, Any], team_filter: str) -> bool:
    team_code = str(team_payload.get("teamTricode", ""))
    team_name = str(team_payload.get("teamName", ""))
    team_city = str(team_payload.get("teamCity", ""))
    haystacks = [
        team_code,
        team_name,
        team_city,
        f"{team_city} {team_name}".strip(),
        display_team_name(team_code, team_name),
    ]
    needle = team_filter.strip().lower()
    return any(needle and needle in item.lower() for item in haystacks if item)


def _pick_game(games: list[dict[str, Any]], team_filter: str | None) -> dict[str, Any]:
    finals = [game for game in games if int(game.get("gameStatus", 0) or 0) == 3]
    if not finals:
        raise RuntimeError("No final NBA games are available from today's NBA scoreboard feed yet.")

    if team_filter:
        for game in finals:
            if _team_matches(game.get("homeTeam", {}), team_filter) or _team_matches(
                game.get("awayTeam", {}), team_filter
            ):
                return game
        raise RuntimeError(f"No final NBA game matched the team filter: {team_filter}")

    finals.sort(key=lambda item: str(item.get("gameEt", "")))
    return finals[-1]


def _pick_top_players(boxscore_game: dict[str, Any]) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    for side_key in ("homeTeam", "awayTeam"):
        team_payload = boxscore_game.get(side_key, {})
        team_code = str(team_payload.get("teamTricode", "") or team_payload.get("teamName", ""))
        for player in team_payload.get("players", []):
            if not player.get("played"):
                continue
            stats = player.get("statistics", {})
            players.append(
                {
                    "name": str(player.get("name", player.get("nameI", ""))),
                    "team": team_code,
                    "points": _safe_int(stats.get("points")),
                    "rebounds": _safe_int(stats.get("reboundsTotal")),
                    "assists": _safe_int(stats.get("assists")),
                    "steals": _safe_int(stats.get("steals")),
                    "blocks": _safe_int(stats.get("blocks")),
                    "field_goals_made": _safe_int(stats.get("fieldGoalsMade")),
                    "field_goals_attempted": _safe_int(stats.get("fieldGoalsAttempted")),
                    "three_points_made": _safe_int(stats.get("threePointersMade")),
                    "three_points_attempted": _safe_int(stats.get("threePointersAttempted")),
                    "plus_minus": _safe_int(stats.get("plusMinusPoints")),
                    "summary": "",
                }
            )

    players.sort(
        key=lambda item: (
            item["points"],
            item["rebounds"] + item["assists"],
            item["steals"] + item["blocks"],
            item["plus_minus"],
        ),
        reverse=True,
    )
    return players[:3]


def _team_stat_summary(team_payload: dict[str, Any]) -> dict[str, int]:
    stats = team_payload.get("statistics", {})
    return {
        "points": _safe_int(team_payload.get("score")),
        "rebounds": _safe_int(stats.get("reboundsTotal")),
        "assists": _safe_int(stats.get("assists")),
        "turnovers": _safe_int(stats.get("turnovers")),
        "three_points_made": _safe_int(stats.get("threePointersMade")),
        "three_points_attempted": _safe_int(stats.get("threePointersAttempted")),
    }


def _build_game_flow(scoreboard_game: dict[str, Any], boxscore_game: dict[str, Any]) -> list[dict[str, str]]:
    flow: list[dict[str, str]] = []
    for side_key in ("awayTeam", "homeTeam"):
        team_payload = boxscore_game.get(side_key, {})
        periods = team_payload.get("periods", [])
        team_name = display_team_name(
            str(team_payload.get("teamTricode", "")),
            str(team_payload.get("teamName", side_key)),
        )
        period_lines = []
        for period in periods:
            period_no = period.get("period")
            score = period.get("score")
            if period_no is None or score is None:
                continue
            period_lines.append(f"第{period_no}节{score}分")
        if period_lines:
            flow.append({"quarter": f"{team_name}单节得分", "note": "，".join(period_lines)})

    home_team = boxscore_game.get("homeTeam", {})
    away_team = boxscore_game.get("awayTeam", {})
    home_score = _safe_int(home_team.get("score"))
    away_score = _safe_int(away_team.get("score"))
    winner = home_team if home_score >= away_score else away_team
    loser = away_team if winner is home_team else home_team
    winner_name = display_team_name(str(winner.get("teamTricode", "")), str(winner.get("teamName", "胜方")))
    loser_name = display_team_name(str(loser.get("teamTricode", "")), str(loser.get("teamName", "负方")))
    flow.append(
        {
            "quarter": "赛果",
            "note": f"{winner_name}以{max(home_score, away_score)}比{min(home_score, away_score)}击败{loser_name}，分差{abs(home_score - away_score)}分。",
        }
    )
    if scoreboard_game.get("gameStatusText"):
        flow.append({"quarter": "状态", "note": str(scoreboard_game["gameStatusText"])})
    return flow[:4]


def _normalize_postgame(scoreboard_game: dict[str, Any], boxscore_game: dict[str, Any]) -> dict[str, Any]:
    home_team = scoreboard_game.get("homeTeam", {})
    away_team = scoreboard_game.get("awayTeam", {})
    home_score = _safe_int(home_team.get("score"))
    away_score = _safe_int(away_team.get("score"))
    winner = home_team if home_score >= away_score else away_team

    home_short = str(home_team.get("teamTricode", ""))
    away_short = str(away_team.get("teamTricode", ""))

    normalized = {
        "league": "NBA",
        "game_id": str(scoreboard_game.get("gameId", "")),
        "game_date": str(scoreboard_game.get("gameEt", "")).split("T")[0] or datetime.now().strftime("%Y-%m-%d"),
        "status": "final",
        "venue": str(
            boxscore_game.get("arena", {}).get("arenaName")
            or scoreboard_game.get("arenaName", "")
            or "Unknown Arena"
        ),
        "source": "nba_live_official",
        "winner": display_team_name(str(winner.get("teamTricode", "")), str(winner.get("teamName", ""))),
        "home_team": {
            "name": display_team_name(home_short, str(home_team.get("teamName", ""))),
            "short_name": home_short,
            "score": home_score,
            "record": _format_record(home_team),
            "stats": _team_stat_summary(boxscore_game.get("homeTeam", {})),
        },
        "away_team": {
            "name": display_team_name(away_short, str(away_team.get("teamName", ""))),
            "short_name": away_short,
            "score": away_score,
            "record": _format_record(away_team),
            "stats": _team_stat_summary(boxscore_game.get("awayTeam", {})),
        },
        "top_players": _pick_top_players(boxscore_game),
        "game_flow": _build_game_flow(scoreboard_game, boxscore_game),
        "notable_context": [
            f"{display_team_name(away_short, away_short)} {away_score} - {home_score} {display_team_name(home_short, home_short)}",
            f"比赛状态：{scoreboard_game.get('gameStatusText', 'Final')}",
            f"比赛日期：{str(scoreboard_game.get('gameEt', '')).split('T')[0]}",
        ],
        "analysis": build_nba_postgame_analysis(boxscore_game),
    }
    return normalized


def fetch_today_nba_postgame_data(
    output_dir: str = OUTPUT_DIR,
    team_filter: str | None = None,
    save_input: bool = False,
) -> str:
    scoreboard_payload = _http_get_json(SCOREBOARD_URL)
    scoreboard = scoreboard_payload.get("scoreboard", {})
    games = scoreboard.get("games", [])
    game = _pick_game(games, team_filter)
    game_id = str(game.get("gameId", ""))
    if not game_id:
        raise RuntimeError("The NBA scoreboard feed did not return a usable gameId.")

    boxscore_payload = _http_get_json(BOXSCORE_URL_TEMPLATE.format(game_id=game_id))
    boxscore_game = boxscore_payload.get("game", {})
    if not boxscore_game:
        raise RuntimeError(f"The NBA boxscore feed returned no game payload for gameId {game_id}.")

    normalized = _normalize_postgame(game, boxscore_game)
    if not save_input:
        temp_dir = ensure_dir(Path(output_dir) / "nba_postgame" / "_fetched")
        path = temp_dir / "latest_input.json"
        write_json(path, normalized)
        return str(path)

    stamp = timestamp_slug()
    saved_dir = ensure_dir(Path(output_dir) / "nba_postgame" / stamp / "_input")
    path = saved_dir / f"nba_postgame_{game_id}.json"
    write_json(path, normalized)
    return str(path)
