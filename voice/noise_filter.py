"""
voice/noise_filter.py
=====================

Lightweight PCM audio pre-processing utilities for AssistantX.

Responsibilities
----------------
- RMS / peak audio analysis
- Voice Activity Detection (VAD)
- Leading/trailing silence trimming
- Safe PCM volume normalization
- Adaptive ambient-noise threshold tracking
- Configurable audio-processing pipeline

Design goals
------------
- Dependency-free
- Thread-safe runtime configuration
- 16-bit signed mono PCM support
- No modification of the original input buffer
- Safe handling of malformed/empty audio
- Suitable for both local and network speech recognition

Expected PCM format
-------------------
- Sample width : 16-bit signed
- Channels     : mono
- Endianness   : native PCM byte order
- Encoding     : linear PCM

This module intentionally does not depend on a specific microphone or
speech-recognition backend.
"""

from __future__ import annotations

import array
import math
import threading
from dataclasses import dataclass

from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

SAMPLE_WIDTH_BYTES = 2
PCM_MIN = -32768
PCM_MAX = 32767

DEFAULT_RMS_THRESHOLD = 300.0
DEFAULT_TARGET_PEAK = 24000
DEFAULT_FRAME_MS = 20

DEFAULT_NOISE_MULTIPLIER = 2.5
DEFAULT_SMOOTHING = 0.10

MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 192000

MIN_FRAME_MS = 5
MAX_FRAME_MS = 200

MIN_RMS_THRESHOLD = 1.0
MAX_RMS_THRESHOLD = 32767.0

MIN_TARGET_PEAK = 1000
MAX_TARGET_PEAK = 32767

MAX_NORMALIZE_GAIN = 4.0


# ============================================================================
# Exceptions
# ============================================================================


class NoiseFilterError(Exception):
    """Base exception for audio noise-filter errors."""


class AudioFormatError(NoiseFilterError):
    """Raised when PCM/audio parameters are invalid."""


class AudioConfigurationError(NoiseFilterError):
    """Raised when noise-filter configuration is invalid."""


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class AudioMetrics:
    """Basic amplitude information about a PCM buffer."""

    rms: float
    peak: int
    sample_count: int
    duration_seconds: float = 0.0

    @property
    def is_silent(self) -> bool:
        """Return True when no measurable signal exists."""
        return self.peak <= 0 or self.rms <= 0.0


@dataclass(frozen=True, slots=True)
class VADResult:
    """Outcome of voice-activity detection."""

    contains_speech: bool
    rms: float
    peak: int
    threshold: float
    sample_count: int = 0
    duration_seconds: float = 0.0

    @property
    def confidence_ratio(self) -> float:
        """
        Return how far the measured RMS is above the threshold.

        This is NOT an ML confidence score. It is simply an energy ratio.
        """
        if self.threshold <= 0:
            return 0.0

        return self.rms / self.threshold


@dataclass(frozen=True, slots=True)
class TrimResult:
    """Result information from silence trimming."""

    audio: bytes
    original_bytes: int
    trimmed_bytes: int
    frames_total: int
    frames_kept: int
    first_voiced_frame: int | None
    last_voiced_frame: int | None

    @property
    def removed_bytes(self) -> int:
        return max(0, self.original_bytes - self.trimmed_bytes)

    @property
    def reduction_ratio(self) -> float:
        if self.original_bytes <= 0:
            return 0.0

        return self.removed_bytes / self.original_bytes


@dataclass(frozen=True, slots=True)
class NoiseFilterStats:
    """Runtime statistics for the noise filter."""

    analyzed_buffers: int
    vad_checks: int
    voiced_buffers: int
    silent_buffers: int
    trimmed_buffers: int
    normalized_buffers: int
    calibration_updates: int


# ============================================================================
# Internal Helpers
# ============================================================================


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _validate_sample_rate(sample_rate: int) -> int:
    if not isinstance(sample_rate, int):
        raise AudioFormatError("sample_rate must be an integer.")

    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise AudioFormatError(
            f"sample_rate must be between "
            f"{MIN_SAMPLE_RATE} and {MAX_SAMPLE_RATE} Hz."
        )

    return sample_rate


def _validate_frame_ms(frame_ms: int) -> int:
    if not isinstance(frame_ms, int):
        raise AudioFormatError("frame_ms must be an integer.")

    if not MIN_FRAME_MS <= frame_ms <= MAX_FRAME_MS:
        raise AudioFormatError(
            f"frame_ms must be between "
            f"{MIN_FRAME_MS} and {MAX_FRAME_MS}."
        )

    return frame_ms


