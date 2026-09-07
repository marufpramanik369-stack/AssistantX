"""
noise_filter.py
================
Lightweight audio pre-processing utilities applied to raw microphone
input before it's handed to the speech recognizer, improving accuracy
in noisy environments without requiring heavy ML-based denoising
libraries.

Techniques implemented:
    - Ambient noise calibration (delegates to speech_recognition's
      built-in adjust_for_ambient_noise when available)
    - Simple energy-based silence trimming (removes leading/trailing
      near-silent audio to shorten recognizer processing time)
    - RMS-based voice activity detection (VAD) to decide whether a
      captured audio chunk contains speech at all, before bothering to
      send it to the (possibly network-bound) recognizer.

All functions operate on raw PCM byte buffers (16-bit signed, mono) to
stay decoupled from any specific audio-capture library.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass

from core.logger import get_logger

logger = get_logger(__name__)

_SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM


@dataclass
class VADResult:
    """Outcome of voice-activity detection on an audio chunk."""

    contains_speech: bool
    rms: float
    peak: int


def _to_samples(pcm_bytes: bytes) -> array.array:
    """Interpret raw bytes as an array of 16-bit signed integers."""
    samples = array.array("h")  # 'h' = signed short (16-bit)
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    return samples


def compute_rms(pcm_bytes: bytes) -> float:
    """
    Compute the root-mean-square amplitude of a PCM audio buffer — a
    standard measure of loudness used for silence/voice detection.
    """
    samples = _to_samples(pcm_bytes)
    if not samples:
        return 0.0
    sum_squares = sum(s * s for s in samples)
    return math.sqrt(sum_squares / len(samples))


def detect_voice_activity(pcm_bytes: bytes, rms_threshold: float = 300.0) -> VADResult:
    """
    Decide whether a chunk of audio likely contains speech, based on RMS
    energy exceeding `rms_threshold`. This threshold is intentionally a
    tunable parameter (exposed via config/constants.py's
    SILENCE_THRESHOLD_SECONDS-adjacent settings) since ideal values vary
    by microphone hardware and room noise floor.
    """
    samples = _to_samples(pcm_bytes)
    rms = compute_rms(pcm_bytes)
    peak = max((abs(s) for s in samples), default=0)
    return VADResult(contains_speech=rms >= rms_threshold, rms=rms, peak=peak)


def trim_silence(
    pcm_bytes: bytes,
    sample_rate: int,
    rms_threshold: float = 300.0,
    frame_ms: int = 20,
) -> bytes:
    """
    Trim leading and trailing near-silent audio from a PCM buffer,
    shortening what gets sent to the recognizer and slightly improving
    both latency and accuracy (less silence for the model to "waste"
    attention on).

    Args:
        pcm_bytes: Raw 16-bit mono PCM audio.
        sample_rate: Sample rate in Hz (e.g. 16000).
        rms_threshold: Frames below this RMS are considered silence.
        frame_ms: Frame size in milliseconds used for the sliding window.

    Returns:
        The trimmed PCM byte buffer. If the entire buffer is silence,
        returns an empty bytes object.
    """
    frame_size_samples = max(1, int(sample_rate * frame_ms / 1000))
    frame_size_bytes = frame_size_samples * _SAMPLE_WIDTH_BYTES

    frames = [
        pcm_bytes[i : i + frame_size_bytes]
        for i in range(0, len(pcm_bytes), frame_size_bytes)
    ]
    if not frames:
        return b""

    voiced_flags = [compute_rms(f) >= rms_threshold for f in frames]

    if not any(voiced_flags):
        logger.debug("trim_silence: entire buffer classified as silence.")
        return b""

    first_voiced = voiced_flags.index(True)
    last_voiced = len(voiced_flags) - 1 - voiced_flags[::-1].index(True)

    # Keep one frame of padding on each side so word onsets/offsets aren't clipped.
    start = max(0, first_voiced - 1)
    end = min(len(frames), last_voiced + 2)

    trimmed = b"".join(frames[start:end])
    logger.debug(
        "trim_silence: %d -> %d bytes (%d frames kept of %d).",
        len(pcm_bytes), len(trimmed), end - start, len(frames),
    )
    return trimmed


def normalize_volume(pcm_bytes: bytes, target_peak: int = 24000) -> bytes:
    """
    Scale PCM audio so its peak amplitude reaches `target_peak`
    (out of a max possible 32767 for 16-bit audio), helping quiet
    microphone input recognize more reliably without clipping loud input.
    """
    samples = _to_samples(pcm_bytes)
    if not samples:
        return pcm_bytes

    current_peak = max((abs(s) for s in samples), default=0)
    if current_peak == 0:
        return pcm_bytes  # pure silence, nothing to scale

    gain = min(target_peak / current_peak, 4.0)  # cap gain to avoid extreme amplification of noise
    if abs(gain - 1.0) < 0.05:
        return pcm_bytes  # already close enough, skip the work

    scaled = array.array("h", (max(-32768, min(32767, int(s * gain))) for s in samples))
    return scaled.tobytes()


class AmbientNoiseCalibrator:
    """
    Tracks a rolling estimate of the ambient noise floor so
    voice/recognizer.py can dynamically adjust its silence threshold
    instead of relying on one fixed constant, improving robustness
    across different rooms/microphones during a single session.
    """

    def __init__(self, initial_threshold: float = 300.0, smoothing: float = 0.1) -> None:
        self.threshold = initial_threshold
        self._smoothing = smoothing  # exponential moving average factor

    def update(self, silent_chunk_pcm: bytes) -> float:
        """Feed in a chunk known/assumed to be silence (e.g. captured
        during a calibration pause) to refine the noise floor estimate."""
        chunk_rms = compute_rms(silent_chunk_pcm)
        self.threshold = (1 - self._smoothing) * self.threshold + self._smoothing * (chunk_rms * 2.5)
        logger.debug("Ambient noise threshold recalibrated to %.1f", self.threshold)
        return self.threshold
        