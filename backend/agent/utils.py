"""
LLM access for every agent.

Providers are OpenAI-compatible endpoints configured from .env. The user picks a
provider + model per chat in the UI; the choice is held in a context variable for
the duration of that request, so agents just call get_llm() / get_structured_llm().

Every key configured for a provider is used: requests take turns across the keys, and a key
that is rate-limited, out of credit or rejected is skipped for the same request (keypool.py).
"""
import os
import threading
from contextvars import ContextVar
from typing import Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.agent.keypool import KeyPool, make_clients
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
        "key_env": ["OPENROUTER_API_KEYS", "OPENROUTER_API_KEY"],
        "models": ["openai/gpt-4o-mini", "nvidia/nemotron-3-ultra-550b-a55b:free", "qwen/qwen3.8-27b:free"],
        "max_tokens": 13000,
        "headers": {"HTTP-Referer": "http://localhost:5173", "X-Title": "FinSight AI"},
    },
    "anthropic": {
        "label": "Anthropic",
        "note": "Paid · Claude",
        "kind": "anthropic",            # native SDK via langchain-anthropic (not OpenAI-compatible)
        "key_env": ["ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"],
        # Cheapest first: the first model is this provider's default.
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
        # Anthropic requires max_tokens; enough for the final structured answer.
        "max_tokens": 4096,
        # The 5.x Claude models reject `temperature` ("deprecated for this model"), so it is not sent.
        "temperature": False,
    },
    "gemini": {
        "label": "Google Gemini",
        "note": "Free tier · low rate limits",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": ["GEMINI_API_KEYS", "GEMINI_API_KEY", "GOOGLE_API_KEYS", "GOOGLE_API_KEY"],
        "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "max_tokens": 4096,
    },
}

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

_selection: ContextVar[Optional[dict]] = ContextVar("llm_selection", default=None)
_pools: Dict[str, KeyPool] = {}
_sync_clients: Dict[str, object] = {}
_lock = threading.Lock()


def _keys(provider: str) -> List[str]:
    """Every key configured for a provider: all of its variables (singular and plural), each of
    which may hold a comma-separated list. Duplicates are dropped, order is kept."""
    keys: List[str] = []
    for var in PROVIDERS[provider]["key_env"]:
        for k in os.getenv(var, "").split(","):
            k = k.strip().strip('"').strip("'")
            if k and k not in keys:
                keys.append(k)
    return keys


def _pool(provider: str) -> KeyPool:
    keys = _keys(provider)
    if not keys:
        raise RuntimeError(f"No API key configured for {PROVIDERS[provider]['label']}. "
                           f"Set {PROVIDERS[provider]['key_env'][0]} in .env.")
    with _lock:
        pool = _pools.get(provider)
        if pool is None or pool.keys != keys:  # keys changed (e.g. .env reloaded)
            pool = _pools[provider] = KeyPool(provider, keys)
            _sync_clients.pop(provider, None)
        return pool


def _http_clients(provider: str, sdk, header: str):
    """Key-rotating HTTP clients for this provider (sync client shared, async client per model)."""
    pool = _pool(provider)
    with _lock:
        if provider not in _sync_clients:
            _sync_clients[provider] = make_clients(sdk, pool, header)[0]
        sync_client = _sync_clients[provider]
    return pool, sync_client, make_clients(sdk, pool, header)[1]


def default_model(provider: str) -> str:
    env_model = os.getenv("LLM_MODEL")
    if provider == "openrouter":
        return env_model or PROVIDERS[provider]["models"][0]
    # e.g. LLM_PROVIDER=anthropic + LLM_MODEL=claude-sonnet-5-5; ignored if it isn't one of this provider's models
    if env_model and env_model in PROVIDERS[provider]["models"]:
        return env_model
    return PROVIDERS[provider]["models"][0]


def list_providers() -> List[dict]:
    out = []
    for pid, p in PROVIDERS.items():
        models = list(p["models"])
        if default_model(pid) not in models:  # e.g. a custom LLM_MODEL from .env
            models.insert(0, default_model(pid))
        out.append({"id": pid, "label": p["label"], "note": p["note"], "models": models,
                    "default_model": default_model(pid), "available": bool(_keys(pid)), "keys": len(_keys(pid)),
                    "resting_keys": _pools[pid].status()["resting"] if pid in _pools else 0})
    return out


