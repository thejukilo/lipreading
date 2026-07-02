# Teaching the model (personalization)

A generic lipreading model has never seen your face or your vocabulary (names
like "Juan", team jargon). The **Teach** tab lets you build a small dataset of
yourself saying your own words, which a later **fine-tuning** step uses to adapt
the model to you — proper personalization, not a post-hoc text fix.

Two stages, both available now:
- **Stage 1 — collect:** record and label examples (Teach tab, or ＋ Add to
  training on the Speak tab).
- **Stage 2 — fine-tune:** the **⚙ Fine-tune a personalized model** button trains
  on your examples and saves a separate **Personalized** model; the base model is
  never touched. Pick it under **Recognition model** on the Speak tab.

## Collecting examples (Teach tab)

1. Go to the **Teach** tab and **Turn camera on** (this only opens the webcam —
   it does not load the speech model, so it's quick).
2. Type a **word or short sentence** you want to teach (e.g. `Juan`, or
   `I'll hand over some cases`).
3. Click **● Record a rep**, say it clearly facing the camera, then **■ Stop &
   save**. Repeat several times for the same phrase.
4. Add more phrases the same way. The list on the right shows each phrase and how
   many reps you've recorded.

Clips are stored in `~/.lipreading/training/` (25 fps, mouth-crop happens at
training time — same pipeline as live recognition).

### Or capture mistakes as you go (Speak tab)

The fastest way to build a dataset is from real use: on the **Speak** tab, when a
transcript comes back wrong, **fix the text in the review box** and click
**＋ Add to training**. It saves that exact clip with your corrected text as a
training example. Every misread you fix becomes personalization data — you can
still Speak or Discard afterwards.

## How much to record

Fine-tuning a big model on a handful of clips **overfits** and can hurt general
accuracy, so we'll train *lightly*. For that to help without harming:
- **Many reps per phrase** (aim for ~10+), varied naturally — not identical.
- **Several phrases**, including whole sentences, not just single names.
- Good, consistent conditions: face the camera, decent lighting, one sentence
  per recording.

More and more varied data is strictly better. Think of it as building up a
personal set over time, not a one-shot fix.

## Realistic expectations

- Personalizing to **your** lips and vocabulary is the highest-ceiling accuracy
  lever we have — much better than a generic model for your names/jargon.
- Names remain the hardest thing in lipreading; your own recordings are the best
  possible signal for them, but don't expect perfection from a few clips.
- The base model is never overwritten. Fine-tuning produces a separate model you
  can switch to, compare against, and delete if a run isn't better.

## Fine-tuning (Stage 2)

When you've collected a decent set (at least a few clips; more is better):

1. On the Teach tab, **turn the camera off** (so training has the full GPU).
2. Click **⚙ Fine-tune a personalized model**. Progress shows in the status line
   (preparing clips → per-epoch loss → done). It runs on your CUDA GPU.
3. It saves `checkpoints/personalized.pth`. On the **Speak** tab, set
   **Recognition model → Personalized (yours)**, then **Start**.

What it does under the hood, and how it avoids "it only says the words I taught
it": a naive fine-tune on a few clips makes the decoder **memorize** those exact
sentences and emit them no matter what the camera shows (catastrophic
forgetting). We prevent that on three fronts, all on by default:

1. **The visual backbone is frozen.** The 3D-conv/ResNet frontend and the whole
   Conformer encoder — the general viseme reader — are never touched. Only the
   decoder + CTC head (the *viseme → your words* mapping) is trained, so general
   lip-reading can't be damaged.
2. **An L2-SP anchor** pulls every trained weight back toward its base value, so
   the decoder stays close to the original instead of collapsing onto your few
   phrases.
3. **A gentle schedule with early stop** — low learning rate, few epochs, and an
   automatic stop the moment the loss floors out (the tell-tale of memorizing
   rather than adapting).

The base model is untouched — switch back to **Base** anytime, or delete
`personalized.pth` to discard a bad run and retrain.

> Fine-tuning always starts from the **base** model (not a previous personalized
> one), so re-training with more data doesn't compound drift.

### If a personalized run still over-focuses

If it leans too hard on the taught phrases, the fix is almost always **more and
more varied data**, not more training:

- Record **whole sentences you'd actually say**, not isolated names. A name on
  its own (just "Juan") gives the decoder nothing to anchor to except that one
  word; the same name inside `Juan is overloaded this week` teaches it in
  context.
- Aim for **many phrases** (10+), each with a few reps, over time.
- For **names/jargon specifically**, the most reliable path is still the
  **Text cleanup** LLM on the Speak tab plus its **context** field (list your
  teammates' names there) — that fixes names without any retraining. Think of
  fine-tuning as adapting to *your face and speaking style*, and the LLM +
  context as the fast, safe way to nail *specific names*.
