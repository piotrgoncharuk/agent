"""Тонкая обёртка над Anthropic SDK: структурированный вывод + обработка отказов."""
from functools import lru_cache
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Модели, для которых доступен серверный fallback "default" (Claude API).
_FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


@lru_cache
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def structured(
    *,
    model: str,
    system: str,
    prompt: str,
    output: type[T],
    effort: str = "medium",
    max_tokens: int = 8000,
    client: anthropic.Anthropic | None = None,
) -> T:
    """Один запрос → валидированный Pydantic-объект."""
    client = client or get_client()
    kwargs = {}
    if model in _FALLBACK_MODELS:
        kwargs = {"betas": [_FALLBACK_BETA], "fallbacks": "default"}
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort},
            output_format=output,
            **kwargs,
        )
    except anthropic.RateLimitError as e:
        raise LLMError(f"rate limited: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("network error") from e

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise LLMError(f"model declined (category={category})")
    if response.stop_reason == "max_tokens":
        raise LLMError("output truncated: increase max_tokens")
    if response.parsed_output is None:
        raise LLMError("no structured output returned")
    return response.parsed_output
