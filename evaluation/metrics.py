"""Metrics for comparing Video Scout against independent baselines."""

from __future__ import annotations

import csv
import math
import re
import statistics
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def boundary_recall_precision_f1(
    predicted_boundaries: list[dict[str, Any]],
    gold_boundaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute exact-match boundary precision, recall, and F1."""
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
    """Match generated claims to labeled gold claims and compute accuracy."""
    gold_claims = read_gold_claims(gold_claims_csv)
    generated_claims = extract_report_claims(report)
    matched = 0
    correct = 0
    incorrect = 0
    unverifiable = 0
    matches: list[dict[str, Any]] = []

    for gold in gold_claims:
        gold_text = str(gold.get("claim_text", "")).strip()
        if not gold_text:
            continue
        best_text, score = _best_match(gold_text, generated_claims)
        if score >= 0.70:
            matched += 1
            label = str(gold.get("label", "")).strip().lower()
            if label == "correct":
                correct += 1
            elif label == "incorrect":
                incorrect += 1
            elif label == "unverifiable":
                unverifiable += 1
            matches.append(
                {
                    "gold_claim": gold_text,
                    "label": label,
                    "matched_claim": best_text,
                    "similarity": round(score, 4),
                }
            )

    denominator = correct + incorrect
    return {
        "accuracy": round(correct / denominator, 4) if denominator else 0.0,
        "coverage": round(matched / len(gold_claims), 4) if gold_claims else 0.0,
        "hallucination_rate": round(incorrect / denominator, 4) if denominator else 0.0,
        "matched": matched,
        "total_gold": len(gold_claims),
        "correct": correct,
        "incorrect": incorrect,
        "unverifiable": unverifiable,
        "matches": matches,
        "generated_claim_count": len(generated_claims),
    }


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


def extract_report_claims(report: dict[str, Any]) -> list[str]:
    """Extract claim-like text from full analysis and key segments."""
    claims: list[str] = []
    _append_claim(claims, report.get("full_analysis", ""))
    _append_claim(claims, report.get("executive_summary", ""))
    for segment in report.get("key_segments", []):
        if not isinstance(segment, dict):
            continue
        _append_claim(claims, segment.get("observation", ""))
        _append_claim(claims, segment.get("decision_analysis", ""))
        _append_claim(claims, segment.get("win_loss_impact", ""))
        for evidence in segment.get("evidence", []):
            _append_claim(claims, evidence)
    for evidence in report.get("evidence_index", []):
        if isinstance(evidence, dict):
            _append_claim(claims, evidence.get("value", ""))
    return _dedupe([item for item in claims if item])


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
        score = SequenceMatcher(None, gold_text, claim).ratio()
        if _has_numeric_contradiction(gold_text, claim):
            # Fuzzy text matching alone can confuse "5/13" with "7/13".
            # Numeric contradictions should not count as fact matches.
            score = min(score, 0.69)
        if score > best_score:
            best_text = claim
            best_score = score
    return best_text, best_score


def _has_numeric_contradiction(left: str, right: str) -> bool:
    left_numbers = re.findall(r"\d+(?:\.\d+)?", left)
    right_numbers = re.findall(r"\d+(?:\.\d+)?", right)
    if not left_numbers or not right_numbers:
        return False
    shorter = min(len(left_numbers), len(right_numbers))
    return left_numbers[:shorter] != right_numbers[:shorter]


def _append_claim(claims: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if len(text) <= 180:
        claims.append(text)
        return
    separators = ["\n", "。", "；", ";"]
    chunks = [text]
    for separator in separators:
        if len(chunks) > 1:
            break
        chunks = [chunk.strip() for chunk in text.split(separator) if chunk.strip()]
    claims.extend(chunk[:220] for chunk in chunks if chunk)


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
