"""Word- and character-error-rate, corpus-aggregated, no dependencies.

Case- and punctuation-insensitive by default, so an uppercase model output is
scored fairly against a lowercase Dutch reference.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = _PUNCT.sub(" ", text)
    return " ".join(text.split())


def _levenshtein(a, b) -> int:
    """Edit distance between two sequences (lists of tokens or chars)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _rate(pairs, unit: str):
    edits = total = 0
    for ref, hyp in pairs:
        r = normalize(ref)
        h = normalize(hyp)
        rseq = list(r) if unit == "char" else r.split()
        hseq = list(h) if unit == "char" else h.split()
        edits += _levenshtein(rseq, hseq)
        total += len(rseq)
    return (edits / total) if total else 0.0, edits, total


def corpus_wer(pairs) -> dict:
    """pairs: iterable of (reference, hypothesis). Returns WER + CER + totals."""
    pairs = list(pairs)
    wer, w_edits, w_total = _rate(pairs, "word")
    cer, c_edits, c_total = _rate(pairs, "char")
    return {
        "wer": wer, "cer": cer,
        "word_edits": w_edits, "words": w_total,
        "char_edits": c_edits, "chars": c_total,
        "n": len(pairs),
    }
