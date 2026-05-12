"""Metrics for comparing Video Scout against independent baselines."""

from __future__ import annotations

import csv
import math
import re
import statistics
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


MATCH_THRESHOLD = 0.55
SKIP_RECURSIVE_KEYS = {
    "metadata",
    "model",
    "latency_seconds",
    "contract_id",
    "tokens",
    "raw_response",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "elapsed_seconds",
}
EVIDENCE_INDEX_SKIP_KEYS = {"source", "timecode"}


def boundary_recall_precision_f1(
    predicted_boundaries: list[dict[str, Any]] | None,
    gold_boundaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute exact-match boundary precision, recall, and F1.

    A None prediction means the evaluated system does not expose boundary
    detection at all, so the metric is intentionally marked as N/A instead of
    being treated as a failed detector.
    """
    if predicted_boundaries is None:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "tp": None,
            "fp": None,
            "fn": None,
            "reason": "system_does_not_output_boundaries",
        }

    predicted = {_boundary_key(item) for item in predicted_boundaries if _boundary_key(item)}
    gold = {_boundary_key(item) for item in gold_boundaries if _boundary_key(item)}
    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def claim_fact_accuracy(report: dict[str, Any], gold_claims_csv: str | Path) -> dict[str, Any]:
    """Match generated candidate claims to labeled gold claims."""
    diagnostics = claim_match_diagnostics(report, gold_claims_csv)
    matched_items = [item for item in diagnostics if item["matched"]]
    correct = sum(1 for item in matched_items if item["gold_label"] == "correct")
    incorrect = sum(1 for item in matched_items if item["gold_label"] == "incorrect")
    unverifiable = sum(1 for item in matched_items if item["gold_label"] == "unverifiable")
    denominator = correct + incorrect
    total_gold = len(diagnostics)
    candidate_count = diagnostics[0]["candidate_count"] if diagnostics else 0
    return {
        "accuracy": round(correct / denominator, 4) if denominator else 0.0,
        "coverage": round(len(matched_items) / total_gold, 4) if total_gold else 0.0,
        "hallucination_rate": round(incorrect / denominator, 4) if denominator else 0.0,
        "matched": len(matched_items),
        "total_gold": total_gold,
        "correct": correct,
        "incorrect": incorrect,
        "unverifiable": unverifiable,
        "matches": [
            {
                "gold_claim": item["gold_text"],
                "label": item["gold_label"],
                "matched_claim": item["best_match_text"],
                "similarity": item["best_match_score"],
            }
            for item in matched_items
        ],
        "candidate_count": candidate_count,
        "generated_claim_count": candidate_count,
    }


def claim_match_diagnostics(report: dict[str, Any], gold_claims_csv: str | Path) -> list[dict[str, Any]]:
    """Return per-gold-claim matching details for debug and case analysis."""
    gold_claims = read_gold_claims(gold_claims_csv)
    candidates = extract_candidate_claims(report)
    diagnostics: list[dict[str, Any]] = []
    for gold in gold_claims:
        gold_text = str(gold.get("claim_text", "")).strip()
        label = str(gold.get("label", "")).strip().lower()
        best_text, score = _best_match(gold_text, candidates)
        matched = bool(gold_text) and score >= MATCH_THRESHOLD
        diagnostics.append(
            {
                "gold_text": gold_text,
                "gold_label": label,
                "matched": matched,
                "best_match_text": best_text if matched else "",
                "best_match_score": round(score, 4),
                "candidate_count": len(candidates),
            }
        )
    return diagnostics


def latency_stats(end_to_end_seconds_list: list[float]) -> dict[str, Any]:
    """Return p50, p95, mean, and sample count for end-to-end latency."""
    values = sorted(float(item) for item in end_to_end_seconds_list)
    if not values:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "n": 0}
    return {
        "p50": round(_percentile(values, 0.50), 4),
        "p95": round(_percentile(values, 0.95), 4),
        "mean": round(statistics.fmean(values), 4),
        "n": len(values),
    }


def read_gold_boundaries(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_gold_claims(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def extract_candidate_claims(report_dict: Any) -> list[str]:
    """Recursively extract claim-like sentence candidates from any report dict."""
    candidates: list[str] = []
    _collect_claims(report_dict, candidates, path=[])
    return _dedupe(
        [
            item
            for item in candidates
            if 6 <= len(item) <= 100 and _is_claim_like(item)
        ]
    )


def extract_report_claims(report: dict[str, Any]) -> list[str]:
    """Backward-compatible alias for older callers."""
    return extract_candidate_claims(report)


def token_overlap_ratio(left: str, right: str) -> float:
    """Compute token overlap with optional jieba and dependency-free fallback."""
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    semantic_left = set(_semantic_tokens(left))
    semantic_right = set(_semantic_tokens(right))
    semantic_overlap = semantic_left & semantic_right
    semantic_score = 0.0
    if len(semantic_overlap) >= 2 and min(len(semantic_left), len(semantic_right)) >= 2:
        semantic_score = _overlap(semantic_left, semantic_right)
    return max(
        _overlap(left_tokens, right_tokens),
        semantic_score,
    )


def _overlap(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _collect_claims(value: Any, claims: list[str], *, path: list[str]) -> None:
    if isinstance(value, str):
        for sentence in _split_sentences(value):
            claims.extend(_fit_claim_length(sentence))
        return
    if isinstance(value, list):
        for item in value:
            _collect_claims(item, claims, path=path)
        return
    if isinstance(value, dict):
        contextual_keys = _collect_contextual_dict_claims(value, claims)
        for key, child in value.items():
            key_text = str(key)
            if key_text in SKIP_RECURSIVE_KEYS:
                continue
            if key_text in contextual_keys:
                continue
            if "evidence_index" in path and key_text in EVIDENCE_INDEX_SKIP_KEYS:
                continue
            _collect_claims(child, claims, path=[*path, key_text])


def _split_sentences(text: str) -> list[str]:
    cleaned = _restore_initial_dots(_protect_initial_dots(str(text or "")))
    protected = _protect_initial_dots(cleaned)
    chunks = re.split(r"(?<=[。！？!?；;])|\n+", protected)
    sentences: list[str] = []
    for chunk in chunks:
        restored = _restore_initial_dots(chunk).strip(" \t\r\n-•，,：:")
        if restored:
            sentences.append(restored)
    return sentences


def _fit_claim_length(sentence: str) -> list[str]:
    text = re.sub(r"\s+", " ", sentence).strip()
    if not text:
        return []
    if 6 <= len(text) <= 100:
        return [text]
    parts = [item.strip(" ，,：:") for item in re.split(r"[，,：:]", text) if item.strip()]
    fitted = [item for item in parts if 6 <= len(item) <= 100]
    if fitted:
        return fitted
    if len(text) > 100:
        return [text[index : index + 100].strip() for index in range(0, len(text), 100) if len(text[index : index + 100].strip()) >= 6]
    return []


def _collect_contextual_dict_claims(value: dict[str, Any], claims: list[str]) -> set[str]:
    period = value.get("period")
    clock = value.get("clock")
    if period in (None, ""):
        return set()
    prefix = f"Q{period} {clock}".strip()
    contextual_keys = {"observation", "decision_analysis", "win_loss_impact", "event_description", "action_summary", "evidence"}
    for key in ("observation", "decision_analysis", "win_loss_impact", "event_description", "action_summary"):
        child = value.get(key)
        if isinstance(child, str) and child.strip():
            for sentence in _split_sentences(f"{prefix} {child}"):
                claims.extend(_fit_claim_length(sentence))
    evidence = value.get("evidence", [])
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, str) and item.strip() and not item.startswith("event:"):
                for sentence in _split_sentences(f"{prefix} {item}"):
                    claims.extend(_fit_claim_length(sentence))
    return contextual_keys


def _boundary_key(item: dict[str, Any]) -> tuple[int, str] | None:
    try:
        period = int(item.get("period", 0) or 0)
    except (TypeError, ValueError):
        return None
    end_event_index = str(item.get("end_event_index", "")).strip()
    if not period or not end_event_index:
        return None
    return period, end_event_index


def _best_match(gold_text: str, generated_claims: list[str]) -> tuple[str, float]:
    best_text = ""
    best_score = 0.0
    for claim in generated_claims:
        sequence_score = SequenceMatcher(None, gold_text, claim).ratio()
        overlap_score = token_overlap_ratio(gold_text, claim)
        score = max(sequence_score, overlap_score)
        if _is_reference_only_claim(gold_text) and sequence_score < MATCH_THRESHOLD:
            score = min(score, MATCH_THRESHOLD - 0.01)
        if (
            _has_numeric_contradiction(gold_text, claim)
            or _has_context_contradiction(gold_text, claim)
            or _has_action_contradiction(gold_text, claim)
        ):
            # Keep numeric traps meaningful: "5/13" must not match "7/13".
            score = min(score, MATCH_THRESHOLD - 0.01)
        if score > best_score:
            best_text = claim
            best_score = score
    return best_text, best_score


def _tokens(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    semantic_tokens = _semantic_tokens(text)
    try:
        import jieba  # type: ignore

        tokens = [item.strip().lower() for item in jieba.lcut(text) if item.strip()]
        if tokens:
            return _dedupe(tokens + semantic_tokens)
    except Exception:
        pass
    if len(normalized) <= 2:
        return _dedupe([normalized] + semantic_tokens)
    char_tokens = [normalized[index : index + 2] for index in range(0, len(normalized) - 1)]
    word_tokens = re.findall(r"[a-zA-Z]+|\d+(?:\.\d+)?", str(text or "").lower())
    return _dedupe(char_tokens + word_tokens + semantic_tokens)


def _semantic_tokens(text: str) -> list[str]:
    raw = str(text or "")
    lowered = raw.lower()
    tokens: list[str] = []
    alias_rules = [
        (("l. james", "lebron", "詹姆斯"), ["player_james", "team_lal"]),
        (("s. curry", "stephen curry", "curry", "库里"), ["player_curry", "team_gsw"]),
        (("a. davis", "anthony davis", "davis", "戴维斯"), ["player_davis", "team_lal"]),
        (("d. green", "draymond green", "green", "格林"), ["player_green", "team_gsw"]),
        (("k. thompson", "klay", "thompson", "汤普森"), ["player_thompson", "team_gsw"]),
        (("lal", "湖人", "湖人队"), ["team_lal"]),
        (("gsw", "勇士", "勇士队"), ["team_gsw"]),
    ]
    for patterns, mapped in alias_rules:
        if any(pattern in lowered or pattern in raw for pattern in patterns):
            tokens.extend(mapped)

    term_rules = [
        (("3pt", "3-pointer", "三分", "三分球"), "shot_three"),
        (("dunk", "扣篮", "扣篮得分"), "shot_dunk"),
        (("cutting", "空切"), "tactic_cutting"),
        (("alley oop", "空接"), "tactic_alley_oop"),
        (("turnover", "失误"), "event_turnover"),
        (("bad pass", "传球失误"), "event_bad_pass"),
        (("lost ball", "丢球"), "event_lost_ball"),
        (("traveling", "走步"), "event_traveling"),
        (("out of bounds", "出界"), "event_out_of_bounds"),
        (("made", "命中"), "result_made"),
        (("missed", "未命中", "不中"), "result_missed"),
        (("final score", "定格", "最终"), "game_final"),
        (("首开纪录", "首次得分", "首开"), "open_score"),
        (("反超", "取得领先", "建立领先"), "lead_change"),
        (("扳平", "缩小至0分", "缩小至 0 分"), "tie_game"),
        (("绝杀", "game winner", "buzzer beater"), "game_winner"),
        (("clutch", "最后8秒", "最后 8 秒", "最后时刻", "关键时刻"), "clutch_late"),
        (("mvp", "最佳"), "award_mvp"),
        (("rebound", "篮板"), "stat_rebound"),
        (("assist", "助攻"), "stat_assist"),
        (("block", "盖帽"), "stat_block"),
        (("points", "得到", "得分"), "stat_points"),
    ]
    for patterns, mapped in term_rules:
        if any(pattern in lowered or pattern in raw for pattern in patterns):
            tokens.append(mapped)

    period_rules = [
        (("q1", "第一节", "首节"), "period_1"),
        (("q2", "第二节", "次节"), "period_2"),
        (("q3", "第三节"), "period_3"),
        (("q4", "第四节", "末节"), "period_4"),
    ]
    for patterns, mapped in period_rules:
        if any(pattern in lowered or pattern in raw for pattern in patterns):
            tokens.append(mapped)

    for number in re.findall(r"\d+(?:\.\d+)?", raw):
        tokens.append(f"num_{number}")
    return tokens


def _normalize_text(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text or "")).lower()


def _has_numeric_contradiction(left: str, right: str) -> bool:
    left_slashes = set(re.findall(r"\d+/\d+", left))
    right_slashes = set(re.findall(r"\d+/\d+", right))
    if left_slashes and right_slashes and not left_slashes <= right_slashes:
        return True

    if _has_three_point_stat_contradiction(left, right):
        return True

    if not _is_box_score_like(left):
        return False
    if not _shares_player_token(left, right):
        return True
    if not _is_box_score_like(right):
        return True
    left_numbers = set(re.findall(r"\d+(?:\.\d+)?", left))
    right_numbers = set(re.findall(r"\d+(?:\.\d+)?", right))
    return bool(left_numbers and right_numbers and not left_numbers <= right_numbers)


def _has_context_contradiction(left: str, right: str) -> bool:
    left_tokens = set(_semantic_tokens(left))
    right_tokens = set(_semantic_tokens(right))
    left_players = {token for token in left_tokens if token.startswith("player_")}
    right_players = {token for token in right_tokens if token.startswith("player_")}
    if left_players and right_players and not left_players & right_players:
        return True
    left_teams = {token for token in left_tokens if token.startswith("team_")}
    right_teams = {token for token in right_tokens if token.startswith("team_")}
    if left_teams and right_teams and not left_teams & right_teams:
        return True
    left_periods = {token for token in left_tokens if token.startswith("period_")}
    right_periods = {token for token in right_tokens if token.startswith("period_")}
    if left_periods and not right_periods:
        return True
    if left_periods and right_periods and not left_periods & right_periods:
        return True
    if "clutch_late" in left_tokens and "clutch_late" not in right_tokens:
        return True
    if "game_winner" in left_tokens and "game_winner" not in right_tokens:
        return True
    return False


def _has_action_contradiction(left: str, right: str) -> bool:
    left_tokens = set(_semantic_tokens(left))
    right_tokens = set(_semantic_tokens(right))
    guarded_tokens = {
        "shot_three",
        "shot_dunk",
        "event_turnover",
        "event_bad_pass",
        "event_lost_ball",
        "event_traveling",
        "event_out_of_bounds",
        "stat_rebound",
        "stat_assist",
        "stat_block",
        "stat_points",
    }
    for token in guarded_tokens & left_tokens:
        if token not in right_tokens:
            return True
    return False


def _has_three_point_stat_contradiction(left: str, right: str) -> bool:
    if "三分" not in left or "三分" not in right:
        return False
    if not _shares_player_token(left, right):
        return False
    left_made = _three_made_count(left)
    right_made = _three_made_count(right)
    if left_made is not None and right_made is not None and left_made != right_made:
        return True
    left_numbers = _numbers_near_text(left, "三分")
    right_numbers = _numbers_near_text(right, "三分")
    return bool(left_numbers and right_numbers and not left_numbers <= right_numbers)


def _three_made_count(text: str) -> int | None:
    raw = str(text or "")
    patterns = [
        r"命中\s*(\d+)\s*个?三分",
        r"三分球?\s*(\d+)\s*/\s*\d+",
        r"三分球?\s*\d+\s*投\s*(\d+)\s*中",
        r"三分球?\s*\d+\s*中\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return int(match.group(1))
    return None


def _numbers_near_text(text: str, marker: str) -> set[str]:
    values: set[str] = set()
    raw = str(text or "")
    for match in re.finditer(marker, raw):
        start = max(0, match.start() - 8)
        end = min(len(raw), match.end() + 12)
        values.update(re.findall(r"\d+(?:\.\d+)?", raw[start:end]))
    return values


def _is_box_score_like(text: str) -> bool:
    raw = str(text or "")
    return (
        "全场" in raw
        or "/" in raw
        or bool(re.search(r"\d+\s*投\s*\d+\s*中", raw))
        or any(term in raw for term in ("篮板", "助攻", "盖帽", "正负值", "罚球", "抢断"))
    )


def _shares_player_token(left: str, right: str) -> bool:
    left_players = {token for token in _semantic_tokens(left) if token.startswith("player_")}
    right_players = {token for token in _semantic_tokens(right) if token.startswith("player_")}
    return bool(left_players and right_players and left_players & right_players)


def _is_claim_like(text: str) -> bool:
    raw = str(text or "").strip()
    if raw.startswith("#"):
        return False
    if re.fullmatch(r"[A-Z]\.\s*[A-Z][A-Za-z]+", raw):
        return False
    if re.fullmatch(r"[A-Z]{2,4}", raw):
        return False
    if not re.search(r"[\u4e00-\u9fff0-9]", raw) and len(raw.split()) <= 4:
        return False
    semantic = set(_semantic_tokens(raw))
    has_action = any(
        token.startswith(("shot_", "event_", "result_", "stat_", "game_", "award_"))
        for token in semantic
    )
    has_number = bool(re.search(r"\d", raw))
    has_chinese_verb = bool(re.search(r"命中|完成|出现|得到|领先|落后|扩大|缩小|终结|反超|定格|惜败|获胜|失去|帮助", raw))
    return has_action or has_number or has_chinese_verb


def _is_reference_only_claim(text: str) -> bool:
    raw = str(text or "")
    if not any(marker in raw for marker in ("此球", "这记", "此次", "这次")):
        return False
    return not any(token.startswith("player_") for token in _semantic_tokens(raw))


def _protect_initial_dots(text: str) -> str:
    return re.sub(r"\b([A-Z])\.", r"\1<dot>", text)


def _restore_initial_dots(text: str) -> str:
    return text.replace("<dot>", ".")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _percentile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    index = max(0, min(len(values) - 1, math.ceil(q * len(values)) - 1))
    return values[index]
