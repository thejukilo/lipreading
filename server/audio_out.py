"""Play audio into an output device — specifically the VB-Cable virtual mic.

Routing model on Windows with VB-Audio Virtual Cable:

    our app  --plays to-->  "CABLE Input (VB-Audio Virtual Cable)"   [render]
    Google Meet  --records from-->  "CABLE Output (VB-Audio Virtual Cable)"  [capture]

So we render TTS to the **CABLE Input** endpoint, and in Meet you pick
**CABLE Output** as the microphone. (Yes, the names feel backwards — "Input" is
the cable's input, i.e. our speaker; "Output" is the cable's output, i.e. Meet's
mic.)
"""

from __future__ import annotations


def list_output_devices() -> list[tuple[int, str, int]]:
    """Return (index, name, max_output_channels) for playback-capable devices."""
    import sounddevice as sd

    out = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_output_channels", 0) > 0:
            out.append((idx, dev["name"], dev["max_output_channels"]))
    return out


def print_output_devices() -> None:
    print("Output (playback) devices:")
    for idx, name, ch in list_output_devices():
        print(f"  [{idx:2d}] {name}  ({ch}ch)")
    print(
        "\nTip: play to 'CABLE Input (VB-Audio Virtual Cable)'; "
        "in Meet select 'CABLE Output ...' as the microphone."
    )


def find_output_device(name_substr: str) -> int | None:
    """First playback device whose name contains ``name_substr`` (case-insensitive)."""
    needle = name_substr.lower()
    for idx, name, _ in list_output_devices():
        if needle in name.lower():
            return idx
    return None


def resolve_output_device(name_or_index: str | int | None) -> int | None:
    """Resolve a device selector to an index.

    ``None`` -> default device. An int (or digit string) -> that index. Otherwise
    a case-insensitive name substring (default target: the VB-Cable input).
    """
    if name_or_index is None:
        return None
    if isinstance(name_or_index, int):
        return name_or_index
    s = str(name_or_index).strip()
    if s.isdigit():
        return int(s)
    idx = find_output_device(s)
    if idx is None:
        raise RuntimeError(
            f"No output device matching '{s}'. Run with --list-audio-devices to "
            "see names. Is VB-Cable installed?"
        )
    return idx


def play_wav(wav_path: str, device: str | int | None = None, blocking: bool = True) -> None:
    """Play a WAV file to ``device`` (name substring, index, or None=default)."""
    import sounddevice as sd
    import soundfile as sf

    data, samplerate = sf.read(wav_path, dtype="float32", always_2d=False)
    dev_idx = resolve_output_device(device)
    sd.play(data, samplerate, device=dev_idx)
    if blocking:
        sd.wait()


if __name__ == "__main__":
    # `python -m server.audio_out` — quick device listing.
    print_output_devices()
