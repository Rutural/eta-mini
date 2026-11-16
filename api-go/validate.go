package main

import (
	"bytes"
	"encoding/json"
	"io"
	"math"
	"math/big"
	"mime"
	"net/http"
	"strconv"
	"strings"
)

// validationError 는 FastAPI 422 응답의 detail 항목과 같은 모양이다.
type validationError struct {
	Loc   []any  `json:"loc"`
	Msg   string `json:"msg"`
	Type  string `json:"type"`
	Input any    `json:"input,omitempty"`
}

type etaRequest struct {
	DistanceKm    float64
	PendingOrders float64 // 정수만 허용하지만 10**30 같은 큰 값도 받으므로 float64 로 보관한다
}

const maxBody = 1 << 20

// parseEtaRequest 는 api/app.py 의 EtaRequest(Pydantic 기본 lax 모드)와 같은 규칙으로 본문을 검증한다.
//   - Content-Type 이 없거나 JSON 계열이어야 한다 (아니면 422)
//   - 본문은 JSON 객체여야 한다. 깨진 JSON 도 422
//   - distance_km: 숫자, 숫자 문자열, bool → float, >= 0
//   - pending_orders: 정수, 소수부 0 인 실수, 정수 문자열, bool → int, >= 0
//   - 정의되지 않은 필드는 무시한다
func parseEtaRequest(r *http.Request) (etaRequest, []validationError) {
	var req etaRequest
	body, err := io.ReadAll(io.LimitReader(r.Body, maxBody))
	if err != nil {
		return req, []validationError{{Loc: []any{"body"}, Msg: "Could not read body", Type: "body_read_error"}}
	}

	if ct := r.Header.Get("Content-Type"); ct != "" && !isJSONContentType(ct) {
		// FastAPI 는 JSON 이 아닌 본문을 객체로 해석하지 못해 model_attributes_type 422 를 낸다.
		return req, []validationError{{Loc: []any{"body"}, Msg: "Input should be a valid dictionary or object to extract fields from", Type: "model_attributes_type", Input: string(body)}}
	}

	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber()
	var raw any
	if err := dec.Decode(&raw); err != nil || dec.More() {
		return req, []validationError{{Loc: []any{"body", 0}, Msg: "JSON decode error", Type: "json_invalid"}}
	}
	if _, err := dec.Token(); err != io.EOF {
		return req, []validationError{{Loc: []any{"body", 0}, Msg: "JSON decode error", Type: "json_invalid"}}
	}
	obj, ok := raw.(map[string]any)
	if !ok {
		return req, []validationError{{Loc: []any{"body"}, Msg: "Input should be a valid dictionary or object to extract fields from", Type: "model_attributes_type", Input: raw}}
	}

	var errs []validationError
	if v, present := obj["distance_km"]; !present {
		errs = append(errs, missing("distance_km"))
	} else if f, e := parseFloat(v); e != nil {
		errs = append(errs, *e.at("distance_km", v))
	} else if f < 0 {
		errs = append(errs, validationError{Loc: []any{"body", "distance_km"}, Msg: "Input should be greater than or equal to 0", Type: "greater_than_equal", Input: v})
	} else {
		req.DistanceKm = f
	}

	if v, present := obj["pending_orders"]; !present {
		errs = append(errs, missing("pending_orders"))
	} else if n, e := parseInt(v); e != nil {
		errs = append(errs, *e.at("pending_orders", v))
	} else if n < 0 {
		errs = append(errs, validationError{Loc: []any{"body", "pending_orders"}, Msg: "Input should be greater than or equal to 0", Type: "greater_than_equal", Input: v})
	} else {
		req.PendingOrders = n
	}
	return req, errs
}

func isJSONContentType(ct string) bool {
	mt, _, err := mime.ParseMediaType(ct)
	if err != nil {
		return false
	}
	typ, sub, ok := strings.Cut(mt, "/")
	return ok && typ == "application" && (sub == "json" || strings.HasSuffix(sub, "+json"))
}

func missing(field string) validationError {
	return validationError{Loc: []any{"body", field}, Msg: "Field required", Type: "missing"}
}

type fieldError struct{ msg, typ string }

func (e *fieldError) at(field string, input any) *validationError {
	return &validationError{Loc: []any{"body", field}, Msg: e.msg, Type: e.typ, Input: input}
}

var (
	errFloatType    = &fieldError{"Input should be a valid number", "float_type"}
	errFloatParsing = &fieldError{"Input should be a valid number, unable to parse string as a number", "float_parsing"}
	errFiniteNumber = &fieldError{"Input should be a finite number", "finite_number"}
	errIntType      = &fieldError{"Input should be a valid integer", "int_type"}
	errIntParsing   = &fieldError{"Input should be a valid integer, unable to parse string as an integer", "int_parsing"}
	errIntFraction  = &fieldError{"Input should be a valid integer, got a number with a fractional part", "int_from_float"}
)

func parseFloat(v any) (float64, *fieldError) {
	var f float64
	switch x := v.(type) {
	case json.Number:
		var err error
		if f, err = strconv.ParseFloat(string(x), 64); err != nil {
			return 0, errFiniteNumber // 1e400 처럼 float64 범위를 넘는 값
		}
	case string:
		var err error
		if f, err = strconv.ParseFloat(strings.TrimSpace(x), 64); err != nil {
			return 0, errFloatParsing
		}
	case bool:
		if x {
			f = 1
		}
	default: // null, 배열, 객체
		return 0, errFloatType
	}
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return 0, errFiniteNumber
	}
	return f, nil
}

// parseInt 는 정수 값을 돌려준다. 큰 정수(10**30)도 받아들이므로 float64 로 돌려준다.
func parseInt(v any) (float64, *fieldError) {
	switch x := v.(type) {
	case json.Number:
		s := string(x)
		if !strings.ContainsAny(s, ".eE") {
			return bigIntToFloat(s, errIntType)
		}
		f, err := strconv.ParseFloat(s, 64)
		if err != nil || math.IsInf(f, 0) {
			return 0, errFiniteNumber
		}
		if f != math.Trunc(f) {
			return 0, errIntFraction
		}
		return f, nil
	case string:
		return bigIntToFloat(strings.TrimSpace(x), errIntParsing)
	case bool:
		if x {
			return 1, nil
		}
		return 0, nil
	default:
		return 0, errIntType
	}
}

func bigIntToFloat(s string, onErr *fieldError) (float64, *fieldError) {
	n, ok := new(big.Int).SetString(s, 10)
	if !ok {
		return 0, onErr
	}
	f, _ := new(big.Float).SetInt(n).Float64()
	return f, nil
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
