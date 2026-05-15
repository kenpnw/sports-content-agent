"""Douyin 60-second script packager."""

from __future__ import annotations

from typing import Any

from social_packager.repurpose import SocialPackage, SocialRepurposer, clip_lines, clip_media_paths


def pack(report: dict[str, Any], clip_manifest: dict[str, Any], *, use_llm: bool = True) -> SocialPackage:
    repurposer = SocialRepurposer(use_llm=use_llm)
    clips = repurposer.select_clips_for_platform(clip_manifest, "douyin", max=2)
    takeaways = repurposer.extract_key_takeaways(report, max=4)
    title = "雷霆大胜湖人，关键不是比分，是霍姆格伦把空间打穿了"
    fallback = _fallback_body(report, clips, takeaways)
    system = "你是抖音篮球短视频编导，写60秒中文口播和镜头分镜。短句、口语、强节奏，不编造事实。"
    user = (
        "基于真实战术报告生成60秒抖音脚本，包含标题、口播、镜头分镜、1-2个GIF引用、hashtag。\n"
        f"摘要：{report.get('executive_summary','')}\n"
        f"MVP：{report.get('mvp_analysis','')}\n"
        f"关键点：{takeaways}\n"
        f"片段：{clip_lines(clips)}"
    )
    body, meta = repurposer.maybe_llm_rewrite(
        platform="douyin",
        system=system,
        user=user,
        fallback=fallback,
        max_tokens=1000,
    )
    return SocialPackage(
        platform="douyin",
        title=title,
        body=body,
        media_paths=clip_media_paths(clips),
        hashtags=["NBA季后赛", "雷霆湖人", "霍姆格伦", "战术复盘"],
        provenance=repurposer.provenance_for(report, clips),
        metadata={"content_type": "60s_script", **meta},
    )


def _fallback_body(report: dict[str, Any], clips: list[dict[str, Any]], takeaways: list[str]) -> str:
    media = clip_lines(clips)
    return "\n".join(
        [
            "标题：雷霆108-90湖人，真正打穿比赛的是霍姆格伦这个点",
            "",
            "60秒口播：",
            "开场3秒：雷霆赢湖人18分，但这场别只看比分。",
            "第4-15秒：霍姆格伦24分12篮板3盖帽0失误，他最麻烦的地方不是高，而是能把湖人防守拉到两难。",
            "第16-30秒：湖人一收缩，他外弹投三分；湖人一外扩，他弱侧空切吃饼。雷霆的空间就这样被打开。",
            "第31-45秒：詹姆斯效率很高，但湖人整体外线和失误控制没跟上，很多回合只能靠个人硬解。",
            "第46-60秒：所以这场的核心问题是：湖人下一场先救空间，还是先控失误？",
            "",
            "镜头分镜：",
            f"1. 开头放比分和标题卡：{report.get('title','OKC vs LAL')}",
            *(f"{index + 2}. GIF片段：{line}" for index, line in enumerate(media)),
            "",
            "Hashtag：#NBA季后赛 #雷霆湖人 #霍姆格伦 #战术复盘",
        ]
    )
