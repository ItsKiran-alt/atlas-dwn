"""Provider-independent LLM access (Groq, Gemini, or none).

* The LLM only interprets, explains and drafts. It never calculates, approves, or controls auditing.
* Every response is parsed as JSON and then validated by the calling skill; invalid output is rejected.
* Secrets are read from environment variables only and are scrubbed from every error message.
* Request shapes follow the providers' documentation as fetched on 2026-10-20 (Groq: OpenAI-compatible chat completions;
  Gemini: models.generateContent). NEITHER ADAPTER HAS BEEN RUN LIVE (no API key available when this was written).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .. import config

LLM_HOSTS = {"api.groq.com", "generativelanguage.googleapis.com"}


class LLMError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind      # not_configured | network | http | rate_limited | parse | blocked | budget


@dataclass
class LLMResult:
    data: dict
    provider: str
    model: str
    tokens: int = 0


class LLM(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, max_tokens: int = 900) -> LLMResult: ...


Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def urllib_post(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    try:
        r = urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, data=body, headers=headers, method="POST"), timeout=timeout)
        return r.status, r.read(config.HTTP_MAX_BYTES)
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000)
    except TimeoutError as e:
        raise LLMError("network", "timed out") from e
    except (urllib.error.URLError, OSError) as e:
        raise LLMError("network", type(e).__name__) from e


def _scrub(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "[redacted]")
    return text[:200]


def parse_json_text(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        v = json.loads(t)
    except json.JSONDecodeError as e:
        raise LLMError("parse", "model output was not valid JSON") from e
    if not isinstance(v, dict):
        raise LLMError("parse", "model output was not a JSON object")
    return v


class _HttpLLM:
    name = ""
    model = ""
    key = ""

    def __init__(self, transport: Transport = urllib_post, key: str | None = None, model: str | None = None, timeout: float = 30.0):
        self.transport, self.timeout = transport, timeout
        self.key = key if key is not None else self._env_key()
        self.model = model or self._env_model()

    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        if not self.key:
            raise LLMError("not_configured", f"{self.name}: API key not set")
        host = urllib.parse.urlsplit(url).hostname
        if not url.startswith("https://") or host not in LLM_HOSTS:
            raise LLMError("blocked", "LLM host not allowed")
        try:
            status, body = self.transport(url, {"Content-Type": "application/json", **headers}, json.dumps(payload).encode(), self.timeout)
        except LLMError:
            raise
        if status == 429:
            raise LLMError("rate_limited", f"{self.name}: rate limited")
        if status >= 400:
            raise LLMError("http", _scrub(f"{self.name}: HTTP {status}", self.key))
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise LLMError("parse", "provider response was not JSON") from e


class GroqLLM(_HttpLLM):
    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def _env_key(self):
        return os.environ.get("GROQ_API_KEY", "")

    def _env_model(self):
        return os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")      # model id listed on Groq's rate-limits page on 2026-10-20

    def complete_json(self, system: str, user: str, max_tokens: int = 900) -> LLMResult:
        r = self._post(self.URL, {"Authorization": f"Bearer {self.key}"},
                       {"model": self.model, "temperature": 0, "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        try:
            text = r["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("parse", "unexpected provider response shape") from e
        return LLMResult(parse_json_text(text), self.name, self.model, int((r.get("usage") or {}).get("total_tokens", 0)))


class GeminiLLM(_HttpLLM):
    name = "gemini"

    def _env_key(self):
        return os.environ.get("GEMINI_API_KEY", "")

    def _env_model(self):
        return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")       # UNVERIFIED default: confirm the current model id in Google AI Studio

    def complete_json(self, system: str, user: str, max_tokens: int = 900) -> LLMResult:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(self.model)}:generateContent"
        r = self._post(url, {"x-goog-api-key": self.key},
                       {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}})
        try:
            parts = r["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("parse", "unexpected provider response shape (blocked or empty?)") from e
        return LLMResult(parse_json_text(text), self.name, self.model, int((r.get("usageMetadata") or {}).get("totalTokenCount", 0)))


class TemplateLLM:
    """No model. Skills use their deterministic fallback and label the output 'template (no AI)'."""
    name = "template"
    model = "rules"

    def complete_json(self, system: str, user: str, max_tokens: int = 900) -> LLMResult:
        raise LLMError("not_configured", "no LLM configured; using deterministic templates")


@dataclass
class ScriptedLLM:
    """Test double: returns queued responses (dict) or raises queued exceptions; records every prompt."""
    responses: list = field(default_factory=list)
    name: str = "scripted"
    model: str = "test"
    calls: list = field(default_factory=list)

    def complete_json(self, system: str, user: str, max_tokens: int = 900) -> LLMResult:
        self.calls.append((system, user))
        if not self.responses:
            raise LLMError("parse", "no scripted response")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResult(r, self.name, self.model, 0)


def make_llm(provider: str | None = None, transport: Transport = urllib_post):
    provider = (provider or os.environ.get("DWN_LLM_PROVIDER", "template")).lower()
    if provider == "groq":
        return GroqLLM(transport=transport)
    if provider == "gemini":
        return GeminiLLM(transport=transport)
    return TemplateLLM()
