"""
voice/noise_filter.py
=====================

Production-grade, dependency-free PCM audio preprocessing for AssistantX.

Responsibilities
----------------
- RMS / peak audio analysis
- Energy-based Voice Activity Detection (VAD)
- Leading/trailing silence trimming
- Safe 16-bit PCM volume normalization
- Adaptive ambient-noise threshold tracking
- Thread-safe configurable processing pipeline
- Runtime diagnostics and statistics

Design goals
------------
- Dependency-free
- Thread-safe runtime configuration
- 16-bit signed mono PCM support
- Never mutates caller-owned input buffers
- Safe handling of malformed/empty audio
- Suitable for microphone and network speech-recognition pipelines
- Backward-compatible public API

Expected PCM format
-------------------
- Sample width : 16-bit signed
- Channels     : mono
- Endianness   : native PCM byte order
- Encoding     : linear PCM

Important
---------
This module intentionally does NOT own:

- microphone access
- speech recognition
- TTS
- voice gender
- JEROX identity
- wake-word detection

Those responsibilities belong to the appropriate AssistantX modules.
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

MIN_MAX_GAIN = 1.0
MAX_MAX_GAIN = 10.0

MIN_PADDING_FRAMES = 0
MAX_PADDING_FRAMES = 10


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
    """Outcome of energy-based voice-activity detection."""

    contains_speech: bool
    rms: float
    peak: int
    threshold: float
    sample_count: int = 0
    duration_seconds: float = 0.0

    @property
    def confidence_ratio(self) -> float:
        """
        Return RMS relative to the active threshold.

        This is NOT an ML confidence score.
        It is only an energy ratio.
        """
        if self.threshold <= 0.0:
            return 0.0

        return self.rms / self.threshold


@dataclass(frozen=True, slots=True)
class TrimResult:
    """Detailed result of silence trimming."""

    audio: bytes
    original_bytes: int
    trimmed_bytes: int
    frames_total: int
    frames_kept: int
    first_voiced_frame: int | None
    last_voiced_frame: int | None

    @property
    def removed_bytes(self) -> int:
        """Return number of bytes removed."""
        return max(0, self.original_bytes - self.trimmed_bytes)

    @property
    def reduction_ratio(self) -> float:
        """Return removed/original byte ratio."""
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


def _clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    """Clamp a numeric value to a safe range."""
    return max(minimum, min(maximum, value))


def _validate_sample_rate(sample_rate: int) -> int:
    """Validate and return an audio sample rate."""
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
        raise AudioFormatError(
            "sample_rate must be an integer."
        )

    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise AudioFormatError(
            f"sample_rate must be between "
            f"{MIN_SAMPLE_RATE} and {MAX_SAMPLE_RATE} Hz."
        )

    return sample_rate


def _validate_frame_ms(frame_ms: int) -> int:
    """Validate and return frame duration in milliseconds."""
    if isinstance(frame_ms, bool) or not isinstance(frame_ms, int):
        raise AudioFormatError(
            "frame_ms must be an integer."
        )

    if not MIN_FRAME_MS <= frame_ms <= MAX_FRAME_MS:
        raise AudioFormatError(
            f"frame_ms must be between "
            f"{MIN_FRAME_MS} and {MAX_FRAME_MS}."
        )

    return frame_ms


def _validate_rms_threshold(
    threshold: float,
    *,
    name: str = "rms_threshold",
) -> float:
    """Validate an RMS threshold."""
    if isinstance(threshold, bool) or not isinstance(
        threshold,
        (int, float),
    ):
        raise AudioConfigurationError(
            f"{name} must be numeric."
        )

    threshold = float(threshold)

    if not math.isfinite(threshold):
        raise AudioConfigurationError(
            f"{name} must be finite."
        )

    if not MIN_RMS_THRESHOLD <= threshold <= MAX_RMS_THRESHOLD:
        raise AudioConfigurationError(
            f"{name} must be between "
            f"{MIN_RMS_THRESHOLD} and {MAX_RMS_THRESHOLD}."
        )

    return threshold


def _validate_target_peak(target_peak: int) -> int:
    """Validate normalization target peak."""
    if isinstance(target_peak, bool) or not isinstance(
        target_peak,
        int,
    ):
        raise AudioConfigurationError(
            "target_peak must be an integer."
        )

    if not MIN_TARGET_PEAK <= target_peak <= MAX_TARGET_PEAK:
        raise AudioConfigurationError(
            f"target_peak must be between "
            f"{MIN_TARGET_PEAK} and {MAX_TARGET_PEAK}."
        )

    return target_peak


def _validate_pcm(
    pcm_bytes: bytes | bytearray | memoryview | None,
) -> bytes:
    """
    Validate and copy PCM input.

    A new bytes object is returned so callers cannot accidentally have
    their mutable bytearray/memoryview modified by downstream processing.
    """
    if pcm_bytes is None:
        return b""

    if not isinstance(
        pcm_bytes,
        (bytes, bytearray, memoryview),
    ):
        raise AudioFormatError(
            "PCM audio must be bytes-like data."
        )

    return bytes(pcm_bytes)


def _to_samples(pcm_bytes: bytes) -> array.array:
    """
    Convert native-endian PCM bytes into signed 16-bit samples.

    Odd trailing bytes are ignored safely because one PCM sample requires
    two bytes.
    """
    pcm_bytes = _validate_pcm(pcm_bytes)

    usable_length = len(pcm_bytes) - (
        len(pcm_bytes) % SAMPLE_WIDTH_BYTES
    )

    if usable_length <= 0:
        return array.array("h")

    samples = array.array("h")

    try:
        samples.frombytes(
            pcm_bytes[:usable_length]
        )
    except (OverflowError, ValueError) as exc:
        raise AudioFormatError(
            "Invalid 16-bit PCM buffer."
        ) from exc

    return samples


def _frame_size_samples(
    sample_rate: int,
    frame_ms: int,
) -> int:
    """Calculate a safe PCM frame size in samples."""
    return max(
        1,
        int(round(sample_rate * frame_ms / 1000.0)),
    )


# ============================================================================
# Audio Analysis
# ============================================================================


def compute_rms(
    pcm_bytes: bytes | bytearray | memoryview,
) -> float:
    """
    Calculate RMS amplitude of a 16-bit PCM buffer.

    Returns
    -------
    float
        RMS amplitude approximately in the range 0..32768.
    """
    samples = _to_samples(pcm_bytes)

    if not samples:
        return 0.0

    sum_squares = math.fsum(
        float(sample) * float(sample)
        for sample in samples
    )

    return math.sqrt(
        sum_squares / len(samples)
    )


def compute_peak(
    pcm_bytes: bytes | bytearray | memoryview,
) -> int:
    """Return absolute peak amplitude of a PCM buffer."""
    samples = _to_samples(pcm_bytes)

    if not samples:
        return 0

    return max(
        abs(sample)
        for sample in samples
    )


def analyze_audio(
    pcm_bytes: bytes | bytearray | memoryview,
    sample_rate: int | None = None,
) -> AudioMetrics:
    """
    Analyze RMS, peak, sample count and optional duration.
    """
    samples = _to_samples(pcm_bytes)

    if not samples:
        return AudioMetrics(
            rms=0.0,
            peak=0,
            sample_count=0,
            duration_seconds=0.0,
        )

    if sample_rate is not None:
        sample_rate = _validate_sample_rate(
            sample_rate
        )

    sum_squares = math.fsum(
        float(sample) * float(sample)
        for sample in samples
    )

    rms = math.sqrt(
        sum_squares / len(samples)
    )

    peak = max(
        abs(sample)
        for sample in samples
    )

    duration = (
        len(samples) / sample_rate
        if sample_rate is not None
        else 0.0
    )

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
    pcm_bytes: bytes | bytearray | memoryview,
    rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    sample_rate: int | None = None,
) -> VADResult:
    """
    Detect likely speech using RMS energy.

    This is an energy-based VAD, not an ML speech classifier.
    """
    rms_threshold = _validate_rms_threshold(
        rms_threshold
    )

    metrics = analyze_audio(
        pcm_bytes,
        sample_rate=sample_rate,
    )

    contains_speech = (
        metrics.rms >= rms_threshold
    )

    return VADResult(
        contains_speech=contains_speech,
        rms=metrics.rms,
        peak=metrics.peak,
        threshold=rms_threshold,
        sample_count=metrics.sample_count,
        duration_seconds=metrics.duration_seconds,
    )


# ============================================================================
# Silence Trimming
# ============================================================================


def trim_silence_with_result(
    pcm_bytes: bytes | bytearray | memoryview,
    sample_rate: int,
    rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    frame_ms: int = DEFAULT_FRAME_MS,
    padding_frames: int = 1,
) -> TrimResult:
    """
    Trim leading and trailing silence.

    A small number of frames can be retained around the detected
    speech region using ``padding_frames``.
    """
    pcm_bytes = _validate_pcm(pcm_bytes)
    sample_rate = _validate_sample_rate(
        sample_rate
    )
    frame_ms = _validate_frame_ms(
        frame_ms
    )
    rms_threshold = _validate_rms_threshold(
        rms_threshold
    )

    if isinstance(padding_frames, bool) or not isinstance(
        padding_frames,
        int,
    ):
        raise AudioConfigurationError(
            "padding_frames must be an integer."
        )

    if not MIN_PADDING_FRAMES <= padding_frames <= MAX_PADDING_FRAMES:
        raise AudioConfigurationError(
            f"padding_frames must be between "
            f"{MIN_PADDING_FRAMES} and {MAX_PADDING_FRAMES}."
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

    # Ensure an incomplete final sample does not enter the frame analysis.
    usable_length = len(pcm_bytes) - (
        len(pcm_bytes) % SAMPLE_WIDTH_BYTES
    )

    if usable_length <= 0:
        return TrimResult(
            audio=b"",
            original_bytes=len(pcm_bytes),
            trimmed_bytes=0,
            frames_total=0,
            frames_kept=0,
            first_voiced_frame=None,
            last_voiced_frame=None,
        )

    pcm_bytes = pcm_bytes[:usable_length]

    frame_samples = _frame_size_samples(
        sample_rate,
        frame_ms,
    )

    frame_size_bytes = (
        frame_samples * SAMPLE_WIDTH_BYTES
    )

    frames = [
        pcm_bytes[index:index + frame_size_bytes]
        for index in range(
            0,
            len(pcm_bytes),
            frame_size_bytes,
        )
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

    trimmed = b"".join(
        frames[start:end]
    )

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
    pcm_bytes: bytes | bytearray | memoryview,
    sample_rate: int,
    rms_threshold: float = DEFAULT_RMS_THRESHOLD,
    frame_ms: int = DEFAULT_FRAME_MS,
) -> bytes:
    """
    Backward-compatible silence trimming helper.
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
    pcm_bytes: bytes | bytearray | memoryview,
    target_peak: int = DEFAULT_TARGET_PEAK,
    max_gain: float = MAX_NORMALIZE_GAIN,
) -> bytes:
    """
    Safely boost quiet PCM toward a target peak.

    The function intentionally does NOT reduce already-loud audio.

    This prevents unnecessary compression of microphone dynamics and
    avoids introducing additional processing where it is not required.
    """
    pcm_bytes = _validate_pcm(pcm_bytes)

    target_peak = _validate_target_peak(
        target_peak
    )

    if isinstance(max_gain, bool) or not isinstance(
        max_gain,
        (int, float),
    ):
        raise AudioConfigurationError(
            "max_gain must be numeric."
        )

    max_gain = float(max_gain)

    if not math.isfinite(max_gain):
        raise AudioConfigurationError(
            "max_gain must be finite."
        )

    if not MIN_MAX_GAIN <= max_gain <= MAX_MAX_GAIN:
        raise AudioConfigurationError(
            f"max_gain must be between "
            f"{MIN_MAX_GAIN} and {MAX_MAX_GAIN}."
        )

    samples = _to_samples(pcm_bytes)

    if not samples:
        return pcm_bytes

    current_peak = max(
        abs(sample)
        for sample in samples
    )

    if current_peak <= 0:
        return pcm_bytes

    # Already loud enough.
    if current_peak >= target_peak:
        return pcm_bytes

    gain = min(
        target_peak / current_peak,
        max_gain,
    )

    # Avoid pointless tiny transformations.
    if abs(gain - 1.0) < 0.05:
        return pcm_bytes

    scaled_samples = array.array(
        "h"
    )

    for sample in samples:
        scaled_value = round(
            sample * gain
        )

        scaled_value = max(
            PCM_MIN,
            min(
                PCM_MAX,
                scaled_value,
            ),
        )

        scaled_samples.append(
            scaled_value
        )

    return scaled_samples.tobytes()


