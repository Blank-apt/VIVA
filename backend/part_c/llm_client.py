"""
Thin OpenAI-compatible client wrapper.

Works against either provider configured in config.py
(Groq for free dev, Mistral for free dev, Moonshot for the
paid hackathon run).

All providers expose an OpenAI-compatible chat completions endpoint,
so this file does not need to know which provider it is talking to.

Handles:
    - Structured Output (response_format: json_schema)
    - Pydantic validation
    - Retries on transient failures / malformed JSON
    - Exponential backoff for rate-limit (429) errors
    - thinking / prompt_cache_key / reasoning_effort params only sent
      when the active provider actually supports them
"""

from __future__ import annotations

import json
import time
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

import config


T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------------

_client = OpenAI(
    api_key=config.LLM_API_KEY,
    base_url=config.LLM_BASE_URL,
)


# ---------------------------------------------------------------------------
# Strict JSON schema helper
# ---------------------------------------------------------------------------

def _to_strict_json_schema(model: Type[BaseModel]) -> dict:
    """
    Convert a Pydantic model's JSON schema into a strict schema.

    Strict structured output requires every object to have:

        - additionalProperties: false
        - every property listed in required

    This also recursively handles nested objects and schemas
    inside $defs.
    """

    schema = model.model_json_schema()

    def _walk(node: object) -> None:
        if isinstance(node, dict):

            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())

            for value in node.values():
                _walk(value)

        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)

    return schema


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class LLMCallError(RuntimeError):
    """
    Raised when the LLM fails to return a schema-valid response
    after all retry attempts.
    """

    pass


# ---------------------------------------------------------------------------
# Structured LLM call
# ---------------------------------------------------------------------------

def call_structured(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: Type[T],
    schema_name: str,
    thinking_enabled: bool = False,
    model: str = config.LLM_MODEL,
    prompt_cache_key: str | None = None,
    max_retries: int = 2,
) -> T:
    """
    Call the configured LLM using structured JSON output.

    The response is parsed and validated against the supplied
    Pydantic model.

    Retries are performed for:
        - malformed JSON
        - Pydantic validation errors
        - transient API/network failures
        - rate-limit (429) responses

    Rate-limit retries use exponential backoff.
    """

    schema = _to_strict_json_schema(response_model)

    # -----------------------------------------------------------------------
    # Build request
    # -----------------------------------------------------------------------

    request_kwargs: dict = dict(
        model=model,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": schema,
                "strict": True,
            },
        },
    )

    # -----------------------------------------------------------------------
    # Optional provider-specific parameters
    # -----------------------------------------------------------------------

    if prompt_cache_key and config.SUPPORTS_EXPLICIT_CACHE_KEY:
        request_kwargs["prompt_cache_key"] = prompt_cache_key

    if config.SUPPORTS_THINKING_TOGGLE:
        request_kwargs["thinking"] = {
            "type": "enabled" if thinking_enabled else "disabled"
        }

    if config.SUPPORTS_REASONING_EFFORT:
        key = "enabled" if thinking_enabled else "disabled"

        request_kwargs["reasoning_effort"] = (
            config.LLM_REASONING_EFFORT_MAP[key]
        )

    # -----------------------------------------------------------------------
    # Retry loop
    # -----------------------------------------------------------------------

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):

        try:
            response = _client.chat.completions.create(
                **request_kwargs
            )

            raw_content = response.choices[0].message.content

            if not raw_content:
                raise LLMCallError(
                    "LLM returned an empty response."
                )

            parsed = json.loads(raw_content)

            return response_model.model_validate(parsed)

        # -------------------------------------------------------------------
        # JSON / Pydantic errors
        # -------------------------------------------------------------------

        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc

            # These errors aren't necessarily fixed by immediately retrying,
            # but retrying can help if the model occasionally produces bad
            # output.
            if attempt < max_retries:
                continue

        # -------------------------------------------------------------------
        # API / network / rate-limit errors
        # -------------------------------------------------------------------

        except Exception as exc:
            last_error = exc

            error_string = str(exc).lower()

            # ---------------------------------------------------------------
            # Rate limit
            # ---------------------------------------------------------------

            if "429" in error_string or "rate limit" in error_string:

                if attempt < max_retries:

                    # Exponential backoff:
                    #
                    # attempt 0 -> 5 seconds
                    # attempt 1 -> 10 seconds
                    # attempt 2 -> 20 seconds
                    #
                    wait_time = 5 * (2 ** attempt)

                    print(
                        f"[llm] Rate limit reached. "
                        f"Retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})..."
                    )

                    time.sleep(wait_time)

                    continue

            # ---------------------------------------------------------------
            # Other API/network errors
            # ---------------------------------------------------------------

            if attempt < max_retries:

                # Short delay for transient errors.
                time.sleep(1)

                continue

    # -----------------------------------------------------------------------
    # All attempts failed
    # -----------------------------------------------------------------------

    raise LLMCallError(
        f"LLM call failed after {max_retries + 1} attempts for schema "
        f"'{schema_name}' "
        f"(provider={config.LLM_PROVIDER}, model={model}): "
        f"{last_error}"
    )