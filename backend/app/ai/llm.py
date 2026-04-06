from __future__ import annotations
"""
LiteLLM wrapper — unified LLM calls with retry + fallback.
Primary: gemini/gemini-2.5-flash
Fallback: gemini/gemini-1.5-flash (if primary fails or rate-limits)
"""
import os
import logging
from typing import Optional, Any
from ..config import settings

logger = logging.getLogger(__name__)


def _sync_api_keys():
    if settings.gemini_api_key:
        os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)


def get_langfuse_client() -> Optional[Any]:
    """Return Langfuse client or None if not configured."""
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse
        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception as exc:
        logger.warning("Langfuse init failed — tracing disabled: %s", exc)
        return None


async def llm_complete(
    system: str,
    messages: list[dict],
    model: str = "gemini/gemini-2.5-flash",
    temperature: float = 0.85,
    max_tokens: int = 2048,
    json_mode: bool = False,
    trace_name: Optional[str] = None,
    trace_user_id: Optional[str] = None,
    langfuse_client: Optional[Any] = None,
) -> str:
    """
    Make an LLM call via LiteLLM with:
    - Automatic retry (3x, exponential backoff)
    - Fallback to gemini-1.5-flash if primary fails
    - Optional Langfuse tracing
    """
    import litellm
    _sync_api_keys()

    # Build message list with system prompt
    all_messages = [{"role": "system", "content": system}] + messages

    kwargs = dict(
        model=model,
        messages=all_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        num_retries=3,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Optional Langfuse trace
    generation = None
    if langfuse_client and trace_name:
        try:
            trace = langfuse_client.trace(
                name=trace_name,
                user_id=trace_user_id,
                tags=["flaxie", settings.app_env],
            )
            generation = trace.generation(
                name=trace_name,
                model=model,
                input=all_messages,
            )
        except Exception:
            pass

    try:
        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content or ""

        if generation:
            try:
                generation.end(output=content[:2000])
            except Exception:
                pass

        return content

    except Exception as primary_exc:
        logger.warning("Primary model %s failed: %s — trying fallback", model, primary_exc)
        fallback = settings.litellm_fallback_model
        if fallback == model:
            raise

        try:
            kwargs["model"] = fallback
            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content or ""
            logger.info("Fallback model %s succeeded", fallback)

            if generation:
                try:
                    generation.end(output=content[:2000], level="WARNING")
                except Exception:
                    pass

            return content
        except Exception as fallback_exc:
            logger.error(
                "Both primary and fallback LLM failed. Primary: %s, Fallback: %s",
                primary_exc,
                fallback_exc,
            )

            if generation:
                try:
                    generation.end(output=str(fallback_exc), level="ERROR")
                except Exception:
                    pass

            raise fallback_exc
