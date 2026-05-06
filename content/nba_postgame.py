from __future__ import annotations

from dataclasses import asdict
from typing import Any

from analysis.nba_postgame_rules import display_team_name
from core.models import NBAPostgameData, PlayerPerformance


def _winner_team(game: NBAPostgameData):
    return game.home_team if game.home_team.score > game.away_team.score else game.away_team


def _loser_team(game: NBAPostgameData):
    return game.away_team if game.home_team.score > game.away_team.score else game.home_team


def _score_line(game: NBAPostgameData) -> str:
    away_name = display_team_name(game.away_team.short_name, game.away_team.name)
    home_name = display_team_name(game.home_team.short_name, game.home_team.name)
    return f"{away_name} {game.away_team.score} - {game.home_team.score} {home_name}"


def _winner_team_name(game: NBAPostgameData) -> str:
    team = _winner_team(game)
    return display_team_name(team.short_name, team.name)


def _loser_team_name(game: NBAPostgameData) -> str:
    team = _loser_team(game)
    return display_team_name(team.short_name, team.name)


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
    pieces = [f"{player.name} {player.points}分 {player.rebounds}板 {player.assists}助"]
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
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    drivers = []
    rebound_diff = winner.stats.rebounds - loser.stats.rebounds
    assist_diff = winner.stats.assists - loser.stats.assists
    turnover_diff = loser.stats.turnovers - winner.stats.turnovers
    three_diff = winner.stats.three_points_made - loser.stats.three_points_made
    margin = abs(winner.stats.points - loser.stats.points)
    if rebound_diff >= 8:
        drivers.append(f"篮板压制（{winner_name} {winner.stats.rebounds} vs {loser_name} {loser.stats.rebounds}）")
    if assist_diff >= 5:
        drivers.append(f"传导更流畅（助攻 {winner.stats.assists} vs {loser.stats.assists}）")
    if three_diff >= 4:
        drivers.append(f"外线命中率拉开差距（三分 {winner.stats.three_points_made} vs {loser.stats.three_points_made}）")
    if turnover_diff >= 3:
        drivers.append(f"失误控制更稳（{loser_name}多丢 {turnover_diff} 次球）")
    if not drivers:
        # Margin-aware fallback — still grounded in real data
        if margin <= 5:
            drivers.append(f"最后关头执行细节分出高下（分差仅 {margin} 分）")
        elif margin >= 20:
            drivers.append(f"差距在第三节前已经成形（终局分差 {margin} 分）")
        else:
            drivers.append(f"综合效率和关键回合执行（{winner_name}最终 +{margin} 分胜出）")
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
    first_line = (
        f"{winner_name}这场在篮板上赢了 {winner.stats.rebounds - loser.stats.rebounds} 个，先把比赛底盘拿住了。"
        if winner.stats.rebounds >= loser.stats.rebounds
        else f"{winner_name}这场篮板不占优，但终结效率和比赛控制做得更好。"
    )
    return [
        first_line,
        f"{winner_name}送出 {winner.stats.assists} 次助攻，回合里更愿意多传一步。",
        f"{loser_name}出现 {loser.stats.turnovers} 次失误，给了对手不少转换机会。",
    ]


def _tactical_points(game: NBAPostgameData) -> list[str]:
    analysis = getattr(game, "analysis", None)
    analysis_points = list(getattr(analysis, "tactical_observations", [])[:2]) if analysis else []
    if analysis_points and getattr(analysis, "primary_driver", ""):
        return analysis_points

    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    return [
        f"{winner_name}回合里更愿意多传一步，球能更顺地转到终结点。",
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
        f"{winner_name}这场赢球，你更认同“{driver}”，还是球星硬解？",
        f"{loser_name}这场最该复盘的是失误，还是防守轮转？",
        f"{winner_name}这种赢法放到更强的对手面前，还能不能继续成立？",
    ]


def _knowledge_lines(knowledge_context: dict[str, Any] | None, game: NBAPostgameData) -> list[str]:
    if not knowledge_context:
        return []

    lines = []
    home_snapshot = knowledge_context.get("home_team", {})
    away_snapshot = knowledge_context.get("away_team", {})
    head_to_head = knowledge_context.get("head_to_head", {})

    if home_snapshot.get("tracked_games"):
        lines.append(home_snapshot.get("summary", ""))
    if away_snapshot.get("tracked_games"):
        lines.append(away_snapshot.get("summary", ""))
    if head_to_head.get("tracked_games"):
        lines.append(head_to_head.get("summary", ""))

    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    if head_to_head.get("tracked_games", 0) >= 2:
        lines.append(f"{winner_name}和{loser_name}这组对位已经有可复用样本，适合继续做连续叙事。")

    return [line for line in lines if line][:3]


