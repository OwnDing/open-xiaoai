"""Xiaozhi WebSocket protocol client (one connection per terminal)."""

import asyncio
import json
import logging

import websockets

from .codec import UPLINK_RATE

log = logging.getLogger(__name__)

HELLO_TIMEOUT = 10.0


class XiaozhiConnection:
    """Connects, exchanges hello, then forwards messages to the callbacks.

    on_json(dict) and on_audio(bytes) run on the event loop; closed is set
    when the socket goes away for any reason.
    """

    def __init__(self, url: str, device_id: str, client_id: str, access_token: str, on_json, on_audio):
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Protocol-Version": "1",
            "Device-Id": device_id,
            "Client-Id": client_id,
        }
        self._on_json, self._on_audio = on_json, on_audio
        self._ws = None
        self._reader = None
        self.session_id = ""
        self.closed = asyncio.Event()

    async def connect(self):
        self._ws = await websockets.connect(
            self.url, additional_headers=self.headers, max_size=None, ping_interval=20, ping_timeout=20
        )
        await self._ws.send(json.dumps({
            "type": "hello",
            "version": 1,
            "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": UPLINK_RATE, "channels": 1, "frame_duration": 60},
        }))
        while True:
            message = await asyncio.wait_for(self._ws.recv(), HELLO_TIMEOUT)
            if isinstance(message, str):
                data = json.loads(message)
                if data.get("type") == "hello":
                    break
        if data.get("transport") != "websocket":
            raise ConnectionError(f"unexpected server hello: {data}")
        self.session_id = data.get("session_id", "")
        self._reader = asyncio.create_task(self._read())
        log.info("connected to %s session=%s", self.url, self.session_id)

    async def _read(self):
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    self._on_audio(message)
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    log.warning("non-JSON text from server: %.80s", message)
                    continue
                try:
                    self._on_json(data)
                except Exception:
                    log.exception("handling server message failed: %s", data)
        except websockets.ConnectionClosed as exc:
            log.info("connection closed: %s", exc)
        except Exception:
            log.exception("connection reader failed")
        finally:
            self.closed.set()

    @property
    def is_open(self) -> bool:
        return self._ws is not None and not self.closed.is_set()

    async def _send(self, message):
        if not self.is_open:
            raise ConnectionError("not connected")
        await self._ws.send(message)

    async def send_json(self, data: dict):
        await self._send(json.dumps({"session_id": self.session_id, **data}, ensure_ascii=False))

    async def send_audio(self, packet: bytes):
        await self._send(packet)

    async def listen_start(self, mode: str = "manual"):
        await self.send_json({"type": "listen", "state": "start", "mode": mode})

    async def listen_stop(self):
        await self.send_json({"type": "listen", "state": "stop"})

    async def listen_detect(self, text: str):
        """Text in place of speech: a wake word gets a greeting, anything else is a question."""
        await self.send_json({"type": "listen", "state": "detect", "text": text})

    async def abort(self):
        await self.send_json({"type": "abort"})

    async def close(self):
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._reader is not None:
            try:
                await asyncio.wait_for(self._reader, 2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._reader.cancel()
        self.closed.set()
