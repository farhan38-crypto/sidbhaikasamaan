"""
ai_client.py
------------
Talks to the AI model so the rest of the app doesn't care which provider is used.

Providers (picked from the keys found in .env):
  * Google Gemini            -> GEMINI_API_KEY   (free key: aistudio.google.com/apikey)
  * OpenAI-compatible APIs   -> OPENAI_API_KEY   (Groq, OpenAI, OpenRouter, ...)
                                A Groq key (starts with "gsk_") is detected automatically.
  * Offline demo mode        -> no key needed; uses the built-in question bank

Reliability features (why the app no longer times out):
  * A fast model is tried first, then a fallback model, then the other provider.
    e.g. gemini-flash-lite-latest -> gemini-flash-latest -> Groq gpt-oss-120b
  * "Thinking" is kept low, so models answer in seconds instead of minutes.
  * Each attempt has its own timeout, and the whole request has a time budget.
  * Errors are turned into plain-English messages (bad key, quota, overloaded, ...).
"""

import json
import os
import re
import time

import requests

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GEMINI_MODELS = "gemini-flash-lite-latest,gemini-flash-latest"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class AIError(Exception):
    """Raised when every AI provider failed or returned something unusable."""


class _AttemptError(Exception):
    """One provider/model attempt failed. `retry_plain` = try again without optional params."""

    def __init__(self, message, retry_plain=False):
        super().__init__(message)
        self.retry_plain = retry_plain


def _env(name, default=""):
    """Read a setting; an empty line like `OPENAI_MODEL=` in .env counts as not set."""
    return os.getenv(name, "").strip() or default


def _models(value):
    return [m.strip() for m in value.split(",") if m.strip()]


class AIClient:
    def __init__(self):
        self.timeout = float(_env("AI_TIMEOUT", "45"))         # seconds per attempt
        self.total_budget = float(_env("AI_TOTAL_BUDGET", "110"))  # seconds for all attempts
        self.config_error = ""

        gemini_key = _env("GEMINI_API_KEY")
        openai_key = _env("OPENAI_API_KEY")
        openai_base = _env("OPENAI_BASE_URL")
        if openai_key.startswith("gsk_") and not openai_base:
            openai_base = GROQ_BASE_URL  # Groq key used without setting the URL
        openai_base = (openai_base or "https://api.openai.com/v1").rstrip("/")
        is_groq = "groq.com" in openai_base
        default_openai_model = DEFAULT_GROQ_MODEL if is_groq else DEFAULT_OPENAI_MODEL

        available = {}
        if gemini_key:
            available["gemini"] = {
                "kind": "gemini", "name": "Gemini", "key": gemini_key,
                "models": _models(_env("GEMINI_MODEL", DEFAULT_GEMINI_MODELS)),
            }
        if openai_key:
            available["openai"] = {
                "kind": "openai", "name": "Groq" if is_groq else "OpenAI-compatible",
                "key": openai_key, "base": openai_base,
                "models": _models(_env("OPENAI_MODEL", default_openai_model)),
            }

        # AI_PROVIDER only decides which provider is tried first; the other stays as backup.
        preferred = _env("AI_PROVIDER").lower()
        if preferred == "offline":
            self.providers = []
            self.config_error = "AI is switched off (AI_PROVIDER=offline)."
        else:
            order = [preferred] if preferred in available else []
            order += [p for p in ("gemini", "openai") if p in available and p not in order]
            self.providers = [available[p] for p in order if available[p]["models"]]
            if not self.providers:
                self.config_error = ("No API key found. Add GEMINI_API_KEY (or a Groq/OpenAI key) "
                                     "to the .env file to turn on AI generation.")

        self._plain_only = set()  # models that rejected our optional params (e.g. thinking level)

    # ------------------------------------------------------------------ info
    @property
    def is_online(self) -> bool:
        return bool(self.providers)

    def chain(self):
        """Every (provider, model) pair in the order they will be tried."""
        return [(p, m) for p in self.providers for m in p["models"]]

    def describe(self) -> dict:
        if not self.providers:
            return {"provider": "offline", "model": "built-in question bank", "online": False,
                    "reason": self.config_error}
        first, model = self.chain()[0]
        return {
            "provider": first["name"], "model": model, "online": True,
            "fallbacks": [f"{p['name']}: {m}" for p, m in self.chain()[1:]],
        }

    # ------------------------------------------------------------- main call
    def generate_json(self, system_prompt, user_prompt, temperature=0.8, max_tokens=8192):
        """Ask the model and return (parsed JSON dict, "Provider · model" that answered)."""
        if not self.providers:
            raise AIError(self.config_error)

        started = time.monotonic()
        errors = []
        for provider, model in self.chain():
            if errors and time.monotonic() - started > self.total_budget:
                errors.append("stopped trying - time budget used up")
                break
            plain = model in self._plain_only
            for _ in range(2):  # second pass only if the model rejected optional params
                try:
                    if provider["kind"] == "gemini":
                        text = self._call_gemini(provider, model, system_prompt, user_prompt,
                                                 temperature, max_tokens, plain)
                    else:
                        text = self._call_openai(provider, model, system_prompt, user_prompt,
                                                 temperature, max_tokens, plain)
                    return extract_json(text), f"{provider['name']} · {model}"
                except _AttemptError as exc:
                    if exc.retry_plain and not plain:
                        self._plain_only.add(model)
                        plain = True
                        continue
                    errors.append(f"{model}: {exc}")
                    break
                except AIError as exc:  # reply was not usable JSON
                    errors.append(f"{model}: {exc}")
                    break

        raise AIError(_summarise(errors))

    # ------------------------------------------------------------ providers
    def _call_gemini(self, provider, model, system_prompt, user_prompt, temperature, max_tokens, plain):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        config = {"temperature": temperature, "maxOutputTokens": max_tokens,
                  "responseMimeType": "application/json"}
        thinking = None if plain else _gemini_thinking(model)
        if thinking:
            config["thinkingConfig"] = thinking
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": config,
        }
        # New "AQ." keys and old "AIza" keys both go in this header.
        headers = {"Content-Type": "application/json", "x-goog-api-key": provider["key"]}
        resp = self._post(url, body, headers)

        if resp.status_code != 200:
            msg = _error_message(resp)
            if resp.status_code == 400 and thinking and "think" in msg.lower():
                raise _AttemptError(msg, retry_plain=True)
            raise _AttemptError(_explain(resp.status_code, msg, "Gemini"))

        data = _json(resp)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
            raise _AttemptError(f"Gemini returned no answer ({reason}).")
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if cand.get("finishReason") == "MAX_TOKENS":
            raise _AttemptError("the answer was cut off (too long).")
        return text

    def _call_openai(self, provider, model, system_prompt, user_prompt, temperature, max_tokens, plain):
        url = f"{provider['base']}/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if not plain:
            body["max_tokens"] = max_tokens
            if "gpt-oss" in model or re.match(r"^(o\d|gpt-5)", model):
                body["reasoning_effort"] = "low"  # keeps reasoning models fast
        headers = {"Authorization": f"Bearer {provider['key']}", "Content-Type": "application/json"}
        resp = self._post(url, body, headers)

        if resp.status_code != 200:
            msg = _error_message(resp)
            if resp.status_code == 400 and not plain and any(
                    w in msg.lower() for w in ("reasoning", "max_tokens", "temperature", "unsupported")):
                raise _AttemptError(msg, retry_plain=True)
            raise _AttemptError(_explain(resp.status_code, msg, provider["name"]))
        try:
            choice = _json(resp)["choices"][0]
            if choice.get("finish_reason") == "length":
                raise _AttemptError("the answer was cut off (too long).")
            return choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _AttemptError("unexpected response format.")

    def _post(self, url, body, headers):
        try:
            return requests.post(url, json=body, headers=headers, timeout=(10, self.timeout))
        except requests.Timeout:
            raise _AttemptError(f"no answer within {self.timeout:.0f} s (timed out).")
        except requests.ConnectionError:
            raise _AttemptError("could not connect - check your internet connection.")
        except requests.RequestException as exc:
            raise _AttemptError(f"request failed ({type(exc).__name__}).")


