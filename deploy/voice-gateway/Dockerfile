FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# Only libopus0 (~200 KB) is needed at the OS layer; PyAV ships its own FFmpeg
# libraries in-wheel for streaming MP3 decoding without spawning subprocesses.
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install --no-cache-dir --only-binary=av -r /app/requirements.txt \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY gateway /app/gateway

EXPOSE 8000 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=3)" || exit 1

CMD ["python", "-m", "gateway.main"]
