# 빌드 컨텍스트는 저장소 루트다.
#   docker build -f api-rust/Dockerfile -t delivery-eta-rust .
#   docker run --rm -p 8082:8080 delivery-eta-rust

# ---------- ONNX Runtime 내려받기 ----------
FROM debian:bookworm-slim AS ort
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*

# 버전은 uv.lock 의 onnxruntime 버전을 그대로 쓴다 (Python 쪽과 같은 런타임).
COPY uv.lock /tmp/uv.lock
RUN set -eu; \
    ORT_VERSION="$(awk '/^name = "onnxruntime"$/ { getline; gsub(/^version = "|"$/, ""); print; exit }' /tmp/uv.lock)"; \
    test -n "$ORT_VERSION" || { echo "uv.lock 에서 onnxruntime 버전을 찾지 못했다" >&2; exit 1; }; \
    case "${TARGETARCH:-amd64}" in \
      amd64) ORT_ARCH=x64 ;; \
      arm64) ORT_ARCH=aarch64 ;; \
      *) echo "지원하지 않는 TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    echo "ONNX Runtime ${ORT_VERSION} (${ORT_ARCH})"; \
    curl -fsSL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/onnxruntime-linux-${ORT_ARCH}-${ORT_VERSION}.tgz" \
      | tar -xz -C /tmp; \
    mkdir -p /opt/ort; \
    cp -a /tmp/onnxruntime-linux-${ORT_ARCH}-${ORT_VERSION}/lib/libonnxruntime.so* /opt/ort/

# ---------- 빌드 ----------
FROM rust:1-bookworm AS build
WORKDIR /src
# 의존성만 먼저 빌드해 캐시한다.
COPY api-rust/Cargo.toml api-rust/Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs && cargo build --release --locked && rm -rf src
COPY api-rust/src ./src
# ort 는 load-dynamic 이라 빌드 중에 ONNX Runtime 을 내려받거나 링크하지 않는다.
RUN touch src/main.rs && cargo test --release --locked && cargo build --release --locked

# ---------- 실행 ----------
FROM debian:bookworm-slim
COPY --from=ort /opt/ort/ /usr/local/lib/
COPY --from=build /src/target/release/api-rust /usr/local/bin/api-rust
COPY artifacts/model_sklearn.onnx /app/artifacts/model_sklearn.onnx

WORKDIR /app
ENV ORT_LIB=/usr/local/lib/libonnxruntime.so \
    MODEL_PATH=/app/artifacts/model_sklearn.onnx \
    PORT=8080
USER nobody
EXPOSE 8080
CMD ["/usr/local/bin/api-rust"]
