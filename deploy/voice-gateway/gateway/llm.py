"""Hermes LLM provider loader + async streaming bridge.

Loads deploy/hermes/xiaozhi-provider/hermes.py directly (alongside scene_run.py,
ha.py and optional voice_enroll.py) with minimal stubs for xiaozhi's logger and
base class, so the full tool-call guard, scene shortcut, music shortcut and
voiceprint enrollment work identically without xiaozhi-esp32-server.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
import threading
import types
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger("voice-gateway.llm")


class _LoguruShim:
    """Adapter providing loguru's `logger.bind(tag=...).info(...)` on stdlib logging."""

    def __init__(self, target: logging.Logger):
        self._log = target

    def bind(self, **_kwargs: Any) -> "_LoguruShim":
        return self

    def __getattr__(self, level: str):
        return getattr(self._log, level)


def _load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_hermes_provider(provider_dir: Path, config: dict[str, Any], extra_dirs: tuple[Path, ...] = ()):
    """Load and instantiate LLMProvider from hermes.py in provider_dir."""
    provider_dir = Path(provider_dir)
    hermes_path = provider_dir / "hermes.py"
    if not hermes_path.is_file():
        raise FileNotFoundError(f"hermes.py not found in {provider_dir}")

    hermes_logger = logging.getLogger("voice-gateway.hermes")
    stubs: dict[str, Any] = {
        "config": types.ModuleType("config"),
        "config.logger": types.SimpleNamespace(setup_logging=lambda: _LoguruShim(hermes_logger)),
        "core": types.ModuleType("core"),
        "core.providers": types.ModuleType("core.providers"),
        "core.providers.llm": types.ModuleType("core.providers.llm"),
        "core.providers.llm.base": types.SimpleNamespace(LLMProviderBase=object),
    }

    saved: dict[str, Any] = {}
    for name, mod in stubs.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod

    # Pre-load optional sibling modules so hermes.py's fallback `import ha` /
    # `import scene_run` / `import voice_enroll` pick them up cleanly.
    search_dirs = [provider_dir, *[Path(d) for d in extra_dirs]]
    sibling_names = ("ha", "scene_run", "voice_enroll")
    loaded_siblings: list[str] = []
    for sib in sibling_names:
        sib_path = next((d / f"{sib}.py" for d in search_dirs if (d / f"{sib}.py").is_file()), None)
        if sib_path is not None:
            saved[sib] = sys.modules.get(sib)
            _load_file_module(sib, sib_path)
            loaded_siblings.append(sib)

    try:
        module = _load_file_module("xiaoqi_hermes_provider", hermes_path)
    finally:
        for name in (*stubs.keys(), *loaded_siblings):
            prev = saved.get(name)
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev

    log.info("Loaded Hermes provider from %s (siblings: %s)", hermes_path, ", ".join(loaded_siblings) or "none")
    return module.LLMProvider(config)


class DirectOpenAIProvider:
    """Minimal fallback OpenAI-compatible SSE provider when hermes.py is absent."""

    def __init__(self, config: dict[str, Any]):
        self.base_url = (config.get("base_url") or config.get("url") or "http://hermes:8642/v1").rstrip("/")
        self.api_key = str(config.get("api_key") or "")
        self.model_name = str(config.get("model_name") or "xiaoqi-home")
        self.temperature = config.get("temperature")
        self.max_tokens = config.get("max_tokens")
        timeout = config.get("timeout") if isinstance(config.get("timeout"), dict) else {}
        self.client = httpx.Client(
            timeout=httpx.Timeout(
                connect=timeout.get("connect", 3.0),
                read=timeout.get("read", 90.0),
                write=10.0,
                pool=5.0,
            )
        )

    def response(self, session_id: str, dialogue: list[dict[str, Any]], **_kwargs: Any):
        body: dict[str, Any] = {"model": self.model_name, "messages": dialogue, "stream": True}
        if self.temperature not in (None, ""):
            body["temperature"] = float(self.temperature)
        if self.max_tokens not in (None, ""):
            body["max_tokens"] = int(self.max_tokens)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with self.client.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                for choice in data.get("choices") or []:
                    content = (choice.get("delta") or {}).get("content")
                    if content:
                        yield content


class LLMBridge:
    """Bridges synchronous provider.response() generator to async streaming with abort."""

    def __init__(self, provider: Any):
        self.provider = provider

    @classmethod
    def from_config(
        cls,
        provider_dir: Path,
        llm_config: dict[str, Any],
        extra_dirs: tuple[Path, ...] = (),
    ) -> "LLMBridge":
        hermes_file = Path(provider_dir) / "hermes.py"
        if hermes_file.is_file():
            provider = load_hermes_provider(provider_dir, llm_config, extra_dirs=extra_dirs)
        else:
            log.warning("hermes.py not found in %s; falling back to DirectOpenAIProvider", provider_dir)
            provider = DirectOpenAIProvider(llm_config)
        return cls(provider)

    async def stream_reply(
        self,
        session_id: str,
        dialogue: list[dict[str, Any]],
        abort_event: asyncio.Event,
    ) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        out_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        stop_thread = threading.Event()

        def _emit(item: tuple[str, Any]) -> None:
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(out_queue.put_nowait, item)
                except RuntimeError:
                    pass

        def worker() -> None:
            gen = None
            try:
                gen = self.provider.response(session_id, dialogue)
                for chunk in gen:
                    if stop_thread.is_set():
                        break
                    if isinstance(chunk, str) and chunk:
                        _emit(("chunk", chunk))
                _emit(("done", None))
            except Exception as exc:
                if not stop_thread.is_set():
                    _emit(("error", exc))
                else:
                    _emit(("done", None))
            finally:
                if gen is not None and hasattr(gen, "close"):
                    try:
                        gen.close()
                    except Exception:
                        pass

        thread = threading.Thread(target=worker, name=f"llm-{session_id[:8]}", daemon=True)
        thread.start()

        abort_wait = asyncio.create_task(abort_event.wait())
        try:
            while True:
                if abort_event.is_set():
                    stop_thread.set()
                    return
                get_task = asyncio.create_task(out_queue.get())
                done, pending = await asyncio.wait(
                    {get_task, abort_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if abort_wait in done:
                    stop_thread.set()
                    get_task.cancel()
                    return
                kind, payload = get_task.result()
                if kind == "chunk":
                    yield payload
                elif kind == "done":
                    return
                elif kind == "error":
                    raise payload
        finally:
            stop_thread.set()
            abort_wait.cancel()
