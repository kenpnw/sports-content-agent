"""Live commentary generation under governance and provenance constraints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.governance import GovernancePolicy, load_governance_policy
from core.prompt_contracts import build_agent_prompt_contracts
from realtime.llm_client import LLMClient, LLMResult
from realtime.models import Commentary, DetectedEvent
from realtime.provenance import build_evidence_catalog, tag_commentary


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "hupu": {
        "label": "Hupu discussion voice",
        "tone": "direct, sharp, discussion-friendly",
        "max_sentences": 2,
        "length_hint": "Keep it to 1-2 short sentences.",
    },
    "douyin": {
        "label": "Douyin short-form voice",
        "tone": "hook-first, emotional, punchy",
        "max_sentences": 2,
        "length_hint": "Make the opening hit fast. One strong beat is enough.",
    },
    "academic": {
        "label": "Analyst voice",
        "tone": "measured, analytical, low-hype",
        "max_sentences": 2,
        "length_hint": "Use concise analytical phrasing.",
    },
}


@dataclass
class LiveCommentaryPolicy:
    min_salience: float = 0.55
    cooldown_seconds: float = 20.0
    contract_id: str = "live_commentary.v1"


class LiveCommentator:
    """Generate one piece of commentary for a detected live event."""

    def __init__(
        self,
        *,
        client: LLMClient | None = None,
        governance: GovernancePolicy | None = None,
        policy: LiveCommentaryPolicy | None = None,
        default_style: str = "hupu",
        enable_llm: bool = True,
    ) -> None:
        self.governance = governance or load_governance_policy()
        self.policy = policy or LiveCommentaryPolicy()
        self.default_style = default_style if default_style in STYLE_PRESETS else "hupu"
        self.contracts = build_agent_prompt_contracts(self.governance, platform="live")
        if not enable_llm:
            self.client = None
        elif client is not None:
            self.client = client
        else:
            try:
                self.client = LLMClient.from_env()
            except Exception:
                self.client = None

    def should_emit(
        self,
        detected_event: DetectedEvent,
        *,
        last_commentary_at_seconds: float | None = None,
        produced_at_seconds: float = 0.0,
    ) -> bool:
        if detected_event.category == "routine":
            return False
        if detected_event.salience < self.policy.min_salience:
            return False
        if last_commentary_at_seconds is None:
            return True
        return (produced_at_seconds - last_commentary_at_seconds) >= self.policy.cooldown_seconds

    def generate_commentary(
        self,
        detected_event: DetectedEvent,
        *,
        produced_at_seconds: float = 0.0,
        style: str | None = None,
        fact_context: dict[str, Any] | None = None,
        research_packet: dict[str, Any] | None = None,
    ) -> Commentary:
        chosen_style = style if style in STYLE_PRESETS else self.default_style
        evidence_catalog = build_evidence_catalog(
            detected_event,
            fact_context=fact_context,
            research_packet=research_packet,
        )
        system_prompt, user_prompt = self._build_prompts(
            detected_event=detected_event,
            style=chosen_style,
            evidence_catalog=evidence_catalog,
            fact_context=fact_context,
            research_packet=research_packet,
        )

        payload: dict[str, Any]
        result: LLMResult | None = None
        fallback_reason = ""
        if self.client is None:
            fallback_reason = "LLM client unavailable; used deterministic fallback."
            payload = self._fallback_payload(detected_event, chosen_style)
        else:
            try:
                payload, result = self.client.generate_json(
                    system=system_prompt,
                    user=user_prompt,
                    contract_id=self.policy.contract_id,
                )
            except Exception as exc:
                fallback_reason = f"LLM call failed; used deterministic fallback. Error: {exc}"
                payload = self._fallback_payload(detected_event, chosen_style)

        commentary_text = self._extract_commentary_text(payload, detected_event, chosen_style)
        sentence_plan = payload.get("sentences")
        provenance = tag_commentary(
            commentary_text,
            detected_event,
            sentence_plan=sentence_plan if isinstance(sentence_plan, list) else None,
            fact_context=fact_context,
            research_packet=research_packet,
        )
        metadata: dict[str, Any] = {
            "style": chosen_style,
            "fallback_reason": fallback_reason,
            "evidence_catalog_keys": list(evidence_catalog.keys()),
        }
        if isinstance(payload.get("facts_used"), list):
            metadata["facts_used"] = [str(item) for item in payload.get("facts_used", [])]
        if isinstance(payload.get("notes"), list):
            metadata["notes"] = [str(item) for item in payload.get("notes", [])]
        if result is not None:
            metadata["usage"] = {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "finish_reason": result.finish_reason,
            }

        return Commentary(
            event=detected_event,
            style=chosen_style,
            raw_text=commentary_text,
            provenance=provenance,
            produced_at_seconds=produced_at_seconds,
            latency_seconds=result.latency_seconds if result else 0.0,
            prompt_contract_id=self.policy.contract_id,
            model=result.model if result else "fallback_template",
            metadata=metadata,
        )

    def _build_prompts(
        self,
        *,
        detected_event: DetectedEvent,
        style: str,
        evidence_catalog: dict[str, dict[str, Any]],
        fact_context: dict[str, Any] | None,
        research_packet: dict[str, Any] | None,
    ) -> tuple[str, str]:
        style_preset = STYLE_PRESETS[style]
        writer_contract = self.contracts.get("writer", {})
        prompt_policy = self.governance.prompt_policy
        catalog_lines = []
        for key, item in evidence_catalog.items():
            catalog_lines.append(
                f"- {key}: source={item['source']}; label={item['label']}; value={json.dumps(item['value'], ensure_ascii=False)}"
            )
        context_lines = []
        for summary in (fact_context or {}).values():
            if isinstance(summary, dict):
                text = str(summary.get("summary", "")).strip()
                if text:
                    context_lines.append(f"- {text}")
        for line in (research_packet or {}).get("text_evidence_lines", [])[:3]:
            context_lines.append(f"- {line}")

        system_prompt = (
            "You are a live basketball commentary assistant. "
            "Always respond in Simplified Chinese. "
            "You must only use supplied facts. "
            "Never fabricate scores, players, timing, or tactical outcomes. "
            "Return strict JSON with this schema: "
            '{"commentary":"...",'
            '"sentences":[{"text":"...","mode":"fact|narrative|speculative","evidence_keys":["..."]}],'
            '"facts_used":["..."],'
            '"notes":["..."]}. '
            "If a sentence contains a concrete fact or number, set mode=fact and attach evidence_keys. "
            "If a sentence is an inference grounded in supplied context, set mode=speculative. "
            "If a sentence is pure flavor with no factual burden, set mode=narrative."
        )

        user_prompt = (
            f"Task: generate live commentary for one detected basketball event.\n"
            f"Style label: {style_preset['label']}\n"
            f"Tone: {style_preset['tone']}\n"
            f"Length rule: {style_preset['length_hint']}\n"
            f"Minimum evidence points for a primary factual claim: {prompt_policy.claim_min_evidence_points}\n"
            f"Required output sections from governance: {', '.join(prompt_policy.required_sections)}\n"
            f"Forbidden patterns: {', '.join(prompt_policy.forbidden_patterns)}\n"
            f"Writer responsibility: {writer_contract.get('responsibility', '')}\n"
            f"Detected event category: {detected_event.category}\n"
            f"Detected event salience: {detected_event.salience:.2f}\n"
            f"Detected event rationale: {detected_event.rationale}\n"
            f"Evidence catalog:\n" + "\n".join(catalog_lines) + "\n"
            f"Optional historical/narrative context:\n" + ("\n".join(context_lines) if context_lines else "- none") + "\n"
            "Output requirement:\n"
            "1. Keep the commentary tight.\n"
            "2. Do not mention evidence keys inside the commentary text.\n"
            "3. Prefer one clear angle instead of listing everything.\n"
            "4. If you infer momentum, pressure, or trend, mark that sentence speculative.\n"
        )
        return system_prompt, user_prompt

    def _fallback_payload(self, detected_event: DetectedEvent, style: str) -> dict[str, Any]:
        event = detected_event.raw_event
        headline = self._fallback_text(detected_event, style)
        sentence_mode = "fact" if event.points > 0 else "narrative"
        evidence_keys = ["event.description", "event.score", "event.clock", "event.actor"]
        if detected_event.category in {"momentum_swing", "lead_change"}:
            sentence_mode = "speculative"
            evidence_keys.append("event.category")
        return {
            "commentary": headline,
            "sentences": [
                {
                    "text": headline,
                    "mode": sentence_mode,
                    "evidence_keys": evidence_keys,
                }
            ],
            "facts_used": evidence_keys,
            "notes": ["deterministic fallback"],
        }

    def _fallback_text(self, detected_event: DetectedEvent, style: str) -> str:
        event = detected_event.raw_event
        actor = event.actor_player or event.actor_team or "This possession"
        score = f"{event.home_score}-{event.away_score}"
        if detected_event.category == "clutch_shot":
            return f"{actor}在{event.clock}打进关键球，比分来到{score}。"
        if detected_event.category == "lead_change":
            return f"{actor}这一球把比赛重新拨到了另一边，当前比分{score}。"
        if detected_event.category == "momentum_swing":
            return f"{actor}把节奏继续往自己这边推，场上气势已经明显起来了。"
        if detected_event.category == "turnover":
            return f"{actor}这回合处理得太伤，直接把球权和节奏都送了出去。"
        if detected_event.category == "timeout":
            return f"暂停先叫出来，这个回合之后场上的调整意味很强。"
        if detected_event.category == "period_end":
            return f"这一节先收住了，比分定格在{score}。"
        if detected_event.category == "game_end":
            return f"比赛结束，最终比分就是{score}。"
        if style == "academic":
            return f"{actor}完成当前事件，场上比分更新为{score}。"
        return f"{actor}这一球打成了，比分来到{score}。"

    def _extract_commentary_text(
        self,
        payload: dict[str, Any],
        detected_event: DetectedEvent,
        style: str,
    ) -> str:
        commentary = str(payload.get("commentary", "")).strip()
        if commentary:
            return commentary
        sentences = payload.get("sentences", [])
        if isinstance(sentences, list):
            joined = " ".join(str(item.get("text", "")).strip() for item in sentences if isinstance(item, dict))
            if joined.strip():
                return joined.strip()
        return self._fallback_text(detected_event, style)


def _self_test() -> None:
    from realtime.models import PlayByPlayEvent

    event = PlayByPlayEvent(
        event_id="demo-live-1",
        period=4,
        clock="PT00M48S",
        description="S. Curry 27-foot 3PT Jump Shot Made",
        home_score=101,
        away_score=104,
        actor_player="Stephen Curry",
        actor_team="GSW",
        action_type="Made Shot",
        sub_type="3PT",
        points=3,
        elapsed_seconds_in_period=(12 * 60) - 48,
    )
    detected = DetectedEvent(
        raw_event=event,
        category="clutch_shot",
        salience=0.93,
        rationale="late-game 3PT in a one-possession game",
    )
    commentator = LiveCommentator(client=None)
    commentary = commentator.generate_commentary(
        detected,
        produced_at_seconds=12.0,
        style="hupu",
    )
    print("[LIVE] Commentary:", commentary.raw_text)
    for tag in commentary.provenance:
        print(
            "[LIVE] Tag:",
            {
                "text": tag.text,
                "state": tag.state,
                "confidence": tag.confidence,
                "evidence_count": len(tag.evidence),
            },
        )
    print("[LIVE] Fallback:", commentary.metadata.get("fallback_reason", "none"))
    print("[LIVE] Test passed")


if __name__ == "__main__":
    _self_test()
