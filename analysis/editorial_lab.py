from __future__ import annotations

from typing import Any

from analysis.nba_postgame_rules import display_team_name
from core.models import NBAPostgameData, PlayerPerformance


POPULAR_TEAM_CODES = {"LAL", "GSW", "BOS", "NYK", "PHI", "MIA", "DAL", "PHX", "MIL"}


def _winner_team(game: NBAPostgameData):
    return game.home_team if game.home_team.score >= game.away_team.score else game.away_team


def _loser_team(game: NBAPostgameData):
    return game.away_team if game.home_team.score >= game.away_team.score else game.home_team


def _winner_name(game: NBAPostgameData) -> str:
    team = _winner_team(game)
    return display_team_name(team.short_name, team.name)


def _loser_name(game: NBAPostgameData) -> str:
    team = _loser_team(game)
    return display_team_name(team.short_name, team.name)


def _scoreline(game: NBAPostgameData) -> str:
    away_name = display_team_name(game.away_team.short_name, game.away_team.name)
    home_name = display_team_name(game.home_team.short_name, game.home_team.name)
    return f"{away_name} {game.away_team.score} - {game.home_team.score} {home_name}"


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


def _streak_from_form(value: str) -> tuple[str, int]:
    if not value:
        return "", 0
    target = value[0]
    count = 0
    for item in value:
        if item != target:
            break
        count += 1
    return target, count


