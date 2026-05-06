"""Optional vision model adapter for frame-level basketball observations."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

try:
    from openai import OpenAI  # type: ignore

    _OPENAI_AVAILABLE = True
except Exception:
    _OPENAI_AVAILABLE = False

from video_scout.models import FrameSample, VisualObservation


class VisionClient:
    """OpenAI-compatible vision adapter.

    This class is optional. The Video Scout demo can run from a prebuilt
    observations JSON without any vision model. Configure these env vars only
    when you want the agent to inspect frame images:

    - VISION_API_KEY
    - VISION_BASE_URL
    - VISION_MODEL
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
    ) -> None:
        if not _OPENAI_AVAILABLE:
            raise ImportError("The `openai` package is required for vision calls.")
        if not api_key:
            raise RuntimeError("VISION_API_KEY is not set.")
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    @classmethod
    def from_env(cls) -> "VisionClient":
        return cls(
            api_key=os.getenv("VISION_API_KEY", "").strip(),
            base_url=os.getenv("VISION_BASE_URL", cls.DEFAULT_BASE_URL).strip(),
            model=os.getenv("VISION_MODEL", cls.DEFAULT_MODEL).strip(),
            timeout=float(os.getenv("VISION_TIMEOUT_SECONDS", "30")),
        )

    def analyze_frame(
        self,
        frame: FrameSample,
        *,
        game_context: dict[str, Any] | None = None,
        max_retries: int = 1,
    ) -> VisualObservation:
        """Ask a vision model for one frame-level tactical observation."""
        image_url = _image_data_url(frame.image_path)
        context = json.dumps(game_context or {}, ensure_ascii=False)
        prompt = (
            "You are a basketball video scout. Analyze this single frame. "
            "Return strict JSON with keys: observation_id, timecode_seconds, "
            "period, clock, frame_path, event_description, possession_team, "
            "defense_team, tactic_tags, players, court_structure, "
            "action_summary, decision_analysis, evidence, confidence, source. "
            "Use Simplified Chinese for all natural-language fields. "
            "Do not identify players unless names are supplied by context or jersey "
            "information is clearly visible. If uncertain, say uncertain."
        )
        user_text = (
            f"Frame metadata: {json.dumps(frame.to_dict(), ensure_ascii=False)}\n"
            f"Game context: {context}\n"
            "Focus on spacing, screen action, help defense, passing choices, "
            "shot quality, and whether the possession hints at a tactical pattern."
        )

        attempt = 0
        last_error: Exception | None = None
        while attempt <= max_retries:
            attempt += 1
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_text},
                                {"type": "image_url", "image_url": {"url": image_url}},
                            ],
                        },
                    ],
                    temperature=0.2,
                    max_tokens=700,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content or "{}"
                payload = json.loads(raw)
                if "observation_id" not in payload:
                    payload["observation_id"] = frame.frame_id
                payload.setdefault("timecode_seconds", frame.timecode_seconds)
                payload.setdefault("period", frame.period)
                payload.setdefault("clock", frame.clock)
                payload.setdefault("frame_path", frame.image_path)
                payload.setdefault("source", f"vision:{self.model}")
                return VisualObservation.from_dict(payload)
            except Exception as exc:
                last_error = exc
                if attempt > max_retries:
                    break
                time.sleep(0.5 * attempt)
        raise RuntimeError(f"Vision analysis failed after {attempt} attempts: {last_error}") from last_error


def _image_data_url(path: str) -> str:
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Frame image not found: {path}")
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"
