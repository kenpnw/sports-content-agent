from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Callable

from content.nba_postgame import build_douyin_package, build_hupu_package
from core.models import NBAPostgameData
from media.social_cards import create_postgame_poster
from publishers.douyin import prepare_douyin_publish
from publishers.hupu import prepare_hupu_publish
from storage.file_store import ensure_dir, read_text, timestamp_slug, write_json, write_text


WorkflowCallback = Callable[[str, str, str, dict[str, Any] | None], None]


def _emit(callback: WorkflowCallback | None, stage: str, status: str, message: str, payload: dict[str, Any] | None = None) -> None:
    if callback:
        callback(stage, status, message, payload)


def _load_game(path: str) -> NBAPostgameData:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return NBAPostgameData.from_dict(payload)


def _headline(game: NBAPostgameData) -> str:
    return getattr(game.analysis, "headline", "").strip() or f"{game.winner}赛后复盘"


def _write_hupu_package(root: Path, package: dict) -> dict:
    ensure_dir(root)
    write_json(root / "package.json", package)
    write_text(root / "article.md", package["article_markdown"])
    return {
        "folder": str(root),
        "title": package["title"],
        "files": ["package.json", "article.md"],
        "preview": package["article_markdown"],
    }


def _write_douyin_package(root: Path, package: dict) -> dict:
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


def run_nba_postgame_workflow(
    input_path: str,
    output_dir: str,
    callback: WorkflowCallback | None = None,
) -> dict:
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

    stamp = timestamp_slug()
    root = ensure_dir(Path(output_dir) / "nba_postgame" / stamp)

    _emit(callback, "generate_content", "running", "Generating Hupu and Douyin content packages.")
    hupu_package = build_hupu_package(game)
    douyin_package = build_douyin_package(game)
    _emit(callback, "generate_content", "completed", "Platform content packages generated.")

    _emit(callback, "generate_assets", "running", "Rendering visual asset pack for publishing.")
    poster_path = create_postgame_poster(game, _headline(game), str(root / "assets" / "douyin_poster.png"))
    assets = {"douyin_poster": poster_path}
    _emit(callback, "generate_assets", "completed", "Poster asset ready.", assets)

    _emit(callback, "write_packages", "running", "Writing content packages to disk.")
    hupu_summary = _write_hupu_package(root / "hupu", hupu_package)
    douyin_summary = _write_douyin_package(root / "douyin", douyin_package)
    _emit(callback, "write_packages", "completed", "Content packages saved.")

    _emit(callback, "prepare_publish", "running", "Preparing Hupu and Douyin publish plans.")
    hupu_publish = prepare_hupu_publish(root / "hupu", hupu_package)
    douyin_publish = prepare_douyin_publish(root / "douyin", douyin_package, assets)
    _emit(callback, "prepare_publish", "completed", "Publish plans created.", {"hupu": hupu_publish, "douyin": douyin_publish})

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
        "assets": assets,
        "platforms": {
            "hupu": {**hupu_summary, "publish": hupu_publish},
            "douyin": {**douyin_summary, "publish": douyin_publish},
        },
    }
    write_json(root / "summary.json", summary)
    _emit(callback, "workflow", "completed", "Workflow finished successfully.", summary)
    return summary
