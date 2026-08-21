"""
Swappable LLM backend.

One env var picks the provider; nothing else in the codebase knows which one is
running:

    LLM_PROVIDER=none      deterministic rule-based reasoning, zero cost, no network
    LLM_PROVIDER=ollama    local models via OLLAMA_BASE_URL (also the sovereign mode)
    LLM_PROVIDER=gemini    Google AI Studio / Gemini API
    LLM_PROVIDER=openai    any OpenAI-compatible endpoint (OpenAI, Groq, together, vLLM)
    LLM_PROVIDER=anthropic Claude

Every provider is reached over plain HTTP with ``httpx`` - no per-vendor SDK is
required, so swapping providers never means installing a new package.

The agent nodes call :func:`complete_json` and always get usable output: if the
provider is unset, unreachable, or returns something that will not parse, the
caller's ``fallback`` is returned and the pipeline carries on. That is what lets
the dashboard run with no key at all.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class LLMInfo:
    """What the dashboard shows in its provider badge."""

    provider: str
    model: str
    available: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "available": self.available,
            "detail": self.detail,
        }


def _resolved() -> tuple[str, str]:
    """(provider, model) after applying sovereign mode and defaults."""
    from orchestrator.config import settings

    provider = (settings.llm_provider or "none").strip().lower()
    if settings.sovereign_mode:
        provider = "ollama"

    model = settings.llm_model.strip()
    if not model:
        model = {
            "ollama": settings.ollama_model,
            "gemini": "gemini-2.0-flash",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-sonnet-5",
        }.get(provider, "")
    return provider, model


def describe() -> LLMInfo:
    """Current provider configuration, without making a network call."""
    from orchestrator.config import settings

    provider, model = _resolved()
    if provider == "none":
        return LLMInfo("none", "rule-based", True, "Deterministic reasoning, no LLM calls")

    key = _api_key(provider, settings)
    if provider == "ollama":
        return LLMInfo(provider, model, True, f"Local endpoint {settings.ollama_base_url}")
    if not key:
        return LLMInfo(provider, model, False, f"No API key set for {provider} - using fallback")
    return LLMInfo(provider, model, True, "Ready")


def _api_key(provider: str, settings) -> str:
    return {
        "gemini": settings.gemini_api_key or settings.google_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
    }.get(provider, "")


async def complete(system: str, user: str, max_tokens: int = 1024) -> str | None:
    """Single-turn completion. Returns None when no provider can serve it."""
    from orchestrator.config import settings

    provider, model = _resolved()
    if provider == "none":
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if provider == "ollama":
                return await _ollama(client, settings, model, system, user)
            if provider == "gemini":
                return await _gemini(client, settings, model, system, user, max_tokens)
            if provider == "openai":
                return await _openai(client, settings, model, system, user, max_tokens)
            if provider == "anthropic":
                return await _anthropic(client, settings, model, system, user, max_tokens)
    except Exception as exc:
        logger.warning("LLM call failed (%s/%s): %s", provider, model, exc)
        return None

    logger.warning("Unknown LLM_PROVIDER %r - falling back to rule-based output", provider)
    return None


async def complete_json(system: str, user: str, fallback: dict, max_tokens: int = 1024) -> dict:
    """Completion parsed as JSON, with a guaranteed-usable fallback.

    The model is asked for JSON, but models wrap it in prose or fences often
    enough that the first balanced ``{...}`` block is extracted before parsing.
    """
    raw = await complete(system, user, max_tokens=max_tokens)
    if not raw:
        return fallback

    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("LLM returned unparseable JSON - using fallback")
    return fallback


async def health() -> LLMInfo:
    """Probe the provider with a trivial prompt. Used by /health."""
    info = describe()
    if info.provider == "none" or not info.available:
        return info
    reply = await complete("Reply with the single word OK.", "ping", max_tokens=8)
    if reply is None:
        return LLMInfo(info.provider, info.model, False, "Provider unreachable - using fallback")
    return LLMInfo(info.provider, info.model, True, "Responding")


# -- provider transports -------------------------------------------------------


async def _ollama(client: httpx.AsyncClient, settings, model, system, user) -> str:
    resp = await client.post(
        f"{settings.ollama_base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "stream": False,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


async def _gemini(client: httpx.AsyncClient, settings, model, system, user, max_tokens) -> str:
    key = settings.gemini_api_key or settings.google_api_key
    resp = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
        },
    )
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


async def _openai(client: httpx.AsyncClient, settings, model, system, user, max_tokens) -> str:
    resp = await client.post(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def _anthropic(client: httpx.AsyncClient, settings, model, system, user, max_tokens) -> str:
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
    )
    resp.raise_for_status()
    return "".join(b.get("text", "") for b in resp.json()["content"])