def config_diagnostics() -> dict:
    """Where the default provider/model come from, and whether the process environment
    overrides .env (python-dotenv never overrides variables that are already set, so a stale
    LLM_MODEL in the shell or Windows user environment silently wins)."""
    from pathlib import Path
    try:
        from dotenv import dotenv_values
        file_vals = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        file_vals = {}
    warnings = []
    for var in ("LLM_PROVIDER", "LLM_MODEL"):
        in_file, in_env = file_vals.get(var), os.getenv(var)
        if in_file and in_env and in_file.strip().strip('"') != in_env:
            warnings.append(f"{var} is '{in_env}' in the process environment but '{in_file}' in .env - "
                            f"the environment value wins. Remove it (PowerShell: Remove-Item Env:{var}; "
                            f"also check Windows user variables) and restart the API.")
    src = ("environment (overrides .env)" if warnings else
           ".env" if file_vals.get("LLM_MODEL") or file_vals.get("LLM_PROVIDER") else "built-in default")
    return {"source": src, "warnings": warnings}


def resolve(provider: Optional[str], model: Optional[str]) -> dict:
    """Validate a UI selection, falling back to the default provider/model."""
    pid = provider if provider in PROVIDERS else DEFAULT_PROVIDER
    if not _keys(pid):
        pid = next((p for p in PROVIDERS if _keys(p)), pid)
    # Only listed models (plus the configured default) - never an arbitrary model name from the client,
    # which on a public deployment could run expensive models on the owner's credit.
    allowed = set(PROVIDERS[pid]["models"]) | {default_model(pid)}
    mdl = model if model in allowed else default_model(pid)
    return {"provider": pid, "model": mdl, "label": PROVIDERS[pid]["label"]}


def use_llm(provider: Optional[str], model: Optional[str]) -> dict:
    """Set the provider/model for the current request (context-local)."""
    sel = resolve(provider, model)
    _selection.set(sel)
    return sel


def current_selection() -> dict:
    return _selection.get() or resolve(None, None)


def get_llm(temperature: float = 0.1, model: Optional[str] = None) -> BaseChatModel:
    if is_inspect():  # backstop: no LLM call can spend credits in inspect mode
        raise InspectModeError(inspect_message())
    sel = current_selection()
    p = PROVIDERS[sel["provider"]]
    if p.get("kind") == "anthropic":
        import anthropic
        pool, sync_client, async_client = _http_clients(sel["provider"], anthropic, "x-api-key")
        return _rotating_anthropic_class()(
            model=model or sel["model"],
            temperature=temperature if p.get("temperature", True) else None,
            api_key=pool.keys[0],  # placeholder: every request gets its key from the pool
            max_tokens=p["max_tokens"],
            default_request_timeout=90,
            max_retries=3,
            sync_http=sync_client,
            async_http=async_client,
        )
    import openai
    pool, sync_client, async_client = _http_clients(sel["provider"], openai, "Authorization")
    kwargs = dict(
        model=model or sel["model"],
        temperature=temperature,
        api_key=pool.keys[0],  # placeholder: every request gets its key from the pool
        base_url=p["base_url"],
        timeout=90,
        max_retries=3,
        http_client=sync_client,
        http_async_client=async_client,
    )
    if p.get("max_tokens"):
        kwargs["max_tokens"] = p["max_tokens"]
    if p.get("headers"):
        kwargs["default_headers"] = p["headers"]
    return ChatOpenAI(**kwargs)


_anthropic_cls = None


def _rotating_anthropic_class():
    """ChatAnthropic that sends through our key-rotating HTTP clients (it has no
    http_client option, so the SDK client properties are overridden)."""
    global _anthropic_cls
    if _anthropic_cls is None:
        from functools import cached_property

        import anthropic
        from langchain_anthropic import ChatAnthropic
        from pydantic import ConfigDict

        class RotatingChatAnthropic(ChatAnthropic):
            model_config = ConfigDict(arbitrary_types_allowed=True)
            sync_http: object = None
            async_http: object = None

            @cached_property
            def _client(self) -> anthropic.Client:
                return anthropic.Client(**self._client_params, http_client=self.sync_http)

            @cached_property
            def _async_client(self) -> anthropic.AsyncClient:
                return anthropic.AsyncClient(**self._client_params, http_client=self.async_http)

        _anthropic_cls = RotatingChatAnthropic
    return _anthropic_cls


_capability_cache: Dict[str, bool] = {}


def supports_json_schema(provider: str, model: str) -> bool:
    """Whether the model accepts response_format/json_schema.

    For OpenRouter this is read once from the public models list (e.g. most ':free'
    variants support tools but not structured outputs). Other providers are assumed to.
    Unknown -> True, so the strict path is tried with function calling as fallback.
    """
    if PROVIDERS.get(provider, {}).get("kind") == "anthropic":
        return False  # use Claude's native tool-based structured output
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
