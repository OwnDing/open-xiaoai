# ==============================
# 构建阶段：多架构兼容、精简、提速
# ==============================
FROM python:3.12-slim AS builder

# 固定 shell，减少层
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# 统一安装依赖（一次性 RUN，减少镜像层数）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Rust（静默安装，自动添加环境）
ENV CARGO_HOME=/root/.cargo \
    PATH=/root/.cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path

# 安装固定主版本的 uv，避免构建依赖额外的 GHCR 凭据助手。
RUN python -m pip install --no-cache-dir "uv>=0.7,<0.8"

# 工作目录
WORKDIR /app

# 复制项目文件
COPY examples/xiaozhi .
COPY packages/client-rust ./client-rust

# 修复 Cargo 路径
RUN sed -i 's/\.\.\/\.\.\/packages\///g' Cargo.toml

# 构建 Rust（缓存加速）
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    cargo build --release

# Python 依赖安装（uv 缓存）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv remove pyaudio && uv sync --locked --no-install-project --no-editable

# 编译 maturin 并清理
RUN --mount=type=cache,target=/root/.cache/uv \
    uv run maturin build --release && uv remove maturin

# ==============================
# 运行阶段：极小体积、安全、跨架构
# ==============================
FROM python:3.12-slim

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

WORKDIR /app

# 运行时依赖（最小化）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopus-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 自动识别架构
ARG TARGETARCH
ENV CLI=true \
    LD_LIBRARY_PATH=/usr/local/lib:/app/.venv/lib/python3.12/site-packages/onnxruntime/capi

# 复制构建产物
COPY --from=builder /app/.venv /app/.venv
COPY examples/xiaozhi/main.py .
COPY examples/xiaozhi/xiaozhi ./xiaozhi

# 自动下载对应架构的 onnxruntime
RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64)  ort_arch="aarch64" ;; \
      amd64)  ort_arch="x64" ;; \
      *) echo "不支持的架构: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/microsoft/onnxruntime/releases/download/v1.23.2/onnxruntime-linux-${ort_arch}-1.23.2.tgz" -o /tmp/ort.tgz; \
    tar -xzf /tmp/ort.tgz -C /tmp; \
    cp /tmp/onnxruntime-linux-${ort_arch}-1.23.2/lib/libonnxruntime.so.1.23.2 /usr/local/lib/; \
    ln -sf libonnxruntime.so.1.23.2 /usr/local/lib/libonnxruntime.so; \
    ldconfig; \
    rm -rf /tmp/ort.tgz /tmp/onnxruntime-linux-${ort_arch}-1.23.2

# 启动命令（精简、直接）
CMD ["/bin/bash", "-c", "source /app/.venv/bin/activate && python xiaozhi/services/audio/kws/keywords.py && exec python main.py"]