def _text_rag_lines(research_packet: dict[str, Any] | None) -> list[str]:
    if not research_packet:
        return []
    return [line for line in research_packet.get("text_evidence_lines", []) if line][:2]


def build_hupu_package(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any] | None = None,
    topic_recommendation: dict[str, Any] | None = None,
    research_packet: dict[str, Any] | None = None,
    editorial_lab: dict[str, Any] | None = None,
) -> dict[str, Any]:
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    score_line = _score_line(game)
    title = f"赛后复盘：{winner_name}击败{loser_name}，{score_line}"

    winning_team_code = _winner_team(game).short_name
    losing_team_code = _loser_team(game).short_name
    winner_star = _best_player(game.top_players, winning_team_code)
    loser_star = _best_player(game.top_players, losing_team_code)

    intro_parts = [_headline(game), f"{winner_name}最终赢了 {abs(game.home_team.score - game.away_team.score)} 分。"]
    if topic_recommendation and topic_recommendation.get("recommended_angle"):
        intro_parts.append(f"如果把这场放进选题池，最适合的切法是“{topic_recommendation['recommended_angle']}”。")
    if winner_star:
        intro_parts.append(f"最抢眼的球员还是 {winner_star.name}，{_short_player_call(winner_star)}。")
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
        body_lines.append(f"- 负方代表：{_player_line(loser_star)}")
    for extra_player in game.top_players[:3]:
        if winner_star and extra_player.name == winner_star.name:
            continue
        if loser_star and extra_player.name == loser_star.name:
            continue
        body_lines.append(f"- 补充表现：{_player_line(extra_player)}")
        break

    body_lines.extend(["", "比赛为什么会这样："])
    body_lines.extend([f"- {line}" for line in _tactical_points(game)])

    knowledge_lines = _knowledge_lines(knowledge_context, game)
    if knowledge_lines:
        body_lines.extend(["", "结构化事实背景："])
        body_lines.extend([f"- {line}" for line in knowledge_lines])

    text_rag_lines = _text_rag_lines(research_packet)
    if text_rag_lines:
        body_lines.extend(["", "文本证据参考："])
        body_lines.extend([f"- {line}" for line in text_rag_lines])

    controversy = (editorial_lab or {}).get("controversy_simulator", {})
    if controversy:
        body_lines.extend(["", "争议模拟器："])
        body_lines.append(f"- 主流观点：{controversy.get('mainstream_side', {}).get('claim', '')}")
        body_lines.extend([f"- 主流证据：{line}" for line in controversy.get("mainstream_side", {}).get("evidence", [])[:2]])
        body_lines.append(f"- 反方观点：{controversy.get('counter_side', {}).get('claim', '')}")
        body_lines.extend([f"- 反方证据：{line}" for line in controversy.get("counter_side", {}).get("evidence", [])[:2]])
        body_lines.append(f"- 最适合扔进评论区的问题：{controversy.get('flame_question', '')}")

    contrarian = (editorial_lab or {}).get("contrarian_finder", {})
    if contrarian:
        body_lines.extend(["", "反直觉角度："])
        body_lines.append(f"- {contrarian.get('claim', '')}")
        body_lines.extend([f"- {line}" for line in contrarian.get("evidence", [])[:2]])

    if game.game_flow:
        body_lines.extend(["", "比赛进程："])
        body_lines.extend([f"- {note.quarter}：{note.note}" for note in game.game_flow[:4]])

    if game.notable_context:
        body_lines.extend(["", "补充信息："])
        body_lines.extend([f"- {line}" for line in game.notable_context[:3]])

    if topic_recommendation:
        body_lines.extend(["", "为什么这场值得发："])
        body_lines.extend([f"- {line}" for line in topic_recommendation.get("why_selected", [])[:3]])

    follow_up = (editorial_lab or {}).get("follow_up_queue", {})
    if follow_up:
        body_lines.extend(["", "后续选题自动续写："])
        for item in follow_up.get("items", [])[:3]:
            body_lines.append(f"- {item.get('title')}：{item.get('watch')}。{item.get('why')}")

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