def _validate_pcm(pcm_bytes: bytes) -> bytes:
    if pcm_bytes is None:
        return b""

    if not isinstance(pcm_bytes, (bytes, bytearray, memoryview)):
        raise AudioFormatError("PCM audio must be bytes-like data.")

    return bytes(pcm_bytes)


def _to_samples(pcm_bytes: bytes) -> array.array:
    """
    Convert PCM bytes into signed 16-bit samples.

    Odd trailing bytes are ignored safely because a 16-bit PCM sample
    requires two bytes.
    """
    pcm_bytes = _validate_pcm(pcm_bytes)

    usable_length = len(pcm_bytes) - (len(pcm_bytes) % SAMPLE_WIDTH_BYTES)

    if usable_length <= 0:
        return array.array("h")

    samples = array.array("h")

    try:
        samples.frombytes(pcm_bytes[:usable_length])
    except (OverflowError, ValueError) as exc:
        raise AudioFormatError("Invalid 16-bit PCM buffer.") from exc

    return samples


# ============================================================================
# Audio Analysis
# ============================================================================


def compute_rms(pcm_bytes: bytes) -> float:
    """
    Calculate RMS amplitude of a 16-bit PCM buffer.

    Returns
    -------
    float
        RMS amplitude in the range approximately 0..32768.
    """
    samples = _to_samples(pcm_bytes)

    if not samples:
        return 0.0

    # math.fsum is more numerically stable than regular sum for
    # large audio buffers.
    sum_squares = math.fsum(float(sample) ** 2 for sample in samples)

    return math.sqrt(sum_squares / len(samples))


def compute_peak(pcm_bytes: bytes) -> int:
    """Return the absolute peak amplitude of a PCM buffer."""
    samples = _to_samples(pcm_bytes)

    if not samples:
        return 0

    return max(abs(sample) for sample in samples)


def analyze_audio(
    pcm_bytes: bytes,
    sample_rate: int | None = None,
) -> AudioMetrics:
    """
    Analyze RMS, peak and sample count for a PCM buffer.
    """
    samples = _to_samples(pcm_bytes)

    if not samples:
        return AudioMetrics(
            rms=0.0,
            peak=0,
            sample_count=0,
            duration_seconds=0.0,
        )

    rms = compute_rms(pcm_bytes)
    peak = max(abs(sample) for sample in samples)

    duration = 0.0

    if sample_rate is not None:
        sample_rate = _validate_sample_rate(sample_rate)
        duration = len(samples) / sample_rate

    return AudioMetrics(
        rms=rms,
        peak=peak,
        sample_count=len(samples),
        duration_seconds=duration,
    )


# ============================================================================
# Voice Activity Detection
# ============================================================================


def detect_voice_activity(
    pcm_bytes: bytes,
    rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    sample_rate: int | None = None,
) -> VADResult:
    """
    Detect likely speech using RMS energy.

    This is an energy-based VAD, not an ML speech classifier.

    Parameters
    ----------
    pcm_bytes:
        Raw 16-bit mono PCM.
    rms_threshold:
        RMS level above which audio is considered voiced.
    sample_rate:
        Optional sample rate used for duration reporting.
    """
    if not MIN_RMS_THRESHOLD <= rms_threshold <= MAX_RMS_THRESHOLD:
        raise AudioConfigurationError(
            f"rms_threshold must be between "
            f"{MIN_RMS_THRESHOLD} and {MAX_RMS_THRESHOLD}."
        )

    metrics = analyze_audio(
        pcm_bytes,
        sample_rate=sample_rate,
    )

    contains_speech = metrics.rms >= rms_threshold

    return VADResult(
        contains_speech=contains_speech,
        rms=metrics.rms,
        peak=metrics.peak,
        threshold=float(rms_threshold),
        sample_count=metrics.sample_count,
        duration_seconds=metrics.duration_seconds,
    )


# ============================================================================
# Silence Trimming
# ============================================================================


