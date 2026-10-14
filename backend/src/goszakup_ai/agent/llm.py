from __future__ import annotations

from typing import Any, Literal

from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI

from goszakup_ai.core.config import Settings

# (max concurrent requests, requests per minute)
PROVIDER_LIMITS = {"openai": (8, 300), "qwen": (2, 15), "gemini": (2, 10)}
REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")

StructuredMethod = Literal["json_schema", "function_calling", "json_mode"]


class LlmConfigError(RuntimeError):
    pass


def make_chat_model(settings: Settings) -> tuple[ChatOpenAI, str, StructuredMethod]:
    provider = settings.llm_provider
    key, model, base_url = {
        "openai": (settings.openai_api_key, settings.openai_model, settings.openai_base_url),
        "qwen": (settings.qwen_api_key, settings.qwen_model, settings.qwen_base_url),
        "gemini": (settings.gemini_api_key, settings.gemini_model, settings.gemini_base_url),
    }[provider]
    if key is None:
        raise LlmConfigError(f"{provider.upper()}_API_KEY is not set")
    concurrency, rpm = PROVIDER_LIMITS[provider]
    concurrency = settings.llm_max_concurrency or concurrency
    rpm = settings.llm_requests_per_minute or rpm
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": key,
        "base_url": base_url,
        "timeout": settings.llm_timeout_sec,
        "max_retries": 3,
        "rate_limiter": InMemoryRateLimiter(
            requests_per_second=rpm / 60, check_every_n_seconds=0.1, max_bucket_size=concurrency
        ),
    }
    if model.startswith(REASONING_PREFIXES):
        kwargs["reasoning_effort"] = "low"
    else:
        kwargs["temperature"] = settings.llm_temperature
    method: StructuredMethod = "json_schema" if provider == "openai" else "function_calling"
    return ChatOpenAI(**kwargs), f"{provider}:{model}", method
