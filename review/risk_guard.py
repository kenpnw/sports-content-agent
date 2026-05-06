from __future__ import annotations

from typing import Any

from core.governance import GovernancePolicy


RISKY_TERMS = [
    "绝对",
    "必然",
    "100%",
    "注定",
    "吊打",
    "无解",
]


def review_platform_risk(
    platform: str,
    package: dict[str, Any],
    fact_check_report: dict[str, Any],
    policy: GovernancePolicy,
) -> dict[str, Any]:
    findings: list[str] = []
    warnings: list[str] = []

    if platform == "hupu":
        content = str(package.get("article_markdown", ""))
    else:
        content = " ".join(scene.get("voiceover", "") for scene in package.get("short_video_script", []))
        content += " " + str(package.get("caption", ""))

    for term in RISKY_TERMS + list(policy.prompt_policy.forbidden_patterns):
        if term and term in content:
            warnings.append(f"内容包含高风险表达或禁用模式：{term}")

    if fact_check_report.get("status") == "fail":
        findings.append("事实核查未通过，当前不应进入发布步骤。")
    elif fact_check_report.get("status") == "warn":
        warnings.append("事实核查存在警告，建议人工复核后再决定是否发布。")

    status = "pass"
    if findings:
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "reviewer": "risk_guard",
        "platform": platform,
        "status": status,
        "findings": findings,
        "warnings": warnings,
    }
