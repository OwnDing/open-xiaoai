FROM ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest

COPY patch_index_stream.py /tmp/patch_index_stream.py
RUN python /tmp/patch_index_stream.py \
    && rm /tmp/patch_index_stream.py