def _build_scene3_voiceover(game: NBAPostgameData, tactical_points: list[str]) -> str:
    """Build a game-specific Scene 3 voiceover grounded in actual match stats."""
    drivers = _derive_drivers(game)
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    margin = abs(game.home_team.score - game.away_team.score)

    # Lead sentence tailored to margin
    if margin <= 5:
        lead = f"这场球拖到最后才分胜负，{winner_name}在最关键的回合抓住了机会。"
    elif margin >= 20:
        lead = f"这场差距其实很早就出来了，{winner_name}把{loser_name}打到无还手之力。"
    else:
        lead = f"这场{winner_name}赢球不是靠手感，是靠{drivers[0]}。"

    # Add tactical context if available
    tactic_note = tactical_points[0] if tactical_points else f"{loser_name}进攻端始终找不到节奏。"
    return f"{lead} {tactic_note}"


def build_douyin_package(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any] | None = None,
    topic_recommendation: dict[str, Any] | None = None,
    research_packet: dict[str, Any] | None = None,
    editorial_lab: dict[str, Any] | None = None,
) -> dict[str, Any]:
    winner_name = _winner_team_name(game)
    loser_name = _loser_team_name(game)
    score_line = _score_line(game)
    winner_star = _best_player(game.top_players, _winner_team(game).short_name)
    winner_star_line = _short_player_call(winner_star) if winner_star else "核心球员站了出来"
    tactical_points = _tactical_points(game)
    discussion = _discussion_angles(game)
    takeaways = _takeaways(game)[:2]
    recommended_angle = topic_recommendation.get("recommended_angle", "") if topic_recommendation else ""
    knowledge_lines = _knowledge_lines(knowledge_context, game)
    text_rag_lines = _text_rag_lines(research_packet)

    hook = f"{winner_name}赢了，而且这场赢得很有内容。"
    if recommended_angle:
        hook = f"{winner_name}赢了，这场最适合从“{recommended_angle}”切进去。"

    persona_accounts = (editorial_lab or {}).get("persona_lab", {}).get("accounts", [])
    douyin_persona = next((item for item in persona_accounts if item.get("key") == "douyin_emotion"), None)
    if douyin_persona and douyin_persona.get("sample_opening"):
        hook = douyin_persona["sample_opening"]

    controversy = (editorial_lab or {}).get("controversy_simulator", {})
    contrarian = (editorial_lab or {}).get("contrarian_finder", {})
    discussion_modes = (editorial_lab or {}).get("discussion_modes", {})

    scenes = [
        {
            "scene": 1,
            "duration_seconds": 4,
            "visual": "比分牌快速出现，双方队名和最终比分直接上屏。",
            "voiceover": f"{hook} 最终比分，{score_line}。",
        },
        {
            "scene": 2,
            "duration_seconds": 6,
            "visual": "胜方核心数据卡叠加关键镜头。",
            "voiceover": f"先看最关键的人，{winner_star_line}，这就是这场最稳定的输出。",
        },
        {
            "scene": 3,
            "duration_seconds": 8,
            "visual": "战术板和攻防镜头切换，突出比赛转折。",
            "voiceover": _build_scene3_voiceover(game, tactical_points),
        },
        {
            "scene": 4,
            "duration_seconds": 6,
            "visual": "总结页加评论引导，字幕强化争议点。",
            "voiceover": controversy.get("flame_question") or ("看完这场，最值得聊的是：" + " ".join(discussion[:2])),
        },
    ]

    caption_parts = [f"{winner_name}拿下比赛，{score_line}。", " ".join(takeaways)]
    if knowledge_lines:
        caption_parts.append(knowledge_lines[0])
    if text_rag_lines:
        caption_parts.append(text_rag_lines[0])
    if contrarian:
        caption_parts.append(contrarian.get("claim", ""))
    if discussion_modes:
        caption_parts.append(discussion_modes.get("viral_conclusion", ""))
    caption_parts.append("你觉得这场真正的转折点是哪一段？")
    caption = " ".join(part for part in caption_parts if part)

    return {
        "platform": "douyin",
        "title": f"{winner_name}赛后30秒复盘",
        "caption": caption,
        "hashtags": ["#NBA", f"#{winner_name}", f"#{loser_name}", "#赛后复盘", "#篮球"],
        "short_video_script": scenes,
        "cover_text": f"{winner_name}赢球关键\n{score_line}",
        "structured_data": asdict(game),
    }