def _safe_average(snapshot: dict[str, Any], field: str) -> float:
    averages = snapshot.get("averages", {})
    value = averages.get(field, 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stat_diffs(game: NBAPostgameData) -> dict[str, int]:
    winner = _winner_team(game)
    loser = _loser_team(game)
    return {
        "margin": abs(game.home_team.score - game.away_team.score),
        "rebounds": winner.stats.rebounds - loser.stats.rebounds,
        "assists": winner.stats.assists - loser.stats.assists,
        "turnovers": loser.stats.turnovers - winner.stats.turnovers,
        "threes": winner.stats.three_points_made - loser.stats.three_points_made,
        "winner_rebounds": winner.stats.rebounds,
        "loser_rebounds": loser.stats.rebounds,
        "winner_assists": winner.stats.assists,
        "loser_assists": loser.stats.assists,
        "winner_turnovers": winner.stats.turnovers,
        "loser_turnovers": loser.stats.turnovers,
        "winner_threes": winner.stats.three_points_made,
        "loser_threes": loser.stats.three_points_made,
    }


def _publish_call(score: float) -> str:
    if score >= 80:
        return "must_publish"
    if score >= 65:
        return "recommended"
    if score >= 50:
        return "backup"
    return "skip"


def _heat_badge(score: float) -> str:
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    return "C"


def _best_platform(hupu_score: float, douyin_score: float) -> str:
    return "hupu" if hupu_score >= douyin_score else "douyin"


def _platform_label(code: str) -> str:
    labels = {
        "hupu": "虎扑",
        "douyin": "抖音",
        "wechat": "深度号",
        "data_lab": "数据号",
    }
    return labels.get(code, code)


def _opportunity_board(
    game: NBAPostgameData,
    topic_recommendation: dict[str, Any],
    selection_context: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = list((selection_context or {}).get("candidates", []))
    if not candidates:
        candidates = [
            {
                "game_id": game.game_id,
                "matchup": f"{game.away_team.name} vs {game.home_team.name}",
                "scoreline": f"{game.away_team.score} - {game.home_team.score}",
                "global_topic_score": topic_recommendation.get("global_topic_score", 0),
                "hupu_topic_score": topic_recommendation.get("hupu_topic_score", 0),
                "douyin_topic_score": topic_recommendation.get("douyin_topic_score", 0),
                "recommended_angle": topic_recommendation.get("recommended_angle", ""),
                "selected_tier": topic_recommendation.get("selected_tier", "recommended"),
            }
        ]

    ranked = sorted(candidates, key=lambda item: item.get("global_topic_score", 0), reverse=True)
    rows = []
    for index, item in enumerate(ranked, start=1):
        hupu_score = float(item.get("hupu_topic_score", 0))
        douyin_score = float(item.get("douyin_topic_score", 0))
        best_platform = _best_platform(hupu_score, douyin_score)
        global_score = float(item.get("global_topic_score", 0))
        rows.append(
            {
                "rank": index,
                "game_id": item.get("game_id", ""),
                "matchup": item.get("matchup", ""),
                "scoreline": item.get("scoreline", ""),
                "global_topic_score": global_score,
                "recommended_angle": item.get("recommended_angle", ""),
                "best_platform": best_platform,
                "best_platform_label": _platform_label(best_platform),
                "publish_call": item.get("selected_tier") or _publish_call(global_score),
                "heat_badge": _heat_badge(global_score),
                "is_selected": item.get("game_id") == game.game_id,
            }
        )

    top_row = rows[0]
    sequencing = (
        f"先发{top_row['best_platform_label']}，"
        f"再把同一场比赛切成{_platform_label('douyin' if top_row['best_platform'] == 'hupu' else 'hupu')}版本。"
    )
    summary = (
        f"今天的榜首是 {top_row['matchup']}，总分 {top_row['global_topic_score']:.1f}。"
        f" 推荐切法是“{top_row['recommended_angle']}”。"
    )
    return {
        "headline": "今日比赛机会榜",
        "summary": summary,
        "sequencing": sequencing,
        "entries": rows[:6],
    }


def _identity_tags(snapshot: dict[str, Any]) -> list[str]:
    assists = _safe_average(snapshot, "assists")
    rebounds = _safe_average(snapshot, "rebounds")
    threes = _safe_average(snapshot, "three_points_made")
    turnovers = _safe_average(snapshot, "turnovers")
    tags: list[str] = []
    if rebounds >= 45:
        tags.append("篮板底盘")
    if assists >= 26:
        tags.append("分享球体系")
    if threes >= 14:
        tags.append("外线产量")
    if turnovers and turnovers <= 12:
        tags.append("控失误")
    if not tags:
        if rebounds >= assists and rebounds >= threes:
            tags.append("身体对抗")
        elif assists >= threes:
            tags.append("回合梳理")
        else:
            tags.append("投射拉开")
    return tags


def _dna_report(game: NBAPostgameData, knowledge_context: dict[str, Any]) -> dict[str, Any]:
    winner = _winner_team(game)
    loser = _loser_team(game)
    winner_snapshot = knowledge_context["home_team"] if winner.short_name == game.home_team.short_name else knowledge_context["away_team"]
    loser_snapshot = knowledge_context["away_team"] if loser.short_name == game.away_team.short_name else knowledge_context["home_team"]
    diffs = _stat_diffs(game)

    winner_tags = _identity_tags(winner_snapshot)
    loser_tags = _identity_tags(loser_snapshot)
    primary_driver = game.analysis.primary_driver or "关键回合执行"

    winner_alignment = "延续球队 DNA"
    if "篮板" in primary_driver and "篮板底盘" not in winner_tags:
        winner_alignment = "本场把不常见的篮板线临时放大了"
    elif "分享球" in primary_driver and "分享球体系" not in winner_tags:
        winner_alignment = "这场更多是临场把球转顺了"
    elif "外线" in primary_driver and "外线产量" not in winner_tags:
        winner_alignment = "这场外线手感高于平时"

    loser_fault = "体系没有撑住"
    if diffs["turnovers"] >= 3:
        loser_fault = f"失误多了 {diffs['turnovers']} 次，先把自己节奏送掉了"
    elif diffs["rebounds"] >= 8:
        loser_fault = f"篮板输了 {diffs['rebounds']} 个，比赛底盘被拿走了"
    elif diffs["threes"] >= 4:
        loser_fault = f"外线差了 {diffs['threes']} 记，比分很难咬住"

    return {
        "winner_team": _winner_name(game),
        "loser_team": _loser_name(game),
        "winner_tags": winner_tags,
        "loser_tags": loser_tags,
        "winner_alignment": winner_alignment,
        "loser_faultline": loser_fault,
        "winner_summary": (
            f"{_winner_name(game)}平时更像一支靠{' / '.join(winner_tags)}维持比赛结构的球队，"
            f"这场的赢球主线是“{primary_driver}”。"
        ),
        "loser_summary": (
            f"{_loser_name(game)}的常规画像偏向{' / '.join(loser_tags)}，"
            f"但这场暴露出来的是：{loser_fault}。"
        ),
    }


def _player_storylines(game: NBAPostgameData, knowledge_context: dict[str, Any]) -> list[dict[str, Any]]:
    stories: list[dict[str, Any]] = []
    for player in game.top_players[:3]:
        snapshot = next(
            (
                item
                for item in knowledge_context.get("top_players", [])
                if item.get("player_name") == player.name and item.get("team_code") == player.team
            ),
            {},
        )
        avg_points = _safe_average(snapshot, "points")
        delta = round(player.points - avg_points, 1) if avg_points else 0.0
        if avg_points:
            if delta >= 6:
                angle = "明显高于近期基线"
            elif delta <= -6:
                angle = "明显低于近期基线"
            else:
                angle = "基本贴着近期基线"
        else:
            angle = "当前样本还不足，先记成第一条剧情线"
        stories.append(
            {
                "player_name": player.name,
                "summary": (
                    f"{player.name}这场拿了 {player.points} 分 {player.rebounds} 板 {player.assists} 助，"
                    f"{angle}。"
                ),
            }
        )
    return stories


def _season_storyline_tree(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any],
    dna_report: dict[str, Any],
) -> dict[str, Any]:
    winner_snapshot = knowledge_context["home_team"] if _winner_team(game).short_name == game.home_team.short_name else knowledge_context["away_team"]
    loser_snapshot = knowledge_context["away_team"] if _loser_team(game).short_name == game.away_team.short_name else knowledge_context["home_team"]
    head_to_head = knowledge_context.get("head_to_head", {})
    winner_streak_type, winner_streak_len = _streak_from_form(str(winner_snapshot.get("recent_form", "")))
    loser_streak_type, loser_streak_len = _streak_from_form(str(loser_snapshot.get("recent_form", "")))

    streak_lines = []
    if winner_streak_len >= 2:
        streak_lines.append(
            f"{_winner_name(game)}当前带着 {winner_streak_len} 场{'连胜' if winner_streak_type == 'W' else '连败'}背景继续往前走。"
        )
    if loser_streak_len >= 2:
        streak_lines.append(
            f"{_loser_name(game)}已经连续 {loser_streak_len} 场{'赢球' if loser_streak_type == 'W' else '输球'}，负面走势还没止住。"
        )
    if not streak_lines:
        streak_lines.append("这场更像单场剧情节点，连续走势还没被完全拉开。")

    revenge_line = "双方目前更像普通样本累积，还不到强复仇线。"
    recent_results = head_to_head.get("recent_results", [])
    if len(recent_results) >= 2:
        current_home_win = bool(recent_results[0].get("home_win_view"))
        previous_home_win = bool(recent_results[1].get("home_win_view"))
        if current_home_win != previous_home_win:
            revenge_line = "这组对位刚完成一次叙事反转，复仇线可以继续追。"
        else:
            revenge_line = "这组对位暂时还是同一方在延续压制。"

    branches = [
        {
            "label": "球队当前叙事线",
            "items": [
                winner_snapshot.get("summary", f"{_winner_name(game)}当前没有足够历史样本。"),
                loser_snapshot.get("summary", f"{_loser_name(game)}当前没有足够历史样本。"),
            ],
        },
        {
            "label": "球员状态线",
            "items": [item["summary"] for item in _player_storylines(game, knowledge_context)],
        },
        {
            "label": "连胜 / 连败线",
            "items": streak_lines,
        },
        {
            "label": "复仇 / 对位线",
            "items": [head_to_head.get("summary", "暂无足够交手样本。"), revenge_line],
        },
        {
            "label": "体系问题线",
            "items": [dna_report["winner_summary"], dna_report["loser_summary"]],
        },
    ]

    root = f"{_winner_name(game)}击败{_loser_name(game)}"
    mermaid_lines = [f'graph TD', f'A["{root}"]']
    node_index = 0
    for branch in branches:
        node_index += 1
        branch_id = f"B{node_index}"
        mermaid_lines.append(f'{branch_id}["{branch["label"]}"]')
        mermaid_lines.append(f"A --> {branch_id}")
        for item_index, item in enumerate(branch["items"], start=1):
            leaf_id = f"{branch_id}_{item_index}"
            safe_text = item.replace('"', "'")
            mermaid_lines.append(f'{leaf_id}["{safe_text}"]')
            mermaid_lines.append(f"{branch_id} --> {leaf_id}")

    return {
        "root": root,
        "branches": branches,
        "mermaid": "\n".join(mermaid_lines),
    }


def _contrarian_angle(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any],
    dna_report: dict[str, Any],
) -> dict[str, Any]:
    diffs = _stat_diffs(game)
    winner_name = _winner_name(game)
    loser_name = _loser_name(game)
    primary_driver = game.analysis.primary_driver or ""

    claim = f"真正决定比赛的不是球星热度，而是{winner_name}把比赛底盘先抢走了。"
    evidence = [
        f"篮板差 {diffs['rebounds']}，{winner_name}先把二次回合和身体对抗拿住了。",
        dna_report["winner_summary"],
    ]
    why_unexpected = "大众更容易先盯着球星得分，但这场更深的决定因素在回合结构。"

    if diffs["turnovers"] >= 4 and "失误" not in primary_driver:
        claim = f"别只夸{winner_name}，这场真正把比赛送走的是{loser_name}自己的失误链。"
        evidence = [
            f"{loser_name}出现 {diffs['loser_turnovers']} 次失误，净多送出 {diffs['turnovers']} 个回合。",
            f"一旦节奏被断，{loser_name}很难把比赛重新接回自己的舒适区。",
        ]
        why_unexpected = "多数赛后稿会先写赢球方表现，但输球方的回合崩塌才是更尖锐的话题。"
    elif diffs["threes"] >= 5 and "外线" not in primary_driver:
        claim = f"看起来是常规赢球，其实决定比赛的是{winner_name}外线把空间彻底拉开了。"
        evidence = [
            f"三分命中差 {diffs['threes']}，{winner_name}外线产量明显更高。",
            "外线一旦把比分差抻开，后面的追分成本会陡增。",
        ]
        why_unexpected = "比分表面看着平稳，但空间质量已经先把比赛倾斜了。"

    return {
        "claim": claim,
        "why_unexpected": why_unexpected,
        "evidence": evidence,
    }


