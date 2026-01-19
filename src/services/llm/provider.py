"""LLM Provider using LiteLLM for multi-provider abstraction."""

from dataclasses import dataclass, field
from typing import Any

import litellm
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.core.exceptions import LLMError

logger = structlog.get_logger()

# Configure LiteLLM
litellm.set_verbose = settings.app_debug

# Set API keys from settings
if settings.openai_api_key:
    litellm.openai_key = settings.openai_api_key
if settings.anthropic_api_key:
    litellm.anthropic_key = settings.anthropic_api_key
if settings.google_api_key:
    litellm.google_key = settings.google_api_key


@dataclass
class LLMResponse:
    """Response from LLM completion."""

    content: str
    model: str
    tokens_input: int = 0
    tokens_output: int = 0
    finish_reason: str = "stop"
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider:
    """LLM provider with multi-model support and fallbacks.

    Uses LiteLLM for unified API across OpenAI, Anthropic, Google, and more.
    """

    def __init__(
        self,
        primary_model: str | None = None,
        fallback_models: list[str] | None = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 500,
    ) -> None:
        self.primary_model = primary_model or settings.litellm_primary_model
        self.fallback_models = fallback_models or [settings.litellm_fallback_model]
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

        logger.info(
            "LLM Provider initialized",
            primary=self.primary_model,
            fallbacks=self.fallback_models,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using the LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt to prepend
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            model: Override model selection
            **kwargs: Additional parameters passed to LiteLLM

        Returns:
            LLMResponse with generated content and metadata
        """
        import time

        model_to_use = model or self.primary_model
        temp = temperature if temperature is not None else self.default_temperature
        max_tok = max_tokens or self.default_max_tokens

        # Prepare messages with system prompt
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        start_time = time.perf_counter()

        try:
            response = await litellm.acompletion(
                model=model_to_use,
                messages=full_messages,
                temperature=temp,
                max_tokens=max_tok,
                **kwargs,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Extract usage info
            usage = response.usage or {}
            tokens_input = getattr(usage, "prompt_tokens", 0)
            tokens_output = getattr(usage, "completion_tokens", 0)

            # Calculate cost using LiteLLM's cost tracking
            try:
                cost = litellm.completion_cost(completion_response=response)
            except Exception:
                cost = 0.0

            content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason or "stop"

            logger.info(
                "LLM completion successful",
                model=model_to_use,
                tokens_in=tokens_input,
                tokens_out=tokens_output,
                latency_ms=round(latency_ms, 2),
                cost_usd=round(cost, 6),
            )

            return LLMResponse(
                content=content,
                model=model_to_use,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                finish_reason=finish_reason,
                latency_ms=latency_ms,
                cost_usd=cost,
                metadata={"raw_response_id": response.id if hasattr(response, "id") else None},
            )

        except Exception as e:
            logger.warning(
                "LLM completion failed, trying fallback",
                model=model_to_use,
                error=str(e),
            )

            # Try fallback models
            for fallback_model in self.fallback_models:
                if fallback_model == model_to_use:
                    continue

                try:
                    return await self.complete(
                        messages=messages,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=fallback_model,
                        **kwargs,
                    )
                except Exception as fallback_error:
                    logger.warning(
                        "Fallback model also failed",
                        model=fallback_model,
                        error=str(fallback_error),
                    )
                    continue

            raise LLMError(f"All LLM providers failed: {e}", provider=model_to_use)

    async def complete_with_context(
        self,
        user_message: str,
        context: str,
        system_prompt: str,
        conversation_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion with RAG context included.

        This is a convenience method that formats the prompt with context.
        """
        # Build the full system prompt with context
        full_system = f"{system_prompt}\n\n{context}" if context else system_prompt

        # Build messages
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        return await self.complete(
            messages=messages,
            system_prompt=full_system,
            **kwargs,
        )

    async def summarize(
        self,
        conversation_text: str,
        max_length: int = 200,
    ) -> str:
        """Generate a summary of conversation for long-term memory."""
        messages = [
            {
                "role": "user",
                "content": f"""Summarize the following customer support conversation in {max_length} words or less.
Focus on:
- Main issues discussed
- Any resolutions provided
- Customer preferences mentioned
- Unresolved issues

Conversation:
{conversation_text}

Summary:""",
            }
        ]

        response = await self.complete(
            messages=messages,
            temperature=0.3,  # Lower temperature for more factual summary
            max_tokens=max_length * 2,  # Rough estimate
        )

        return response.content.strip()

    async def extract_entities(
        self,
        text: str,
    ) -> dict[str, Any]:
        """Extract named entities and key information from text."""
        messages = [
            {
                "role": "user",
                "content": f"""Extract key information from this customer message. Return JSON with:
- "intent": main intent (question, complaint, request, feedback, other)
- "entities": dict of extracted entities (product names, order numbers, dates, etc)
- "sentiment": positive, neutral, or negative
- "urgency": low, medium, or high

Message: {text}

JSON:""",
            }
        ]

        response = await self.complete(
            messages=messages,
            temperature=0.1,
            max_tokens=200,
        )

        # Parse JSON from response
        import json

        try:
            # Try to extract JSON from the response
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse entity extraction response", content=response.content)
            return {
                "intent": "other",
                "entities": {},
                "sentiment": "neutral",
                "urgency": "medium",
            }


# Singleton instance
_llm_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Get or create the LLM provider singleton."""
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider
