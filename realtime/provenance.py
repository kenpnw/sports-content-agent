"""Sentence-level provenance tagging for live commentary.

The goal of this module is not to solve attribution perfectly. The goal is
to make the provenance layer deterministic, inspectable, and good enough for
defense/demo use:

1. The LLM is asked to return a sentence plan with evidence keys.
2. This module validates that plan against a local evidence catalog.
3. Each sentence is downgraded or confirmed as:
   - verified
   - speculative
   - narrative

That gives us a concrete, UI-friendly trace without introducing another
non-deterministic model call in the critical path.
"""

from __future__ import annotations

import re
from typing import Any

from realtime.models import DetectedEvent, ProvenanceTag


_SENTENCE_PATTERN = re.compile(r"[^。！？!?]+[。！？!?]?")
_HEDGE_WORDS = (
    "maybe",
    "probably",
    "likely",
    "perhaps",
    "seems",
    "looks like",
    "可能",
    "大概",
    "也许",
    "像是",
    "看起来",
)


def _sentence_split(text: str) -> list[str]:
    return [chunk.strip() for chunk in _SENTENCE_PATTERN.findall(text) if chunk.strip()]


def build_evidence_catalog(
    detected_event: DetectedEvent,
    *,
    fact_context: dict[str, Any] | None = None,
    research_packet: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a deterministic evidence catalog for one detected event."""
    event = detected_event.raw_event
    catalog: dict[str, dict[str, Any]] = {
        "event.description": {
            "key": "event.description",
            "source": "play_by_play",
            "label": "event description",
            "value": event.description,
            "note": "Raw play-by-play line from the replay or official feed.",
        },
        "event.score": {
            "key": "event.score",
            "source": "play_by_play",
            "label": "score snapshot",
            "value": {"home": event.home_score, "away": event.away_score},
            "note": "Live score at the moment this event happened.",
        },
        "event.clock": {
            "key": "event.clock",
            "source": "play_by_play",
            "label": "clock",
            "value": {"period": event.period, "clock": event.clock},
            "note": "Quarter and clock for the current play.",
        },
        "event.actor": {
            "key": "event.actor",
            "source": "play_by_play",
            "label": "primary actor",
            "value": {
                "player": event.actor_player,
                "team": event.actor_team,
                "action_type": event.action_type,
                "sub_type": event.sub_type,
                "points": event.points,
            },
            "note": "The main player/team involved in the current event.",
        },
        "event.category": {
            "key": "event.category",
            "source": "event_detector",
            "label": "detected category",
            "value": {
                "category": detected_event.category,
                "salience": detected_event.salience,
                "rationale": detected_event.rationale,
            },
            "note": "Rule-based commentary trigger classification.",
        },
    }

    if fact_context:
        home_team = fact_context.get("home_team", {})
        away_team = fact_context.get("away_team", {})
        head_to_head = fact_context.get("head_to_head", {})
        top_players = fact_context.get("top_players", [])
        if home_team:
            catalog["fact.home_team"] = {
                "key": "fact.home_team",
                "source": "fact_store",
                "label": "home team snapshot",
                "value": home_team,
                "note": "Recent form and tracked averages for the home team.",
            }
        if away_team:
            catalog["fact.away_team"] = {
                "key": "fact.away_team",
                "source": "fact_store",
                "label": "away team snapshot",
                "value": away_team,
                "note": "Recent form and tracked averages for the away team.",
            }
        if head_to_head:
            catalog["fact.head_to_head"] = {
                "key": "fact.head_to_head",
                "source": "fact_store",
                "label": "head to head",
                "value": head_to_head,
                "note": "Stored matchup samples between the two teams.",
            }
        for index, item in enumerate(top_players[:4], start=1):
            key = f"fact.top_player_{index}"
            catalog[key] = {
                "key": key,
                "source": "fact_store",
                "label": f"tracked player {index}",
                "value": item,
                "note": "Historical player snapshot from the local fact store.",
            }

    if research_packet:
        for index, hit in enumerate(research_packet.get("text_rag_hits", [])[:3], start=1):
            key = f"rag.hit_{index}"
            catalog[key] = {
                "key": key,
                "source": "text_rag",
                "label": hit.get("title", f"RAG hit {index}"),
                "value": {
                    "title": hit.get("title", ""),
                    "excerpt": hit.get("excerpt", ""),
                    "source_type": hit.get("source_type", ""),
                    "uri": hit.get("uri", ""),
                },
                "note": "Retrieved narrative context from the local text RAG store.",
            }

    return catalog


def _normalize_plan(
    commentary_text: str,
    sentence_plan: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if sentence_plan:
        normalized: list[dict[str, Any]] = []
        for item in sentence_plan:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            normalized.append(
                {
                    "text": text,
                    "mode": str(item.get("mode", "narrative")).strip().lower(),
                    "evidence_keys": [str(key) for key in item.get("evidence_keys", [])],
                }
            )
        if normalized:
            return normalized
    return [{"text": sentence, "mode": "narrative", "evidence_keys": []} for sentence in _sentence_split(commentary_text)]


def _contains_hedge(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in _HEDGE_WORDS)


def _resolve_state(mode: str, evidence: list[dict[str, Any]], text: str) -> str:
    if mode == "speculative":
        return "speculative"
    if mode == "fact":
        if evidence and not _contains_hedge(text):
            return "verified"
        return "speculative"
    if evidence and _contains_hedge(text):
        return "speculative"
    return "narrative"


def tag_commentary(
    commentary_text: str,
    detected_event: DetectedEvent,
    *,
    sentence_plan: list[dict[str, Any]] | None = None,
    fact_context: dict[str, Any] | None = None,
    research_packet: dict[str, Any] | None = None,
) -> list[ProvenanceTag]:
    """Turn commentary text plus an optional model plan into provenance tags."""
    catalog = build_evidence_catalog(
        detected_event,
        fact_context=fact_context,
        research_packet=research_packet,
    )
    plan = _normalize_plan(commentary_text, sentence_plan)
    tags: list[ProvenanceTag] = []
    for item in plan:
        evidence = [catalog[key] for key in item["evidence_keys"] if key in catalog]
        state = _resolve_state(item["mode"], evidence, item["text"])
        confidence = 1.0 if state == "verified" else 0.72 if state == "speculative" else 0.95
        note = (
            "Grounded in local fact sources."
            if state == "verified"
            else "Contains inference or partial grounding."
            if state == "speculative"
            else "Pure narrative phrasing without factual load."
        )
        tags.append(
            ProvenanceTag(
                text=item["text"],
                state=state,
                evidence=evidence,
                confidence=confidence,
                notes=note,
            )
        )
    return tags
