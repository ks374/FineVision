"""Generate the deterministic reward-cue WAV used by FineVision tasks."""

import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE_HZ = 44_100
DURATION_S = 0.6
BEEP_COUNT = 6
TONE_FREQUENCY_HZ = 1200
TONE_DURATION_S = 0.05
ONSET_INTERVAL_S = 0.10
FADE_S = 0.003
AMPLITUDE = 0.35


def generate(output_path):
    total_frames = round(DURATION_S * SAMPLE_RATE_HZ)
    tone_frames = round(TONE_DURATION_S * SAMPLE_RATE_HZ)
    onset_interval_frames = round(ONSET_INTERVAL_S * SAMPLE_RATE_HZ)
    fade_frames = round(FADE_S * SAMPLE_RATE_HZ)

    pcm = bytearray()
    for frame in range(total_frames):
        beep_index = frame // onset_interval_frames
        local_frame = frame % onset_interval_frames
        value = 0.0
        if beep_index < BEEP_COUNT and local_frame < tone_frames:
            fade_in = min(1.0, local_frame / fade_frames)
            fade_out = min(1.0, (tone_frames - 1 - local_frame) / fade_frames)
            envelope = min(fade_in, fade_out)
            value = AMPLITUDE * envelope * math.sin(
                2.0 * math.pi * TONE_FREQUENCY_HZ * frame / SAMPLE_RATE_HZ
            )
        pcm.extend(struct.pack("<h", round(value * 32767)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE_HZ)
        wav_file.writeframes(pcm)


if __name__ == "__main__":
    generate(
        Path(__file__).resolve().parents[1]
        / "audio"
        / "reward_cue_600ms_6beeps.wav"
    )