def trim_silence_with_result(
    pcm_bytes: bytes,
    sample_rate: int,
    rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    frame_ms: int = DEFAULT_FRAME_MS,
    padding_frames: int = 1,
) -> TrimResult:
    """
    Trim leading/trailing silence while preserving small padding.

    Returns detailed information about the operation.
    """
    pcm_bytes = _validate_pcm(pcm_bytes)
    sample_rate = _validate_sample_rate(sample_rate)
    frame_ms = _validate_frame_ms(frame_ms)

    if not 0 <= padding_frames <= 10:
        raise AudioConfigurationError(
            "padding_frames must be between 0 and 10."
        )

    if not pcm_bytes:
        return TrimResult(
            audio=b"",
            original_bytes=0,
            trimmed_bytes=0,
            frames_total=0,
            frames_kept=0,
            first_voiced_frame=None,
            last_voiced_frame=None,
        )

    frame_size_samples = max(
        1,
        int(sample_rate * frame_ms / 1000),
    )

    frame_size_bytes = frame_size_samples * SAMPLE_WIDTH_BYTES

    frames = [
        pcm_bytes[index:index + frame_size_bytes]
        for index in range(0, len(pcm_bytes), frame_size_bytes)
    ]

    voiced_flags = [
        compute_rms(frame) >= rms_threshold
        for frame in frames
    ]

    if not any(voiced_flags):
        logger.debug(
            "trim_silence: entire buffer classified as silence."
        )

        return TrimResult(
            audio=b"",
            original_bytes=len(pcm_bytes),
            trimmed_bytes=0,
            frames_total=len(frames),
            frames_kept=0,
            first_voiced_frame=None,
            last_voiced_frame=None,
        )

    first_voiced = voiced_flags.index(True)

    last_voiced = (
        len(voiced_flags)
        - 1
        - voiced_flags[::-1].index(True)
    )

    start = max(
        0,
        first_voiced - padding_frames,
    )

    end = min(
        len(frames),
        last_voiced + padding_frames + 1,
    )

    trimmed = b"".join(frames[start:end])

    logger.debug(
        "trim_silence: %d -> %d bytes; "
        "frames %d/%d kept.",
        len(pcm_bytes),
        len(trimmed),
        end - start,
        len(frames),
    )

    return TrimResult(
        audio=trimmed,
        original_bytes=len(pcm_bytes),
        trimmed_bytes=len(trimmed),
        frames_total=len(frames),
        frames_kept=end - start,
        first_voiced_frame=first_voiced,
        last_voiced_frame=last_voiced,
    )


def trim_silence(
    pcm_bytes: bytes,
    sample_rate: int,
    rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    frame_ms: int = DEFAULT_FRAME_MS,
) -> bytes:
    """
    Backward-compatible silence trimming helper.

    Returns only the processed PCM bytes.
    """
    result = trim_silence_with_result(
        pcm_bytes=pcm_bytes,
        sample_rate=sample_rate,
        rms_threshold=rms_threshold,
        frame_ms=frame_ms,
    )

    return result.audio


# ============================================================================
# Volume Normalization
# ============================================================================


def normalize_volume(
    pcm_bytes: bytes,
    target_peak: int = DEFAULT_TARGET_PEAK,
    max_gain: float = MAX_NORMALIZE_GAIN,
) -> bytes:
    """
    Normalize PCM volume toward a target peak.

    Important:
        The function only increases volume when needed. It does not
        aggressively reduce already-loud audio, preventing unnecessary
        distortion and preserving microphone dynamics.
    """
    pcm_bytes = _validate_pcm(pcm_bytes)

    if not MIN_TARGET_PEAK <= target_peak <= MAX_TARGET_PEAK:
        raise AudioConfigurationError(
            f"target_peak must be between "
            f"{MIN_TARGET_PEAK} and {MAX_TARGET_PEAK}."
        )

    if not 1.0 <= max_gain <= 10.0:
        raise AudioConfigurationError(
            "max_gain must be between 1.0 and 10.0."
        )

    samples = _to_samples(pcm_bytes)

    if not samples:
        return pcm_bytes

    current_peak = max(abs(sample) for sample in samples)

    if current_peak <= 0:
        return pcm_bytes

    # Only boost quiet audio.
    if current_peak >= target_peak:
        return pcm_bytes

    gain = min(
        target_peak / current_peak,
        max_gain,
    )

    if abs(gain - 1.0) < 0.05:
        return pcm_bytes

    scaled = array.array(
        "h",
        (
            max(
                PCM_MIN,
                min(
                    PCM_MAX,
                    round(sample * gain),
                ),
            )
            for sample in samples
        ),
    )

    return scaled.tobytes()


# ============================================================================
# Adaptive Ambient Noise Calibration
# ============================================================================


class AmbientNoiseCalibrator:
    """
    Adaptive ambient-noise estimator.

    The caller should feed chunks that are believed to contain only
    background noise/silence.

    The resulting threshold is intentionally conservative:
        noise_rms * noise_multiplier

    This helps prevent a fixed RMS threshold from behaving badly across
    different microphones and environments.
    """

    def __init__(
        self,
        initial_threshold: float = DEFAULT_RMS_THRESHOLD,
        smoothing: float = DEFAULT_SMOOTHING,
        noise_multiplier: float = DEFAULT_NOISE_MULTIPLIER,
        minimum_threshold: float = DEFAULT_RMS_THRESHOLD,
        maximum_threshold: float = 12000.0,
    ) -> None:

        if not MIN_RMS_THRESHOLD <= initial_threshold <= MAX_RMS_THRESHOLD:
            raise AudioConfigurationError(
                "initial_threshold is outside the valid range."
            )

        if not 0.001 <= smoothing <= 1.0:
            raise AudioConfigurationError(
                "smoothing must be between 0.001 and 1.0."
            )

        if not 1.0 <= noise_multiplier <= 10.0:
            raise AudioConfigurationError(
                "noise_multiplier must be between 1.0 and 10.0."
            )

        if minimum_threshold > maximum_threshold:
            raise AudioConfigurationError(
                "minimum_threshold cannot exceed maximum_threshold."
            )

        self._lock = threading.RLock()

        self._threshold = float(initial_threshold)
        self._smoothing = float(smoothing)
        self._noise_multiplier = float(noise_multiplier)

        self._minimum_threshold = float(minimum_threshold)
        self._maximum_threshold = float(maximum_threshold)

        self._updates = 0
        self._last_noise_rms = 0.0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def threshold(self) -> float:
        """Current adaptive RMS threshold."""
        with self._lock:
            return self._threshold

    @property
    def noise_floor(self) -> float:
        """Latest measured ambient RMS."""
        with self._lock:
            return self._last_noise_rms

    @property
    def updates(self) -> int:
        """Number of calibration updates performed."""
        with self._lock:
            return self._updates

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def update(self, silent_chunk_pcm: bytes) -> float:
        """
        Feed a presumed-silent chunk into the noise estimator.

        Returns the new threshold.
        """
        chunk_rms = compute_rms(silent_chunk_pcm)

        with self._lock:
            proposed_threshold = (
                chunk_rms * self._noise_multiplier
            )

            self._threshold = (
                (1.0 - self._smoothing) * self._threshold
                + self._smoothing * proposed_threshold
            )

            self._threshold = _clamp(
                self._threshold,
                self._minimum_threshold,
                self._maximum_threshold,
            )

            self._last_noise_rms = chunk_rms
            self._updates += 1

            threshold = self._threshold

        logger.debug(
            "Ambient noise updated: rms=%.1f threshold=%.1f",
            chunk_rms,
            threshold,
        )

        return threshold

    def reset(self, threshold: float | None = None) -> None:
        """Reset the adaptive threshold."""
        new_threshold = (
            self._minimum_threshold
            if threshold is None
            else float(threshold)
        )

        if not MIN_RMS_THRESHOLD <= new_threshold <= MAX_RMS_THRESHOLD:
            raise AudioConfigurationError(
                "reset threshold is outside the valid range."
            )

        with self._lock:
            self._threshold = _clamp(
                new_threshold,
                self._minimum_threshold,
                self._maximum_threshold,
            )
            self._last_noise_rms = 0.0
            self._updates = 0

    def diagnostics(self) -> dict:
        """Return safe runtime diagnostics."""
        with self._lock:
            return {
                "threshold": round(self._threshold, 2),
                "noise_floor": round(self._last_noise_rms, 2),
                "smoothing": self._smoothing,
                "noise_multiplier": self._noise_multiplier,
                "minimum_threshold": self._minimum_threshold,
                "maximum_threshold": self._maximum_threshold,
                "updates": self._updates,
            }


# ============================================================================
# Noise Filter Pipeline
# ============================================================================


class NoiseFilter:
    """
    Thread-safe high-level audio-processing pipeline.

    Typical flow:

        raw microphone PCM
            ↓
        VAD
            ↓
        silence trim
            ↓
        optional normalization
            ↓
        speech recognizer
    """

    def __init__(
        self,
        rms_threshold: float = DEFAULT_RMS_THRESHOLD,
        frame_ms: int = DEFAULT_FRAME_MS,
        target_peak: int = DEFAULT_TARGET_PEAK,
        normalize: bool = True,
        adaptive_threshold: bool = True,
    ) -> None:

        if not MIN_RMS_THRESHOLD <= rms_threshold <= MAX_RMS_THRESHOLD:
            raise AudioConfigurationError(
                "rms_threshold is outside the valid range."
            )

        _validate_frame_ms(frame_ms)

        if not MIN_TARGET_PEAK <= target_peak <= MAX_TARGET_PEAK:
            raise AudioConfigurationError(
                "target_peak is outside the valid range."
            )

        self._lock = threading.RLock()

        self._rms_threshold = float(rms_threshold)
        self._frame_ms = frame_ms
        self._target_peak = target_peak
        self._normalize_enabled = bool(normalize)
        self._adaptive_enabled = bool(adaptive_threshold)

        self._calibrator = AmbientNoiseCalibrator(
            initial_threshold=rms_threshold,
        )

        self._analyzed_buffers = 0
        self._vad_checks = 0
        self._voiced_buffers = 0
        self._silent_buffers = 0
        self._trimmed_buffers = 0
        self._normalized_buffers = 0
        self._calibration_updates = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def rms_threshold(self) -> float:
        with self._lock:
            if self._adaptive_enabled:
                return self._calibrator.threshold

            return self._rms_threshold

    @property
    def frame_ms(self) -> int:
        with self._lock:
            return self._frame_ms

    def set_threshold(self, threshold: float) -> None:
        """Set the static RMS threshold."""
        if not MIN_RMS_THRESHOLD <= threshold <= MAX_RMS_THRESHOLD:
            raise AudioConfigurationError(
                "Invalid RMS threshold."
            )

        with self._lock:
            self._rms_threshold = float(threshold)

    def set_frame_ms(self, frame_ms: int) -> None:
        """Update frame size."""
        _validate_frame_ms(frame_ms)

        with self._lock:
            self._frame_ms = frame_ms

    def set_normalization(self, enabled: bool) -> None:
        """Enable/disable volume normalization."""
        with self._lock:
            self._normalize_enabled = bool(enabled)

    def set_adaptive_threshold(self, enabled: bool) -> None:
        """Enable/disable adaptive ambient-noise thresholding."""
        with self._lock:
            self._adaptive_enabled = bool(enabled)

    # ------------------------------------------------------------------
    # VAD
    # ------------------------------------------------------------------

    def detect_voice(
        self,
        pcm_bytes: bytes,
        sample_rate: int | None = None,
    ) -> VADResult:
        """Run VAD using the current threshold."""
        threshold = self.rms_threshold

        result = detect_voice_activity(
            pcm_bytes=pcm_bytes,
            rms_threshold=threshold,
            sample_rate=sample_rate,
        )

        with self._lock:
            self._vad_checks += 1

            if result.contains_speech:
                self._voiced_buffers += 1
            else:
                self._silent_buffers += 1

        return result

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def calibrate(self, silent_chunk_pcm: bytes) -> float:
        """
        Update adaptive threshold using presumed background noise.
        """
        threshold = self._calibrator.update(
            silent_chunk_pcm
        )

        with self._lock:
            self._calibration_updates += 1

        return threshold

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        *,
        require_voice: bool = True,
        trim: bool = True,
        normalize: bool | None = None,
    ) -> bytes:
        """
        Process a PCM buffer through the configured pipeline.

        Returns
        -------
        bytes
            Processed PCM data. Empty bytes means no usable speech
            was detected when require_voice=True.
        """
        pcm_bytes = _validate_pcm(pcm_bytes)
        sample_rate = _validate_sample_rate(sample_rate)

        with self._lock:
            self._analyzed_buffers += 1
            frame_ms = self._frame_ms

            normalization_enabled = (
                self._normalize_enabled
                if normalize is None
                else bool(normalize)
            )

        if not pcm_bytes:
            return b""

        # --------------------------------------------------------------
        # VAD
        # --------------------------------------------------------------

        vad = self.detect_voice(
            pcm_bytes,
            sample_rate=sample_rate,
        )

        if require_voice and not vad.contains_speech:
            return b""

        processed = pcm_bytes

        # --------------------------------------------------------------
        # Silence trimming
        # --------------------------------------------------------------

        if trim:
            result = trim_silence_with_result(
                pcm_bytes=processed,
                sample_rate=sample_rate,
                rms_threshold=self.rms_threshold,
                frame_ms=frame_ms,
            )

            if result.audio:
                if result.audio != processed:
                    with self._lock:
                        self._trimmed_buffers += 1

                processed = result.audio
            elif require_voice:
                return b""

        # --------------------------------------------------------------
        # Volume normalization
        # --------------------------------------------------------------

        if normalization_enabled and processed:
            normalized = normalize_volume(
                processed,
                target_peak=self._target_peak,
            )

            if normalized != processed:
                with self._lock:
                    self._normalized_buffers += 1

                processed = normalized

        return processed

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> NoiseFilterStats:
        """Return immutable runtime statistics."""
        with self._lock:
            return NoiseFilterStats(
                analyzed_buffers=self._analyzed_buffers,
                vad_checks=self._vad_checks,
                voiced_buffers=self._voiced_buffers,
                silent_buffers=self._silent_buffers,
                trimmed_buffers=self._trimmed_buffers,
                normalized_buffers=self._normalized_buffers,
                calibration_updates=self._calibration_updates,
            )

    def diagnostics(self) -> dict:
        """Return safe diagnostic information."""
        with self._lock:
            stats = self.stats()

            return {
                "rms_threshold": round(
                    self.rms_threshold,
                    2,
                ),
                "frame_ms": self._frame_ms,
                "target_peak": self._target_peak,
                "normalization_enabled": (
                    self._normalize_enabled
                ),
                "adaptive_threshold_enabled": (
                    self._adaptive_enabled
                ),
                "stats": {
                    "analyzed_buffers": stats.analyzed_buffers,
                    "vad_checks": stats.vad_checks,
                    "voiced_buffers": stats.voiced_buffers,
                    "silent_buffers": stats.silent_buffers,
                    "trimmed_buffers": stats.trimmed_buffers,
                    "normalized_buffers": stats.normalized_buffers,
                    "calibration_updates": stats.calibration_updates,
                },
                "calibrator": self._calibrator.diagnostics(),
            }

    def reset_stats(self) -> None:
        """Reset runtime counters without changing configuration."""
        with self._lock:
            self._analyzed_buffers = 0
            self._vad_checks = 0
            self._voiced_buffers = 0
            self._silent_buffers = 0
            self._trimmed_buffers = 0
            self._normalized_buffers = 0
            self._calibration_updates = 0


# ============================================================================
# Global Instance
# ============================================================================


noise_filter = NoiseFilter()


# ============================================================================
# Convenience API
# ============================================================================


def filter_audio(
    pcm_bytes: bytes,
    sample_rate: int,
    *,
    require_voice: bool = True,
    trim: bool = True,
    normalize: bool | None = None,
) -> bytes:
    """
    Process audio using the global NoiseFilter instance.
    """
    return noise_filter.process(
        pcm_bytes=pcm_bytes,
        sample_rate=sample_rate,
        require_voice=require_voice,
        trim=trim,
        normalize=normalize,
    )


def is_voice(
    pcm_bytes: bytes,
    rms_threshold: float | None = None,
) -> bool:
    """
    Convenience helper to check whether a PCM buffer contains voice.
    """
    threshold = (
        noise_filter.rms_threshold
        if rms_threshold is None
        else rms_threshold
    )

    return detect_voice_activity(
        pcm_bytes,
        rms_threshold=threshold,
    ).contains_speech


def get_audio_metrics(
    pcm_bytes: bytes,
    sample_rate: int | None = None,
) -> AudioMetrics:
    """Convenience wrapper around analyze_audio()."""
    return analyze_audio(
        pcm_bytes,
        sample_rate=sample_rate,
    )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "DEFAULT_FRAME_MS",
    "DEFAULT_RMS_THRESHOLD",
    "DEFAULT_TARGET_PEAK",
    "PCM_MAX",
    "PCM_MIN",
    # Constants
    "SAMPLE_WIDTH_BYTES",
    # Calibration
    "AmbientNoiseCalibrator",
    "AudioConfigurationError",
    "AudioFormatError",
    # Data models
    "AudioMetrics",
    # Pipeline
    "NoiseFilter",
    # Exceptions
    "NoiseFilterError",
    "NoiseFilterStats",
    "TrimResult",
    "VADResult",
    "analyze_audio",
    "compute_peak",
    # Analysis
    "compute_rms",
    "detect_voice_activity",
    # Convenience
    "filter_audio",
    "get_audio_metrics",
    "is_voice",
    "noise_filter",
    "normalize_volume",
    # Processing
    "trim_silence",
    "trim_silence_with_result",
]
