"""
Central place for environment-driven config. Nothing sensitive is
hardcoded here — set real values via a local .env file (see .env.example)
or real environment variables; either works.

Supports three OpenAI-compatible providers behind one interface, switched
with LLM_PROVIDER:

  - "groq": free tier, no credit card required. Runs openai/gpt-oss-120b.
    Free tier: 30 RPM, 1K RPD, 8K TPM, 200K TPD.

  - "mistral" (default): free "Experiment" tier, no credit card (phone
    verification required). Runs mistral-large-latest — the free tier
    covers all Mistral models at the same rate limit, so there's no
    quality/cost tradeoff in picking Large over Small for dev.
    Free tier: ~1 request/second, ~500K tokens/minute, ~1B tokens/month.

  - "moonshot": Moonshot's own hosted API (kimi-k2.6 by default). Swap to
    this once you've bought Kimi credits for the hackathon itself.

Usage — copy .env.example to .env in this same folder and fill in your
real key, e.g.:
    LLM_PROVIDER=mistral
    MISTRAL_API_KEY=...

Loading it from a file (instead of `export` in a terminal) means it
doesn't matter which terminal/tab you run uvicorn from — the app reads
its own key every time it starts, so there's nothing to lose track of.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # reads a .env file in the current working directory, if present

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mistral")  # "groq" | "mistral" | "moonshot"

_PROVIDER_DEFAULTS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        # NOTE: moonshotai/kimi-k2-instruct-0905 (the model this originally
        # pointed at) was deprecated by Groq on 2026-03-23 in favor of this
        # model — a different model family than Kimi, but Groq's own
        # recommended replacement, with confirmed strict json_schema support.
        "model": "openai/gpt-oss-120b",
        # gpt-oss-120b is a reasoning model that supports "low"/"medium"/"high".
        "reasoning_effort": {"disabled": "low", "enabled": "medium"},
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "model": "mistral-large-latest",
        # mistral-large-latest actively REJECTS reasoning_effort with a
        # 400 ("reasoning_effort is not enabled for this model") — it's
        # apparently only accepted by specific Mistral models (small,
        # medium), not Large. Rather than guess which ones, just don't
        # send it at all for this provider.
        "reasoning_effort": None,
    },
    "moonshot": {
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "model": "kimi-k2.6",
        # kimi-k2.6 uses a separate `thinking: {type: enabled|disabled}`
        # param instead of reasoning_effort — see SUPPORTS_THINKING_TOGGLE.
        "reasoning_effort": None,
    },
}

if LLM_PROVIDER not in _PROVIDER_DEFAULTS:
    raise ValueError(
        f"Unknown LLM_PROVIDER={LLM_PROVIDER!r}, expected one of {list(_PROVIDER_DEFAULTS)}"
    )

_provider_cfg = _PROVIDER_DEFAULTS[LLM_PROVIDER]

LLM_BASE_URL = _provider_cfg["base_url"]
LLM_API_KEY = os.environ.get(
    _provider_cfg["api_key_env"], f"[{_provider_cfg['api_key_env']}]"
)
LLM_MODEL = os.environ.get("LLM_MODEL", _provider_cfg["model"])

# kimi-k2.6 (Moonshot's own hosted API) supports toggling `thinking`
# on/off explicitly; Groq and Mistral don't have that param, they use
# reasoning_effort instead (see below). Moonshot's API also supports an
# explicit prompt_cache_key; Groq/Mistral's caching (if any) is automatic.
SUPPORTS_THINKING_TOGGLE = LLM_PROVIDER == "moonshot"
SUPPORTS_EXPLICIT_CACHE_KEY = LLM_PROVIDER == "moonshot"

# Maps thinking_enabled (bool) -> this provider's actual reasoning_effort
# string. None for providers/models that don't support the param at all.
LLM_REASONING_EFFORT_MAP = _provider_cfg["reasoning_effort"]
SUPPORTS_REASONING_EFFORT = LLM_REASONING_EFFORT_MAP is not None

# Prints once, when this module is first imported (i.e. when uvicorn boots,
# before it serves any request) — so the terminal actually RUNNING the
# server tells you directly whether it saw the key, instead of you having
# to infer it from a 401 three steps later or from a check run in a
# different terminal. Never prints the full key.
if LLM_API_KEY == f"[{_provider_cfg['api_key_env']}]":
    print(
        f"[config] WARNING: {_provider_cfg['api_key_env']} is NOT set in "
        f"this process — every LLM call will 401. Set it and restart "
        f"uvicorn (not just --reload) in THIS terminal."
    )
else:
    print(
        f"[config] provider={LLM_PROVIDER} model={LLM_MODEL} "
        f"{_provider_cfg['api_key_env']} loaded "
        f"(starts with '{LLM_API_KEY[:6]}...', length {len(LLM_API_KEY)})"
    )
