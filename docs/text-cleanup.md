# LLM text cleanup

Lipreading confuses words that look alike on the lips — "god" for "dog",
"beating" for "meeting" — because the model reads mouth shapes, not meaning. An
LLM pass reads the whole sentence and fixes those misrecognitions from context
before the text is spoken.

Off by default. Two backends, chosen in the **Text cleanup** dropdown:

| Backend | Where it runs | Notes |
|---|---|---|
| **Local LLM (Ollama)** | your machine | Private, no API key, free. Needs Ollama + a model. Uses your GPU/CPU. |
| **Claude (cloud)** | Anthropic API | Highest quality, lowest setup. Needs an API key; text is sent to the API. |

## Local (Ollama)

1. Install Ollama: https://ollama.com
2. Pull a model: `ollama pull llama3.1:8b` (or `qwen2.5:7b`, etc.)
3. In the app: **Text cleanup → Local LLM (Ollama)**. Leave **Cleanup model** blank
   for the default (`llama3.1:8b`) or type the model you pulled.

Runs at `http://localhost:11434`. Nothing leaves your machine.

## Claude (cloud)

1. `pip install -r requirements-llm.txt`
2. In the app: **Text cleanup → Claude (cloud)**, and paste your Anthropic API
   key into **Claude API key** (stored locally in `~/.lipreading/config.json`;
   or leave blank and set the `ANTHROPIC_API_KEY` environment variable instead).
3. **Cleanup model** defaults to `claude-haiku-4-5` (fast + cheap — ideal for a
   one-sentence fix). You can set another model id if you prefer.

## How it behaves

- Applies **after** transcription, **before** review/speaking. You'll see a
  "polishing text…" status.
- The prompt tells the LLM to fix only likely misrecognitions and keep your
  meaning, wording, and length — not to rewrite or add content.
- **Never blocks:** if the LLM is unreachable (Ollama down, bad key, offline),
  the app falls back to the raw transcript and shows the reason.
- With the **review** step on, you still see and can edit the cleaned text
  before it's spoken.

## Latency

- **Claude Haiku:** ~0.3–1s per sentence.
- **Ollama:** depends on your model/hardware (a 7–8B model on a GPU is ~0.5–2s).

Both are fine with the review step. In **Speak immediately** mode the cleanup
adds a beat before your voice plays.

## Command line

```powershell
python -m server.live_app --corrector anthropic --corrector-model claude-haiku-4-5
python -m server.live_app --corrector ollama   --corrector-model llama3.1:8b
```

## Privacy note

Local (Ollama) keeps everything on your machine. The Claude backend sends the
transcript text (not audio or video) to the Anthropic API — fine for most use,
but keep it in mind for sensitive meetings; use the local backend if in doubt.
