"""Local HTTP control API (localhost only by default).

  GET  /status            terminal state and last turn
  POST /wake              start listening as if the wake word was heard
  POST /ask   {"text"}    send text instead of speech; the reply plays here
  POST /stop              stop playback / the conversation, back to standby
"""

import asyncio
import json
import logging
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)
MAX_BODY = 64 * 1024


async def _respond(writer, status: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 409: "Conflict"}.get(status, "Error")
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii") + body
    )
    await writer.drain()


async def _handle(terminal, reader, writer):
    try:
        request = await asyncio.wait_for(reader.readline(), 5)
        method, target, _ = request.decode("latin-1").split(" ", 2)
        length = 0
        while True:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode("latin-1").strip()
            if not line:
                break
            name, _, value = line.partition(":")
            if name.lower() == "content-length":
                length = min(int(value.strip()), MAX_BODY)
        body = await reader.readexactly(length) if length else b""
        url = urlparse(target)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if body:
            params.update(json.loads(body.decode("utf-8")))
        status, payload = await _route(terminal, method.upper(), url.path, params)
        await _respond(writer, status, payload)
    except Exception as exc:
        log.debug("control request failed: %s", exc)
        try:
            await _respond(writer, 400, {"error": str(exc)})
        except Exception:
            pass
    finally:
        writer.close()


async def _route(terminal, method, path, params):
    if method == "GET" and path == "/status":
        return 200, terminal.status()
    if method != "POST":
        return 404, {"error": f"{method} {path} not supported"}
    if path in ("/wake", "/ask") and terminal.conn is None:
        return 409, {"error": "not connected to the server"}
    if path == "/wake":
        terminal.start_dialog("manual")
        return 200, {"ok": True}
    if path == "/ask":
        text = str(params.get("text", "")).strip()
        if not text:
            return 400, {"error": "text is required"}
        terminal.start_dialog("text", text)
        return 200, {"ok": True}
    if path == "/stop":
        await terminal.stop_dialog()
        return 200, {"ok": True}
    return 404, {"error": f"unknown path {path}"}


async def serve(terminal, host: str, port: int):
    server = await asyncio.start_server(lambda r, w: _handle(terminal, r, w), host, port)
    log.info("control API on http://%s:%d", host, port)
    return server
