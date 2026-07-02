# Teaching the model (personalization)

A generic lipreading model has never seen your face or your vocabulary (names
like "Juan", team jargon). The **Teach** tab lets you build a small dataset of
yourself saying your own words, which a later **fine-tuning** step uses to adapt
the model to you — proper personalization, not a post-hoc text fix.

This is built in two stages:
- **Stage 1 — collect (this):** record and label examples. Available now.
- **Stage 2 — fine-tune (next):** train on your examples to produce a separate
  **Personalized** model you select in the app; the base model stays untouched.

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

## Next

Once you've collected a decent set, the fine-tuning step will: reprocess your
clips through the mouth-crop pipeline, lightly adapt the base checkpoint on them
(low learning rate, few steps, on your CUDA GPU), and save
`checkpoints/personalized.pth` — selectable as a "Personalized" model.
