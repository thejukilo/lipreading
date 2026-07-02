"""Persist the user's setup choices so they don't reconfigure every launch.

Stored as JSON at ``~/.lipreading/config.json``. Only the user-facing knobs are
saved; model/path internals keep their defaults unless overridden.
"""

from __future__ import annotations

import dataclasses
import json
import os

from .session import SessionConfig

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".lipreading")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# Only these fields are surfaced/saved by the GUI.
SAVED_FIELDS = (
    "camera", "tts", "voice", "clone_engine", "output_device", "monitor_device",
    "monitor_on", "auto_speak", "device", "ptt_key",
)


def load_config() -> SessionConfig:
    cfg = SessionConfig()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return cfg
    for k in SAVED_FIELDS:
        if k in data:
            setattr(cfg, k, data[k])
    return cfg


def save_config(cfg: SessionConfig) -> str:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {k: getattr(cfg, k) for k in SAVED_FIELDS}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return CONFIG_PATH


def config_to_dict(cfg: SessionConfig) -> dict:
    return dataclasses.asdict(cfg)
