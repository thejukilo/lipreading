"""Global push-to-talk key handling (pynput), shared by the CLI and the GUI."""

from __future__ import annotations


def resolve_key(name: str):
    from pynput import keyboard

    named = {
        "ctrl": keyboard.Key.ctrl, "ctrl_l": keyboard.Key.ctrl_l,
        "ctrl_r": keyboard.Key.ctrl_r, "alt": keyboard.Key.alt,
        "alt_l": keyboard.Key.alt_l, "alt_r": keyboard.Key.alt_r,
        "shift": keyboard.Key.shift, "shift_r": keyboard.Key.shift_r,
        "space": keyboard.Key.space,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8, "f9": keyboard.Key.f9,
        "f10": keyboard.Key.f10,
    }
    if name in named:
        return named[name]
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(
        f"Unsupported key '{name}'. Try a single letter or one of: "
        f"{', '.join(sorted(named))}."
    )


def key_matches(pressed, target) -> bool:
    """Match, treating generic ctrl/alt/shift as either side."""
    from pynput import keyboard

    if pressed == target:
        return True
    fam = {
        keyboard.Key.ctrl: {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
        keyboard.Key.alt: {keyboard.Key.alt_l, keyboard.Key.alt_r,
                           getattr(keyboard.Key, "alt_gr", None)},
        keyboard.Key.shift: {keyboard.Key.shift_l, keyboard.Key.shift_r},
    }
    return pressed in fam.get(target, set())


class PushToTalkListener:
    """Fire ``on_down`` once per hold of the target key, ``on_up`` on release.

    Global (works while another app is focused). The key can be changed live via
    ``set_key`` without restarting the listener.
    """

    def __init__(self, key_name: str, on_down, on_up) -> None:
        self.on_down = on_down
        self.on_up = on_up
        self._held = False
        self._listener = None
        self.set_key(key_name)

    def set_key(self, name: str) -> None:
        self.target = resolve_key(name)
        self.key_name = name
        self._held = False

    def _on_press(self, key) -> None:
        if not self._held and key_matches(key, self.target):
            self._held = True
            self.on_down()

    def _on_release(self, key) -> None:
        if self._held and key_matches(key, self.target):
            self._held = False
            self.on_up()

    def start(self) -> None:
        from pynput import keyboard

        if self._listener is None:
            self._listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
            self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