# ============================================================================
# Adaptive Ambient Noise Calibration
# ============================================================================


class AmbientNoiseCalibrator:
    """
    Thread-safe adaptive ambient-noise estimator.

    The caller should feed chunks believed to contain only background
    noise/silence.

    Threshold calculation:

        noise_rms * noise_multiplier

    followed by exponential smoothing and configured bounds.
    """

    def __init__(
        self,
        initial_threshold: float = DEFAULT_RMS_THRESHOLD,
        smoothing: float = DEFAULT_SMOOTHING,
        noise_multiplier: float = DEFAULT_NOISE_MULTIPLIER,
        minimum_threshold: float = DEFAULT_RMS_THRESHOLD,
        maximum_threshold: float = 12000.0,
    ) -> None:

        initial_threshold = _validate_rms_threshold(
            initial_threshold,
            name="initial_threshold",
        )

        minimum_threshold = _validate_rms_threshold(
            minimum_threshold,
            name="minimum_threshold",
        )

        maximum_threshold = _validate_rms_threshold(
            maximum_threshold,
            name="maximum_threshold",
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

        self._smoothing = float(
            smoothing
        )

        self._noise_multiplier = float(
            noise_multiplier
        )

        self._minimum_threshold = float(
            minimum_threshold
        )

        self._maximum_threshold = float(
            maximum_threshold
        )

        self._threshold = _clamp(
            float(initial_threshold),
            self._minimum_threshold,
            self._maximum_threshold,
        )

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
        """Number of calibration updates."""
        with self._lock:
            return self._updates

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def update(
        self,
        silent_chunk_pcm: bytes | bytearray | memoryview,
    ) -> float:
        """
        Feed a presumed-silent audio chunk into the estimator.

        Returns
        -------
        float
            New adaptive threshold.
        """
        chunk_rms = compute_rms(
            silent_chunk_pcm
        )

        with self._lock:
            proposed_threshold = (
                chunk_rms
                * self._noise_multiplier
            )

            self._threshold = (
                (1.0 - self._smoothing)
                * self._threshold
                + self._smoothing
                * proposed_threshold
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
            "Ambient noise updated: "
            "rms=%.1f threshold=%.1f",
            chunk_rms,
            threshold,
        )

        return threshold

    def reset(
        self,
        threshold: float | None = None,
    ) -> None:
        """Reset adaptive calibration state."""
        if threshold is None:
            new_threshold = self._minimum_threshold
        else:
            new_threshold = _validate_rms_threshold(
                threshold,
                name="reset threshold",
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
                "threshold": round(
                    self._threshold,
                    2,
                ),
                "noise_floor": round(
                    self._last_noise_rms,
                    2,
                ),
                "smoothing": self._smoothing,
                "noise_multiplier": self._noise_multiplier,
                "minimum_threshold": (
                    self._minimum_threshold
                ),
                "maximum_threshold": (
                    self._maximum_threshold
                ),
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

    This class does not know anything about JEROX, TTS or wake words.
    """

    def __init__(
        self,
        rms_threshold: float = DEFAULT_RMS_THRESHOLD,
        frame_ms: int = DEFAULT_FRAME_MS,
        target_peak: int = DEFAULT_TARGET_PEAK,
        normalize: bool = True,
        adaptive_threshold: bool = True,
    ) -> None:

        rms_threshold = _validate_rms_threshold(
            rms_threshold
        )

        frame_ms = _validate_frame_ms(
            frame_ms
        )

        target_peak = _validate_target_peak(
            target_peak
        )

        self._lock = threading.RLock()

        self._rms_threshold = rms_threshold
        self._frame_ms = frame_ms
        self._target_peak = target_peak

        self._normalize_enabled = bool(
            normalize
        )

        self._adaptive_enabled = bool(
            adaptive_threshold
        )

        self._calibrator = AmbientNoiseCalibrator(
            initial_threshold=rms_threshold,
        )

        # Runtime counters.
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
        """Return the active RMS threshold."""
        with self._lock:
            if self._adaptive_enabled:
                return self._calibrator.threshold

            return self._rms_threshold

    @property
    def frame_ms(self) -> int:
        """Return configured frame duration."""
        with self._lock:
            return self._frame_ms

    @property
    def target_peak(self) -> int:
        """Return configured normalization target."""
        with self._lock:
            return self._target_peak

    @property
    def normalization_enabled(self) -> bool:
        """Return whether normalization is enabled."""
        with self._lock:
            return self._normalize_enabled

    @property
    def adaptive_threshold_enabled(self) -> bool:
        """Return whether adaptive thresholding is enabled."""
        with self._lock:
            return self._adaptive_enabled

    def set_threshold(
        self,
        threshold: float,
    ) -> None:
        """Set the static RMS threshold."""
        threshold = _validate_rms_threshold(
            threshold
        )

        with self._lock:
            self._rms_threshold = threshold

            # Keep adaptive mode internally consistent.
            if not self._adaptive_enabled:
                return

            self._calibrator.reset(
                threshold
            )

    def set_frame_ms(
        self,
        frame_ms: int,
    ) -> None:
        """Update frame duration."""
        frame_ms = _validate_frame_ms(
            frame_ms
        )

        with self._lock:
            self._frame_ms = frame_ms

    def set_target_peak(
        self,
        target_peak: int,
    ) -> None:
        """Update normalization target peak."""
        target_peak = _validate_target_peak(
            target_peak
        )

        with self._lock:
            self._target_peak = target_peak

    def set_normalization(
        self,
        enabled: bool,
    ) -> None:
        """Enable or disable volume normalization."""
        with self._lock:
            self._normalize_enabled = bool(
                enabled
            )

    def set_adaptive_threshold(
        self,
        enabled: bool,
    ) -> None:
        """Enable or disable adaptive thresholding."""
        with self._lock:
            self._adaptive_enabled = bool(
                enabled
            )

    # ------------------------------------------------------------------
    # VAD
    # ------------------------------------------------------------------

    def detect_voice(
        self,
        pcm_bytes: bytes | bytearray | memoryview,
        sample_rate: int | None = None,
    ) -> VADResult:
        """Run VAD using the current active threshold."""
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

    def calibrate(
        self,
        silent_chunk_pcm: bytes | bytearray | memoryview,
    ) -> float:
        """
        Update adaptive threshold from presumed ambient audio.
        """
        threshold = self._calibrator.update(
            silent_chunk_pcm
        )

        with self._lock:
            self._calibration_updates += 1

        return threshold

    def reset_calibration(self) -> None:
        """Reset adaptive calibration state."""
        with self._lock:
            self._calibrator.reset(
                self._rms_threshold
            )

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(
        self,
        pcm_bytes: bytes | bytearray | memoryview,
        sample_rate: int,
        *,
        require_voice: bool = True,
        trim: bool = True,
        normalize: bool | None = None,
    ) -> bytes:
        """
        Process a PCM buffer through the configured pipeline.

        Parameters
        ----------
        pcm_bytes:
            Raw 16-bit mono PCM.

        sample_rate:
            PCM sample rate.

        require_voice:
            If True, return empty bytes when VAD detects no signal.

        trim:
            Remove leading/trailing silence.

        normalize:
            Per-call override for normalization.
            ``None`` uses the configured setting.

        Returns
        -------
        bytes
            Processed PCM.

        Notes
        -----
        Empty bytes means that no usable audio was produced.
        """
        pcm_bytes = _validate_pcm(
            pcm_bytes
        )

        sample_rate = _validate_sample_rate(
            sample_rate
        )

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
            trim_result = trim_silence_with_result(
                pcm_bytes=processed,
                sample_rate=sample_rate,
                rms_threshold=self.rms_threshold,
                frame_ms=frame_ms,
            )

            if trim_result.audio:
                if trim_result.audio != processed:
                    with self._lock:
                        self._trimmed_buffers += 1

                processed = trim_result.audio

            elif require_voice:
                return b""

        # --------------------------------------------------------------
        # Volume normalization
        # --------------------------------------------------------------

        if normalization_enabled and processed:
            with self._lock:
                target_peak = self._target_peak

            normalized = normalize_volume(
                processed,
                target_peak=target_peak,
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
                analyzed_buffers=(
                    self._analyzed_buffers
                ),
                vad_checks=self._vad_checks,
                voiced_buffers=self._voiced_buffers,
                silent_buffers=self._silent_buffers,
                trimmed_buffers=self._trimmed_buffers,
                normalized_buffers=(
                    self._normalized_buffers
                ),
                calibration_updates=(
                    self._calibration_updates
                ),
            )

    def diagnostics(self) -> dict:
        """Return safe runtime diagnostic information."""
        with self._lock:
            stats = NoiseFilterStats(
                analyzed_buffers=(
                    self._analyzed_buffers
                ),
                vad_checks=self._vad_checks,
                voiced_buffers=self._voiced_buffers,
                silent_buffers=self._silent_buffers,
                trimmed_buffers=self._trimmed_buffers,
                normalized_buffers=(
                    self._normalized_buffers
                ),
                calibration_updates=(
                    self._calibration_updates
                ),
            )

            active_threshold = (
                self._calibrator.threshold
                if self._adaptive_enabled
                else self._rms_threshold
            )

            return {
                "module": "voice.noise_filter",
                "pcm": {
                    "sample_width_bytes": (
                        SAMPLE_WIDTH_BYTES
                    ),
                    "encoding": "signed_16bit_pcm",
                    "channels": 1,
                },
                "rms_threshold": round(
                    active_threshold,
                    2,
                ),
                "static_rms_threshold": round(
                    self._rms_threshold,
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
                    "analyzed_buffers": (
                        stats.analyzed_buffers
                    ),
                    "vad_checks": (
                        stats.vad_checks
                    ),
                    "voiced_buffers": (
                        stats.voiced_buffers
                    ),
                    "silent_buffers": (
                        stats.silent_buffers
                    ),
                    "trimmed_buffers": (
                        stats.trimmed_buffers
                    ),
                    "normalized_buffers": (
                        stats.normalized_buffers
                    ),
                    "calibration_updates": (
                        stats.calibration_updates
                    ),
                },
                "calibrator": (
                    self._calibrator.diagnostics()
                ),
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
    pcm_bytes: bytes | bytearray | memoryview,
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
    pcm_bytes: bytes | bytearray | memoryview,
    rms_threshold: float | None = None,
) -> bool:
    """
    Convenience helper for energy-based voice detection.
    """
    if rms_threshold is None:
        threshold = noise_filter.rms_threshold
    else:
        threshold = _validate_rms_threshold(
            rms_threshold
        )

    return detect_voice_activity(
        pcm_bytes,
        rms_threshold=threshold,
    ).contains_speech


def get_audio_metrics(
    pcm_bytes: bytes | bytearray | memoryview,
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
    # Constants
    "SAMPLE_WIDTH_BYTES",
    "PCM_MIN",
    "PCM_MAX",
    "DEFAULT_FRAME_MS",
    "DEFAULT_RMS_THRESHOLD",
    "DEFAULT_TARGET_PEAK",
    # Exceptions
    "NoiseFilterError",
    "AudioFormatError",
    "AudioConfigurationError",
    # Data models
    "AudioMetrics",
    "VADResult",
    "TrimResult",
    "NoiseFilterStats",
    # Calibration
    "AmbientNoiseCalibrator",
    # Pipeline
    "NoiseFilter",
    "noise_filter",
    # Analysis
    "compute_rms",
    "compute_peak",
    "analyze_audio",
    "detect_voice_activity",
    # Processing
    "trim_silence",
    "trim_silence_with_result",
    "normalize_volume",
    # Convenience
    "filter_audio",
    "is_voice",
    "get_audio_metrics",
]
