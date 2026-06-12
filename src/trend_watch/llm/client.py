from __future__ import annotations

import json
import time
from typing import Any

from trend_watch.utils.logging import LoggerMixin

_RETRY_DELAYS = (1.0, 3.0, 9.0)
_OLLAMA_DEFAULT_URL = "http://localhost:11434/v1"
_OPENAI_COMPATIBLE = {"ollama", "groq", "openai"}


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if "</think>" in raw:
        raw = raw.split("</think>", 1)[1].strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    return raw.strip()


class LLMClient(LoggerMixin):
    """Provider-aware LLM client (Anthropic or any OpenAI-compatible endpoint)."""

    def __init__(self, settings=None, *, think: bool = True) -> None:
        if settings is None:
            from trend_watch.config.settings import get_settings
            settings = get_settings().llm
        self._cfg = settings
        self._provider = (self._cfg.provider or "ollama").lower()
        self._think = think
        self._client: Any = None
        self._init_client()

    def _init_client(self) -> None:
        if self._provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=self._cfg.api_key.get_secret_value()
            )
        elif self._provider == "ollama":
            self._native_url = self._native_ollama_url(self._cfg.base_url)
        elif self._provider in _OPENAI_COMPATIBLE:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self._cfg.base_url or None,
                api_key=self._cfg.api_key.get_secret_value() or "",
            )
        else:
            raise ValueError(f"Unknown LLM provider: {self._provider}")

    @staticmethod
    def _native_ollama_url(base_url: str) -> str:
        base = (base_url or _OLLAMA_DEFAULT_URL).rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}/api/chat"

    @property
    def model(self) -> str:
        return self._cfg.model

    @property
    def provider(self) -> str:
        return self._provider

    def complete_text(self, system: str, user: str) -> str:
        return self._call(system, user)

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        raw = self._call(system, user)
        cleaned = _strip_fences(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    pass
            raise

    def _call(self, system: str, user: str) -> str:
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                if self._provider == "anthropic":
                    return self._call_anthropic(system, user)
                if self._provider == "ollama":
                    return self._call_ollama_native(system, user)
                return self._call_openai(system, user)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if delay is not None:
                    self.log.warning("LLM call error on attempt %d (%s): %s", attempt, self._provider, exc)
                    time.sleep(delay)
        raise RuntimeError(f"LLM call failed after {len(_RETRY_DELAYS) + 1} attempts") from last_exc

    def _call_anthropic(self, system: str, user: str) -> str:
        message = self._client.messages.create(
            model=self._cfg.model,
            max_tokens=self._cfg.max_tokens,
            temperature=self._cfg.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return (message.content[0].text or "").strip()

    def _call_ollama_native(self, system: str, user: str) -> str:
        import requests
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = requests.post(
            self._native_url,
            json={
                "model": self._cfg.model,
                "messages": messages,
                "think": self._think,
                "stream": False,
                "options": {
                    "temperature": self._cfg.temperature,
                    "num_predict": self._cfg.max_tokens,
                },
            },
            timeout=600,
        )
        resp.raise_for_status()
        return (resp.json().get("message", {}).get("content") or "").strip()

    def _call_openai(self, system: str, user: str) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = self._client.chat.completions.create(
            model=self._cfg.model,
            max_tokens=self._cfg.max_tokens,
            temperature=self._cfg.temperature,
            messages=messages,
        )
        return (resp.choices[0].message.content or "").strip()
