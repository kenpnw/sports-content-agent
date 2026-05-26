from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from analysis.nba_postgame_rules import build_nba_postgame_analysis, display_team_name
from analysis.topic_engine import score_game_topic
from config import OUTPUT_DIR
from core.models import NBAPostgameData
from storage.file_store import ensure_dir, timestamp_slug, write_json
from storage.knowledge_store import FactStore


SCOREBOARD_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
BOXSCORE_URL_TEMPLATE = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
REQUEST_HEADERS = {
    # Pretend we're a real Chrome visitor coming from www.nba.com
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

# How many days back to scan when today has no finals
DEFAULT_LOOKBACK_DAYS = 7


def _http_get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"NBA official feed returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        reason_text = str(reason)
        if "handshake operation timed out" in reason_text or isinstance(reason, (TimeoutError, socket.timeout)):
            raise RuntimeError(
                "Unable to reach the NBA official feed from this machine because the TLS handshake timed out. "
                "This usually means the local network, proxy, firewall, or outbound HTTPS route to nba.com/cdn.nba.com "
                "is unstable or blocked. It is not the same as 'no games available'."
            ) from exc
        if "WinError 10055" in reason_text:
            raise RuntimeError(
                "Unable to reach the NBA official feed because Windows reported WinError 10055. "
                "That usually means the local network stack is under pressure, the socket queue is full, "
                "or a proxy/VPN/firewall is exhausting outbound connections. It is a local connectivity problem, "
                "not a broken NBA data schema."
            ) from exc
        raise RuntimeError(f"Unable to reach the NBA official feed: {reason_text}") from exc


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


def _cached_input_matches(payload: dict[str, Any], team_filter: str) -> bool:
    if not team_filter:
        return True
    needle = team_filter.strip().lower()
    haystacks = [
        str(payload.get("winner", "")),
        str(payload.get("game_id", "")),
        str(payload.get("home_team", {}).get("name", "")),
        str(payload.get("home_team", {}).get("short_name", "")),
        str(payload.get("away_team", {}).get("name", "")),
        str(payload.get("away_team", {}).get("short_name", "")),
    ]
    return any(needle and needle in item.lower() for item in haystacks if item)


def _pick_finals(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finals = [game for game in games if int(game.get("gameStatus", 0) or 0) == 3]
    if not finals:
        raise RuntimeError("No final NBA games are available from today's NBA scoreboard feed yet.")
    return finals


def _normalize_schedule_game(raw_game: dict[str, Any]) -> dict[str, Any]:
    """Convert a scheduleLeagueV2 game record into the same shape as todaysScoreboard games."""
    home = raw_game.get("homeTeam", {}) or {}
    away = raw_game.get("awayTeam", {}) or {}
    return {
        "gameId": str(raw_game.get("gameId", "")),
        "gameCode": raw_game.get("gameCode", ""),
        "gameStatus": int(raw_game.get("gameStatus", 0) or 0),
        "gameStatusText": raw_game.get("gameStatusText", ""),
        "gameEt": raw_game.get("gameDateTimeEst", "") or raw_game.get("gameDateTimeUTC", ""),
        "homeTeam": {
            "teamId": home.get("teamId"),
            "teamTricode": home.get("teamTricode", ""),
            "teamName": home.get("teamName", ""),
            "teamCity": home.get("teamCity", ""),
            "score": home.get("score", 0),
        },
        "awayTeam": {
            "teamId": away.get("teamId"),
            "teamTricode": away.get("teamTricode", ""),
            "teamName": away.get("teamName", ""),
            "teamCity": away.get("teamCity", ""),
            "score": away.get("score", 0),
        },
    }


def list_recent_finals(lookback_days: int = 30) -> list[dict[str, Any]]:
    """Lightweight list of finished games for UI display (no boxscore fetch).

    Returns list of dicts with: game_id, game_date, home_team, away_team,
    home_score, away_score, status_text, gameLabel (if available, e.g., 'WCF G3').
    Sorted by date descending (newest first).
    """
    payload = _http_get_json(SCHEDULE_URL)
    schedule = payload.get("leagueSchedule", {}) or {}
    game_dates = schedule.get("gameDates", []) or []

    today = datetime.now().date()
    cutoff = today - timedelta(days=lookback_days)

    rows: list[dict[str, Any]] = []
    for block in game_dates:
        date_str = str(block.get("gameDate", "")).split("T")[0]
        if not date_str:
            continue
        try:
            if "/" in date_str:
                parts = date_str.split(" ")[0].split("/")
                date_obj = datetime(int(parts[2]), int(parts[0]), int(parts[1])).date()
            else:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        if date_obj < cutoff or date_obj > today:
            continue
        for raw in block.get("games", []) or []:
            if int(raw.get("gameStatus", 0) or 0) != 3:
                continue  # only finals
            home = raw.get("homeTeam", {}) or {}
            away = raw.get("awayTeam", {}) or {}
            home_score = int(home.get("score", 0) or 0)
            away_score = int(away.get("score", 0) or 0)
            winner_tri = (
                home.get("teamTricode") if home_score > away_score
                else away.get("teamTricode") if away_score > home_score
                else ""
            )
            game_label = raw.get("gameLabel", "") or ""
            game_sublabel = raw.get("gameSubLabel", "") or ""
            rows.append({
                "game_id": str(raw.get("gameId", "")),
                "game_date": date_obj.isoformat(),
                "home_tricode": home.get("teamTricode", ""),
                "home_name": home.get("teamName", ""),
                "home_city": home.get("teamCity", ""),
                "home_score": home_score,
                "away_tricode": away.get("teamTricode", ""),
                "away_name": away.get("teamName", ""),
                "away_city": away.get("teamCity", ""),
                "away_score": away_score,
                "winner": winner_tri,
                "status_text": raw.get("gameStatusText", "Final"),
                "game_label": game_label,        # e.g., "West Conference Finals"
                "game_sublabel": game_sublabel,  # e.g., "Game 3"
                "is_playoff": bool(str(raw.get("gameId", "")).startswith("004")),
            })

    rows.sort(key=lambda r: (r["game_date"], r["game_id"]), reverse=True)
    return rows


def _scan_schedule_for_recent_finals(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Pull NBA's full season schedule and return Final games from the last N days.

    Returns games sorted by date (newest first). Each game has the same shape as
    items returned by `todaysScoreboard_00.json` so downstream code is identical.
    """
    payload = _http_get_json(SCHEDULE_URL)
    schedule = payload.get("leagueSchedule", {}) or {}
    game_dates = schedule.get("gameDates", []) or []

    today = datetime.now().date()
    cutoff = today - timedelta(days=lookback_days)

    candidates: list[tuple[str, dict[str, Any]]] = []
    for game_date_block in game_dates:
        date_str = str(game_date_block.get("gameDate", "")).split("T")[0]
        if not date_str:
            continue
        try:
            # NBA date format is "MM/DD/YYYY 00:00:00" usually
            if "/" in date_str:
                parts = date_str.split(" ")[0].split("/")
                date_obj = datetime(int(parts[2]), int(parts[0]), int(parts[1])).date()
            else:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        if date_obj < cutoff or date_obj > today:
            continue
        for raw_game in game_date_block.get("games", []) or []:
            if int(raw_game.get("gameStatus", 0) or 0) != 3:
                continue
            candidates.append((date_obj.isoformat(), _normalize_schedule_game(raw_game)))

    # newest first
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [g for _, g in candidates]


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
            period_lines.append(f"第{period_no}节 {score} 分")
        if period_lines:
            flow.append({"quarter": f"{team_name}单节得分", "note": "，".join(period_lines)})

    home_team = boxscore_game.get("homeTeam", {})
    away_team = boxscore_game.get("awayTeam", {})
    home_score = _safe_int(home_team.get("score"))
    away_score = _safe_int(away_team.get("score"))
    winner = home_team if home_score > away_score else away_team
    loser = away_team if winner is home_team else home_team
    winner_score = _safe_int(winner.get("score"))
    loser_score = _safe_int(loser.get("score"))
    winner_name = display_team_name(str(winner.get("teamTricode", "")), str(winner.get("teamName", "胜方")))
    loser_name = display_team_name(str(loser.get("teamTricode", "")), str(loser.get("teamName", "负方")))
    flow.append(
        {
            "quarter": "赛果",
            "note": f"{winner_name}以 {winner_score} 比 {loser_score} 击败{loser_name}，分差 {abs(winner_score - loser_score)} 分。",
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
    winner = home_team if home_score > away_score else away_team

    home_short = str(home_team.get("teamTricode", ""))
    away_short = str(away_team.get("teamTricode", ""))
    game_date = str(scoreboard_game.get("gameEt", "")).split("T")[0] or datetime.now().strftime("%Y-%m-%d")

    return {
        "league": "NBA",
        "game_id": str(scoreboard_game.get("gameId", "")),
        "game_date": game_date,
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
            f"比赛日期：{game_date}",
        ],
        "analysis": build_nba_postgame_analysis(boxscore_game),
    }


def _build_candidate(
    scoreboard_game: dict[str, Any],
    boxscore_game: dict[str, Any],
    fact_store: FactStore,
) -> dict[str, Any]:
    normalized = _normalize_postgame(scoreboard_game, boxscore_game)
    game = NBAPostgameData.from_dict(normalized)
    knowledge_context = fact_store.build_game_context(game)
    topic_engine = score_game_topic(game, knowledge_context)
    return {
        "game": game,
        "normalized": normalized,
        "knowledge_context": knowledge_context,
        "topic_engine": topic_engine,
    }


def _selection_report_from_candidate(
    candidate: dict[str, Any],
    strategy: str,
    candidate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    game = candidate["game"]
    topic_engine = candidate["topic_engine"]
    return {
        "strategy": strategy,
        "selected_game_id": game.game_id,
        "selected_game": {
            "winner": game.winner,
            "scoreline": f"{game.away_team.name} {game.away_team.score} - {game.home_team.score} {game.home_team.name}",
            "global_topic_score": topic_engine["global_topic_score"],
            "recommended_angle": topic_engine["recommended_angle"],
            "selected_tier": topic_engine["selected_tier"],
        },
        "why_selected": topic_engine["why_selected"],
        "candidates": candidate_rows,
    }


def _candidate_rows(candidate_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "game_id": item["game"].game_id,
            "matchup": f"{item['game'].away_team.name} vs {item['game'].home_team.name}",
            "scoreline": f"{item['game'].away_team.score} - {item['game'].home_team.score}",
            "global_topic_score": item["topic_engine"]["global_topic_score"],
            "hupu_topic_score": item["topic_engine"]["hupu_topic_score"],
            "douyin_topic_score": item["topic_engine"]["douyin_topic_score"],
            "recommended_angle": item["topic_engine"]["recommended_angle"],
        }
        for item in candidate_items
    ]


def _select_candidate(candidate_items: list[dict[str, Any]], team_filter: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_rows = sorted(_candidate_rows(candidate_items), key=lambda row: row["global_topic_score"], reverse=True)
    selected = max(
        candidate_items,
        key=lambda item: (
            item["topic_engine"]["global_topic_score"],
            item["topic_engine"]["douyin_topic_score"],
            item["topic_engine"]["hupu_topic_score"],
        ),
    )
    strategy = f"team_filter:{team_filter}" if team_filter else "topic_engine_best_of_day"
    selection = _selection_report_from_candidate(selected, strategy=strategy, candidate_rows=candidate_rows)
    return selected, selection


def _latest_cached_fetch(output_dir: str, team_filter: str | None, network_error: str) -> dict[str, Any] | None:
    candidates = sorted(
        Path(output_dir).joinpath("nba_postgame").rglob("nba_postgame_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None

    fact_store = FactStore()
    fact_store.initialize()
    fact_store.bootstrap_from_workspace()

    matched_candidates: list[dict[str, Any]] = []
    selected_path: Path | None = None
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _cached_input_matches(payload, team_filter or ""):
            continue
        game = NBAPostgameData.from_dict(payload)
        knowledge_context = fact_store.build_game_context(game)
        topic_engine = score_game_topic(game, knowledge_context)
        matched_candidates.append(
            {
                "game": game,
                "normalized": payload,
                "knowledge_context": knowledge_context,
                "topic_engine": topic_engine,
            }
        )
        if selected_path is None:
            selected_path = path

    if not matched_candidates or selected_path is None:
        return None

    selected, selection = _select_candidate(matched_candidates, team_filter=team_filter)
    selection["strategy"] = "cached_fallback"
    selection["fallback_reason"] = network_error
    selection["cached_input_path"] = str(selected_path)
    selection["cached_candidates_count"] = len(matched_candidates)

    return {
        "input_path": str(selected_path),
        "selection": selection,
        "source_mode": "cache_fallback",
    }


def fetch_today_nba_postgame_data(
    output_dir: str = OUTPUT_DIR,
    team_filter: str | None = None,
    save_input: bool = False,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    game_id: str | None = None,
) -> dict[str, Any]:
    try:
        finals: list[dict[str, Any]] = []

        if game_id:
            # Explicit game pick — scan the schedule with a wide window for that one game
            print(f"[nba_live] fetching specific game_id={game_id} via schedule…")
            all_recent = _scan_schedule_for_recent_finals(lookback_days=60)
            finals = [g for g in all_recent if str(g.get("gameId", "")) == str(game_id)]
            if not finals:
                raise RuntimeError(f"game_id={game_id} not found in recent schedule (60 days).")
        else:
            # Step 1: try today's live scoreboard (fast path)
            try:
                scoreboard_payload = _http_get_json(SCOREBOARD_URL)
                scoreboard = scoreboard_payload.get("scoreboard", {})
                finals = _pick_finals(scoreboard.get("games", []))
                print(f"[nba_live] found {len(finals)} final games in today's live scoreboard")
            except RuntimeError as exc:
                # Step 2: today has no finals, scan recent days via league schedule
                print(f"[nba_live] today has no finals ({exc}); scanning last {lookback_days} days via schedule…")
                finals = _scan_schedule_for_recent_finals(lookback_days=lookback_days)
                if not finals:
                    raise RuntimeError(
                        f"No final NBA games found today or in the past {lookback_days} days via the official feed."
                    )
                print(f"[nba_live] found {len(finals)} final games in the last {lookback_days} days")

        fact_store = FactStore()
        fact_store.initialize()
        fact_store.bootstrap_from_workspace()

        candidate_items: list[dict[str, Any]] = []
        for game in finals:
            if team_filter and not (
                _team_matches(game.get("homeTeam", {}), team_filter)
                or _team_matches(game.get("awayTeam", {}), team_filter)
            ):
                continue
            game_id = str(game.get("gameId", ""))
            if not game_id:
                continue
            boxscore_payload = _http_get_json(BOXSCORE_URL_TEMPLATE.format(game_id=game_id))
            boxscore_game = boxscore_payload.get("game", {})
            if not boxscore_game:
                print(f"[nba_live] WARNING: boxscore payload for game {game_id} returned no 'game' key — skipping.")
                continue
            candidate_items.append(_build_candidate(game, boxscore_game, fact_store))

        if not candidate_items:
            if team_filter:
                raise RuntimeError(f"No final NBA game matched the team filter: {team_filter}")
            raise RuntimeError("No usable final NBA games were returned from today's official feed.")

        selected, selection = _select_candidate(candidate_items, team_filter=team_filter)
        normalized = dict(selected["normalized"])
        normalized["selection"] = selection
        normalized["topic_engine"] = selected["topic_engine"]
        normalized["knowledge_context"] = selected["knowledge_context"]

        stamp = timestamp_slug() if save_input else "_fetched"
        target_dir = ensure_dir(Path(output_dir) / "nba_postgame" / stamp)
        if save_input:
            input_dir = ensure_dir(target_dir / "_input")
            path = input_dir / f"nba_postgame_{selected['game'].game_id}.json"
        else:
            path = target_dir / "latest_input.json"
        write_json(path, normalized)

        if save_input:
            write_json(target_dir / "selection.json", selection)
        else:
            write_json(target_dir / "latest_selection.json", selection)

        return {
            "input_path": str(path),
            "selection": selection,
            "source_mode": "live",
        }
    except RuntimeError as exc:
        cached = _latest_cached_fetch(output_dir=output_dir, team_filter=team_filter, network_error=str(exc))
        if cached:
            return cached
        raise
