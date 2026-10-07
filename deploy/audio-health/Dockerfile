# Build the ABI3 bridge library and the A113 client; preserve existing model assets.
FROM rust:1.95.0-slim-bookworm AS toolchain
FROM ghcr.io/cross-rs/armv7-unknown-linux-gnueabihf:0.2.5 AS compiler
ENV CARGO_HOME=/root/.cargo RUSTUP_HOME=/root/.rustup PATH=/root/.cargo/bin:$PATH
COPY --from=toolchain /usr/local/cargo/bin /root/.cargo/bin
COPY --from=toolchain /usr/local/rustup /root/.rustup
WORKDIR /src

FROM compiler AS builder
COPY packages/client-rust ./packages/client-rust
COPY examples/xiaozhi/Cargo.toml examples/xiaozhi/Cargo.lock ./examples/xiaozhi/
COPY examples/xiaozhi/src ./examples/xiaozhi/src
ENV PYO3_NO_PYTHON=1
RUN --mount=type=cache,target=/root/.cargo/registry \
    cargo build -j 2 --locked --release --manifest-path examples/xiaozhi/Cargo.toml

FROM compiler AS speaker
RUN rustup target add armv7-unknown-linux-gnueabihf
COPY packages/client-rust /src
ENV CARGO_TARGET_ARMV7_UNKNOWN_LINUX_GNUEABIHF_LINKER=arm-linux-gnueabihf-gcc
RUN --mount=type=cache,target=/root/.cargo/registry \
    cargo build -j 2 --locked --release --target armv7-unknown-linux-gnueabihf --bin client

FROM local/open-xiaoai-xiaozhi:smooth-audio AS runtime
COPY --from=builder /src/examples/xiaozhi/target/release/libopen_xiaoai_server.so /app/.venv/lib/python3.12/site-packages/open_xiaoai_server/open_xiaoai_server.abi3.so
COPY examples/xiaozhi/xiaozhi/services/audio/health.py /app/xiaozhi/services/audio/health.py
COPY examples/xiaozhi/xiaozhi/xiaoai.py /app/xiaozhi/xiaoai.py
COPY examples/xiaozhi/xiaozhi/event.py /app/xiaozhi/event.py
COPY examples/xiaozhi/xiaozhi/services/audio/kws/__init__.py /app/xiaozhi/services/audio/kws/__init__.py
COPY examples/xiaozhi/xiaozhi/services/audio/kws/sherpa.py /app/xiaozhi/services/audio/kws/sherpa.py
ENV OPEN_XIAOAI_HEALTH_LOG=/app/logs/audio-health.jsonl

FROM scratch AS client-artifact
COPY --from=speaker /src/target/armv7-unknown-linux-gnueabihf/release/client /client
