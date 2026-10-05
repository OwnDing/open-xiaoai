FROM ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest

COPY voice_devices.py /opt/xiaozhi-esp32-server/core/utils/voice_devices.py
COPY edge_stream.py /opt/xiaozhi-esp32-server/core/providers/tts/edge_stream.py
COPY patch_server.py /tmp/patch_server.py
RUN python /tmp/patch_server.py \
    && rm /tmp/patch_server.py

COPY audio_health.py /opt/xiaozhi-esp32-server/core/utils/audio_health.py
COPY patch_audio_health.py /tmp/patch_audio_health.py
RUN python /tmp/patch_audio_health.py && rm /tmp/patch_audio_health.py
