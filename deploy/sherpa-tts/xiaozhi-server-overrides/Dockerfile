FROM ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest

COPY voice_devices.py /opt/xiaozhi-esp32-server/core/utils/voice_devices.py
COPY patch_server.py /tmp/patch_server.py
RUN python /tmp/patch_server.py \
    && rm /tmp/patch_server.py
