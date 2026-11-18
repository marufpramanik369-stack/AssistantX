"""
ai/auto_provider.py
===================
Automatic online/offline AI selection for AssistantX.

    Internet works  -> Gemini   (if it fails -> Ollama)
    No internet     -> Ollama

Place at:  C:\\AssistantX\\ai\\auto_provider.py

Optional settings (settings_manager):
    ai.prefer_offline  = True   # try Ollama first even when online
    ai.ollama_model    = "<name>"  # which Ollama model to use (offline_setup.py sets this)
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.request
from urllib.parse import urlparse
from typing import Any

from ai.provider import AIProviderBase, ChatMessage, CompletionResult, Role, try_get_provider

logger = logging.getLogger(__name__)

# ---- Assistant identity (added to the system prompt of every request) ----
ASSISTANT_NAME = "MOHONA"
CREATOR_NAME_EN = "Mohammad Maruf Pramanik"
CREATOR_NAME_BN = "মোহাম্মদ মারুফ প্রামানিক"
IDENTITY_TEXT = (
    "IDENTITY (highest priority - overrides any earlier name or description): "
    f"Your name is {ASSISTANT_NAME}. You are the user's personal assistant. "
    "Never call yourself ChatGPT , Gemini , or any other name. "
    "When you introduce yourself or are asked your name, say that you are the user's "
    f"personal assistant {ASSISTANT_NAME} (in Bangla: 'আমি আপনার পার্সোনাল অ্যাসিস্ট্যান্ট {ASSISTANT_NAME}'). "
    "If anyone asks who created, built, made or developed you, answer that you were created by "
    f"the software engineer {CREATOR_NAME_EN} (in Bangla: 'আমাকে সফটওয়্যার ইঞ্জিনিয়ার "
    f"{CREATOR_NAME_BN} তৈরি করেছেন'). Never say you were made by Google or anyone else. "
    "Do not repeat your name or your creator in every message; mention them only when relevant."
)

ONLINE_HOST = ("generativelanguage.googleapis.com", 443)
NET_CACHE_SECONDS = 10.0
OLLAMA_URL = "http://localhost:11434"
# A local model on a laptop (CPU) can need a minute or more to load and answer.
# Override with the setting  ai.ollama_timeout  (seconds).
OLLAMA_TIMEOUT = 180.0
# A local CPU model gets much slower with a long chat history, so only the last
# few messages are sent to Ollama. Override with the setting  ai.ollama_history.
OLLAMA_HISTORY = 6
# Online side: when Ollama is ready as a fallback, don't wait too long for Gemini.
# Override with the setting  ai.gemini_timeout  (seconds).
GEMINI_TIMEOUT = 20.0
# If Gemini is the ONLY option (Ollama not running), be patient instead of failing early.
GEMINI_TIMEOUT_ALONE = 45.0
# How long a healthy / unhealthy Ollama check is remembered (seconds).
HEALTH_CACHE_SECONDS = 15.0
HEALTH_RETRY_SECONDS = 3.0


class AutoProvider(AIProviderBase):
    """Chooses Gemini or Ollama for every request."""

    name = "auto"
    default_model = "auto"

    def __init__(self) -> None:
        super().__init__(model="auto")
        self._providers: dict[str, Any] = {}
        self._net_ok = False
        self._net_at = -1e9
        self.last_used: tuple[str, str] | None = None   # ("gemini"|"ollama", model)
        self.last_errors: list[str] = []
        # After Gemini fails it is skipped for a while, so later messages go straight
        # to Ollama instead of wasting seconds on a request that will fail again.
        self._cooldown: dict[str, float] = {}
        self._cooldown_why: dict[str, str] = {}
        self._health: dict[str, tuple[bool, float]] = {}
        self._model_pick_at = -1e9
        self._watch_thread = None
        self._watch_stop = False
        self._watch_every = 5.0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _setting(key: str, default: Any = None) -> Any:
        try:
            from config.settings import settings_manager
            value = settings_manager.get(key, default)
            return default if value is None else value
        except Exception:
            return default

    def _probe_internet(self) -> bool:
        try:
            socket.create_connection(ONLINE_HOST, timeout=2).close()
            ok = True
        except OSError:
            ok = False
        self._net_ok = ok
        self._net_at = time.monotonic()
        return ok

    def _watching(self) -> bool:
        t = self._watch_thread
        return bool(t and t.is_alive() and not self._watch_stop)

    def _internet(self) -> bool:
        age = time.monotonic() - self._net_at
        if self._watching() and age < self._watch_every * 4:
            return self._net_ok          # kept fresh by the background watcher
        if age < NET_CACHE_SECONDS:
            return self._net_ok
        return self._probe_internet()

    def start_watcher(self, interval: float = 5.0) -> None:
        """Track internet + Ollama state in the background, so a user request never
        has to wait for those checks: switching online <-> local becomes instant."""
        if self._watching():
            return
        self._watch_every = max(0.5, float(interval))
        self._watch_stop = False

        def loop() -> None:
            while not self._watch_stop:
                try:
                    self._probe_internet()
                    prov = self._get("ollama")
                    if prov is not None:
                        self._pick_ollama_model(prov)
                        self._healthy("ollama", prov, force=True)
                except Exception as exc:
                    logger.debug("AutoProvider watcher: %s", exc)
                time.sleep(self._watch_every)

        self._watch_thread = threading.Thread(target=loop, daemon=True,
                                              name="auto-provider-watch")
        self._watch_thread.start()

    def stop_watcher(self) -> None:
        self._watch_stop = True

    def _get(self, name: str) -> Any:
        if name not in self._providers:
            prov = try_get_provider(name)
            if prov is not None and name == "ollama":
                try:
                    prov.timeout = float(self._setting("ai.ollama_timeout", OLLAMA_TIMEOUT))
                except Exception:
                    pass
            if prov is not None and name == "gemini":
                try:
                    prov.timeout = float(self._setting("ai.gemini_timeout", GEMINI_TIMEOUT))
                except Exception:
                    pass
            self._providers[name] = prov
        return self._providers[name]

    def _pick_ollama_model(self, prov: Any) -> None:
        """If no model is configured, use the first model Ollama has installed."""
        if self._setting("ai.ollama_model"):
            return
        now = time.monotonic()
        if getattr(prov, "model", "") and now - self._model_pick_at < 60:
            return
        self._model_pick_at = now

# ===================================================UPDATEDs========================================================

        try:
            url = OLLAMA_URL + "/api/tags"
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return
            request = urllib.request.Request(url, headers={"User-Agent": "AssistantX"})
            with urllib.request.urlopen(request, timeout=2) as r:  # nosec B310 - localhost HTTP only
                models = [m["name"] for m in json.load(r).get("models", [])]
            if models:
                prov.model = models[0]
        except Exception:
            pass

    @staticmethod
    def _with_identity(messages):
        """Insert the identity instruction right after the first system message."""
        role = lambda m: getattr(m.role, "value", m.role)
        extra = ChatMessage(Role.SYSTEM, IDENTITY_TEXT)
        out, done = [], False
        for m in messages:
            out.append(m)
            if not done and role(m) == "system":
                out.append(extra)
                done = True
        if not done:
            out.insert(0, extra)
        return out

    def _trim_for_local(self, messages):
        """Keep system message(s) + only the most recent chat messages (faster offline)."""
        try:
            keep = max(1, int(self._setting("ai.ollama_history", OLLAMA_HISTORY)))
        except (TypeError, ValueError):
            keep = OLLAMA_HISTORY
        role = lambda m: getattr(m.role, "value", m.role)
        system = [m for m in messages if role(m) == "system"]
        rest = [m for m in messages if role(m) != "system"]
        return system + rest[-keep:]

    @staticmethod
    def _pause_for(error: str) -> tuple[float, str]:
        """How long to skip Gemini after this kind of failure."""
        low = (error or "").lower()
        if "429" in low or "resource_exhausted" in low or "quota" in low:
            return 1800.0, "free quota used up"
        if "404" in low or "not_found" in low or "no longer available" in low:
            return 3600.0, "model not available"
        if "timed out" in low or "timeout" in low or "503" in low or "unavailable" in low:
            return 5.0, "slow or busy"
        return 0.0, "request failed"

    def _healthy(self, name: str, prov: Any, force: bool = False) -> bool:
        """Provider health check; Ollama's result is cached to avoid a network call per message."""
        if name != "ollama":
            try:
                return bool(prov.health_check())
            except Exception:
                return False
        ok, stamp = self._health.get(name, (False, -1e9))
        age = time.monotonic() - stamp
        if not force:
            if self._watching() and age < self._watch_every * 4:
                return ok                # kept fresh by the background watcher
            if age < (HEALTH_CACHE_SECONDS if ok else HEALTH_RETRY_SECONDS):
                return ok
        try:
            ok = bool(prov.health_check())
        except Exception:
            ok = False
        self._health[name] = (ok, time.monotonic())
        return ok

    def _candidates(self) -> list[Any]:
        self.last_errors = []
        online = self._internet()
        if online and self._setting("ai.prefer_offline", False):
            order = ["ollama", "gemini"]
        elif online:
            order = ["gemini", "ollama"]
        else:
            order = ["ollama"]
            self.last_errors.append("no internet connection")

        found = []
        paused = []
        for name in order:
            prov = self._get(name)
            if prov is None:
                self.last_errors.append(f"{name}: could not be created")
                continue
            if name == "ollama":
                self._pick_ollama_model(prov)
            until = self._cooldown.get(name, 0.0)
            now = time.monotonic()
            if until > now:
                mins = max(1, round((until - now) / 60))
                self.last_errors.append(
                    f"{name}: skipped for ~{mins} min ({self._cooldown_why.get(name, '')})")
                paused.append(prov)
                continue
            ok = self._healthy(name, prov)
            if not ok:
                hint = ("Ollama is not running or has no model" if name == "ollama"
                        else "Gemini key / SDK not available")
                self.last_errors.append(f"{name}: {hint}")
                continue
            found.append(prov)
        if not found and paused:      # nothing else works: try the paused one anyway
            found = paused
        return found

    # --------------------------------------------------------------- required API
    def is_available(self) -> bool:
        try:
            return bool(self._candidates())
        except Exception:
            return False

    def generate(self, messages, max_retries: int = 1, **kwargs):
        # The inner providers already retry; avoid long extra waits here.
        return super().generate(messages, max_retries=1, **kwargs)

    def _call_api(self, messages, **kwargs) -> CompletionResult:
        started = time.monotonic()
        messages = self._with_identity(messages)
        candidates = self._candidates()
        errors = list(self.last_errors)

        for prov in candidates:
            logger.info("AutoProvider: trying %s (%s)", prov.name, prov.model)
            msgs = self._trim_for_local(messages)
            if prov.name == "gemini":
                has_fallback = any(c.name == "ollama" for c in candidates)
                try:
                    prov.timeout = (float(self._setting("ai.gemini_timeout", GEMINI_TIMEOUT))
                                    if has_fallback else GEMINI_TIMEOUT_ALONE)
                except Exception:
                    pass
            retries = 1 if (prov.name == "gemini" and len(candidates) > 1) else 2
            res = prov.generate(msgs, max_retries=retries, **kwargs)
            if res.ok and res.has_text:
                self._cooldown.pop(prov.name, None)
                self.last_used = (prov.name, prov.model)
                return res
            err = res.error or "empty response"
            errors.append(f"{prov.name}: {err}")
            if prov.name == "gemini":
                seconds, why = self._pause_for(err)
                self._cooldown["gemini"] = time.monotonic() + seconds
                self._cooldown_why["gemini"] = why
            logger.warning("AutoProvider: %s failed, trying next. (%s)", prov.name, res.error)

        return CompletionResult.failure(
            provider=self.name,
            model=self.model,
            latency_seconds=time.monotonic() - started,
            error=" | ".join(errors) or "No AI provider available",
        )

    def diagnostics(self) -> dict[str, Any]:
        info = super().diagnostics()
        info.update({
            "internet": self._net_ok,
            "last_used": self.last_used,
            "last_errors": list(self.last_errors),
            "gemini_skipped_for_s": max(0, round(self._cooldown.get("gemini", 0.0) - time.monotonic())),
        })
        return info

    