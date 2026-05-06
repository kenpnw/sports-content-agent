from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from analysis.editorial_lab import build_editorial_lab
from analysis.research_router import build_research_packet
from analysis.topic_engine import score_game_topic
from content.nba_postgame import build_douyin_package, build_hupu_package
from core.governance import load_governance_policy
from core.models import NBAPostgameData
from core.prompt_contracts import build_agent_prompt_contracts
from media.social_cards import create_postgame_poster
from publishers.douyin import prepare_douyin_publish
from publishers.hupu import prepare_hupu_publish
from review.fact_check import review_platform_package, review_topic_engine
from review.risk_guard import review_platform_risk
from storage.file_store import ensure_dir, timestamp_slug, write_json, write_text
from storage.knowledge_store import FactStore
from storage.text_rag_store import TextRagStore


WorkflowCallback = Callable[[str, str, str, dict[str, Any] | None], None]


def _emit(
    callback: WorkflowCallback | None,
    stage: str,
    status: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if callback:
        callback(stage, status, message, payload)


def _load_game(path: str) -> NBAPostgameData:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return NBAPostgameData.from_dict(payload)


def _headline(game: NBAPostgameData) -> str:
    return getattr(game.analysis, "headline", "").strip() or f"{game.winner}赛后复盘"


def _write_hupu_package(root: Path, package: dict[str, Any]) -> dict[str, Any]:
    ensure_dir(root)
    write_json(root / "package.json", package)
    write_text(root / "article.md", package["article_markdown"])
    return {
        "folder": str(root),
        "title": package["title"],
        "files": ["package.json", "article.md"],
        "preview": package["article_markdown"],
    }


def _write_douyin_package(root: Path, package: dict[str, Any]) -> dict[str, Any]:
    ensure_dir(root)
    write_json(root / "package.json", package)
    script_lines = []
    for scene in package["short_video_script"]:
        script_lines.extend(
            [
                f"Scene {scene['scene']} ({scene['duration_seconds']}s)",
                f"Visual: {scene['visual']}",
                f"VO: {scene['voiceover']}",
                "",
            ]
        )
    script_lines.extend(
        [
            f"Caption: {package['caption']}",
            "Hashtags: " + " ".join(package["hashtags"]),
            f"Cover: {package['cover_text']}",
        ]
    )
    script_content = "\n".join(script_lines)
    write_text(root / "script.md", script_content)
    return {
        "folder": str(root),
        "title": package["title"],
        "files": ["package.json", "script.md"],
        "preview": script_content,
    }


def _apply_review_gate(
    publish_plan: dict[str, Any],
    fact_check_report: dict[str, Any],
    risk_report: dict[str, Any],
) -> dict[str, Any]:
    gated = dict(publish_plan)
    notes = list(gated.get("notes", []))
    if fact_check_report.get("status") == "fail" or risk_report.get("status") == "fail":
        gated["status"] = "blocked_by_review"
        gated["mode"] = f"{gated.get('mode', 'review')}_blocked"
        notes.append("Publishing is blocked because supervision failed.")
    elif fact_check_report.get("status") == "warn" or risk_report.get("status") == "warn":
        gated["status"] = "needs_editor_review"
        notes.append("Publishing requires editor review because supervision raised warnings.")

    for line in fact_check_report.get("findings", []) + fact_check_report.get("warnings", []):
        notes.append(f"fact_check: {line}")
    for line in risk_report.get("findings", []) + risk_report.get("warnings", []):
        notes.append(f"risk_guard: {line}")
    gated["notes"] = notes
    return gated


def run_nba_postgame_workflow(
    input_path: str,
    output_dir: str,
    callback: WorkflowCallback | None = None,
    selection_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _emit(callback, "workflow", "started", "NBA postgame workflow started.", {"input": input_path})

    _emit(callback, "load_input", "running", "Loading normalized NBA input.")
    game = _load_game(input_path)
    _emit(
        callback,
        "load_input",
        "completed",
        "Normalized game data loaded.",
        {
            "winner": game.winner,
            "home_team": game.home_team.name,
            "away_team": game.away_team.name,
        },
    )

    _emit(callback, "governance", "running", "Loading prompt policy, RAG standards, and agent supervision contracts.")
    governance = load_governance_policy()
    prompt_contracts = build_agent_prompt_contracts(governance, platform="hupu,douyin")
    _emit(
        callback,
        "governance",
        "completed",
        "Governance policy loaded.",
        {
            "version": governance.version,
            "roles": [role.name for role in governance.agent_roles],
        },
    )

    _emit(callback, "knowledge_layer", "running", "Refreshing fact store and text RAG store.")
    fact_store = FactStore()
    fact_store.initialize()
    bootstrapped_facts = fact_store.bootstrap_from_workspace(exclude_paths={input_path})
    fact_store.ingest_postgame(game)
    knowledge_context = fact_store.build_game_context(game)

    text_rag_store = TextRagStore()
    text_rag_store.initialize()
    bootstrapped_docs = text_rag_store.bootstrap_from_directory(
        chunk_target=governance.rag_policy.chunk_rules.get("target_chars", 900),
        overlap=governance.rag_policy.chunk_rules.get("overlap_chars", 120),
        max_chunks_per_doc=governance.rag_policy.chunk_rules.get("max_chunks_per_doc", 12),
    )
    research_packet = build_research_packet(
        game=game,
        knowledge_context=knowledge_context,
        text_rag_store=text_rag_store,
        source_priority=governance.rag_policy.source_priority,
    )
    topic_recommendation = score_game_topic(game, knowledge_context)
    _emit(
        callback,
        "knowledge_layer",
        "completed",
        "Fact store, text RAG, and topic engine output are ready.",
        {
            "bootstrapped_facts": bootstrapped_facts,
            "bootstrapped_text_docs": bootstrapped_docs,
            "global_topic_score": topic_recommendation["global_topic_score"],
            "recommended_angle": topic_recommendation["recommended_angle"],
            "selected_tier": topic_recommendation["selected_tier"],
        },
    )

    _emit(callback, "editorial_lab", "running", "Building opportunity board, controversy simulator, and season storyline tree.")
    editorial_lab = build_editorial_lab(
        game=game,
        knowledge_context=knowledge_context,
        topic_recommendation=topic_recommendation,
        selection_context=selection_context,
    )
    _emit(
        callback,
        "editorial_lab",
        "completed",
        "Editorial lab outputs are ready.",
        {
            "opportunity_headline": editorial_lab["opportunity_board"]["headline"],
            "contrarian_claim": editorial_lab["contrarian_finder"]["claim"],
            "storyline_root": editorial_lab["season_storyline_tree"]["root"],
        },
    )

    stamp = timestamp_slug()
    root = ensure_dir(Path(output_dir) / "nba_postgame" / stamp)

    _emit(callback, "generate_content", "running", "Generating Hupu and Douyin content packages.")
    hupu_package = build_hupu_package(
        game,
        knowledge_context=knowledge_context,
        topic_recommendation=topic_recommendation,
        research_packet=research_packet,
        editorial_lab=editorial_lab,
    )
    douyin_package = build_douyin_package(
        game,
        knowledge_context=knowledge_context,
        topic_recommendation=topic_recommendation,
        research_packet=research_packet,
        editorial_lab=editorial_lab,
    )
    _emit(callback, "generate_content", "completed", "Platform content packages generated.")

    _emit(callback, "supervision", "running", "Running fact-checker and risk-guard supervision.")
    topic_fact_check = review_topic_engine(topic_recommendation, governance)
    hupu_fact_check = review_platform_package("hupu", hupu_package, topic_recommendation, governance)
    douyin_fact_check = review_platform_package("douyin", douyin_package, topic_recommendation, governance)
    hupu_risk = review_platform_risk("hupu", hupu_package, hupu_fact_check, governance)
    douyin_risk = review_platform_risk("douyin", douyin_package, douyin_fact_check, governance)
    supervision = {
        "topic_engine": topic_fact_check,
        "platforms": {
            "hupu": {"fact_check": hupu_fact_check, "risk_guard": hupu_risk},
            "douyin": {"fact_check": douyin_fact_check, "risk_guard": douyin_risk},
        },
    }
    _emit(
        callback,
        "supervision",
        "completed",
        "Supervision reports generated.",
        {
            "topic_engine": topic_fact_check["status"],
            "hupu": hupu_risk["status"],
            "douyin": douyin_risk["status"],
        },
    )

    _emit(callback, "generate_assets", "running", "Rendering visual asset pack for publishing.")
    poster_path = create_postgame_poster(game, _headline(game), str(root / "assets" / "douyin_poster.png"))
    assets = {"douyin_poster": poster_path}
    _emit(callback, "generate_assets", "completed", "Poster asset ready.", assets)

    _emit(callback, "write_packages", "running", "Writing content packages to disk.")
    hupu_summary = _write_hupu_package(root / "hupu", hupu_package)
    douyin_summary = _write_douyin_package(root / "douyin", douyin_package)
    _emit(callback, "write_packages", "completed", "Content packages saved.")

    _emit(callback, "prepare_publish", "running", "Preparing Hupu and Douyin publish plans.")
    hupu_publish = _apply_review_gate(
        prepare_hupu_publish(root / "hupu", hupu_package),
        hupu_fact_check,
        hupu_risk,
    )
    douyin_publish = _apply_review_gate(
        prepare_douyin_publish(root / "douyin", douyin_package, assets),
        douyin_fact_check,
        douyin_risk,
    )
    _emit(
        callback,
        "prepare_publish",
        "completed",
        "Publish plans created.",
        {"hupu": hupu_publish, "douyin": douyin_publish},
    )

    summary = {
        "workflow": "nba_postgame",
        "input": input_path,
        "output_root": str(root),
        "game": {
            "winner": game.winner,
            "scoreline": f"{game.away_team.name} {game.away_team.score} - {game.home_team.score} {game.home_team.name}",
            "date": game.game_date,
            "venue": game.venue,
            "headline": getattr(game.analysis, "headline", ""),
            "primary_driver": getattr(game.analysis, "primary_driver", ""),
        },
        "selection": selection_context or {},
        "governance": governance.summary(),
        "prompt_contracts": prompt_contracts,
        "knowledge_context": knowledge_context,
        "research_packet": research_packet,
        "topic_engine": topic_recommendation,
        "editorial_lab": editorial_lab,
        "supervision": supervision,
        "assets": assets,
        "platforms": {
            "hupu": {**hupu_summary, "publish": hupu_publish},
            "douyin": {**douyin_summary, "publish": douyin_publish},
        },
    }
    write_json(root / "summary.json", summary)
    _emit(callback, "workflow", "completed", "Workflow finished successfully.", summary)
    return summary
