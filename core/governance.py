from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from config import DATA_DIR
from storage.file_store import read_json


GOVERNANCE_PATH = DATA_DIR / "standards" / "governance.json"


@dataclass
class PromptPolicy:
    required_sections: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    claim_min_evidence_points: int = 2
    primary_claim_min_confidence: float = 0.8
    publish_min_topic_score: float = 65.0


@dataclass
class RagPolicy:
    source_priority: list[str] = field(default_factory=list)
    mandatory_metadata: list[str] = field(default_factory=list)
    freshness_rules: dict[str, int] = field(default_factory=dict)
    chunk_rules: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentRole:
    name: str
    responsibility: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    reviewed_by: str = ""


@dataclass
class GovernancePolicy:
    version: str
    prompt_policy: PromptPolicy
    rag_policy: RagPolicy
    agent_roles: list[AgentRole]

    def role_map(self) -> dict[str, AgentRole]:
        return {role.name: role for role in self.agent_roles}

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "prompt_policy": {
                "claim_min_evidence_points": self.prompt_policy.claim_min_evidence_points,
                "primary_claim_min_confidence": self.prompt_policy.primary_claim_min_confidence,
                "publish_min_topic_score": self.prompt_policy.publish_min_topic_score,
                "required_sections": self.prompt_policy.required_sections,
                "forbidden_patterns": self.prompt_policy.forbidden_patterns,
            },
            "rag_policy": {
                "source_priority": self.rag_policy.source_priority,
                "mandatory_metadata": self.rag_policy.mandatory_metadata,
                "freshness_rules": self.rag_policy.freshness_rules,
                "chunk_rules": self.rag_policy.chunk_rules,
            },
            "agent_roles": [
                {
                    "name": role.name,
                    "responsibility": role.responsibility,
                    "inputs": role.inputs,
                    "outputs": role.outputs,
                    "reviewed_by": role.reviewed_by,
                }
                for role in self.agent_roles
            ],
        }


def load_governance_policy(path: Path = GOVERNANCE_PATH) -> GovernancePolicy:
    payload = read_json(path)
    prompt_payload = payload.get("prompt_policy", {})
    rag_payload = payload.get("rag_policy", {})
    roles_payload = payload.get("agent_roles", [])
    return GovernancePolicy(
        version=str(payload.get("version", "1.0")),
        prompt_policy=PromptPolicy(
            required_sections=[str(item) for item in prompt_payload.get("required_sections", [])],
            forbidden_patterns=[str(item) for item in prompt_payload.get("forbidden_patterns", [])],
            claim_min_evidence_points=int(prompt_payload.get("claim_min_evidence_points", 2)),
            primary_claim_min_confidence=float(prompt_payload.get("primary_claim_min_confidence", 0.8)),
            publish_min_topic_score=float(prompt_payload.get("publish_min_topic_score", 65.0)),
        ),
        rag_policy=RagPolicy(
            source_priority=[str(item) for item in rag_payload.get("source_priority", [])],
            mandatory_metadata=[str(item) for item in rag_payload.get("mandatory_metadata", [])],
            freshness_rules={str(key): int(value) for key, value in rag_payload.get("freshness_rules", {}).items()},
            chunk_rules={str(key): int(value) for key, value in rag_payload.get("chunk_rules", {}).items()},
        ),
        agent_roles=[
            AgentRole(
                name=str(item.get("name", "")),
                responsibility=str(item.get("responsibility", "")),
                inputs=[str(value) for value in item.get("inputs", [])],
                outputs=[str(value) for value in item.get("outputs", [])],
                reviewed_by=str(item.get("reviewed_by", "")),
            )
            for item in roles_payload
            if isinstance(item, dict)
        ],
    )