def _controversy_simulator(
    game: NBAPostgameData,
    topic_recommendation: dict[str, Any],
    contrarian_angle: dict[str, Any],
) -> dict[str, Any]:
    winner_name = _winner_name(game)
    loser_name = _loser_name(game)
    diffs = _stat_diffs(game)
    primary_driver = game.analysis.primary_driver or "赢球逻辑"
    winner_star = _best_player(game.top_players, _winner_team(game).short_name)

    mainstream_claim = f"{winner_name}这场最该被夸的，就是{primary_driver}。"
    mainstream_evidence = [
        f"推荐角度已经明确给到“{topic_recommendation.get('recommended_angle', primary_driver)}”。",
        f"比分结果是 {_scoreline(game)}，赢球结论本身成立。",
        f"核心数据差里最扎眼的是：篮板 {diffs['rebounds']} / 助攻 {diffs['assists']} / 三分 {diffs['threes']}。",
    ]
    if winner_star:
        mainstream_evidence.append(f"{winner_star.name}交出 {winner_star.points} 分 {winner_star.rebounds} 板 {winner_star.assists} 助。")

    counter_claim = contrarian_angle["claim"]
    counter_evidence = list(contrarian_angle["evidence"])
    flame_question = f"这场到底该吹{winner_name}打得好，还是该喷{loser_name}自己先崩了？"
    if winner_star:
        flame_question = f"这场你会把头功给{winner_star.name}，还是给{primary_driver}这条团队线？"

    return {
        "title": "争议模拟器",
        "mainstream_side": {
            "label": "主流观点",
            "claim": mainstream_claim,
            "evidence": mainstream_evidence,
        },
        "counter_side": {
            "label": "反方观点",
            "claim": counter_claim,
            "evidence": counter_evidence,
        },
        "flame_question": flame_question,
        "high_engagement_take": f"更容易高赞的切法是：{contrarian_angle['claim']}",
    }


