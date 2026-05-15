"""Xiaohongshu image-text note packager."""

from __future__ import annotations

from typing import Any

from social_packager.repurpose import SocialPackage, SocialRepurposer, clip_lines, clip_media_paths


def pack(report: dict[str, Any], clip_manifest: dict[str, Any], *, use_llm: bool = True) -> SocialPackage:
    repurposer = SocialRepurposer(use_llm=use_llm)
    clips = repurposer.select_clips_for_platform(clip_manifest, "xiaohongshu", max=4)
    takeaways = repurposer.extract_key_takeaways(report, max=4)
    title = "雷霆vs湖人G1｜这场不是简单大胜，是空间被打穿"
    fallback = _fallback_body(report, clips, takeaways)
    system = "你是小红书篮球图文作者，写200-400字中文笔记，可用emoji，语气清楚但不夸张，不编造事实。"
    user = (
        "基于真实战术报告写小红书图文笔记，包含3-4个GIF顺序提示、emoji和tag。\n"
        f"摘要：{report.get('executive_summary','')}\n"
        f"关键点：{takeaways}\n"
        f"片段：{clip_lines(clips)}"
    )
    body, meta = repurposer.maybe_llm_rewrite(
        platform="xiaohongshu",
        system=system,
        user=user,
        fallback=fallback,
        max_tokens=800,
    )
    return SocialPackage(
        platform="xiaohongshu",
        title=title,
        body=body,
        media_paths=clip_media_paths(clips),
        hashtags=["NBA季后赛", "雷霆", "湖人", "篮球战术", "霍姆格伦"],
        provenance=repurposer.provenance_for(report, clips),
        metadata={"content_type": "image_text_note", **meta},
    )


def _fallback_body(report: dict[str, Any], clips: list[dict[str, Any]], takeaways: list[str]) -> str:
    lines = [
        "🏀 雷霆108-90湖人，这场真的不只是“大胜”这么简单。",
        "",
        "最值得看的是霍姆格伦这个点：24分12篮板3盖帽0失误。他一外弹，湖人内线就不敢死守；他一空切，湖人弱侧协防又会慢半拍。",
        "",
        "📌 我会按这几个GIF看：",
    ]
    for line in clip_lines(clips)[:4]:
        lines.append(f"- {line.splitlines()[0]}")
    lines.extend(
        [
            "",
            "几个结论：",
            *(f"✨ {item}" for item in takeaways[:3]),
            "",
            "湖人下一场如果外线空间和失误控制不改善，只靠詹姆斯高效硬解会很累。",
            "",
            "#NBA季后赛 #雷霆 #湖人 #霍姆格伦 #篮球战术",
        ]
    )
    return "\n".join(lines)
