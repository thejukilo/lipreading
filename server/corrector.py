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
    "You clean up transcripts from a silent-speech (lipreading) system. The "
    "recognizer confuses words that look similar on the lips, so the text often "
    "contains a wrong but similar-looking word (e.g. 'god'->'dog', "
    "'beating'->'meeting'). Rewrite the transcript so it reads as natural, "
    "correct English, fixing likely misrecognitions from context. Rules: keep "
    "the speaker's original meaning, wording, and length as close as possible; "
    "only change words that are likely errors; do NOT add information, answer "
    "questions, or add commentary or quotation marks. Output ONLY the corrected "
    "sentence, nothing else."
)


class Corrector:
    def correct(self, text: str) -> str:
        raise NotImplementedError


class NoopCorrector(Corrector):
    def correct(self, text: str) -> str:
        return text


class OllamaCorrector(Corrector):
    """Local LLM via Ollama (http://localhost:11434). Private, no API key."""

    def __init__(self, model: str = "llama3.1:8b",
                 host: str = "http://localhost:11434") -> None:
        self.model = model
        self.host = host.rstrip("/")

    def correct(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return text
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(
                f"Ollama request failed ({e}). Is Ollama running and is the "
                f"model '{self.model}' pulled?  ollama pull {self.model}"
            ) from e
        out = (data.get("message", {}) or {}).get("content", "").strip()
        return out or text


class AnthropicCorrector(Corrector):
    """Cloud LLM via Claude (Anthropic SDK). Higher quality; needs an API key."""

    def __init__(self, model: str = "claude-haiku-4-5",
                 api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key or None  # None -> SDK reads ANTHROPIC_API_KEY
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
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        out = "".join(b.text for b in msg.content if b.type == "text").strip()
        return out or text


def make_corrector(
    backend: str = "off",
    model: str = "",
    api_key: str = "",
    ollama_host: str = "http://localhost:11434",
) -> Corrector:
    backend = (backend or "off").lower()
    if backend in ("off", "", "none"):
        return NoopCorrector()
    if backend == "ollama":
        return OllamaCorrector(model=model or "llama3.1:8b", host=ollama_host)
    if backend == "anthropic":
        return AnthropicCorrector(model=model or "claude-haiku-4-5",
                                  api_key=api_key or None)
    return NoopCorrector()
