"""CLI for generating social media packages from Video Scout outputs."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from social_packager import douyin_script, hupu_thread, weibo_card, xiaohongshu_post
from social_packager.repurpose import SocialPackage, load_json, write_json


PACKERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], SocialPackage]] = {
    "hupu": hupu_thread.pack,
    "douyin": douyin_script.pack,
    "weibo": weibo_card.pack,
    "xiaohongshu": xiaohongshu_post.pack,
}

MARKDOWN_FILENAMES = {
    "hupu": "post.md",
    "douyin": "script.md",
    "weibo": "post.md",
    "xiaohongshu": "post.md",
}


def run_social_packager(
    *,
    report_path: str | Path,
    clip_manifest_path: str | Path,
    platforms: list[str],
    output_dir: str | Path | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Generate selected platform packages and write markdown/json artifacts."""
    report = load_json(report_path)
    clip_manifest = load_json(clip_manifest_path)
    target = Path(output_dir) if output_dir else Path("data/generated/social") / datetime.now().strftime("%Y%m%d_%H%M%S")
    target.mkdir(parents=True, exist_ok=True)

    packages: list[SocialPackage] = []
    for platform in platforms:
        if platform not in PACKERS:
            raise ValueError(f"Unsupported platform: {platform}")
        package = PACKERS[platform](report, clip_manifest, use_llm=use_llm)
        platform_dir = target / platform
        platform_dir.mkdir(parents=True, exist_ok=True)
        markdown_name = MARKDOWN_FILENAMES[platform]
        (platform_dir / markdown_name).write_text(_markdown_for(package), encoding="utf-8")
        write_json(platform_dir / "package.json", package.to_dict())
        packages.append(package)

    summary = {
        "report_path": str(report_path),
        "clip_manifest_path": str(clip_manifest_path),
        "output_dir": str(target.resolve()),
        "platforms": [item.platform for item in packages],
        "package_count": len(packages),
        "packages": [
            {
                "platform": item.platform,
                "title": item.title,
                "media_count": len(item.media_paths),
                "markdown_path": str((target / item.platform / MARKDOWN_FILENAMES[item.platform]).resolve()),
                "package_json_path": str((target / item.platform / "package.json").resolve()),
                "llm_used": bool(item.metadata.get("llm_used", False)),
                "fallback_reason": item.metadata.get("fallback_reason", ""),
            }
            for item in packages
        ],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(target / "summary.json", summary)
    return summary


def _markdown_for(package: SocialPackage) -> str:
    lines = [
        f"# {package.title}",
        "",
        package.body.strip(),
        "",
        "## Media",
    ]
    lines.extend([f"- {path}" for path in package.media_paths] or ["- 无"])
    if package.hashtags:
        lines.extend(["", "## Hashtags", " ".join(f"#{tag}" for tag in package.hashtags)])
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate social media packages from Video Scout report artifacts.")
    parser.add_argument("--report", required=True, help="Video Scout report.json path.")
    parser.add_argument("--clip-manifest", required=True, help="Video Scout clip_manifest.json path.")
    parser.add_argument("--platforms", default="hupu,douyin,weibo,xiaohongshu", help="Comma-separated platforms.")
    parser.add_argument("--output", default="", help="Output directory; defaults to data/generated/social/<timestamp>.")
    parser.add_argument("--use-llm", action="store_true", help="Use realtime.llm_client for platform rewriting; fallback if unavailable.")
    return parser.parse_args()


def _parse_platforms(value: str) -> list[str]:
    platforms = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return platforms or ["hupu", "douyin", "weibo", "xiaohongshu"]


def main() -> None:
    args = parse_args()
    summary = run_social_packager(
        report_path=args.report,
        clip_manifest_path=args.clip_manifest,
        platforms=_parse_platforms(args.platforms),
        output_dir=args.output or None,
        use_llm=args.use_llm,
    )
    import json

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
