"""Phase 3 — training a Dutch VSR model from the English auto_avsr checkpoint.

A self-contained training/eval pipeline for a *new language*, kept apart from the
Phase-1 live app. See docs/phase3-dutch.md.

Pilot design (Plan A): reuse the English tokenizer + model as-is and fine-tune on
Dutch clips that are already in the model's native format (96x96, 25 fps, mouth-
cropped). No vocab surgery -- fastest path to an honest WER/CER number. Plan B (a
dedicated Dutch tokenizer + decoder head) is the follow-up if Plan A is promising.
"""
