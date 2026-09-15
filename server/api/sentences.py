"""Prompt sentences for the Teach flow.

A curated set of short, phonetically varied English sentences the user reads to
the camera. Kept deliberately everyday and easy to say in one breath. The client
asks for N at a time; we sample without replacement per request.
"""

from __future__ import annotations

import random

SENTENCES: tuple[str, ...] = (
    "The weather is nice today.",
    "Can you hear me clearly now?",
    "I would like a cup of coffee.",
    "Please call me back this afternoon.",
    "My name is easy to remember.",
    "We are meeting at the office tomorrow.",
    "Thank you very much for your help.",
    "Let us go for a walk in the park.",
    "The train leaves in ten minutes.",
    "I really enjoyed the film last night.",
    "Could you pass me the salt, please?",
    "She sells seashells by the seashore.",
    "How much does this one cost?",
    "The children are playing in the garden.",
    "I need to buy some bread and milk.",
    "It was great to see you again.",
    "Turn left at the second traffic light.",
    "My favourite colour is dark blue.",
    "The book is on the top shelf.",
    "We should plan our holiday soon.",
    "Open the window to let some air in.",
    "He works as a doctor in the city.",
    "This coffee is too hot to drink.",
    "Remember to lock the front door.",
    "The meeting has been moved to Friday.",
    "I will send you the details by email.",
    "A quick brown fox jumps over the fence.",
    "Please speak a little more slowly.",
    "The battery on my phone is almost dead.",
    "Let me know if you need anything else.",
)


def sample_sentences(n: int = 10) -> list[str]:
    n = max(1, min(int(n), len(SENTENCES)))
    return random.sample(SENTENCES, n)
