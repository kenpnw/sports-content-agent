from __future__ import annotations

from typing import Any


TEAM_NAME_MAP = {
    "ATL": "老鹰",
    "BOS": "凯尔特人",
    "BKN": "篮网",
    "CHA": "黄蜂",
    "CHI": "公牛",
    "CLE": "骑士",
    "DAL": "独行侠",
    "DEN": "掘金",
    "DET": "活塞",
    "GSW": "勇士",
    "HOU": "火箭",
    "IND": "步行者",
    "LAC": "快船",
    "LAL": "湖人",
    "MEM": "灰熊",
    "MIA": "热火",
    "MIL": "雄鹿",
    "MIN": "森林狼",
    "NOP": "鹈鹕",
    "NYK": "尼克斯",
    "OKC": "雷霆",
    "ORL": "魔术",
    "PHI": "76人",
    "PHX": "太阳",
    "POR": "开拓者",
    "SAC": "国王",
    "SAS": "马刺",
    "TOR": "猛龙",
    "UTA": "爵士",
    "WAS": "奇才",
}


def display_team_name(short_name: str, fallback: str) -> str:
    return TEAM_NAME_MAP.get(short_name, fallback)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _team_stat_summary(team_payload: dict[str, Any]) -> dict[str, int]:
    stats = team_payload.get("statistics", {})
    return {
        "points": _safe_int(team_payload.get("score")),
        "rebounds": _safe_int(stats.get("reboundsTotal")),
        "assists": _safe_int(stats.get("assists")),
        "turnovers": _safe_int(stats.get("turnovers")),
        "three_points_made": _safe_int(stats.get("threePointersMade")),
        "three_points_attempted": _safe_int(stats.get("threePointersAttempted")),
        "second_chance_points": _safe_int(stats.get("pointsSecondChance")),
        "fast_break_points": _safe_int(stats.get("pointsFastBreak")),
        "points_in_paint": _safe_int(stats.get("pointsInThePaint")),
        "bench_points": _safe_int(stats.get("benchPoints")),
    }


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
                    "plus_minus": _safe_int(stats.get("plusMinusPoints")),
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
    return players


def build_nba_postgame_analysis(boxscore_game: dict[str, Any]) -> dict[str, Any]:
    home_team = boxscore_game.get("homeTeam", {})
    away_team = boxscore_game.get("awayTeam", {})
    home_score = _safe_int(home_team.get("score"))
    away_score = _safe_int(away_team.get("score"))
    winner_payload = home_team if home_score >= away_score else away_team
    loser_payload = away_team if winner_payload is home_team else home_team

    winner_stats = _team_stat_summary(winner_payload)
    loser_stats = _team_stat_summary(loser_payload)
    winner_name = display_team_name(
        str(winner_payload.get("teamTricode", "")),
        str(winner_payload.get("teamName", "胜方")),
    )
    loser_name = display_team_name(
        str(loser_payload.get("teamTricode", "")),
        str(loser_payload.get("teamName", "负方")),
    )

    top_players = _pick_top_players(boxscore_game)
    winner_code = str(winner_payload.get("teamTricode", ""))
    loser_code = str(loser_payload.get("teamTricode", ""))
    winner_star = next((player for player in top_players if player["team"] == winner_code), None)
    loser_star = next((player for player in top_players if player["team"] == loser_code), None)

    rebound_diff = winner_stats["rebounds"] - loser_stats["rebounds"]
    assist_diff = winner_stats["assists"] - loser_stats["assists"]
    turnover_diff = loser_stats["turnovers"] - winner_stats["turnovers"]
    three_diff = winner_stats["three_points_made"] - loser_stats["three_points_made"]
    bench_diff = winner_stats["bench_points"] - loser_stats["bench_points"]
    paint_diff = winner_stats["points_in_paint"] - loser_stats["points_in_paint"]
    second_chance_diff = winner_stats["second_chance_points"] - loser_stats["second_chance_points"]

    drivers: list[dict[str, str | int]] = []
    if rebound_diff >= 8:
        drivers.append({"type": "rebounding", "label": "篮板压制", "value": rebound_diff})
    if assist_diff >= 5:
        drivers.append({"type": "ball_movement", "label": "分享球更顺", "value": assist_diff})
    if three_diff >= 4:
        drivers.append({"type": "three_point_volume", "label": "外线火力拉开差距", "value": three_diff})
    if turnover_diff >= 3:
        drivers.append({"type": "turnover_control", "label": "失误控制更稳", "value": turnover_diff})
    if bench_diff >= 8:
        drivers.append({"type": "bench_support", "label": "替补火力顶住了比赛", "value": bench_diff})
    if paint_diff >= 10:
        drivers.append({"type": "paint_pressure", "label": "禁区冲击更强", "value": paint_diff})
    if second_chance_diff >= 5:
        drivers.append({"type": "second_chance", "label": "二次进攻更狠", "value": second_chance_diff})
    if winner_star and winner_star["points"] >= 28:
        drivers.append({"type": "star_takeover", "label": f"{winner_star['name']}接管比赛", "value": winner_star["points"]})
    if not drivers:
        drivers.append({"type": "execution", "label": "关键回合执行更干净", "value": 1})

    primary = drivers[0]
    secondary = drivers[1] if len(drivers) > 1 else None
    reason_labels = [item["label"] for item in drivers[:3]]

    headline = f"{winner_name}拿下比赛，最硬的赢球逻辑就是{reason_labels[0]}"
    if secondary:
        headline += f"，再加上{secondary['label']}。"
    else:
        headline += "。"

    key_takeaways = [f"{winner_name}这场最直观的优势就是{primary['label']}。"]
    if secondary:
        key_takeaways.append(f"第二个明显差别在于{secondary['label']}。")
    if winner_star:
        key_takeaways.append(
            f"{winner_star['name']}交出{winner_star['points']}分{winner_star['rebounds']}板{winner_star['assists']}助，是这场最稳定的核心输出。"
        )
    elif loser_star:
        key_takeaways.append(
            f"{loser_name}虽然有{loser_star['name']}苦撑场面，但整体内容还是没能翻过来。"
        )

    tactical_observations = []
    if rebound_diff >= 8:
        tactical_observations.append(f"{winner_name}先把身体对抗和篮板球拿住了，比赛底盘自然就偏向他们。")
    if assist_diff >= 5:
        tactical_observations.append(f"{winner_name}回合里更愿意多传一步，球能更顺地转到终结点，这就是助攻差出来的原因。")
    if three_diff >= 4:
        tactical_observations.append(f"{loser_name}没能及时限制外线，比分一旦被三分球拉开，追分难度就会明显抬升。")
    if turnover_diff >= 3:
        tactical_observations.append(f"{loser_name}失误一多，转换和节奏都交出去，比赛很容易被对面一波带走。")
    if not tactical_observations:
        tactical_observations.append(f"{winner_name}在关键回合的执行更稳定，比分接近时没有给{loser_name}反扑窗口。")
    tactical_observations = tactical_observations[:2]

    discussion_angles = [
        f"{winner_name}这场赢球，你更认同{reason_labels[0]}，还是球星硬解？",
        f"{loser_name}这场最该复盘的是防守轮转，还是进攻处理球？",
        f"{winner_name}这种赢法放到更强的对手面前，还能不能继续成立？",
    ]

    return {
        "headline": headline,
        "primary_driver": primary["label"],
        "secondary_driver": secondary["label"] if secondary else "",
        "key_takeaways": key_takeaways,
        "tactical_observations": tactical_observations,
        "trending_angles": discussion_angles,
        "driver_details": drivers,
    }
