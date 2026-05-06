"""Independent baselines for Video Scout evaluation.

These analyzers deliberately avoid the main possession-boundary and
auto-observation code paths. They use the shared realtime.llm_client wrapper
for fair latency accounting, but they do not reuse Video Scout's tactical
pipeline internals.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from realtime.llm_client import LLMClient, LLMResult
from storage.file_store import read_json


class HighlightOnlyAnalyzer:
    """Baseline that treats made 3PT/dunk events as highlight moments."""

    SYSTEM_ID = "highlight_only"

    def __init__(self, *, client: LLMClient | None = None) -> None:
        self.client = client if client is not None else _optional_client()

    def analyze(self, replay_path: str | Path, court_report_path: str | Path | None = None) -> dict[str, Any]:
        """Return a report-like dict without possession reasoning."""
        start = time.monotonic()
        replay = read_json(Path(replay_path))
        court_context = _safe_read_json(court_report_path)
        events = [item for item in replay.get("events", []) if isinstance(item, dict)]
        highlights = _select_highlights(events)
        predicted_boundaries = [_boundary_from_event(event) for event in highlights]
        segments = [_segment_from_highlight(event) for event in highlights]
        fallback = False
        fallback_reason = ""
        llm_payload: dict[str, Any] = {}

        if self.client is None:
            fallback = True
            fallback_reason = "LLM client unavailable."
            analysis = _fallback_highlight_summary(highlights)
        else:
            try:
                result = self.client.generate(
                    system=(
                        "You are a concise Chinese basketball content analyst. "
                        "Use only the supplied highlight events. Do not infer hidden possessions."
                    ),
                    user=(
                        "Write one compact tactical summary paragraph from these made-shot highlights. "
                        "This baseline intentionally ignores turnovers, rebounds, and possession boundaries.\n"
                        f"Game: {json.dumps(_game_context(replay, court_context), ensure_ascii=False)}\n"
                        f"Highlights: {json.dumps(highlights, ensure_ascii=False)}"
                    ),
                    model="deepseek-chat",
                    temperature=0.35,
                    max_tokens=700,
                    contract_id="evaluation.baseline.highlight_only",
                    max_retries=0,
                )
                analysis = result.text.strip() or _fallback_highlight_summary(highlights)
                llm_payload = _llm_result_payload(result)
            except Exception as exc:
                fallback = True
                fallback_reason = str(exc)
                analysis = _fallback_highlight_summary(highlights)

        elapsed = time.monotonic() - start
        return {
            "title": "Highlight-only baseline tactical summary",
            "executive_summary": "This baseline only reads made 3PT and dunk highlights, so it misses non-scoring tactical turns.",
            "full_analysis": analysis,
            "key_segments": segments,
            "tactical_themes": ["made-shot highlight selection"],
            "quarter_flow": [],
            "deciding_factors": [],
            "mvp_analysis": "",
            "player_tactical_profiles": [],
            "limitations": [
                "No possession classification.",
                "No turnover or defensive-rebound boundary detection.",
                "No court-report player stat evidence injection.",
            ],
            "evidence_index": [
                {
                    "id": f"highlight_{_event_id(event)}",
                    "timecode": _clock(event),
                    "source": "pbp_highlight_only",
                    "value": _description(event),
                }
                for event in highlights
            ],
            "metadata": {
                "system": self.SYSTEM_ID,
                "fallback": fallback,
                "fallback_reason": fallback_reason,
                "elapsed_seconds": round(elapsed, 2),
                "predicted_boundaries": predicted_boundaries,
                "llm": llm_payload,
            },
        }


class GPTOnlyAnalyzer:
    """Baseline that sends raw PBP JSON directly to the LLM."""

    SYSTEM_ID = "gpt_only"

    def __init__(self, *, client: LLMClient | None = None) -> None:
        self.client = client if client is not None else _optional_client()

    def analyze(self, replay_path: str | Path, court_report_path: str | Path | None = None) -> dict[str, Any]:
        """Return a report-like dict without event detection or evidence catalog."""
        start = time.monotonic()
        replay = read_json(Path(replay_path))
        fallback = False
        fallback_reason = ""
        llm_payload: dict[str, Any] = {}

        if self.client is None:
            fallback = True
            fallback_reason = "LLM client unavailable."
            analysis = _fallback_gpt_only_summary(replay)
        else:
            try:
                result = self.client.generate(
                    system=(
                        "You are a Chinese basketball tactical writer. "
                        "You only receive raw play-by-play JSON. Do not cite external stats."
                    ),
                    user=(
                        "Write about 2000 Chinese characters of tactical analysis directly from this raw PBP JSON. "
                        "Do not run event detection, do not use court-report stats, and do not build an evidence catalog.\n"
                        f"Raw PBP JSON: {json.dumps(replay, ensure_ascii=False)}"
                    ),
                    model="deepseek-chat",
                    temperature=0.4,
                    max_tokens=1800,
                    contract_id="evaluation.baseline.gpt_only",
                    max_retries=0,
                )
                analysis = result.text.strip() or _fallback_gpt_only_summary(replay)
                llm_payload = _llm_result_payload(result)
            except Exception as exc:
                fallback = True
                fallback_reason = str(exc)
                analysis = _fallback_gpt_only_summary(replay)

        elapsed = time.monotonic() - start
        return {
            "title": "GPT-only raw PBP tactical report",
            "executive_summary": "This baseline asks the LLM to analyze raw PBP directly without structured evidence routing.",
            "full_analysis": analysis,
            "key_segments": [],
            "tactical_themes": [],
            "quarter_flow": [],
            "deciding_factors": [],
            "mvp_analysis": "",
            "player_tactical_profiles": [],
            "limitations": [
                "No possession boundary detector.",
                "No court-report evidence injection.",
                "No structured evidence index.",
            ],
            "evidence_index": [],
            "metadata": {
                "system": self.SYSTEM_ID,
                "fallback": fallback,
                "fallback_reason": fallback_reason,
                "elapsed_seconds": round(elapsed, 2),
                "predicted_boundaries": [],
                "llm": llm_payload,
                "court_report_path_ignored": str(court_report_path or ""),
            },
        }


def _optional_client() -> LLMClient | None:
    try:
        return LLMClient.from_env()
    except Exception:
        return None


def _safe_read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = read_json(Path(path))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _game_context(replay: dict[str, Any], court_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_id": replay.get("game_id", court_context.get("game_id", "")),
        "home_team": replay.get("home_team", court_context.get("home_team", "")),
        "away_team": replay.get("away_team", court_context.get("away_team", "")),
        "final_score": court_context.get("final_score", ""),
        "mvp": court_context.get("mvp", ""),
    }


def _select_highlights(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred = [
        event
        for event in events
        if _is_made_shot(event)
        and (_sub_type(event).upper() == "3PT" or "dunk" in _description(event).lower())
    ]
    if preferred:
        return preferred
    return [event for event in events if _is_made_shot(event)]


def _segment_from_highlight(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "timecode": _clock(event),
        "period": _period(event),
        "clock": _clock(event),
        "tactic_type": "highlight_made_shot",
        "observation": _description(event),
        "decision_analysis": "Baseline treats this made shot as a highlight, without reconstructing the possession that created it.",
        "win_loss_impact": "Scoring value is visible, but turnover, momentum, and non-scoring context are ignored.",
        "evidence": [f"event:{_event_id(event)}", _description(event)],
        "confidence": 0.55,
    }


def _boundary_from_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "period": _period(event),
        "end_event_index": _event_id(event),
        "end_reason": "made_shot",
        "possession_team": _team(event),
    }


def _fallback_highlight_summary(highlights: list[dict[str, Any]]) -> str:
    descriptions = "；".join(_description(event) for event in highlights[:8])
    return (
        "集锦基线只保留命中三分和扣篮，因此它能说明哪些球进了，却很难解释这些球为什么出现。"
        f"样本高光包括：{descriptions}。该结果适合模拟普通自动剪集锦产品，但不足以替代回合级战术分析。"
    )


def _fallback_gpt_only_summary(replay: dict[str, Any]) -> str:
    events = [item for item in replay.get("events", []) if isinstance(item, dict)]
    descriptions = "；".join(_description(event) for event in events[:10])
    return (
        "裸 GPT 基线直接读取整段 PBP 文本，没有显式边界检测和证据注入。"
        f"它能复述若干事件，例如：{descriptions}，但无法稳定给出可验证的回合级证据链。"
    )


def _llm_result_payload(result: LLMResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "latency_seconds": round(result.latency_seconds, 2),
        "tokens": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        },
        "finish_reason": result.finish_reason,
    }


def _is_made_shot(event: dict[str, Any]) -> bool:
    return str(event.get("shotResult", "")).lower() == "made" or "made shot" in str(event.get("actionType", "")).lower()


def _period(event: dict[str, Any]) -> int:
    return int(event.get("period", 0) or 0)


def _clock(event: dict[str, Any]) -> str:
    return str(event.get("clock", ""))


def _description(event: dict[str, Any]) -> str:
    return str(event.get("description", ""))


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("actionId", event.get("event_id", "")))


def _sub_type(event: dict[str, Any]) -> str:
    return str(event.get("subType", ""))


def _team(event: dict[str, Any]) -> str:
    return str(event.get("teamTricode", event.get("team", "")))

