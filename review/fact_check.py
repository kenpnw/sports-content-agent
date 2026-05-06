from __future__ import annotations

from typing import Any

from core.governance import GovernancePolicy


def review_topic_engine(topic_engine: dict[str, Any], policy: GovernancePolicy) -> dict[str, Any]:
    findings: list[str] = []
    warnings: list[str] = []
    required_evidence = policy.prompt_policy.claim_min_evidence_points
    required_confidence = policy.prompt_policy.primary_claim_min_confidence

    for claim in topic_engine.get("evidence_claims", []):
        evidence_count = len(claim.get("evidence", []))
        confidence = float(claim.get("confidence_score", 0))
        if evidence_count < required_evidence:
            findings.append(f"主张“{claim.get('claim', '')}”的证据点不足，当前只有 {evidence_count} 个。")
        if confidence < required_confidence:
            findings.append(f"主张“{claim.get('claim', '')}”的置信度 {confidence:.2f} 低于阈值 {required_confidence:.2f}。")

    global_score = float(topic_engine.get("global_topic_score", 0))
    if global_score < policy.prompt_policy.publish_min_topic_score:
        warnings.append(
            f"这场比赛的总选题分只有 {global_score:.1f}，低于建议发布阈值 {policy.prompt_policy.publish_min_topic_score:.1f}。"
        )

    status = "pass"
    if findings:
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "reviewer": "fact_checker",
        "status": status,
        "findings": findings,
        "warnings": warnings,
        "checked_items": {
            "claim_min_evidence_points": required_evidence,
            "primary_claim_min_confidence": required_confidence,
            "publish_min_topic_score": policy.prompt_policy.publish_min_topic_score,
        },
    }


def review_platform_package(
    platform: str,
    package: dict[str, Any],
    topic_engine: dict[str, Any],
    policy: GovernancePolicy,
) -> dict[str, Any]:
    findings: list[str] = []
    warnings: list[str] = []

    if platform == "hupu":
        content = str(package.get("article_markdown", ""))
    else:
        scene_text = " ".join(scene.get("voiceover", "") for scene in package.get("short_video_script", []))
        content = scene_text + " " + str(package.get("caption", ""))

    title = str(package.get("title", ""))
    if not title.strip():
        findings.append("标题为空。")
    if topic_engine.get("recommended_angle") and topic_engine["recommended_angle"] not in content:
        warnings.append("平台内容没有显式体现推荐角度，可以考虑加强主线一致性。")

    primary_driver = ""
    structured_data = package.get("structured_data", {})
    analysis = structured_data.get("analysis", {}) if isinstance(structured_data, dict) else {}
    if isinstance(analysis, dict):
        primary_driver = str(analysis.get("primary_driver", ""))
    if primary_driver and primary_driver not in content:
        warnings.append(f"平台内容未明确点出主赢球逻辑“{primary_driver}”。")

    status = "pass"
    if findings:
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "reviewer": "fact_checker",
        "platform": platform,
        "status": status,
        "findings": findings,
        "warnings": warnings,
    }
