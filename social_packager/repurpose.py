"""Shared helpers for repurposing Video Scout reports into platform packages."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from realtime.llm_client import LLMClient


@dataclass
class SocialPackage:
    """One platform-ready content package with media and evidence lineage."""

    platform: str
    title: str
    body: str
    media_paths: list[str]
    hashtags: list[str]
    provenance: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SocialRepurposer:
    """Condense tactical reports and select platform-appropriate GIF evidence."""

    def __init__(self, *, use_llm: bool = True) -> None:
        self.use_llm = bool(use_llm)
        self._client: LLMClient | None = None

    def extract_key_takeaways(self, report: dict[str, Any], max: int = 5) -> list[str]:
        """Extract concise takeaways from deciding factors and key segments."""
        candidates: list[str] = []
        for item in report.get("deciding_factors", []):
            if item:
                candidates.append(str(item).strip())
        for item in report.get("tactical_themes", []):
            if item:
                candidates.append(str(item).strip())
        for segment in report.get("key_segments", []):
            if not isinstance(segment, dict):
                continue
            impact = str(segment.get("win_loss_impact", "")).strip()
            observation = str(segment.get("observation", "")).strip()
            tactic = str(segment.get("tactic_type", "")).strip()
            if impact:
                candidates.append(f"{tactic}：{impact}" if tactic else impact)
            elif observation:
                candidates.append(observation)
        return _unique([_trim_sentence(item, 110) for item in candidates if item])[:max]

    def select_clips_for_platform(
        self,
        clip_manifest: dict[str, Any],
        platform: str,
        max: int,
    ) -> list[dict[str, Any]]:
        """Select generated GIF clips that best fit a platform's consumption pattern."""
        clips = [item for item in clip_manifest.get("clips", []) if isinstance(item, dict)]
        available = [
            item
            for item in clips
            if str(item.get("gif_status", "")).lower() == "generated" and str(item.get("gif_path", "")).strip()
        ]
        if not available:
            available = [item for item in clips if str(item.get("output_path", "")).strip()]
        ranked = sorted(available, key=lambda item: _clip_score(item, platform), reverse=True)
        return ranked[:max]

    def provenance_for(self, report: dict[str, Any], clips: list[dict[str, Any]]) -> dict[str, Any]:
        """Keep original evidence index and selected clip ids attached to a package."""
        clip_ids = [str(item.get("observation_id", item.get("label", ""))) for item in clips]
        segment_ids = {
            str(evidence)
            for segment in report.get("key_segments", [])
            if isinstance(segment, dict)
            for evidence in segment.get("evidence", [])
            if str(evidence) in clip_ids or str(evidence).startswith("event:")
        }
        return {
            "report_title": report.get("title", ""),
            "evidence_index": report.get("evidence_index", []),
            "selected_clip_ids": clip_ids,
            "selected_segment_or_event_ids": sorted(segment_ids),
            "source_metadata": report.get("metadata", {}),
        }

    def maybe_llm_rewrite(
        self,
        *,
        platform: str,
        system: str,
        user: str,
        fallback: str,
        max_tokens: int = 900,
    ) -> tuple[str, dict[str, Any]]:
        """Use the shared LLM client when available, otherwise return fallback."""
        if not self.use_llm:
            return fallback, {"llm_used": False, "fallback_reason": "use_llm_disabled"}
        try:
            if self._client is None:
                self._client = LLMClient.from_env()
            result = self._client.generate(
                system=system,
                user=user,
                contract_id=f"social_packager.{platform}.v1",
                max_tokens=max_tokens,
                temperature=0.65,
            )
            text = result.text.strip()
            if not text:
                raise ValueError("empty LLM response")
            return text, {
                "llm_used": True,
                "model": result.model,
                "latency_seconds": round(result.latency_seconds, 3),
                "fallback_reason": "",
            }
        except Exception as exc:
            return fallback, {"llm_used": False, "fallback_reason": str(exc)}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clip_media_paths(clips: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for clip in clips:
        path = str(clip.get("gif_path") or clip.get("output_path") or "").strip()
        if path:
            paths.append(path)
    return paths


def clip_lines(clips: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for index, clip in enumerate(clips, start=1):
        players = "、".join(str(item) for item in clip.get("players", []) if item)
        tags = " / ".join(str(item) for item in clip.get("tactic_tags", [])[:2])
        desc = str(clip.get("event_description", "")).strip()
        media = str(clip.get("gif_path") or clip.get("output_path") or "")
        lines.append(f"{index}. Q{clip.get('period')} {clip.get('clock')}｜{players}｜{tags}｜{desc}\n   GIF: {media}")
    return lines


def top_players(report: dict[str, Any], limit: int = 4) -> list[str]:
    players: list[str] = []
    for profile in report.get("player_tactical_profiles", []):
        if isinstance(profile, dict) and profile.get("player"):
            line = str(profile.get("player"))
            if profile.get("stat_evidence"):
                line += f"（{profile.get('stat_evidence')}）"
            players.append(line)
    return players[:limit]


def normalize_title(report: dict[str, Any]) -> str:
    title = str(report.get("title", "")).strip()
    return title or "OKC 雷霆 vs LAL 湖人 — 2026 西部半决赛 G1"


def safe_weibo(text: str, limit: int = 140) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    suffix = " #NBA季后赛#"
    return clean[: max(0, limit - len(suffix) - 1)].rstrip("，。； ") + suffix


def _clip_score(clip: dict[str, Any], platform: str) -> tuple[int, float, int]:
    tags = {str(item).lower() for item in clip.get("tactic_tags", [])}
    label = str(clip.get("label", "")).lower()
    score = 0
    if "period_end" in tags or "game_end" in tags or "period_end" in label or "game_end" in label:
        score -= 4
    if "key_shot" in tags:
        score += 5
    if "lead_change" in tags or "lead_change" in label:
        score += 4
    if "momentum_swing" in tags or "momentum" in label:
        score += 3
    if "three_point_creation" in tags:
        score += 3
    if "rim_pressure" in tags:
        score += 2
    if platform == "xiaohongshu" and clip.get("players"):
        score += 1
    confidence = float(clip.get("refinement_shift_seconds", 0.0) or 0.0)
    index = -int(clip.get("index", 0) or 0)
    return score, -confidence, index


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _trim_sentence(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip("，。； ") + "…"
