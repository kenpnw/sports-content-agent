from __future__ import annotations

from typing import Any

from core.models import NBAPostgameData
from storage.text_rag_store import TextRagStore


def _team_queries(game: NBAPostgameData) -> list[str]:
    return [
        f"{game.away_team.name} {game.home_team.name}",
        game.home_team.name,
        game.away_team.name,
        f"{game.winner} 赛后",
        f"{game.game_date} {game.home_team.name}",
    ]


def build_research_packet(
    game: NBAPostgameData,
    knowledge_context: dict[str, Any],
    text_rag_store: TextRagStore,
    source_priority: list[str] | None = None,
) -> dict[str, Any]:
    source_types = source_priority[:4] if source_priority else None
    seen_doc_ids: set[str] = set()
    document_hits: list[dict[str, Any]] = []

    for query in _team_queries(game):
        for hit in text_rag_store.search(query=query, sport=game.league, limit=3, source_types=source_types):
            if hit["doc_id"] in seen_doc_ids:
                continue
            seen_doc_ids.add(hit["doc_id"])
            document_hits.append(hit)
        if len(document_hits) >= 5:
            break

    evidence_lines = []
    for hit in document_hits[:3]:
        evidence_lines.append(f"{hit['title']} ({hit['source_type']})：{hit['excerpt']}")

    return {
        "query_terms": _team_queries(game),
        "text_rag_hits": document_hits[:5],
        "text_evidence_lines": evidence_lines,
        "fact_context_summary": [
            knowledge_context.get("home_team", {}).get("summary", ""),
            knowledge_context.get("away_team", {}).get("summary", ""),
            knowledge_context.get("head_to_head", {}).get("summary", ""),
        ],
    }
