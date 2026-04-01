from __future__ import annotations

from dataclasses import asdict

from core.models import NBAPostgameData, PlayerPerformance


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


def _display_team_name(short_name: str, fallback: str) -> str:
    return TEAM_NAME_MAP.get(short_name, fallback)


def _winner_team(game: NBAPostgameData):
    return game.home_team if game.home_team.score >= game.away_team.score else game.away_team


def _loser_team(game: NBAPostgameData):
    return game.away_team if game.home_team.score >= game.away_team.score else game.home_team


def _score_line(game: NBAPostgameData) -> str:
    away_name = _display_team_name(game.away_team.short_name, game.away_team.name)
    home_name = _display_team_name(game.home_team.short_name, game.home_team.name)
    return f"{away_name} {game.away_team.score} - {game.home_team.score} {home_name}"


def _winner_team_name(game: NBAPostgameData) -> str:
    team = _winner_team(game)
    return _display_team_name(team.short_name, team.name)


def _loser_team_name(game: NBAPostgameData) -> str:
    team = _loser_team(game)
    return _display_team_name(team.short_name, team.name)


def _best_player(players: list[PlayerPerformance], team: str | None = None) -> PlayerPerformance | None:
    filtered = [player for player in players if team is None or player.team == team]
    if not filtered:
        return None
    filtered.sort(
        key=lambda player: (
            player.points,
            player.rebounds + player.assists,
            player.steals + player.blocks,
            player.plus_minus,
        ),
        reverse=True,
    )
    return filtered[0]


def _player_line(player: PlayerPerformance) -> str:
    pieces = [f"{player.name} {player.points}分{player.rebounds}板{player.assists}助"]
    if player.steals:
        pieces.append(f"{player.steals}断")
    if player.blocks:
        pieces.append(f"{player.blocks}帽")
    if player.field_goals_attempted:
        pieces.append(f"投篮{player.field_goals_made}/{player.field_goals_attempted}")
    if player.three_points_attempted:
        pieces.append(f"三分{player.three_points_made}/{player.three_points_attempted}")
    if player.plus_minus:
        pieces.append(f"正负值{player.plus_minus:+d}")
    return "，".join(pieces)


def _short_player_call(player: PlayerPerformance) -> str:
    return f"{player.name}{player.points}分{player.rebounds}板{player.assists}助"


def _derive_drivers(game: NBAPostgameData) -> list[str]:
    winner = _winner_team(game)
    loser = _loser_team(game)
    drivers = []
    rebound_diff = winner.stats.rebounds - loser.stats.rebounds
    assist_diff = winner.stats.assists - loser.stats.assists
    turnover_diff = loser.stats.turnovers - winner.stats.turnovers
    three_diff = winner.stats.three_points_made - loser.stats.three_points_made
    if rebound_diff >= 8:
        drivers.append("篮板压制")
    if assist_diff >= 5:
        drivers.append("分享球更顺")
    if three_diff >= 4:
        drivers.append("外线火力更稳定")
    if turnover_diff >= 3:
        drivers.append("失误控制更稳")
    if not drivers:
        drivers.append("关键回合执行更干净")
    return drivers


def _headline(game: NBAPostgameData) -> str:
    analysis = getattr(game, "analysis", None)
    if analysis and getattr(analysis, "primary_driver", ""):
        primary = getattr(analysis, "primary_driver", "")
        secondary = getattr(analysis, "secondary_driver", "")
        if secondary:
            return f"{_winner_team_name(game)}拿下比赛，最硬的赢球逻辑就是{primary}，再加上{secondary}。"
        return f"{_winner_team_name(game)}拿下比赛，最硬的赢球逻辑就是{primary}。"

    drivers = _derive_drivers(game)
    if len(drivers) > 1:
        return f"{_winner_team_name(game)}拿下比赛，最硬的赢球逻辑就是{drivers[0]}，再加上{drivers[1]}。"
    return f"{_winner_team_name(game)}拿下比赛，最硬的赢球逻辑就是{drivers[0]}。"


def _takeaways(game: NBAPostgameData) -> list[str]:
    analysis = getattr(game, "analysis", None)
    analysis_takeaways = list(getattr(analysis, "key_takeaways", [])[:3]) if analysis else []
    if analysis_takeaways and getattr(analysis, "primary_driver", ""):
        return analysis_takeaways

    winner = _winner_team(game)
    loser = _loser_team(game)
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    return [
        f"{winner_name}这场在篮板上赢了{winner.stats.rebounds - loser.stats.rebounds}个，先把比赛基础盘拿住了。"
        if winner.stats.rebounds >= loser.stats.rebounds
        else f"{winner_name}这场篮板不占优，但终结效率和比赛控制做得更好。",
        f"{winner_name}送出{winner.stats.assists}次助攻，回合里更愿意多传一步。",
        f"{loser_name}出现{loser.stats.turnovers}次失误，给了对面不少转换机会。",
    ]


def _tactical_points(game: NBAPostgameData) -> list[str]:
    analysis = getattr(game, "analysis", None)
    analysis_points = list(getattr(analysis, "tactical_observations", [])[:2]) if analysis else []
    if analysis_points and getattr(analysis, "primary_driver", ""):
        return analysis_points

    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    return [
        f"{winner_name}回合里愿意多传一步，球能更顺地转到终结点。",
        f"{loser_name}一旦进攻停球，后续回合质量就会明显下降。",
    ]


