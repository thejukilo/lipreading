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

What it does under the hood: reprocesses your clips through the same mouth-crop
pipeline as inference, then lightly adapts the base checkpoint (low learning
rate, few epochs, gradient clipping) so it nudges toward your face/vocabulary
without forgetting general English. The base model is untouched — switch back to
**Base** anytime, or delete `personalized.pth` to discard a bad run and retrain.

> Fine-tuning always starts from the **base** model (not a previous personalized
> one), so re-training with more data doesn't compound drift. Tune amount/epochs
> by collecting more data rather than training repeatedly.
