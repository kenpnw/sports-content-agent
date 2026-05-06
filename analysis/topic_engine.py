from __future__ import annotations

from datetime import date
from typing import Any

from analysis.nba_postgame_rules import display_team_name
from core.models import NBAPostgameData


STAR_POWER_MAP = {
    "LeBron James": 100,
    "Stephen Curry": 98,
    "Kevin Durant": 96,
    "Nikola Jokic": 96,
    "Luka Doncic": 95,
    "Giannis Antetokounmpo": 95,
    "Jayson Tatum": 92,
    "Anthony Davis": 90,
    "Victor Wembanyama": 89,
    "Ja Morant": 88,
    "Shai Gilgeous-Alexander": 94,
}

TEAM_HEAT_MAP = {
    "LAL": 96,
    "GSW": 94,
    "BOS": 91,
    "NYK": 89,
    "PHI": 87,
    "MIA": 85,
    "DAL": 86,
    "DEN": 84,
    "PHX": 86,
    "MIL": 83,
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _safe_recent_form(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("recent_form", ""))


def _consecutive_prefix_count(value: str, target: str) -> int:
    count = 0
    for item in value:
        if item != target:
            break
        count += 1
    return count


def _evidence(source: str, field: str, value: Any, note: str) -> dict[str, Any]:
    return {
        "source": source,
        "field": field,
        "value": value,
        "note": note,
    }


def _make_dimension(
    key: str,
    label: str,
    score: float,
    weight: float,
    reason: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": round(_clamp(score), 1),
        "weight": weight,
        "reason": reason,
        "evidence": evidence,
    }


def _make_claim(
    claim: str,
    evidence: list[dict[str, Any]],
    signal_strength: float,
    consistency_score: float,
) -> dict[str, Any]:
    coverage = min(1.0, len(evidence) / 3)
    confidence = (0.35 * coverage) + (0.35 * signal_strength) + (0.30 * consistency_score)
    return {
        "claim": claim,
        "evidence": evidence,
        "evidence_coverage": round(coverage, 2),
        "signal_strength": round(signal_strength, 2),
        "consistency_score": round(consistency_score, 2),
        "confidence_score": round(confidence, 2),
    }


def _event_strength(game: NBAPostgameData) -> dict[str, Any]:
    margin = abs(game.home_team.score - game.away_team.score)
    highest_player_points = max((player.points for player in game.top_players), default=0)
    if margin <= 3:
        base = 92
        reason = "分差足够小，天然具备赛后传播张力。"
    elif margin <= 6:
        base = 84
        reason = "比赛在关键回合才彻底分出胜负。"
    elif margin <= 10:
        base = 72
        reason = "不是绝杀级别，但仍然有明显的悬念和转折空间。"
    elif margin <= 15:
        base = 54
        reason = "分差中等，更依赖球星和故事线来抬升题目价值。"
    else:
        base = 32
        reason = "比赛本身悬念有限，需要靠其他维度补足。"
    if highest_player_points >= 35:
        base += 6
        reason += " 同时还有足够亮眼的个人数据。"
    evidence = [
        _evidence("game_boxscore", "margin", margin, "分差越小，赛后讨论度通常越高。"),
        _evidence(
            "game_boxscore",
            "highest_player_points",
            highest_player_points,
            "球星高光能明显抬升这场比赛的传播上限。",
        ),
    ]
    return {"score": _clamp(base), "reason": reason, "evidence": evidence}


def _star_power(game: NBAPostgameData) -> dict[str, Any]:
    player_peak = 0
    player_name = ""
    for player in game.top_players:
        score = STAR_POWER_MAP.get(player.name, 58 + min(player.points, 35) * 0.6)
        if score > player_peak:
            player_peak = score
            player_name = player.name
    team_peak = max(
        TEAM_HEAT_MAP.get(game.home_team.short_name, 58),
        TEAM_HEAT_MAP.get(game.away_team.short_name, 58),
    )
    score = _clamp((0.65 * player_peak) + (0.35 * team_peak))
    evidence = [
        _evidence("player_attention", "top_star", player_name or "n/a", "球星自带流量。"),
        _evidence(
            "team_attention",
            "team_heat",
            {
                display_team_name(game.home_team.short_name, game.home_team.name): TEAM_HEAT_MAP.get(game.home_team.short_name, 58),
                display_team_name(game.away_team.short_name, game.away_team.name): TEAM_HEAT_MAP.get(game.away_team.short_name, 58),
            },
            "球队基本盘会放大同一场比赛的讨论规模。",
        ),
    ]
    reason = f"{player_name or '头部球员'}和流量球队共同抬高了这场比赛的天然关注度。"
    return {"score": score, "reason": reason, "evidence": evidence}


def _narrative_value(game: NBAPostgameData, context: dict[str, Any]) -> dict[str, Any]:
    winner_code = game.home_team.short_name if game.home_team.score >= game.away_team.score else game.away_team.short_name
    winner_context = context["home_team"] if winner_code == game.home_team.short_name else context["away_team"]
    loser_context = context["away_team"] if winner_code == game.home_team.short_name else context["home_team"]
    head_to_head = context["head_to_head"]

    score = 48.0
    reasons = []
    evidence = [
        _evidence("knowledge_store", "winner_recent_form", winner_context.get("recent_form", ""), "用于判断连胜、反弹或延续性。"),
        _evidence("knowledge_store", "head_to_head", head_to_head.get("tracked_games", 0), "交手样本越多，故事线越容易成立。"),
    ]

    winner_form = _safe_recent_form(winner_context)
    loser_form = _safe_recent_form(loser_context)
    winner_pre_losses = _consecutive_prefix_count(winner_form, "L")
    winner_pre_wins = _consecutive_prefix_count(winner_form, "W")
    loser_pre_losses = _consecutive_prefix_count(loser_form, "L")

    if winner_pre_losses >= 2:
        score += 18
        reasons.append("胜方带着连败背景完成止跌，反弹线明显。")
    elif winner_pre_wins >= 2:
        score += 16
        reasons.append("胜方原本就有连胜惯性，这场属于延续叙事。")
    if loser_pre_losses >= 2:
        score += 8
        reasons.append("败方近期也在下滑，能形成强弱走势对照。")
    if head_to_head.get("tracked_games", 0) >= 2:
        score += 12
        reasons.append("双方已有历史交手样本，适合做延续关系线。")

    if not reasons:
        reasons.append("这场更多还是靠比赛本身和球星表现来驱动传播。")

    return {"score": _clamp(score), "reason": " ".join(reasons), "evidence": evidence}


def _data_support(game: NBAPostgameData, context: dict[str, Any]) -> dict[str, Any]:
    available_fields = 0
    if game.top_players:
        available_fields += 1
    if game.game_flow:
        available_fields += 1
    if game.analysis.key_takeaways:
        available_fields += 1
    if context["head_to_head"].get("tracked_games", 0):
        available_fields += 1
    if context["home_team"].get("tracked_games", 0):
        available_fields += 1
    if context["away_team"].get("tracked_games", 0):
        available_fields += 1

    score = 50 + (available_fields * 8)
    evidence = [
        _evidence("normalized_input", "top_players_count", len(game.top_players), "有核心球员表现，内容就不止剩比分。"),
        _evidence("normalized_input", "game_flow_count", len(game.game_flow), "比赛过程信息能让文案更像复盘。"),
        _evidence("knowledge_store", "history_available", available_fields, "历史样本越多，证据链越稳。"),
    ]
    reason = "这场比赛已经具备生成主结论、背景信息和证据说明的基本材料。"
    return {"score": _clamp(score), "reason": reason, "evidence": evidence}


def _timing_score(game: NBAPostgameData) -> dict[str, Any]:
    try:
        game_day = date.fromisoformat(game.game_date)
    except ValueError:
        game_day = date.today()
    day_gap = abs((date.today() - game_day).days)
    if day_gap == 0:
        score = 95
        reason = "比赛日期就是今天，时效性是满的。"
    elif day_gap == 1:
        score = 72
        reason = "已经过了一天，但还在典型赛后窗口内。"
    else:
        score = 40
        reason = "时间已经拉开，必须靠强叙事或强球星才能继续推。"
    evidence = [_evidence("time_window", "day_gap", day_gap, "越接近比赛结束，内容分发效率越高。")]
    return {"score": score, "reason": reason, "evidence": evidence}


def _platform_scores(
    event_score: float,
    star_score: float,
    narrative_score: float,
    data_score: float,
    game: NBAPostgameData,
) -> tuple[float, float]:
    discussion_bonus = 10 if len(game.analysis.trending_angles) >= 2 else 0
    visual_bonus = 8 if any(player.points >= 30 for player in game.top_players) else 0
    hupu = _clamp((0.40 * event_score) + (0.30 * narrative_score) + (0.20 * data_score) + discussion_bonus)
    douyin = _clamp((0.40 * event_score) + (0.35 * star_score) + (0.15 * data_score) + visual_bonus)
    return round(hupu, 1), round(douyin, 1)


def _recommended_angle(game: NBAPostgameData, context: dict[str, Any], star_score: float, narrative_score: float) -> str:
    winner_name = game.winner
    primary_driver = game.analysis.primary_driver or "赢球逻辑"
    head_to_head = context["head_to_head"]
    winner_is_home = game.home_team.score >= game.away_team.score
    winner_snapshot = context["home_team"] if winner_is_home else context["away_team"]
    recent_form = _safe_recent_form(winner_snapshot)

    top_star = next((player for player in game.top_players if player.points >= 28), None)
    if star_score >= 85 and top_star:
        return f"{top_star.name}高光 + {primary_driver}"
    if narrative_score >= 72 and head_to_head.get("tracked_games", 0) >= 2:
        return f"交手延续线 + {primary_driver}"
    if recent_form.startswith("LL"):
        return f"{winner_name}止跌反弹线 + {primary_driver}"
    return f"{winner_name}赢球逻辑线：{primary_driver}"


def score_game_topic(game: NBAPostgameData, context: dict[str, Any]) -> dict[str, Any]:
    event = _event_strength(game)
    star = _star_power(game)
    narrative = _narrative_value(game, context)
    data = _data_support(game, context)
    timing = _timing_score(game)
    hupu_score, douyin_score = _platform_scores(
        event_score=event["score"],
        star_score=star["score"],
        narrative_score=narrative["score"],
        data_score=data["score"],
        game=game,
    )
    platform_average = (hupu_score + douyin_score) / 2
    global_score = round(
        (0.25 * event["score"])
        + (0.20 * star["score"])
        + (0.20 * narrative["score"])
        + (0.15 * platform_average)
        + (0.10 * data["score"])
        + (0.10 * timing["score"]),
        1,
    )

    dimensions = [
        _make_dimension("event_strength", "事件强度", event["score"], 0.25, event["reason"], event["evidence"]),
        _make_dimension("star_power", "球星影响力", star["score"], 0.20, star["reason"], star["evidence"]),
        _make_dimension("narrative_value", "叙事价值", narrative["score"], 0.20, narrative["reason"], narrative["evidence"]),
        _make_dimension(
            "platform_fit",
            "平台适配度",
            platform_average,
            0.15,
            f"虎扑 {hupu_score}，抖音 {douyin_score}。",
            [
                _evidence("platform_fit", "hupu_topic_score", hupu_score, "偏讨论和复盘的适配度。"),
                _evidence("platform_fit", "douyin_topic_score", douyin_score, "偏口播和高光切法的适配度。"),
            ],
        ),
        _make_dimension("data_support", "数据支撑度", data["score"], 0.10, data["reason"], data["evidence"]),
        _make_dimension("timing", "时效竞争度", timing["score"], 0.10, timing["reason"], timing["evidence"]),
    ]

    recommended_angle = _recommended_angle(game, context, star["score"], narrative["score"])
    why_selected = [
        f"事件强度 {event['score']:.1f} 分，{event['reason']}",
        f"平台适配度里虎扑 {hupu_score} / 抖音 {douyin_score}，说明这场同时适合论坛复盘和短视频切法。",
        f"推荐角度是“{recommended_angle}”，因为它最能把这场的核心传播点讲清楚。",
    ]

    primary_claim = _make_claim(
        claim=f"这场比赛值得进入优先选题池，因为事件张力和平台适配度都过线了。",
        evidence=event["evidence"] + [
            _evidence("platform_fit", "hupu_topic_score", hupu_score, "虎扑适配度足够高。"),
            _evidence("platform_fit", "douyin_topic_score", douyin_score, "抖音适配度也过线。"),
        ],
        signal_strength=min(1.0, global_score / 100),
        consistency_score=0.92,
    )
    angle_claim = _make_claim(
        claim=f"这场更适合从“{recommended_angle}”切入，而不是只报比分。",
        evidence=[
            _evidence("analysis", "primary_driver", game.analysis.primary_driver, "当前比赛的直接赢球逻辑。"),
            _evidence("analysis", "headline", game.analysis.headline, "已有结论和推荐角度一致。"),
            _evidence("knowledge_store", "head_to_head", context["head_to_head"].get("tracked_games", 0), "如有历史样本，角度可以更稳。"),
        ],
        signal_strength=0.88,
        consistency_score=0.9,
    )

    return {
        "global_topic_score": global_score,
        "hupu_topic_score": hupu_score,
        "douyin_topic_score": douyin_score,
        "recommended_angle": recommended_angle,
        "selected_tier": (
            "must_publish"
            if global_score >= 80
            else "recommended"
            if global_score >= 65
            else "backup"
            if global_score >= 50
            else "skip"
        ),
        "why_selected": why_selected,
        "dimension_scores": dimensions,
        "evidence_claims": [primary_claim, angle_claim],
    }
