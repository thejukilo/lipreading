"""LLM transcript cleanup.

Lipreading confuses words that look alike on the lips (god/dog, beating/meeting).
The VSR model has no language understanding, so a small LLM pass — given the
whole sentence as context — fixes those misrecognitions. Pluggable like the TTS
layer: Off by default, a local option (Ollama, private) and a cloud option
(Claude Haiku, higher quality).
"""

from __future__ import annotations

import json
import os
import urllib.request

SYSTEM_PROMPT = (
    "You are a word-level corrector for a lipreading system — NOT an editor. The "
    "recognizer sometimes outputs a wrong word that looks similar on the lips "
    "(e.g. 'god'->'dog', 'beating'->'meeting'). Your ONLY job is to fix those "
    "specific mistakes.\n"
    "Rules:\n"
    "- Change a word ONLY when it is almost certainly a lipreading error that "
    "makes the sentence wrong or nonsensical. Otherwise copy every word EXACTLY.\n"
    "- Do NOT paraphrase or 'improve' the wording. Do NOT replace correct words "
    "with synonyms (keep 'supermarket' as 'supermarket', 'car' as 'car').\n"
    "- Do NOT change grammar, tense, sentence structure, punctuation, or style, "
    "and do NOT add or remove words beyond fixing a misrecognition.\n"
    "- Keep the original capitalization.\n"
    "- Reply in the SAME LANGUAGE as the input. NEVER translate (Dutch stays "
    "Dutch, English stays English).\n"
    "Output ONLY the resulting sentence, nothing else. If nothing needs fixing, "
    "return the sentence unchanged."
)

# Few-shot anchors: fixes + deliberate no-change examples in BOTH English and
# Dutch, so the model learns to fix lip-errors, never paraphrase correct words,
# and stay in the input's language (Dutch in -> Dutch out, no translation).
_FEW_SHOT = [
    ("I love to walk with my god in the park",
     "I love to walk with my dog in the park"),
    ("Hi welcome, in this beating we will present the numbers.",
     "Hi welcome, in this meeting we will present the numbers."),
    ("I will go to the supermarket and drive with my car.",
     "I will go to the supermarket and drive with my car."),
    # Dutch: a p/b viseme fix, and a no-change anchor (do not translate/paraphrase).
    ("de kinderen spelen buiten met de pal",
     "de kinderen spelen buiten met de bal"),
    ("ik ga naar de supermarkt en rijd met mijn auto",
     "ik ga naar de supermarkt en rijd met mijn auto"),
]


def _system_prompt(context: str = "") -> str:
    """Base rules, plus the speaker's personal names/jargon if provided."""
    context = (context or "").strip()
    if not context:
        return SYSTEM_PROMPT
    return (
        SYSTEM_PROMPT
        + "\n\nSPEAKER CONTEXT — names, terms and jargon this person actually "
        "uses. When a word is a likely misrecognition and one of these fits, "
        "prefer it (e.g. a name the recognizer turned into a common word). Do "
        "NOT force these in where they don't fit:\n" + context
    )


def _build_messages(text: str) -> list[dict]:
    msgs = []
    for user, assistant in _FEW_SHOT:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": assistant})
    msgs.append({"role": "user", "content": text})
    return msgs


class Corrector:
    def correct(self, text: str) -> str:
        raise NotImplementedError


class NoopCorrector(Corrector):
    def correct(self, text: str) -> str:
        return text


class OllamaCorrector(Corrector):
    """Local LLM via Ollama (http://localhost:11434). Private, no API key."""

    def __init__(self, model: str = "llama3.1:8b",
                 host: str = "http://localhost:11434", context: str = "") -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.context = context

    def correct(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return text
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0},  # deterministic, minimal edits
            "messages": [{"role": "system", "content": _system_prompt(self.context)}]
            + _build_messages(text),
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            # Generous timeout: the FIRST request loads the model into memory,
            # which can take a while (later requests are fast while it stays warm).
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(
                f"Ollama request failed ({e}). If it timed out, the model was "
                f"probably loading — try once more. Otherwise check Ollama is "
                f"running and the model is pulled:  ollama pull {self.model}"
            ) from e
        out = (data.get("message", {}) or {}).get("content", "").strip()
        return out or text


class AnthropicCorrector(Corrector):
    """Cloud LLM via Claude (Anthropic SDK). Higher quality; needs an API key."""

    def __init__(self, model: str = "claude-haiku-4-5",
                 api_key: str | None = None, context: str = "") -> None:
        self.model = model
        self._api_key = api_key or None  # None -> SDK reads ANTHROPIC_API_KEY
        self.context = context
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError(
                    "Claude cleanup needs the anthropic package:\n"
                    "  pip install anthropic"
                ) from e
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def correct(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return text
        client = self._get_client()
        msg = client.messages.create(
            model=self.model,
            max_tokens=256,
            system=_system_prompt(self.context),
            messages=_build_messages(text),
        )
        out = "".join(b.text for b in msg.content if b.type == "text").strip()
        return out or text


def list_ollama_models(host: str = "http://localhost:11434") -> list[str]:
    """Names of models installed in Ollama (via /api/tags). [] if unreachable."""
    try:
        req = urllib.request.Request(host.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


# Curated Claude models for the cleanup dropdown (fastest/cheapest first).
CLAUDE_MODELS = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"]


def make_corrector(
    backend: str = "off",
    model: str = "",
    api_key: str = "",
    ollama_host: str = "http://localhost:11434",
    context: str = "",
) -> Corrector:
    backend = (backend or "off").lower()
    if backend in ("off", "", "none"):
        return NoopCorrector()
    if backend == "ollama":
        return OllamaCorrector(model=model or "llama3.1:8b", host=ollama_host,
                               context=context)
    if backend == "anthropic":
        return AnthropicCorrector(model=model or "claude-haiku-4-5",
                                  api_key=api_key or None, context=context)
    return NoopCorrector()