def _persona_lab(
    game: NBAPostgameData,
    topic_recommendation: dict[str, Any],
    controversy: dict[str, Any],
    contrarian_angle: dict[str, Any],
) -> dict[str, Any]:
    winner_name = _winner_name(game)
    loser_name = _loser_name(game)
    recommended_angle = topic_recommendation.get("recommended_angle", game.analysis.primary_driver or "赢球逻辑")
    scoreline = _scoreline(game)

    accounts = [
        {
            "key": "hupu_discussion",
            "label": "虎扑号",
            "voice": "嘴硬、先下判断、结尾抛问题",
            "sample_title": f"这场别只看比分，{winner_name}真正赢在“{recommended_angle}”",
            "sample_opening": controversy["counter_side"]["claim"],
        },
        {
            "key": "douyin_emotion",
            "label": "抖音号",
            "voice": "强 hook、短句、情绪先行",
            "sample_title": f"{winner_name}这场不是普通赢球",
            "sample_opening": f"先别急着吹球星，{scoreline}背后真正扎心的是：{contrarian_angle['claim']}",
        },
        {
            "key": "deep_column",
            "label": "深度号",
            "voice": "更像专栏编辑，强调赛季叙事",
            "sample_title": f"{winner_name}这场，是赛季剧情线继续往前走的一集",
            "sample_opening": f"如果把这场放回赛季叙事，它不是单场结果，而是“{recommended_angle}”这条线继续成立。",
        },
        {
            "key": "data_analyst",
            "label": "数据号",
            "voice": "去情绪化，直接摆结构差",
            "sample_title": f"{winner_name} vs {loser_name}：别吵，先看结构差",
            "sample_opening": f"数据结论先放这：篮板差、助攻差、失误差已经足够解释这场球的大部分结果。",
        },
    ]

    experiments = [
        {
            "platform": "虎扑",
            "angle": controversy["counter_side"]["claim"],
            "goal": "制造讨论和回帖量",
        },
        {
            "platform": "抖音",
            "angle": contrarian_angle["claim"],
            "goal": "把前 3 秒 hook 做得更狠",
        },
        {
            "platform": "深度号",
            "angle": topic_recommendation.get("recommended_angle", ""),
            "goal": "把单场写成连续叙事",
        },
        {
            "platform": "数据号",
            "angle": "结构差先于情绪判断",
            "goal": "降低模板味，强化可信度",
        },
    ]

    return {
        "accounts": accounts,
        "experiments": experiments,
    }