def _discussion_angles(game: NBAPostgameData) -> list[str]:
    analysis = getattr(game, "analysis", None)
    analysis_angles = list(getattr(analysis, "trending_angles", [])[:3]) if analysis else []
    if analysis_angles and getattr(analysis, "primary_driver", ""):
        return analysis_angles

    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    driver = _derive_drivers(game)[0]
    return [
        f"{winner_name}这场赢球，你更认同{driver}，还是球星硬解？",
        f"{loser_name}这场最该复盘的是失误，还是防守轮转？",
        f"{winner_name}这种赢法放到更强的对手面前，还能不能继续成立？",
    ]


def build_hupu_package(game: NBAPostgameData) -> dict:
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    score_line = _score_line(game)
    title = f"赛后复盘：{winner_name}击败{loser_name}，{score_line}"

    winning_team_code = _winner_team(game).short_name
    losing_team_code = _loser_team(game).short_name
    winner_star = _best_player(game.top_players, winning_team_code)
    loser_star = _best_player(game.top_players, losing_team_code)

    intro_parts = [_headline(game), f"{winner_name}最终赢了{abs(game.home_team.score - game.away_team.score)}分。"]
    if winner_star:
        intro_parts.append(f"最抢眼的球员还是{winner_star.name}，{_short_player_call(winner_star)}。")
    intro = " ".join(intro_parts)

    body_lines = [
        title,
        "",
        intro,
        "",
        f"比赛地点：{game.venue}",
        f"最终比分：{score_line}",
        "",
        "先说结论：",
    ]
    body_lines.extend([f"- {line}" for line in _takeaways(game)])

    body_lines.extend(["", "关键球员："])
    if winner_star:
        body_lines.append(f"- 胜方核心：{_player_line(winner_star)}")
    if loser_star and (not winner_star or loser_star.name != winner_star.name):
        body_lines.append(f"- 败方代表：{_player_line(loser_star)}")
    for extra_player in game.top_players[:3]:
        if winner_star and extra_player.name == winner_star.name:
            continue
        if loser_star and extra_player.name == loser_star.name:
            continue
        body_lines.append(f"- 补充表现：{_player_line(extra_player)}")
        break

    body_lines.extend(["", "比赛为什么会这样："])
    body_lines.extend([f"- {line}" for line in _tactical_points(game)])

    if game.game_flow:
        body_lines.extend(["", "比赛进程："])
        body_lines.extend([f"- {note.quarter}：{note.note}" for note in game.game_flow[:4]])

    if game.notable_context:
        body_lines.extend(["", "背景信息："])
        body_lines.extend([f"- {line}" for line in game.notable_context[:3]])

    body_lines.extend(["", "评论区可以聊："])
    body_lines.extend([f"- {line}" for line in _discussion_angles(game)])

    return {
        "platform": "hupu",
        "title": title,
        "summary": intro,
        "tags": ["NBA", winner_name, loser_name, "赛后复盘"],
        "article_markdown": "\n".join(body_lines),
        "structured_data": asdict(game),
    }


def build_douyin_package(game: NBAPostgameData) -> dict:
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    score_line = _score_line(game)
    winner_star = _best_player(game.top_players, _winner_team(game).short_name)
    winner_star_line = _short_player_call(winner_star) if winner_star else "核心球员站了出来"
    tactical_points = _tactical_points(game)
    discussion = _discussion_angles(game)
    takeaways = _takeaways(game)[:2]

    scenes = [
        {
            "scene": 1,
            "duration_seconds": 4,
            "visual": "比分牌快速出现，双方队名和最终比分直接上屏",
            "voiceover": f"{winner_name}赢了，而且这场赢得很干脆。最终比分，{score_line}。",
        },
        {
            "scene": 2,
            "duration_seconds": 6,
            "visual": "胜方核心数据卡，叠加关键镜头",
            "voiceover": f"先看最关键的人，{winner_star_line}，这就是这场球最稳定的输出。",
        },
        {
            "scene": 3,
            "duration_seconds": 8,
            "visual": "战术板和攻防镜头切换，突出比赛转折",
            "voiceover": "这场球真正拉开，不只是手感问题。" + " ".join(tactical_points),
        },
        {
            "scene": 4,
            "duration_seconds": 6,
            "visual": "总结页加评论引导，字幕强化争议点",
            "voiceover": "所以这场球看完，最值得聊的是：" + " ".join(discussion[:2]),
        },
    ]

    caption = f"{winner_name}拿下比赛，{score_line}。{' '.join(takeaways)} 你觉得这场真正的转折点是哪一段？"

    return {
        "platform": "douyin",
        "title": f"{winner_name}赛后30秒复盘",
        "caption": caption,
        "hashtags": ["#NBA", f"#{winner_name}", f"#{loser_name}", "#赛后复盘", "#篮球"],
        "short_video_script": scenes,
        "cover_text": f"{winner_name}赢球关键\n{score_line}",
        "structured_data": asdict(game),
    }
