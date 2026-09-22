"""
translate_service.py
=====================
Text translation and language detection.

Backend strategy:
    1. Google Translate's free, unofficial web endpoint (the same one
       translate.google.com's website itself calls) — used by default
       since it requires no API key or billing setup, which matters for
       a voice assistant feature that should work immediately after
       install. This is NOT the official paid Cloud Translation API;
       it's rate-limited and unofficial, so it's wrapped with a clear
       upgrade path.
    2. Google Cloud Translation API — used automatically instead if
       GOOGLE_TRANSLATE_API_KEY is configured, for production-grade
       reliability and higher rate limits.

Language codes follow ISO 639-1 (e.g. 'en', 'bn', 'hi', 'es') to stay
consistent with voice/languages.py's locale handling elsewhere in the
codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config.constants import (
    HTTP_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
    TRANSLATE_DEFAULT_TARGET,
)
from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_HOURS = 72  # translations of the same text are stable; cache generously
_FREE_ENDPOINT_URL = "https://translate.googleapis.com/translate_a/single"
_CLOUD_API_URL = "https://translation.googleapis.com/language/translate/v2"
_CLOUD_DETECT_URL = "https://translation.googleapis.com/language/translate/v2/detect"

# A practical subset of common language names -> ISO 639-1 codes, so
# callers/voice commands can say "translate to Bangla" rather than
# needing to know the code 'bn' — extend freely as needed.
LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "english": "en", "bangla": "bn", "bengali": "bn", "hindi": "hi",
    "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "russian": "ru", "japanese": "ja", "korean": "ko",
    "chinese": "zh-CN", "mandarin": "zh-CN", "arabic": "ar", "urdu": "ur",
    "turkish": "tr", "dutch": "nl", "polish": "pl", "vietnamese": "vi",
    "thai": "th", "indonesian": "id", "swedish": "sv", "greek": "el",
}


class TranslateServiceError(RuntimeError):
    """Raised when a translation or language-detection request fails."""


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    source_language: str
    target_language: str

    def to_dict(self) -> dict:
        return {
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TranslationResult:
        return cls(**data)


@dataclass
class LanguageDetection:
    language_code: str
    confidence: float


def _get_requests():
    try:
        import requests

        return requests
    except ImportError as exc:
        raise TranslateServiceError(
            "Translation requires the 'requests' package. Run: pip install requests"
        ) from exc


def resolve_language_code(name_or_code: str) -> str:
    """
    Resolve a spoken language name ('bangla', 'french') or an already
    valid code ('bn', 'fr') into its ISO 639-1 code. Unrecognized input
    is passed through as-is (lets the backend attempt it / reject it
    with its own clear error, rather than silently failing here).
    """
    normalized = name_or_code.strip().lower()
    if normalized in LANGUAGE_NAME_TO_CODE:
        return LANGUAGE_NAME_TO_CODE[normalized]
    return name_or_code.strip()


def _cache_key(prefix: str, *parts: str) -> str:
    normalized = "|".join(p.strip().lower() for p in parts)
    return f"translate:{prefix}:{normalized}"


def _cache_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_HOURS)).isoformat()


def _try_get_cached(cache_key: str):
    try:
        from database import db_manager

        return db_manager.get_cache(cache_key)
    except Exception as exc:  # noqa: BLE001 - cache is a pure optimization, never fatal
        logger.debug("Translate cache unavailable (%s); proceeding without it.", exc)
        return None


def _try_set_cached(cache_key: str, value) -> None:
    try:
        from database import db_manager

        db_manager.set_cache(cache_key, value, expires_at=_cache_expiry())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write translate cache (%s); continuing without caching.", exc)


# --------------------------------------------------------------------------- #
# Free endpoint backend (default, no API key)
# --------------------------------------------------------------------------- #

def _translate_free(text: str, target: str, source: str) -> TranslationResult:
    requests = _get_requests()
    try:
        response = requests.get(
            _FREE_ENDPOINT_URL,
            params={
                "client": "gtx",
                "sl": source,
                "tl": target,
                "dt": "t",
                "q": text,
            },
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TranslateServiceError(f"Translation request failed: {exc}") from exc

    try:
        payload = response.json()
        # Response shape: [[[translated_chunk, original_chunk, ...], ...], ..., detected_source_lang]
        translated_text = "".join(chunk[0] for chunk in payload[0] if chunk[0])
        detected_source = payload[2] if len(payload) > 2 and isinstance(payload[2], str) else source
    except (ValueError, IndexError, TypeError) as exc:
        raise TranslateServiceError(f"Unexpected translation response format: {exc}") from exc

    return TranslationResult(
        original_text=text,
        translated_text=translated_text,
        source_language=detected_source,
        target_language=target,
    )


def _detect_free(text: str) -> LanguageDetection:
    """
    The free endpoint doesn't expose a dedicated detect-only call, so
    detection is done as a side effect of translating to English and
    reading back the detected source language field.
    """
    result = _translate_free(text, target="en", source="auto")
    return LanguageDetection(language_code=result.source_language, confidence=1.0)


# --------------------------------------------------------------------------- #
# Google Cloud Translation API backend (used when an API key is configured)
# --------------------------------------------------------------------------- #

def _translate_cloud(text: str, target: str, source: str, api_key: str) -> TranslationResult:
    requests = _get_requests()
    params = {"key": api_key, "q": text, "target": target, "format": "text"}
    if source != "auto":
        params["source"] = source

    try:
        response = requests.post(
            _CLOUD_API_URL,
            data=params,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TranslateServiceError(f"Cloud translation request failed: {exc}") from exc

    data = response.json()
    try:
        translation = data["data"]["translations"][0]
    except (KeyError, IndexError) as exc:
        raise TranslateServiceError(f"Unexpected Cloud Translation response: {exc}") from exc

    return TranslationResult(
        original_text=text,
        translated_text=translation["translatedText"],
        source_language=translation.get("detectedSourceLanguage", source),
        target_language=target,
    )


def _detect_cloud(text: str, api_key: str) -> LanguageDetection:
    requests = _get_requests()
    try:
        response = requests.post(
            _CLOUD_DETECT_URL,
            data={"key": api_key, "q": text},
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TranslateServiceError(f"Cloud language detection request failed: {exc}") from exc

    data = response.json()
    try:
        detection = data["data"]["detections"][0][0]
    except (KeyError, IndexError) as exc:
        raise TranslateServiceError(f"Unexpected Cloud Detection response: {exc}") from exc

    return LanguageDetection(
        language_code=detection["language"],
        confidence=float(detection.get("confidence", 0.0)),
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def translate(
    text: str,
    target: str = TRANSLATE_DEFAULT_TARGET,
    source: str = "auto",
) -> TranslationResult:
    """
    Translate `text` into the target language.

    Args:
        text: The text to translate.
        target: Target language name or ISO code, e.g. 'bangla' or 'bn'.
        source: Source language name/code, or 'auto' to auto-detect
            (default — recommended unless the source is already known,
            since auto-detection is generally accurate for sentences of
            reasonable length).

    Uses the Google Cloud Translation API automatically if
    GOOGLE_TRANSLATE_API_KEY is configured; otherwise falls back to the
    free unofficial endpoint with zero configuration required.

    Raises:
        TranslateServiceError: on empty text or a request failure.
    """
    text = text.strip()
    if not text:
        raise TranslateServiceError("Empty text to translate.")

    target_code = resolve_language_code(target)
    source_code = resolve_language_code(source) if source != "auto" else "auto"

    cache_key = _cache_key("text", text, source_code, target_code)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return TranslationResult.from_dict(cached)

    api_key = get_env("GOOGLE_TRANSLATE_API_KEY")
    if api_key:
        result = _translate_cloud(text, target_code, source_code, api_key)
        backend = "cloud_api"
    else:
        result = _translate_free(text, target_code, source_code)
        backend = "free_endpoint"

    logger.info(
        "Translated %d char(s) %s -> %s via %s.",
        len(text), result.source_language, result.target_language, backend,
    )
    _try_set_cached(cache_key, result.to_dict())
    return result


def detect_language(text: str) -> LanguageDetection:
    """
    Detect the language of `text` without translating it.

    Raises:
        TranslateServiceError: on empty text or a request failure.
    """
    text = text.strip()
    if not text:
        raise TranslateServiceError("Empty text for language detection.")

    cache_key = _cache_key("detect", text)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return LanguageDetection(**cached)

    api_key = get_env("GOOGLE_TRANSLATE_API_KEY")
    result = _detect_cloud(text, api_key) if api_key else _detect_free(text)

    _try_set_cached(cache_key, {"language_code": result.language_code, "confidence": result.confidence})
    return result


def is_available() -> bool:
    """Translation always has a usable backend (the free endpoint needs
    no key), so this only checks that the 'requests' package is installed."""
    try:
        _get_requests()
        return True
    except TranslateServiceError:
        return False


def is_using_premium_backend() -> bool:
    """Whether GOOGLE_TRANSLATE_API_KEY is configured (True, Cloud API)
    or the free unofficial endpoint is in use (False)."""
    return bool(get_env("GOOGLE_TRANSLATE_API_KEY"))
