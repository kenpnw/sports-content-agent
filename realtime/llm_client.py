"""DeepSeek (OpenAI-compatible) client wrapper.

Why a wrapper instead of using `openai` directly:

1. Centralised config from `.env` so the rest of the codebase never sees keys
2. Built-in latency telemetry (one of the thesis evaluation metrics)
3. Hook point for prompt-contract enforcement before/after each call
4. Retry with backoff
5. Easy to swap provider later (Qwen, GLM, OpenAI) without touching callers

Usage
-----
>>> from realtime.llm_client import LLMClient
>>> client = LLMClient.from_env()
>>> result = client.generate(
...     system="You are a sports commentator.",
...     user="Curry hit a 3 to take the lead.",
...     contract_id="live_commentary.v1",
... )
>>> print(result.text, result.latency_seconds)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# `python-dotenv` is optional at import time; if absent we fall back to
# whatever environment variables are already set.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# We use the `openai` SDK because DeepSeek's API is OpenAI-compatible.
# Import is deferred so that other modules in this package can still load
# even on machines where the SDK is not yet installed.
try:
    from openai import OpenAI  # type: ignore
    _OPENAI_AVAILABLE = True
except Exception:
    _OPENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class LLMResult:
    """One LLM call's result, with telemetry useful for thesis evaluation."""

    text: str
    model: str
    provider: str
    latency_seconds: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    contract_id: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """Thin wrapper around DeepSeek's OpenAI-compatible chat API.

    The client is intentionally stateless aside from connection config.
    Prompt-contract enforcement is a separate concern handled by the
    `live_commentator` module — this class only adds the contract id to the
    telemetry record.
    """

    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        provider: str = "deepseek",
        default_model: str = DEFAULT_MODEL,
        temperature: float = 0.6,
        max_tokens: int = 400,
        timeout: float = 20.0,
    ) -> None:
        if not api_key or not api_key.startswith("sk-"):
            raise ValueError(
                "LLMClient requires an api_key starting with 'sk-'. "
                "Did you fill in `.env` from `.env.example`?"
            )
        if not _OPENAI_AVAILABLE:
            raise ImportError(
                "The `openai` package is required. "
                "Install it with: pip install openai>=1.0"
            )
        self._provider = provider
        self._default_model = default_model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    # ------------------------------------------------------------------ #
    # Construction helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env(cls) -> "LLMClient":
        """Build a client from environment variables.

        Honoured variables (defaults shown):
            LLM_PROVIDER         = deepseek
            LLM_BASE_URL         = https://api.deepseek.com/v1
            LLM_API_KEY          = (no default)
            LLM_MODEL_FAST       = deepseek-chat
            LLM_TEMPERATURE      = 0.6
            LLM_MAX_TOKENS       = 400
            LLM_TIMEOUT_SECONDS  = 20
        """
        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Copy `.env.example` to `.env` and fill in your key."
            )
        return cls(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", cls.DEFAULT_BASE_URL).strip(),
            provider=os.getenv("LLM_PROVIDER", "deepseek").strip(),
            default_model=os.getenv("LLM_MODEL_FAST", cls.DEFAULT_MODEL).strip(),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.6")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "400")),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
        )

    # ------------------------------------------------------------------ #
    # Core generation
    # ------------------------------------------------------------------ #

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        contract_id: str = "",
        json_mode: bool = False,
        max_retries: int = 2,
    ) -> LLMResult:
        """Run one chat completion.

        Parameters
        ----------
        system, user
            System prompt and user prompt strings.
        model
            Override the default model for this call. Use `deepseek-reasoner`
            for harder analysis tasks; `deepseek-chat` for fast commentary.
        temperature, max_tokens
            Per-call overrides; defaults come from env.
        contract_id
            Tag this call belongs to (recorded in telemetry only — actual
            contract enforcement happens in the commentator module).
        json_mode
            When True, asks the model to return strict JSON.
        max_retries
            Total attempts = 1 + max_retries.
        """
        chosen_model = model or self._default_model
        chosen_temp = self._temperature if temperature is None else temperature
        chosen_max = self._max_tokens if max_tokens is None else max_tokens

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = dict(
            model=chosen_model,
            messages=messages,
            temperature=chosen_temp,
            max_tokens=chosen_max,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        attempt = 0
        last_error: Exception | None = None
        while attempt <= max_retries:
            attempt += 1
            t0 = time.monotonic()
            try:
                resp = self._client.chat.completions.create(**kwargs)
                latency = time.monotonic() - t0
                choice = resp.choices[0]
                usage = getattr(resp, "usage", None)
                return LLMResult(
                    text=(choice.message.content or "").strip(),
                    model=chosen_model,
                    provider=self._provider,
                    latency_seconds=latency,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
                    total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
                    finish_reason=str(choice.finish_reason or ""),
                    contract_id=contract_id,
                    raw_response=resp.model_dump() if hasattr(resp, "model_dump") else {},
                )
            except Exception as exc:  # broad catch is acceptable for retry logic
                last_error = exc
                if attempt > max_retries:
                    break
                time.sleep(0.5 * attempt)
        raise RuntimeError(
            f"LLM call failed after {attempt} attempts: {last_error}"
        ) from last_error

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        contract_id: str = "",
    ) -> tuple[dict[str, Any], LLMResult]:
        """Generate a JSON object. Raises if the model returns non-JSON."""
        result = self.generate(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            contract_id=contract_id,
            json_mode=True,
        )
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Model did not return valid JSON. Got:\n{result.text}\nError: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object; got {type(payload).__name__}")
        return payload, result


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _is_insufficient_balance_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "insufficient balance" in text or "error code: 402" in text


def _self_test() -> None:
    print("[LLMClient] Provider:", os.getenv("LLM_PROVIDER", "deepseek"))
    print("[LLMClient] Model:", os.getenv("LLM_MODEL_FAST", "deepseek-chat"))
    test_prompt = "用一句话评论库里末节连中三记三分"
    print("[LLMClient] Test prompt:", test_prompt)
    try:
        client = LLMClient.from_env()
        result = client.generate(
            system="你是一个简洁、专业的篮球解说员。每次只输出一句中文。",
            user=test_prompt,
            contract_id="self_test.v1",
        )
    except Exception as exc:
        if _is_insufficient_balance_error(exc):
            print("[LLMClient] DeepSeek account has insufficient balance.")
            print("[LLMClient] Recharge the DeepSeek account, then run this test again.")
            raise SystemExit(2)
        print(f"[LLMClient] Test failed: {exc}")
        raise SystemExit(1)
    print("[LLMClient] Response:", result.text)
    print(f"[LLMClient] Latency: {result.latency_seconds:.2f}s")
    print(f"[LLMClient] Tokens: prompt={result.prompt_tokens} "
          f"completion={result.completion_tokens} total={result.total_tokens}")
    print("[LLMClient] Test passed")


if __name__ == "__main__":
    _self_test()
