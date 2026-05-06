from __future__ import annotations

from typing import Any

from core.governance import GovernancePolicy


def build_agent_prompt_contracts(policy: GovernancePolicy, platform: str | None = None) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    platform_scope = platform or "all"
    for role in policy.agent_roles:
        contracts[role.name] = {
            "role": role.name,
            "platform_scope": platform_scope,
            "responsibility": role.responsibility,
            "allowed_inputs": role.inputs,
            "required_outputs": role.outputs,
            "reviewed_by": role.reviewed_by,
            "must_include": list(policy.prompt_policy.required_sections),
            "must_avoid": list(policy.prompt_policy.forbidden_patterns),
            "claim_min_evidence_points": policy.prompt_policy.claim_min_evidence_points,
            "primary_claim_min_confidence": policy.prompt_policy.primary_claim_min_confidence,
            "rag_source_priority": list(policy.rag_policy.source_priority),
        }
    return contracts
