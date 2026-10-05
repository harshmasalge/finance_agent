"""
LLM access for every agent.

Providers are OpenAI-compatible endpoints configured from .env. The user picks a
provider + model per chat in the UI; the choice is held in a context variable for
the duration of that request, so agents just call get_llm() / get_structured_llm().
"""
import itertools
import os
import threading
from contextvars import ContextVar
from typing import Dict, List, Optional

from langchain_openai import ChatOpenAI

from backend.app_mode import InspectModeError, inspect_message, is_inspect

PROVIDERS: Dict[str, dict] = {
    "groq": {
        "label": "Groq",
        "note": "Free tier",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": ["GROQ_API_KEYS", "GROQ_API_KEY"],
        "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
        # Groq's free tier limits tokens per minute and counts the requested completion size.
        "max_tokens": 2048,
    },
    "openrouter": {
        "label": "OpenRouter",
        "note": "Paid credits",
        "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        "key_env": ["OPENROUTER_API_KEY"],
        "models": ["openai/gpt-4o-mini"],
        "max_tokens": 13000,
        "headers": {"HTTP-Referer": "http://localhost:5173", "X-Title": "FinSight AI"},
    },
    "gemini": {
        "label": "Google Gemini",
        "note": "Free tier · low rate limits",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": ["GEMINI_API_KEYS", "GOOGLE_API_KEYS", "GOOGLE_API_KEY"],
        "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "max_tokens": 4096,
    },
}

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

_selection: ContextVar[Optional[dict]] = ContextVar("llm_selection", default=None)
_cycles: Dict[str, itertools.cycle] = {}
_lock = threading.Lock()


def _keys(provider: str) -> List[str]:
    for var in PROVIDERS[provider]["key_env"]:
        raw = os.getenv(var, "")
        keys = [k.strip().strip('"') for k in raw.split(",") if k.strip()]
        if keys:
            return keys
    return []


def _next_key(provider: str) -> str:
    """Round-robin across all configured keys so free-tier limits are shared."""
    keys = _keys(provider)
    if not keys:
        raise RuntimeError(f"No API key configured for {PROVIDERS[provider]['label']}. "
                           f"Set {PROVIDERS[provider]['key_env'][0]} in .env.")
    with _lock:
        if provider not in _cycles or len(_keys(provider)) != len(keys):
            _cycles[provider] = itertools.cycle(keys)
        return next(_cycles[provider])


def default_model(provider: str) -> str:
    if provider == "openrouter":
        return os.getenv("LLM_MODEL", PROVIDERS[provider]["models"][0])
    return PROVIDERS[provider]["models"][0]


def list_providers() -> List[dict]:
    return [{
        "id": pid, "label": p["label"], "note": p["note"], "models": p["models"],
        "default_model": default_model(pid), "available": bool(_keys(pid)), "keys": len(_keys(pid)),
    } for pid, p in PROVIDERS.items()]


def resolve(provider: Optional[str], model: Optional[str]) -> dict:
    """Validate a UI selection, falling back to the default provider/model."""
    pid = provider if provider in PROVIDERS else DEFAULT_PROVIDER
    if not _keys(pid):
        pid = next((p for p in PROVIDERS if _keys(p)), pid)
    mdl = model if model in PROVIDERS[pid]["models"] or (pid == "openrouter" and model) else default_model(pid)
    return {"provider": pid, "model": mdl, "label": PROVIDERS[pid]["label"]}


def use_llm(provider: Optional[str], model: Optional[str]) -> dict:
    """Set the provider/model for the current request (context-local)."""
    sel = resolve(provider, model)
    _selection.set(sel)
    return sel


def current_selection() -> dict:
    return _selection.get() or resolve(None, None)


def get_llm(temperature: float = 0.1, model: Optional[str] = None) -> ChatOpenAI:
    if is_inspect():  # backstop: no LLM call can spend credits in inspect mode
        raise InspectModeError(inspect_message())
    sel = current_selection()
    p = PROVIDERS[sel["provider"]]
    kwargs = dict(
        model=model or sel["model"],
        temperature=temperature,
        api_key=_next_key(sel["provider"]),
        base_url=p["base_url"],
        timeout=90,
        max_retries=3,
    )
    if p.get("max_tokens"):
        kwargs["max_tokens"] = p["max_tokens"]
    if p.get("headers"):
        kwargs["default_headers"] = p["headers"]
    return ChatOpenAI(**kwargs)


_capability_cache: Dict[str, bool] = {}


def supports_json_schema(provider: str, model: str) -> bool:
    """Whether the model accepts response_format/json_schema.

    For OpenRouter this is read once from the public models list (e.g. most ':free'
    variants support tools but not structured outputs). Other providers are assumed to.
    Unknown -> True, so the strict path is tried with function calling as fallback.
    """
    if provider != "openrouter":
        return True
    key = model
    if key not in _capability_cache:
        try:
            import json
            import urllib.request
            req = urllib.request.Request(f"{PROVIDERS['openrouter']['base_url']}/models",
                                         headers={"User-Agent": "finsight"})
            models = json.load(urllib.request.urlopen(req, timeout=10))["data"]
            for m in models:
                params = set(m.get("supported_parameters") or [])
                _capability_cache[m["id"]] = bool(params & {"structured_outputs", "response_format"})
        except Exception:
            pass
        _capability_cache.setdefault(key, True)
    return _capability_cache[key]


def get_structured_llm(schema, temperature: float = 0.1):
    """LLM that must return `schema`.

    Uses strict JSON-schema mode when the model supports it, with function calling as
    fallback; models without structured-output support go straight to function calling
    (no wasted requests on free-tier models).
    """
    sel = current_selection()
    tools = get_llm(temperature).with_structured_output(schema, method="function_calling").with_retry(stop_after_attempt=2)
    if not supports_json_schema(sel["provider"], sel["model"]):
        return tools
    strict = get_llm(temperature).with_structured_output(schema, method="json_schema", strict=True)
    return strict.with_fallbacks([tools])
