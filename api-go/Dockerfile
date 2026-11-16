# 빌드 컨텍스트는 저장소 루트다.
#   docker build -f api-go/Dockerfile -t delivery-eta-go .
#   docker run --rm -p 8081:8080 delivery-eta-go

# ---------- 빌드 ----------
FROM golang:1.25-bookworm AS build
ARG TARGETARCH

# ONNX Runtime: 버전은 uv.lock 의 onnxruntime 버전을 그대로 쓴다 (Python 쪽과 같은 런타임).
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

WORKDIR /src
COPY api-go/go.mod api-go/go.sum ./
RUN go mod download
COPY api-go/*.go ./
# onnxruntime_go 는 cgo 로 libonnxruntime 을 런타임에 dlopen 한다.
RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/api-go .

# ---------- 실행 ----------
FROM debian:bookworm-slim
COPY --from=build /opt/ort/ /usr/local/lib/
COPY --from=build /out/api-go /usr/local/bin/api-go
COPY artifacts/model_sklearn.onnx /app/artifacts/model_sklearn.onnx

WORKDIR /app
ENV ORT_LIB_PATH=/usr/local/lib/libonnxruntime.so \
    MODEL_PATH=/app/artifacts/model_sklearn.onnx \
    PORT=8080
USER nobody
EXPOSE 8080
CMD ["/usr/local/bin/api-go"]
