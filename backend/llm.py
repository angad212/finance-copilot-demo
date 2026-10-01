"""Thin wrapper around the Anthropic client: retries, structured output, validation."""
import asyncio
from dataclasses import dataclass
from typing import Callable

import anthropic
from pydantic import BaseModel

from config import settings

_client = None

TRANSIENT_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def get_llm():
    """FastAPI dependency. Returns None when no API key is configured."""
    global _client
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def with_backoff(fn: Callable, retries: int | None = None, base_delay: float | None = None):
    """Call an async function, retrying transient errors with exponential backoff."""
    retries = settings.llm_retries if retries is None else retries
    base_delay = settings.llm_backoff_seconds if base_delay is None else base_delay
    for attempt in range(retries + 1):
        try:
            return await fn()
        except TRANSIENT_ERRORS:
            if attempt == retries:
                raise
            await asyncio.sleep(base_delay * 2**attempt)


def strip_fences(text: str) -> str:
    text = text.strip()
    return text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()


@dataclass
class StructuredResult:
    data: BaseModel | None
    attempts: int
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    raw: str | None = None


async def structured_call(
    client,
    *,
    system: str,
    user_text: str,
    schema: type[BaseModel],
    validate: Callable | None = None,
    max_tokens: int = 300,
) -> StructuredResult:
    """Ask for JSON, validate it, retry once with a correction, never guess."""
    messages = [{"role": "user", "content": user_text}]
    result = StructuredResult(data=None, attempts=0)

    for attempt in (1, 2):
        result.attempts = attempt
        try:
            response = await with_backoff(
                lambda: client.messages.create(
                    model=settings.llm_model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                )
            )
        except Exception as e:  # network down, auth failure, etc.
            result.error = f"LLM request failed: {type(e).__name__}: {str(e)[:200]}"
            return result

        usage = getattr(response, "usage", None)
        if usage:
            result.input_tokens += getattr(usage, "input_tokens", 0) or 0
            result.output_tokens += getattr(usage, "output_tokens", 0) or 0

        text = response.content[0].text
        result.raw = text
        try:
            data = schema.model_validate_json(strip_fences(text))
            if validate:
                validate(data)
        except ValueError as e:
            result.error = str(e)
            messages = messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"That reply was invalid ({result.error}). "
                    "Reply again with only the JSON object.",
                },
            ]
            continue

        result.data = data
        result.error = None
        return result

    return result