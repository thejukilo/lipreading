"""Training-label normalization: labels must match the model's LRS3-style
vocabulary (UPPERCASE, no punctuation), so LLM-cleanup styling can't leak in."""

from __future__ import annotations

from server.finetune import normalize_label


def test_uppercases():
    assert normalize_label("my name is lode") == "MY NAME IS LODE"


def test_strips_punctuation_from_cleanup():
    # A typical LLM-cleaned sentence with commas/period/casing.
    assert normalize_label("My name is Lode, and I like cinnamon.") == \
        "MY NAME IS LODE AND I LIKE CINNAMON"


def test_keeps_apostrophes_for_contractions():
    assert normalize_label("I don't know") == "I DON'T KNOW"
    assert normalize_label("I don’t know") == "I DON'T KNOW"  # smart quote


def test_collapses_whitespace_and_trims():
    assert normalize_label("  hello   world \n") == "HELLO WORLD"


def test_empty_and_punct_only():
    assert normalize_label("") == ""
    assert normalize_label("!!! ...") == ""
