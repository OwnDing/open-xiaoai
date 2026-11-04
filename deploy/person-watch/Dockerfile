FROM python:3.11-slim

ARG OMZ=https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

COPY requirements.txt /app/requirements.txt
RUN python -m pip install -r /app/requirements.txt \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# Intel Open Model Zoo person detector (Apache-2.0), OpenVINO IR, FP16, 1.8 M parameters.
ADD ${OMZ}/person-detection-0202/FP16/person-detection-0202.xml \
    ${OMZ}/person-detection-0202/FP16/person-detection-0202.bin \
    /models/

COPY *.py /app/
WORKDIR /app

EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1

CMD ["python", "watch.py"]
