import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xiaozhi.services.protocols.typing import DeviceState
from xiaozhi.services.protocols.websocket_protocol import WebsocketProtocol


_CLOSED = object()


class FakeConfig:
    def get_config(self, key):
        values = {
            "NETWORK.WEBSOCKET_URL": "ws://example.test/xiaozhi/v1/",
            "NETWORK.WEBSOCKET_ACCESS_TOKEN": "test-token",
        }
        return values[key]

    def get_client_id(self):
        return "test-client"

    def get_device_id(self):
        return "test-device"


class FakeWebsocket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.messages.get()
        if message is _CLOSED:
            raise StopAsyncIteration
        return message

    async def send(self, message):
        data = json.loads(message)
        if data.get("type") == "hello":
            await self.messages.put(
                json.dumps({"type": "hello", "transport": "websocket"})
            )

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.messages.put(_CLOSED)

    async def close_from_server(self):
        await self.messages.put(_CLOSED)


class WebsocketReconnectTests(unittest.IsolatedAsyncioTestCase):
    def make_protocol(self):
        config = FakeConfig()
        with patch(
            "xiaozhi.services.protocols.websocket_protocol.ConfigManager.instance",
            return_value=config,
        ):
            protocol = WebsocketProtocol()
        protocol._reconnect_initial_delay = 0.01
        protocol._reconnect_max_delay = 0.02
        return protocol

    async def wait_until(self, predicate, timeout=2.5):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.01)

    async def test_retries_when_initial_connection_is_unavailable(self):
        protocol = self.make_protocol()
        attempts = 0

        async def connect(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("server unavailable")
            return FakeWebsocket()

        with (
            patch(
                "xiaozhi.services.protocols.websocket_protocol.websockets.connect",
                side_effect=connect,
            ),
            patch(
                "xiaozhi.services.protocols.websocket_protocol.get_xiaozhi",
                return_value=SimpleNamespace(device_state=DeviceState.IDLE),
            ),
        ):
            await protocol.open_audio_channel()
            await self.wait_until(protocol.is_audio_channel_opened)

        self.assertEqual(attempts, 3)
        await protocol.close_audio_channel()

    async def test_reconnects_after_server_closes_connection(self):
        protocol = self.make_protocol()
        sockets = []

        async def connect(*args, **kwargs):
            websocket = FakeWebsocket()
            sockets.append(websocket)
            return websocket

        with (
            patch(
                "xiaozhi.services.protocols.websocket_protocol.websockets.connect",
                side_effect=connect,
            ),
            patch(
                "xiaozhi.services.protocols.websocket_protocol.get_xiaozhi",
                return_value=SimpleNamespace(device_state=DeviceState.IDLE),
            ),
        ):
            await protocol.open_audio_channel()
            await sockets[0].close_from_server()
            await self.wait_until(lambda: len(sockets) == 2)
            await self.wait_until(protocol.is_audio_channel_opened)

        self.assertEqual(len(sockets), 2)
        await protocol.close_audio_channel()

    async def test_awaits_async_json_callback(self):
        protocol = self.make_protocol()
        websocket = FakeWebsocket()
        received = asyncio.Event()

        async def connect(*args, **kwargs):
            return websocket

        async def on_json(message):
            if message.get("type") == "tts":
                received.set()

        protocol.on_incoming_json = on_json
        with (
            patch(
                "xiaozhi.services.protocols.websocket_protocol.websockets.connect",
                side_effect=connect,
            ),
            patch(
                "xiaozhi.services.protocols.websocket_protocol.get_xiaozhi",
                return_value=SimpleNamespace(device_state=DeviceState.IDLE),
            ),
        ):
            await protocol.open_audio_channel()
            await websocket.messages.put(json.dumps({"type": "tts", "state": "start"}))
            await self.wait_until(received.is_set)

        await protocol.close_audio_channel()


if __name__ == "__main__":
    unittest.main()
