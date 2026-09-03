"""Swappable OpenAI-compatible chat-completions backend for the agent under
test. Any provider that speaks the OpenAI tool-calling format works — set
LLM_PROVIDER to a known preset or LLM_PROVIDER=custom with LLM_BASE_URL.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openai import APIStatusError, AsyncOpenAI

PROVIDER_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
}

# $ per 1M tokens as (input, output). Unlisted models cost $0 in reporting —
# that is a "pricing unknown" signal, not a claim the model is free.
PRICING_PER_1M = {
    "gpt-4o-mini": (0.15, 0.60),
}


@dataclass
class ModelUsage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class ModelReply:
    tool_name: Optional[str]
    tool_args: Dict[str, Any]
    tool_call_id: Optional[str]
    raw_content: Optional[str]
    usage: ModelUsage


@dataclass
class Model:
    provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "custom"))
    model_name: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    base_url: Optional[str] = None
    api_key: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.model_name:
            raise ValueError("no model name: set LLM_MODEL or pass model_name=")
        resolved_base_url = (
            self.base_url
            or os.environ.get("LLM_BASE_URL")
            or PROVIDER_BASE_URLS.get(self.provider)
        )
        if not resolved_base_url:
            raise ValueError(
                f"no base_url for provider={self.provider!r}; set LLM_BASE_URL "
                f"or use one of {list(PROVIDER_BASE_URLS)}"
            )
        # MUST be the async client. A sync HTTP call here blocks the whole
        # asyncio event loop for the length of the LLM request (tens of
        # seconds on a slow provider) — which starves the Solari browser
        # session's control-channel keepalives running on that same loop.
        # Verified live: a sync client produced a `Control channel closed
        # (1006)` abnormal disconnect and a session with no replay ever
        # generated, even though the agent run itself completed normally.
        self._client = AsyncOpenAI(
            api_key=self.api_key or os.environ["LLM_API_KEY"],
            base_url=resolved_base_url,
            timeout=60.0,
            max_retries=1,
        )

    async def step(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ModelReply:
        # A bulk matrix run hits real, transient provider outages (seen live:
        # a 502 from the LLM gateway with `retryable: true`). Retry with
        # backoff on top of the client's own retries rather than letting one
        # bad request kill a whole matrix pass. Every exit from this loop is
        # either `break` (success) or `raise` (final attempt, or a
        # non-retryable status) — it never runs to exhaustion.
        for attempt in range(4):
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                break
            except APIStatusError as e:
                if e.status_code < 500 or attempt == 3:
                    raise
                await asyncio.sleep(2 * (2 ** attempt))
        choice = resp.choices[0].message
        usage = resp.usage

        price_in, price_out = PRICING_PER_1M.get(self.model_name, (0.0, 0.0))
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cost = (prompt_tokens / 1_000_000 * price_in) + (
            completion_tokens / 1_000_000 * price_out
        )

        tool_call = choice.tool_calls[0] if choice.tool_calls else None
        return ModelReply(
            tool_name=tool_call.function.name if tool_call else None,
            tool_args=json.loads(tool_call.function.arguments or "{}") if tool_call else {},
            tool_call_id=tool_call.id if tool_call else None,
            raw_content=choice.content,
            usage=ModelUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
            ),
        )
