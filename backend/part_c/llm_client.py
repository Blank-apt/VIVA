"""
Thin OpenAI-compatible client wrapper. Works against either provider
configured in config.py (Groq for free dev, Moonshot for the paid
hackathon run) — both expose an OpenAI-shaped chat completions endpoint,
so this file never needs to know which one it's talking to.

Handles:
  - Structured Output (response_format: json_schema) so responses parse
    directly into Pydantic models instead of hand-rolled JSON parsing
  - Retries on transient failures / malformed JSON
  - thinking / prompt_cache_key / reasoning_effort params only sent when
    the active provider actually supports them (see config.py)
"""
from __future__ import annotations

import json
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

import config

T = TypeVar("T", bound=BaseModel)

_client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)


def _to_strict_json_schema(model: Type[BaseModel]) -> dict:
    """
    Groq/OpenAI-style strict structured output requires, on EVERY object
    in the schema (including nested ones under $defs, reached via $ref):
      - "additionalProperties": false
      - every property listed in "required" — even ones with a Python
        default. Pydantic's model_json_schema() does neither by default,
        which is exactly what produced the 400 error ("additionalProperties
        must be set on every object") the first time this ran against
        Groq's strict validator.

    Forcing every property into "required" doesn't change the Python-side
    contract: fields that had a default (e.g. checklist=[]) just mean the
    model must now always include that key explicitly (e.g. an empty
    list), which our code already handles fine either way.
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


class LLMCallError(RuntimeError):
    """Raised when the LLM fails to return a schema-valid response after retries."""


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
    Calls the configured LLM with Structured Output constrained to
    response_model's JSON schema, and returns a validated instance of
    response_model.

    Raises LLMCallError if every attempt fails (network error, or the
    model returns something that doesn't parse/validate).
    """
    schema = _to_strict_json_schema(response_model)

    request_kwargs: dict = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
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

    if prompt_cache_key and config.SUPPORTS_EXPLICIT_CACHE_KEY:
        request_kwargs["prompt_cache_key"] = prompt_cache_key

    if config.SUPPORTS_THINKING_TOGGLE:
        request_kwargs["thinking"] = {
            "type": "enabled" if thinking_enabled else "disabled"
        }

    if config.SUPPORTS_REASONING_EFFORT:
        key = "enabled" if thinking_enabled else "disabled"
        request_kwargs["reasoning_effort"] = config.LLM_REASONING_EFFORT_MAP[key]

    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        try:
            response = _client.chat.completions.create(**request_kwargs)
            raw_content = response.choices[0].message.content
            parsed = json.loads(raw_content)
            return response_model.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            continue
        except Exception as exc:  # network/API errors etc.
            last_error = exc
            continue

    raise LLMCallError(
        f"LLM call failed after {max_retries + 1} attempts for schema "
        f"'{schema_name}' (provider={config.LLM_PROVIDER}, model={model}): "
        f"{last_error}"
    )