def _comment_forecast(
    game: NBAPostgameData,
    controversy: dict[str, Any],
    contrarian_angle: dict[str, Any],
) -> dict[str, Any]:
    winner = _winner_team(game)
    loser = _loser_team(game)
    rivalry_risk = "medium"
    if winner.short_name in POPULAR_TEAM_CODES or loser.short_name in POPULAR_TEAM_CODES:
        rivalry_risk = "high"
    if abs(game.home_team.score - game.away_team.score) >= 15:
        rivalry_risk = "medium"

    template_risk = "如果标题只写谁拿了多少分，很容易被喷成模板味。"
    likely_comment_styles = [
        "队蜜会先争论这场到底该吹球星还是吹体系。",
        "中立球迷更容易追着反方观点讨论输球方是不是先崩了。",
        "数据党会重点盯篮板、助攻、失误这些结构差。",
    ]
    return {
        "flame_point": controversy["flame_question"],
        "high_like_point": contrarian_angle["claim"],
        "template_risk": template_risk,
        "rivalry_risk": rivalry_risk,
        "likely_comment_styles": likely_comment_styles,
    }


def _follow_up_queue(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any],
    dna_report: dict[str, Any],
) -> dict[str, Any]:
    winner_snapshot = knowledge_context["home_team"] if _winner_team(game).short_name == game.home_team.short_name else knowledge_context["away_team"]
    loser_snapshot = knowledge_context["away_team"] if _loser_team(game).short_name == game.away_team.short_name else knowledge_context["home_team"]
    winner_star = _best_player(game.top_players, _winner_team(game).short_name)
    items = [
        {
            "title": "下一场继续盯赢球主线",
            "watch": game.analysis.primary_driver or "赢球结构",
            "why": f"如果{_winner_name(game)}下一场还能把这条线延续，单场内容就能升级成连续专题。",
        },
        {
            "title": "继续追输球方的问题线",
            "watch": dna_report["loser_faultline"],
            "why": f"{_loser_name(game)}这场的问题如果再出现，就可以写成连续崩点。",
        },
    ]
    if winner_star:
        items.append(
            {
                "title": "球星状态线",
                "watch": f"{winner_star.name}下一场还能不能把火力延续住",
                "why": f"这场之后，{winner_star.name}已经具备连续选题价值。",
            }
        )
    else:
        items.append(
            {
                "title": "体系验证线",
                "watch": winner_snapshot.get("summary", "继续观察球队样本"),
                "why": "如果没有绝对头牌高光，体系延续性就更值得追。",
            }
        )

    return {
        "headline": "后续选题自动续写",
        "items": items[:3],
        "extra_note": loser_snapshot.get("summary", ""),
    }


