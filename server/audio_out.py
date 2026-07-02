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


def _play_on_devices(data, samplerate: int, devices: list[int | None], blocking: bool) -> None:
    """Play the same buffer to several output devices at once (one stream each)."""
    import threading

    import numpy as np
    import sounddevice as sd

    if data.dtype != np.float32:
        data = data.astype(np.float32)

    # Prepend a short silence so a cold output device's warm-up drops the
    # silence instead of the first word (fixes "only heard the last part").
    lead = int(0.30 * samplerate)
    if lead > 0:
        pad = (np.zeros(lead, dtype=np.float32) if data.ndim == 1
               else np.zeros((lead, data.shape[1]), dtype=np.float32))
        data = np.concatenate([pad, data], axis=0)

    channels = 1 if data.ndim == 1 else data.shape[1]

    # De-dup while preserving order (default None is distinct from an explicit index).
    seen, targets, errors = set(), [], []
    for d in devices:
        if d not in seen:
            seen.add(d)
            targets.append(d)

    def worker(dev):
        try:
            with sd.OutputStream(samplerate=samplerate, device=dev,
                                 channels=channels, dtype="float32") as stream:
                stream.write(data)
        except Exception as e:  # a bad monitor device shouldn't kill the mic feed
            errors.append((dev, e))

    threads = [threading.Thread(target=worker, args=(d,), daemon=True) for d in targets]
    for t in threads:
        t.start()
    if blocking:
        for t in threads:
            t.join()
    if errors:
        msgs = "; ".join(f"device {d}: {e}" for d, e in errors)
        raise RuntimeError(f"playback failed on {msgs}")


def play_wav(
    wav_path: str,
    device: str | int | None = None,
    monitor: bool = False,
    monitor_device: str | int | None = None,
    blocking: bool = True,
) -> None:
    """Play a WAV to ``device`` (the virtual mic); optionally also to speakers.

    ``monitor=True`` additionally plays to ``monitor_device`` (default: system
    default output = your headphones) so you can hear what's being sent to Meet.
    """
    import soundfile as sf

    data, samplerate = sf.read(wav_path, dtype="float32", always_2d=False)
    targets = [resolve_output_device(device)]
    if monitor:
        targets.append(resolve_output_device(monitor_device))  # None -> default speakers
    _play_on_devices(data, samplerate, targets, blocking)


if __name__ == "__main__":
    # `python -m server.audio_out` — quick device listing.
    print_output_devices()
