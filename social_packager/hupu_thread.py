"""Hupu long-thread packager for tactical review reports."""

from __future__ import annotations

from typing import Any

from social_packager.repurpose import (
    SocialPackage,
    SocialRepurposer,
    clip_lines,
    clip_media_paths,
    normalize_title,
    top_players,
)


def pack(report: dict[str, Any], clip_manifest: dict[str, Any], *, use_llm: bool = True) -> SocialPackage:
    repurposer = SocialRepurposer(use_llm=use_llm)
    clips = repurposer.select_clips_for_platform(clip_manifest, "hupu", max=2)
    takeaways = repurposer.extract_key_takeaways(report, max=5)
    title = f"赛后复盘：雷霆108-90湖人，霍姆格伦这场把湖人空间问题打明白了"
    fallback = _fallback_body(report, clips, takeaways)
    system = "你是虎扑篮球区资深版主型作者，写中文长帖，直接、懂球、能引导讨论。不要编造输入之外的事实。"
    user = (
        "请基于下面的真实战术报告，写一篇虎扑长帖，800-1500字，保留具体球员和战术细节，"
        "末尾给讨论引导。不要写成新闻通稿。\n\n"
        f"标题：{normalize_title(report)}\n"
        f"摘要：{report.get('executive_summary','')}\n"
        f"MVP：{report.get('mvp_analysis','')}\n"
        f"关键点：{takeaways}\n"
        f"片段：{clip_lines(clips)}"
    )
    body, meta = repurposer.maybe_llm_rewrite(
        platform="hupu",
        system=system,
        user=user,
        fallback=fallback,
        max_tokens=1800,
    )
    if len(body) < 650:
        body = fallback
        meta = {**meta, "fallback_reason": meta.get("fallback_reason") or "hupu_body_too_short"}
    return SocialPackage(
        platform="hupu",
        title=title,
        body=body,
        media_paths=clip_media_paths(clips),
        hashtags=["NBA", "雷霆", "湖人", "战术复盘"],
        provenance=repurposer.provenance_for(report, clips),
        metadata={"content_type": "thread", **meta},
    )


def _fallback_body(report: dict[str, Any], clips: list[dict[str, Any]], takeaways: list[str]) -> str:
    players = top_players(report)
    lines = [
        "这场雷霆108-90赢湖人，表面看是分差拉开，底层其实是两个问题叠在一起：雷霆的空间点更多，湖人的进攻容错更低。",
        "",
        report.get("executive_summary", ""),
        "",
        "先说最关键的人：霍姆格伦。报告里给到的是24分12篮板3盖帽0失误，他不只是终结点，也是改变湖人防守站位的人。湖人一收缩，他能外弹投三分；湖人一外扩，他又能从弱侧空切到篮下。这个点一旦被打开，湖人的协防就会变得很难受。",
        "",
        "几个回合很能说明问题：",
    ]
    for line in clip_lines(clips):
        lines.append(f"- {line}")
    lines.extend(
        [
            "",
            "我觉得这场的胜负手不是单纯“谁手感更好”，而是雷霆把每一次湖人轮转慢半拍都转成了实打实的空间收益。多尔特、杰伦、麦凯恩这些点能把球投进，湖人就不能只盯着SGA和霍姆格伦。",
            "",
            "湖人这边，詹姆斯效率很高，但这反而说明问题：当主要解法还是詹姆斯硬解，其他点没法稳定把空间撑起来，雷霆就敢更坚决地收缩、协防、保护篮板。里夫斯和斯马特的外线效率不够，很多回合打到最后只能变成高难度出手。",
            "",
            "这场可以提炼成三句话：",
        ]
    )
    lines.extend([f"1. {item}" for item in takeaways[:3]])
    if players:
        lines.extend(["", "几个球员侧重点："])
        lines.extend([f"- {item}" for item in players])
    lines.extend(
        [
            "",
            "所以问题来了：湖人下一场要优先解决的是外线空间，还是减少失误？如果继续让詹姆斯高效但其他点断电，这轮系列赛会不会很快被雷霆的阵容深度拖垮？",
        ]
    )
    return "\n".join(lines)