def _discussion_modes(
    game: NBAPostgameData,
    topic_recommendation: dict[str, Any],
    controversy: dict[str, Any],
    contrarian_angle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "data_conclusion": f"数据结论：这场最稳的切法还是“{topic_recommendation.get('recommended_angle', game.analysis.primary_driver or '赢球逻辑')}”。",
        "viral_conclusion": f"传播结论：最能带起评论的说法是“{contrarian_angle['claim']}”。",
        "controversy_conclusion": f"争议结论：{controversy['flame_question']}",
    }


def build_editorial_lab(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any],
    topic_recommendation: dict[str, Any],
    selection_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opportunity_board = _opportunity_board(game, topic_recommendation, selection_context)
    dna_report = _dna_report(game, knowledge_context)
    contrarian_angle = _contrarian_angle(game, knowledge_context, dna_report)
    controversy = _controversy_simulator(game, topic_recommendation, contrarian_angle)
    storyline_tree = _season_storyline_tree(game, knowledge_context, dna_report)
    persona_lab = _persona_lab(game, topic_recommendation, controversy, contrarian_angle)
    comment_forecast = _comment_forecast(game, controversy, contrarian_angle)
    follow_up_queue = _follow_up_queue(game, knowledge_context, dna_report)
    discussion_modes = _discussion_modes(game, topic_recommendation, controversy, contrarian_angle)

    return {
        "opportunity_board": opportunity_board,
        "controversy_simulator": controversy,
        "season_storyline_tree": storyline_tree,
        "persona_lab": persona_lab,
        "comment_forecast": comment_forecast,
        "follow_up_queue": follow_up_queue,
        "contrarian_finder": contrarian_angle,
        "discussion_modes": discussion_modes,
        "dna_system": dna_report,
    }
