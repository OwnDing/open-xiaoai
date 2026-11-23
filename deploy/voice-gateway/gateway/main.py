"""Voice Gateway entrypoint: Xiaozhi-compatible WebSocket (:8000) + HTTP control (:8003)."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from pathlib import Path
import resource
import signal
import sys
import time
from typing import Any

from aiohttp import web
import websockets

from .asr import SenseVoiceASR
from .config import GatewayConfig
from .health import AudioHealthSink
from .llm import LLMBridge
from .session import DeviceSession, SessionRegistry
from .voiceprint import VoiceprintClient

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("voice-gateway")


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except OSError:
        pass
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS returns bytes, Linux returns KiB.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(usage / divisor, 1)


def _header(ws: Any, name: str) -> str:
    req = getattr(ws, "request", None)
    headers = getattr(req, "headers", None) if req is not None else getattr(ws, "request_headers", None)
    if headers is None:
        return ""
    return str(headers.get(name) or headers.get(name.lower()) or "").strip()


class VoiceGatewayApp:
    def __init__(self, config: GatewayConfig, asr: Any | None = None, llm: LLMBridge | None = None):
        self.config = config
        self.started_at = time.time()
        self.asr = asr if asr is not None else SenseVoiceASR(
            model_dir=config.asr_config["model_dir"],
            num_threads=int(config.asr_config.get("num_threads") or config.asr_threads),
            language=str(config.asr_config.get("language") or "auto"),
            use_itn=bool(config.asr_config.get("use_itn", True)),
            max_audio_s=float(config.asr_config.get("max_audio_s") or config.max_audio_s),
        )
        self.llm = llm if llm is not None else LLMBridge.from_config(
            config.hermes_provider_dir,
            config.llm_config,
            extra_dirs=(config.home_rules_dir,),
        )
        self.voiceprint = VoiceprintClient(config.voiceprint_config)
        self.health = AudioHealthSink(config.health_log_path)
        self.registry = SessionRegistry()

    async def handle_ws(self, ws: Any, _path: str = "") -> None:
        device_id = _header(ws, "Device-Id")
        client_id = _header(ws, "Client-Id")
        session = DeviceSession(
            ws=ws,
            config=self.config,
            asr=self.asr,
            llm=self.llm,
            voiceprint=self.voiceprint,
            health=self.health,
            registry=self.registry,
            device_id=device_id,
            client_id=client_id,
        )
        await session.run()

    def build_http_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/health", self._http_health)
        app.router.add_get("/status", self._http_status)
        app.router.add_post("/announce", self._http_announce)
        return app

    async def _http_health(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "uptime_s": round(time.time() - self.started_at, 1),
                "rss_mb": _rss_mb(),
                "devices": len(self.registry.all()),
                "asr_utterances": getattr(self.asr, "utterances", 0),
                "voiceprint_enabled": self.voiceprint.enabled,
            }
        )

    async def _http_status(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "uptime_s": round(time.time() - self.started_at, 1),
                "rss_mb": _rss_mb(),
                "output_mode": self.config.output_mode,
                "asr": {
                    "model": str(getattr(self.asr, "model_path", "")),
                    "utterances": getattr(self.asr, "utterances", 0),
                    "total_infer_s": round(getattr(self.asr, "total_infer_s", 0.0), 3),
                },
                "voiceprint_enabled": self.voiceprint.enabled,
                "devices": [s.status_dict() for s in self.registry.all()],
            }
        )

    async def _http_announce(self, request: web.Request) -> web.Response:
        token = self.config.announce_token
        if token:
            auth = request.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(auth, expected):
                return web.json_response({"error": "unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text is required"}, status=400)
        device_id = body.get("device_id")
        room = body.get("room")
        targets = self.registry.find(device_id=device_id, room=room)
        if not targets:
            return web.json_response({"delivered": [], "error": "no matching online device"}, status=404)
        delivered = []
        busy = []
        for session in targets:
            ok = await session.announce(text)
            if ok:
                delivered.append({"device_id": session.device_id, "room": session.profile.room})
            else:
                busy.append({"device_id": session.device_id, "room": session.profile.room})
        return web.json_response({"delivered": delivered, "busy": busy})

    async def close(self) -> None:
        await self.voiceprint.close()


async def run_forever(config_path: str | Path) -> None:
    config = GatewayConfig.from_file(config_path)
    gateway = VoiceGatewayApp(config)

    http_runner = web.AppRunner(gateway.build_http_app(), access_log=None)
    await http_runner.setup()
    http_site = web.TCPSite(http_runner, config.http_host, config.http_port)
    await http_site.start()

    ws_server = await websockets.serve(
        gateway.handle_ws,
        config.ws_host,
        config.ws_port,
        max_size=None,
        ping_interval=30,
        ping_timeout=30,
    )

    log.info(
        "Voice Gateway listening: ws://%s:%d/xiaozhi/v1/ | http://%s:%d/health | output_mode=%s | rss=%.1f MB",
        config.ws_host,
        config.ws_port,
        config.http_host,
        config.http_port,
        config.output_mode,
        _rss_mb(),
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await stop.wait()
    finally:
        log.info("Shutting down Voice Gateway...")
        ws_server.close()
        await ws_server.wait_closed()
        await http_runner.cleanup()
        await gateway.close()


def main() -> None:
    config_path = os.getenv("GATEWAY_CONFIG", "/app/data/.config.yaml")
    asyncio.run(run_forever(config_path))


if __name__ == "__main__":
    main()
