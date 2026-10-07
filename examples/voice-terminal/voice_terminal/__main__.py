"""python -m voice_terminal {run,devices} ..."""

import argparse
import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import control
from .config import load_config


def _run(args):
    from .audio import FileMicrophone, FileSpeaker, Microphone, Speaker
    from .frontend import Frontend
    from .kws import WakeWordDetector
    from .terminal import Terminal
    from .vad import SpeechDetector

    config = load_config(args.config)
    if args.server:
        config.server.websocket_url = args.server
    if args.control_port is not None:
        config.control.port = args.control_port
    frontend = Frontend(config.audio.frontend)
    wake = None if args.no_wake else WakeWordDetector(config.wake, config.path(config.wake.model_dir))
    config.vad.model = str(config.path(config.vad.model))
    speech = SpeechDetector(config.vad)

    if args.input_file:
        script = [(float(at), path) for at, path in (item.split("@", 1) if "@" in item else ("0", item) for item in args.input_file)]

        def make_mic(on_frame):
            return FileMicrophone(script, frontend, on_frame)
    else:
        def make_mic(on_frame):
            return Microphone(config.audio.input, config.audio.host_api, frontend, on_frame)

    speaker = FileSpeaker(args.output_file) if args.output_file else Speaker(config.audio.output, config.audio.host_api, config.audio.output_gain, config.audio.playback_buffer_ms)
    terminal = Terminal(config, make_mic, speaker, wake, speech)

    async def main():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, terminal.shutdown)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(terminal.shutdown))
        server = None
        if config.control.port:
            server = await control.serve(terminal, config.control.host, config.control.port)
        if args.duration:
            loop.call_later(args.duration, terminal.shutdown)
        try:
            await terminal.run()
        finally:
            if server is not None:
                server.close()
        logging.getLogger(__name__).info("stopped: %s", terminal.status())

    try:
        asyncio.run(main())
    finally:
        frontend.close()
    return 0


def _devices(args):
    from .audio import list_devices

    for index, api, inputs, outputs, rate, name in list_devices(args.host_api):
        print(f"[{index:2d}] {api:<20} in={inputs} out={outputs} rate={rate:.0f}  {name}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="voice_terminal", description="小智语音终端")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the terminal")
    run.add_argument("--config", required=True)
    run.add_argument("--server", help="override [server] websocket_url")
    run.add_argument("--control-port", type=int, help="override [control] port (0 disables)")
    run.add_argument("--no-wake", action="store_true", help="disable the wake word (use /wake or /ask)")
    run.add_argument("--input-file", action="append", metavar="[SECONDS@]WAV",
                     help="test: feed WAV clips instead of the mic (repeatable)")
    run.add_argument("--output-file", metavar="WAV", help="test: record playback to a WAV instead of the speaker")
    run.add_argument("--duration", type=float, help="test: stop after N seconds")
    run.add_argument("--log-file", help="also log to this file (rotated at 1 MB, 5 kept)")
    devices = sub.add_parser("devices", help="list audio devices")
    devices.add_argument("--host-api", default="", help="filter by host API name, e.g. WASAPI")
    args = parser.parse_args(argv)
    handlers = [logging.StreamHandler()]
    if getattr(args, "log_file", None):
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(args.log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        handlers=handlers,
    )
    for noisy in ("websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return _run(args) if args.cmd == "run" else _devices(args)


if __name__ == "__main__":
    sys.exit(main())
