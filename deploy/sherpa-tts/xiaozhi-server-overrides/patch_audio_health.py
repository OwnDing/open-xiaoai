"""Idempotent diagnostics hooks for both a fresh and an existing backend image."""
from pathlib import Path


def patch(root=Path('/opt/xiaozhi-esp32-server')):
    path = root / 'core/connection.py'
    source = path.read_text(encoding='utf-8')
    marker = 'from core.utils.audio_health import handle_health, count_audio'
    if marker in source:
        return
    text = '        if isinstance(message, str):\n            await handleTextMessage(self, message)'
    binary = '        elif isinstance(message, bytes):\n'
    if source.count(text) != 1 or source.count(binary) != 1:
        raise RuntimeError('audio-health routing anchors changed; refusing partial patch')
    source = marker + '\n' + source
    source = source.replace(text, '        if isinstance(message, str):\n            if handle_health(self, message):\n                return\n            await handleTextMessage(self, message)')
    source = source.replace(binary, binary + '            count_audio(self, message)\n')
    compile(source, str(path), 'exec')
    path.write_text(source, encoding='utf-8')


if __name__ == '__main__':
    patch()
