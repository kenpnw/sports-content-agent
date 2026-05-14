"""Fetch official NBA play-by-play and normalize it for replay simulation.

This module reads the public NBA CDN liveData play-by-play feed and writes the
small replay schema consumed by the existing `realtime` and `video_scout`
pipelines. It intentionally does not depend on unofficial scraping packages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PBP_URL_TEMPLATE = "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json"
SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
TODAY_SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
DEFAULT_OUTPUT_DIR = Path("data/replays")
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
}


def fetch_play_by_play(game_id: str) -> dict[str, Any]:
    """Fetch and normalize one NBA play-by-play feed."""
    _validate_game_id(game_id)
    raw_payload = _http_get_json(PBP_URL_TEMPLATE.format(game_id=game_id))
    actions = raw_payload.get("game", {}).get("actions", [])
    if not isinstance(actions, list):
        raise RuntimeError("NBA CDN PBP payload changed: expected game.actions list.")

    schedule_game = _find_schedule_game(game_id)
    normalized = _normalize_replay(game_id=game_id, actions=actions, schedule_game=schedule_game)
    if len(normalized["events"]) < 50:
        print("[warning] PBP 可能不完整：抓到的事件少于 50 条。", file=sys.stderr)
    return normalized


def list_recent_playoffs(days: int = 30) -> list[dict[str, Any]]:
    """Return recent playoff games from the NBA CDN schedule feed."""
    schedule = _http_get_json(SCHEDULE_URL)
    today = _current_nba_date()
    start_date = today - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    for game_date in schedule.get("leagueSchedule", {}).get("gameDates", []):
        parsed_date = _parse_schedule_date(str(game_date.get("gameDate", "")))
        if not parsed_date or parsed_date < start_date or parsed_date > today:
            continue
        for game in game_date.get("games", []):
            game_id = str(game.get("gameId", ""))
            if not game_id.startswith("004"):
                continue
            away = game.get("awayTeam", {})
            home = game.get("homeTeam", {})
            away_code = str(away.get("teamTricode", "") or "")
            home_code = str(home.get("teamTricode", "") or "")
            rows.append(
                {
                    "game_id": game_id,
                    "date": parsed_date.isoformat(),
                    "matchup": f"{away_code}@{home_code}".strip("@"),
                    "final_score": _format_score(away, home),
                    "status": str(game.get("gameStatusText", "")),
                }
            )
    rows.sort(key=lambda item: (item["date"], item["game_id"]))
    return rows


def save_replay(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_replay(
    *,
    game_id: str,
    actions: list[dict[str, Any]],
    schedule_game: dict[str, Any] | None,
) -> dict[str, Any]:
    teams = _team_context(schedule_game, actions)
    events = [_normalize_action(action) for action in actions if isinstance(action, dict)]
    return {
        "game_id": game_id,
        "home_team": teams["home_team"],
        "away_team": teams["away_team"],
        "home_team_full": teams["home_team_full"],
        "away_team_full": teams["away_team_full"],
        "events": events,
        "metadata": {
            "source": "nba_cdn_liveData_playbyplay",
            "event_count": len(events),
            "game_date": teams.get("game_date", ""),
            "game_code": teams.get("game_code", ""),
        },
    }


def _normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("actionType", ""))
    shot_value = _shot_value(action)
    return {
        "actionId": str(action.get("actionNumber", action.get("actionId", ""))),
        "period": _safe_int(action.get("period")),
        "clock": str(action.get("clock", "")),
        "description": str(action.get("description", "")),
        "scoreHome": _safe_int(action.get("scoreHome")),
        "scoreAway": _safe_int(action.get("scoreAway")),
        "playerNameI": str(action.get("playerNameI", "")),
        "actionType": action_type,
        "subType": _normalized_subtype(action),
        "shotResult": str(action.get("shotResult", "")),
        "shotValue": shot_value,
        "teamTricode": str(action.get("teamTricode", "")),
        "assistPlayerNameInitial": str(action.get("assistPlayerNameInitial", "")),
        "stealPlayerName": str(action.get("stealPlayerName", "")),
        "blockPlayerName": str(action.get("blockPlayerName", "")),
        "personId": _safe_int(action.get("personId")),
        "teamId": _safe_int(action.get("teamId")),
        "qualifiers": [str(item) for item in action.get("qualifiers", [])],
    }


def _normalized_subtype(action: dict[str, Any]) -> str:
    action_type = str(action.get("actionType", "")).lower()
    sub_type = str(action.get("subType", ""))
    if action_type == "3pt":
        return "3PT"
    if action_type == "freethrow":
        return "Free Throw"
    if action_type == "rebound":
        return "OffReb" if sub_type.lower().startswith("off") else "DefReb"
    return sub_type


def _shot_value(action: dict[str, Any]) -> int:
    action_type = str(action.get("actionType", "")).lower()
    if action_type == "3pt":
        return 3
    if action_type == "2pt":
        return 2
    if action_type == "freethrow":
        return 1
    return 0


def _team_context(schedule_game: dict[str, Any] | None, actions: list[dict[str, Any]]) -> dict[str, str]:
    if schedule_game:
        home = schedule_game.get("homeTeam", {})
        away = schedule_game.get("awayTeam", {})
        return {
            "home_team": str(home.get("teamTricode", "")),
            "away_team": str(away.get("teamTricode", "")),
            "home_team_full": _team_full_name(home),
            "away_team_full": _team_full_name(away),
            "game_date": _parse_schedule_date(str(schedule_game.get("_gameDate", ""))).isoformat()
            if schedule_game.get("_gameDate") and _parse_schedule_date(str(schedule_game.get("_gameDate", "")))
            else "",
            "game_code": str(schedule_game.get("gameCode", "")),
        }
    teams = sorted({str(action.get("teamTricode", "")) for action in actions if action.get("teamTricode")})
    away = teams[0] if teams else ""
    home = teams[1] if len(teams) > 1 else ""
    return {
        "home_team": home,
        "away_team": away,
        "home_team_full": home,
        "away_team_full": away,
        "game_date": "",
        "game_code": "",
    }


def _team_full_name(team: dict[str, Any]) -> str:
    city = str(team.get("teamCity", "") or "").strip()
    name = str(team.get("teamName", "") or "").strip()
    return f"{city} {name}".strip() or str(team.get("teamTricode", ""))


def _find_schedule_game(game_id: str) -> dict[str, Any] | None:
    try:
        schedule = _http_get_json(SCHEDULE_URL)
    except RuntimeError:
        return None
    for game_date in schedule.get("leagueSchedule", {}).get("gameDates", []):
        for game in game_date.get("games", []):
            if str(game.get("gameId", "")) == game_id:
                enriched = dict(game)
                enriched["_gameDate"] = str(game_date.get("gameDate", ""))
                return enriched
    return None


def _current_nba_date() -> date:
    try:
        scoreboard = _http_get_json(TODAY_SCOREBOARD_URL)
        value = str(scoreboard.get("scoreboard", {}).get("gameDate", ""))
        if value:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    return datetime.utcnow().date()


def _parse_schedule_date(value: str) -> date | None:
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19] if fmt.startswith("%m") else value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _format_score(away: dict[str, Any], home: dict[str, Any]) -> str:
    away_code = str(away.get("teamTricode", "") or "")
    home_code = str(home.get("teamTricode", "") or "")
    away_score = _safe_int(away.get("score"))
    home_score = _safe_int(home.get("score"))
    if not away_score and not home_score:
        return ""
    return f"{away_code} {away_score} - {home_score} {home_code}"


def _http_get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError("该 game_id 不存在或已下线。") from exc
        raise RuntimeError(f"NBA CDN 返回 HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法访问 NBA CDN: {getattr(exc, 'reason', exc)}") from exc


def _validate_game_id(game_id: str) -> None:
    if not re.fullmatch(r"\d{10}", str(game_id or "")):
        raise ValueError("game_id 格式错误：应为 10 位数字，例如 0042500221。")


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _print_recent_playoff_table(rows: list[dict[str, Any]]) -> None:
    print("game_id    | date       | matchup | final_score")
    print("-" * 58)
    for row in rows:
        print(
            f"{row['game_id']:<10} | {row['date']:<10} | "
            f"{row['matchup']:<7} | {row['final_score'] or row['status']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch official NBA CDN play-by-play.")
    parser.add_argument("--game-id", default="", help="NBA game id, e.g. 0042500221.")
    parser.add_argument("--list-recent-playoffs", action="store_true", help="List recent playoff games from schedule CDN.")
    parser.add_argument("--output", default="", help="Output replay JSON path.")
    parser.add_argument("--season-type", choices=["playoff", "regular"], default="playoff")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_recent_playoffs:
        _print_recent_playoff_table(list_recent_playoffs())
        return
    if not args.game_id:
        raise SystemExit("--game-id is required unless --list-recent-playoffs is used.")
    try:
        _validate_game_id(args.game_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.season_type == "playoff" and not str(args.game_id).startswith("004"):
        raise SystemExit("game_id 格式错误：playoff 比赛 game_id 应以 004 开头。")
    payload = fetch_play_by_play(args.game_id)
    output = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{args.game_id}.json"
    save_replay(output, payload)
    print(
        json.dumps(
            {
                "game_id": payload["game_id"],
                "matchup": f"{payload['away_team']}@{payload['home_team']}",
                "events": len(payload["events"]),
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
