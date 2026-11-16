// delivery-eta 의 Go 구현. api/app.py 와 같은 계약(GET /health, POST /eta)을 따른다.
//
// 예측은 ONNX 모델(입력 "X" [1, 2] float32 → 출력 "variable")을 ONNX Runtime 으로 실행한다.
// 정규화는 모델 안에 있으므로 원래 단위의 값을 그대로 넣는다.
//
// 환경 변수
//
//	PORT          듣는 포트 (기본 8080)
//	MODEL_PATH    ONNX 모델 경로 (기본 artifacts/model_sklearn.onnx)
//	ORT_LIB_PATH  libonnxruntime 공유 라이브러리 경로 (기본 /usr/local/lib/libonnxruntime.so)
//	MODEL_IMPL    /health, /eta 의 model 필드 값 (기본 onnx)
package main

import (
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"strings"
)

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	modelName := getenv("MODEL_IMPL", "onnx")
	pred, err := NewPredictor(
		getenv("ORT_LIB_PATH", "/usr/local/lib/libonnxruntime.so"),
		getenv("MODEL_PATH", "artifacts/model_sklearn.onnx"),
	)
	if err != nil {
		log.Fatalf("모델 로드 실패: %v", err)
	}
	defer pred.Close()

	addr := ":" + getenv("PORT", "8080")
	log.Printf("delivery-eta (go, model=%s) listening on %s", modelName, addr)
	log.Fatal(http.ListenAndServe(addr, newMux(pred, modelName)))
}

// estimator 는 테스트에서 가짜 구현으로 바꿀 수 있게 예측 함수를 추상화한다.
type estimator interface {
	Estimate(distanceKm float64, pendingOrders float64) (float64, error)
}

func newMux(est estimator, modelName string) *http.ServeMux {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, strings.ReplaceAll(indexHTML, "{model}", modelName))
	})

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "model": modelName})
	})

	mux.HandleFunc("POST /eta", func(w http.ResponseWriter, r *http.Request) {
		req, errs := parseEtaRequest(r)
		if len(errs) > 0 {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]any{"detail": errs})
			return
		}
		minutes, err := est.Estimate(req.DistanceKm, req.PendingOrders)
		if err != nil {
			log.Printf("예측 실패: %v", err)
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "prediction failed"})
			return
		}
		if math.IsNaN(minutes) || math.IsInf(minutes, 0) {
			// float32 범위를 넘는 입력은 모델 출력이 inf 가 된다. null/500 대신 422 로 거부한다.
			writeJSON(w, http.StatusUnprocessableEntity, map[string]any{"detail": []validationError{{
				Loc:  []any{"body"},
				Msg:  "Input values are too large to compute a finite estimate",
				Type: "value_error",
			}}})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"minutes": minutes, "model": modelName})
	})

	return mux
}

const indexHTML = `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>delivery-eta API</title>
</head>
<body>
  <h1>delivery-eta API (Go)</h1>
  <p>거리와 밀린 주문 수로 배달 예상 시간(분)을 계산하는 API입니다.</p>
  <p>현재 구현체: <code>{model}</code></p>
  <ul>
    <li>GET <a href="/health">/health</a> — 서비스 상태와 구현체 이름</li>
    <li>POST /eta — <code>{"distance_km": 2.0, "pending_orders": 1}</code> → <code>{"minutes": ..., "model": "{model}"}</code></li>
  </ul>
</body>
</html>
`
