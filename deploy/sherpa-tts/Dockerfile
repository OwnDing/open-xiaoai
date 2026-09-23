FROM python:3.11-slim

ARG MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-zh_CN-xiao_ya-medium.tar.bz2"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SHERPA_MODEL_DIR=/models/vits-piper-zh_CN-xiao_ya-medium

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install -r /app/requirements.txt \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN mkdir -p /models \
    && MODEL_URL="$MODEL_URL" python -c "import os, tarfile, urllib.request; url=os.environ['MODEL_URL']; archive='/tmp/model.tar.bz2'; urllib.request.urlretrieve(url, archive); tarfile.open(archive, 'r:bz2').extractall('/models'); os.remove(archive)"

COPY server.py /app/server.py
WORKDIR /app

EXPOSE 11996

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11996/health', timeout=3)" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "11996", "--workers", "1"]