# ---------------------------------------------------------------- helpers
def _gemini_thinking(model: str):
    """Keep thinking short so answers come back fast. Format depends on the model generation."""
    m = model.lower()
    if re.search(r"gemini-2\.0|gemma", m):
        return None                                   # no thinking support
    if "gemini-2.5" in m:
        return None if "pro" in m else {"thinkingBudget": 0}
    # Gemini 3.x and the "-latest" aliases use thinking levels.
    # "minimal" is only accepted by Flash-Lite; the bigger models accept "low".
    return {"thinkingLevel": "minimal" if "lite" in m else "low"}


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        raise _AttemptError("the server sent back something that wasn't JSON.")


def _error_message(resp) -> str:
    try:
        err = resp.json().get("error", {})
        if isinstance(err, dict):
            status = err.get("status") or ""
            details = json.dumps(err.get("details", ""))
            reason = "ACCESS_TOKEN_TYPE_UNSUPPORTED" if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in details else ""
            return " ".join(x for x in (err.get("message", ""), status, reason) if x)[:300]
        return str(err)[:300]
    except ValueError:
        return resp.text[:300]


def _explain(code: int, msg: str, provider: str) -> str:
    low = msg.lower()
    if "access_token_type_unsupported" in low:
        return (f"{provider} rejected this API key type. Create a new key at "
                "aistudio.google.com/apikey, or add a Groq key as a backup.")
    if code in (400, 401, 403) and ("api key" in low or "api_key" in low or code == 401):
        return f"{provider} says the API key is invalid or not allowed ({code})."
    if code == 403:
        return f"{provider} refused the request ({code}): {msg[:120]}"
    if code == 404:
        return f"model not found ({code}) - check the model name in .env."
    if code == 429:
        return f"rate limit or free quota used up ({code}) - wait a minute and try again."
    if code >= 500:
        return f"{provider} is overloaded or down right now ({code})."
    return f"{provider} error {code}: {msg[:150]}"


def _summarise(errors) -> str:
    """Group models that failed for the same reason: 'a, b: reason | c: other reason'."""
    if not errors:
        return "No AI provider answered."
    grouped = {}
    for err in errors:
        model, _, reason = err.partition(": ")
        grouped.setdefault(reason or model, []).append(model if reason else "")
    parts = [f"{', '.join(m for m in models if m)}: {reason}".lstrip(": ") for reason, models in grouped.items()]
    prefix = "" if len(errors) == 1 else "All AI models failed - "
    return prefix + " | ".join(parts)


def extract_json(text: str) -> dict:
    """Models sometimes wrap JSON in ```code fences``` or add chatter - clean that up."""
    if not text or not text.strip():
        raise AIError("the model returned an empty reply.")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        try:
            data = json.loads(cleaned[start: end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        raise AIError("the model's reply was not valid JSON.")
    return data
