"""Async client for the optional voiceprint service (deploy/voiceprint)."""

from __future__ import annotations

import logging
import time
from urllib.parse import parse_qs, urlparse

import aiohttp

log = logging.getLogger("voice-gateway.voiceprint")

BACKOFF_S = 30.0


class VoiceprintClient:
    """Posts utterance WAV audio to deploy/voiceprint in parallel with ASR.

    Mirrors deploy/sherpa-tts/xiaozhi-server-overrides/voiceprint_provider.py:
    it records the speaker for the session on the voiceprint server without
    altering the ASR transcript, and backs off for 30 s when unreachable.
    """

    def __init__(self, config: dict | None):
        cfg = config or {}
        url = str(cfg.get("url") or "").strip()
        parsed = urlparse(url)
        self.enabled = bool(parsed.scheme and parsed.netloc)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}" if self.enabled else ""
        self.api_key = (
            str(cfg.get("key") or parse_qs(parsed.query).get("key", [""])[0])
            if self.enabled
            else ""
        )
        self.timeout_s = float(cfg.get("timeout_s", 1.5)) if self.enabled else 0.0
        self._down_until = 0.0
        self._session: aiohttp.ClientSession | None = None
        if self.enabled:
            log.info("Voiceprint hook enabled: %s (timeout=%.1fs)", self.base_url, self.timeout_s)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def identify(self, wav_bytes: bytes, session_id: str, device_id: str) -> None:
        if not self.enabled or not wav_bytes or time.monotonic() < self._down_until:
            return
        form = aiohttp.FormData()
        form.add_field("session_id", session_id or "")
        form.add_field("device_id", device_id or "")
        form.add_field("file", wav_bytes, filename="audio.wav", content_type="audio/wav")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            session = self._get_session()
            async with session.post(
                f"{self.base_url}/voiceprint/identify",
                data=form,
                headers=headers,
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                result = await resp.json()
            decision = result.get("decision") or {}
            member = decision.get("member") or {}
            log.info(
                "voiceprint: %s %s score=%s %.3fs",
                member.get("name") or "未识别",
                decision.get("decided_by"),
                decision.get("score"),
                time.monotonic() - started,
            )
        except Exception as exc:
            self._down_until = time.monotonic() + BACKOFF_S
            log.warning("voiceprint call failed, backing off %.0fs: %s", BACKOFF_S, exc)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
