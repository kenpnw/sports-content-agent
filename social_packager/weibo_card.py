"""Weibo short-card packager."""

from __future__ import annotations

from typing import Any

from social_packager.repurpose import SocialPackage, SocialRepurposer, clip_media_paths, safe_weibo


def pack(report: dict[str, Any], clip_manifest: dict[str, Any], *, use_llm: bool = True) -> SocialPackage:
    repurposer = SocialRepurposer(use_llm=use_llm)
    clips = repurposer.select_clips_for_platform(clip_manifest, "weibo", max=1)
    fallback = safe_weibo(
        "雷霆108-90湖人，霍姆格伦24分12板3帽0失误是胜负手。"
        "湖人不是输在詹姆斯，是真正被雷霆的空间、空切和外线轮转惩罚了。#NBA季后赛# #雷霆湖人#"
    )
    system = "你是微博篮球账号编辑。写一条不超过140字的中文微博，必须有话题，不能编造事实。"
    user = f"报告摘要：{report.get('executive_summary','')}\nMVP：{report.get('mvp_analysis','')}\n请输出一条微博正文。"
    body, meta = repurposer.maybe_llm_rewrite(
        platform="weibo",
        system=system,
        user=user,
        fallback=fallback,
        max_tokens=240,
    )
    body = safe_weibo(body)
    return SocialPackage(
        platform="weibo",
        title="雷霆大胜湖人",
        body=body,
        media_paths=clip_media_paths(clips),
        hashtags=["NBA季后赛", "雷霆湖人"],
        provenance=repurposer.provenance_for(report, clips),
        metadata={"content_type": "weibo_card", "char_count": len(body), **meta},
    )
