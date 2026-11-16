package main

import (
	"encoding/json"
	"math"
	"net/http/httptest"
	"strings"
	"testing"
)

// ruleEstimator 는 api/predictors/rule.py 와 같은 공식(10 + 3*km + 2*주문)으로 계약만 확인한다.
type ruleEstimator struct{}

func (ruleEstimator) Estimate(d, o float64) (float64, error) {
	return float64(float32(10 + 3*d + 2*o)), nil
}

func do(t *testing.T, method, path, body, ct string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if ct != "" {
		req.Header.Set("Content-Type", ct)
	}
	rec := httptest.NewRecorder()
	newMux(ruleEstimator{}, "onnx").ServeHTTP(rec, req)
	var out map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	return rec.Code, out
}

const appJSON = "application/json"

// /health 는 200 과 정확히 status, model 두 키를 돌려준다.
func TestHealth(t *testing.T) {
	code, body := do(t, "GET", "/health", "", "")
	if code != 200 || body["status"] != "ok" || body["model"] != "onnx" || len(body) != 2 {
		t.Fatalf("got %d %v", code, body)
	}
}

// /eta 는 알려진 입력에 minutes, model 두 필드를 돌려준다.
func TestEtaKnownValues(t *testing.T) {
	cases := []struct {
		body string
		want float64
	}{
		{`{"distance_km": 2.0, "pending_orders": 1}`, 18},
		{`{"distance_km": 0, "pending_orders": 0}`, 10},
		{`{"distance_km": -0.0, "pending_orders": 0}`, 10},
		{`{"distance_km": 3, "pending_orders": 0}`, 19},
		{`{"distance_km": 1000.0, "pending_orders": 10000}`, 23010},
		{`{"distance_km": 0, "pending_orders": 1000000000000000000000000000000}`, 2e30},
		// Pydantic lax 모드와 같은 강제 변환
		{`{"distance_km": "2", "pending_orders": "1"}`, 18},
		{`{"distance_km": true, "pending_orders": true}`, 15},
		{`{"distance_km": 1, "pending_orders": 1.0}`, 15},
		{`{"distance_km": 1, "pending_orders": 0, "x": 1}`, 13},
	}
	for _, c := range cases {
		code, body := do(t, "POST", "/eta", c.body, appJSON)
		if code != 200 || len(body) != 2 || body["model"] != "onnx" {
			t.Errorf("%s: got %d %v", c.body, code, body)
			continue
		}
		if got := body["minutes"].(float64); math.Abs(got-c.want) > 1e-6*math.Max(1, c.want) {
			t.Errorf("%s: minutes=%v want %v", c.body, got, c.want)
		}
	}
}

// 잘못된 입력은 422 와 FastAPI 형식의 detail 목록을 돌려준다.
func TestEtaInvalidInput422(t *testing.T) {
	cases := []struct{ body, ct string }{
		{`{"distance_km": -1.0, "pending_orders": 0}`, appJSON},
		{`{"distance_km": -0.0001, "pending_orders": 0}`, appJSON},
		{`{"distance_km": 1.0, "pending_orders": -1}`, appJSON},
		{`{"distance_km": "abc", "pending_orders": 0}`, appJSON},
		{`{"distance_km": 1.0, "pending_orders": "many"}`, appJSON},
		{`{"distance_km": 1.0, "pending_orders": 1.5}`, appJSON},
		{`{"distance_km": null, "pending_orders": 0}`, appJSON},
		{`{"distance_km": NaN, "pending_orders": 0}`, appJSON},
		{`{"distance_km": 1e400, "pending_orders": 0}`, appJSON},
		{`{"distance_km": 1e308, "pending_orders": 0}`, appJSON}, // float32 로 넘쳐 inf
		{`{"pending_orders": 0}`, appJSON},
		{`{"distance_km": 1.0}`, appJSON},
		{`{}`, appJSON},
		{`{"distance_km": 1,`, appJSON},
		{`[1, 2]`, appJSON},
		{`{"distance_km": 1, "pending_orders": 0}`, "text/plain"},
	}
	for _, c := range cases {
		code, body := do(t, "POST", "/eta", c.body, c.ct)
		detail, ok := body["detail"].([]any)
		if code != 422 || !ok || len(detail) == 0 {
			t.Errorf("%s (%s): got %d %v", c.body, c.ct, code, body)
		}
	}
}

// 누락된 필드는 loc 에 ["body", 필드명] 으로 표시한다.
func TestEta422PointsToMissingField(t *testing.T) {
	_, body := do(t, "POST", "/eta", `{"pending_orders": 0}`, appJSON)
	b, _ := json.Marshal(body["detail"])
	if !strings.Contains(string(b), `"loc":["body","distance_km"]`) {
		t.Fatalf("detail=%s", b)
	}
}

// GET /eta 는 405, 없는 경로는 404 다.
func TestMethodAndPath(t *testing.T) {
	if code, _ := do(t, "GET", "/eta", "", ""); code != 405 {
		t.Errorf("GET /eta: %d", code)
	}
	if code, _ := do(t, "GET", "/no-such-path", "", ""); code != 404 {
		t.Errorf("404: %d", code)
	}
}
