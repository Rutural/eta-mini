//! api/app.py 의 EtaRequest(Pydantic 기본 lax 모드)와 같은 규칙으로 POST /eta 본문을 검증한다.
//!
//! axum 의 `Json` 추출기는 형식 오류에 400·415 를 돌려주므로 쓰지 않고, 본문을 직접 파싱해
//! 모든 입력 오류를 FastAPI 와 같은 422 `{"detail": [...]}` 로 맞춘다.
//!
//! - Content-Type 이 없거나 JSON 계열(application/json, application/*+json)이어야 한다
//! - 본문은 JSON 객체여야 한다. 깨진 JSON 도 422
//! - distance_km: 숫자, 숫자 문자열, bool → float, 유한, >= 0
//! - pending_orders: 정수, 소수부 0 인 실수, 정수 문자열, bool → int, >= 0
//! - 정의되지 않은 필드는 무시한다

use serde::Serialize;
use serde_json::{Map, Number, Value, json};

/// FastAPI 422 응답의 detail 항목과 같은 모양.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ValidationError {
    pub loc: Vec<Value>,
    pub msg: String,
    #[serde(rename = "type")]
    pub typ: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input: Option<Value>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EtaRequest {
    pub distance_km: f64,
    /// 정수만 허용하지만 10**30 같은 큰 값도 받으므로 f64 로 보관한다.
    pub pending_orders: f64,
}

const DICT_MSG: &str = "Input should be a valid dictionary or object to extract fields from";

struct FieldError {
    msg: &'static str,
    typ: &'static str,
}

const FLOAT_TYPE: FieldError = FieldError { msg: "Input should be a valid number", typ: "float_type" };
const FLOAT_PARSING: FieldError = FieldError {
    msg: "Input should be a valid number, unable to parse string as a number",
    typ: "float_parsing",
};
const FINITE_NUMBER: FieldError = FieldError { msg: "Input should be a finite number", typ: "finite_number" };
const INT_TYPE: FieldError = FieldError { msg: "Input should be a valid integer", typ: "int_type" };
const INT_PARSING: FieldError = FieldError {
    msg: "Input should be a valid integer, unable to parse string as an integer",
    typ: "int_parsing",
};
const INT_FRACTION: FieldError = FieldError {
    msg: "Input should be a valid integer, got a number with a fractional part",
    typ: "int_from_float",
};

fn err(loc: Vec<Value>, msg: &str, typ: &str, input: Option<Value>) -> ValidationError {
    // null 입력은 Go 구현(omitempty)과 같이 input 을 생략한다.
    let input = input.filter(|v| !v.is_null());
    ValidationError { loc, msg: msg.to_string(), typ: typ.to_string(), input }
}

fn json_invalid() -> ValidationError {
    err(vec![json!("body"), json!(0)], "JSON decode error", "json_invalid", None)
}

pub fn is_json_content_type(ct: &str) -> bool {
    let mt = ct.split(';').next().unwrap_or("").trim().to_ascii_lowercase();
    match mt.split_once('/') {
        Some(("application", sub)) => sub == "json" || (sub.ends_with("+json") && sub.len() > 5),
        _ => false,
    }
}

/// 요청 본문을 검증한다. `content_type` 은 Content-Type 헤더 값(없으면 None).
pub fn parse_eta_request(content_type: Option<&str>, body: &[u8]) -> Result<EtaRequest, Vec<ValidationError>> {
    if let Some(ct) = content_type.filter(|ct| !ct.is_empty()) {
        if !is_json_content_type(ct) {
            // FastAPI 는 JSON 이 아닌 본문을 객체로 해석하지 못해 model_attributes_type 422 를 낸다.
            let input = Value::String(String::from_utf8_lossy(body).into_owned());
            return Err(vec![err(vec![json!("body")], DICT_MSG, "model_attributes_type", Some(input))]);
        }
    }

    let raw: Value = serde_json::from_slice(body).map_err(|_| vec![json_invalid()])?;
    let obj: &Map<String, Value> = match &raw {
        Value::Object(m) => m,
        other => {
            return Err(vec![err(vec![json!("body")], DICT_MSG, "model_attributes_type", Some(other.clone()))]);
        }
    };

    let mut errs = Vec::new();
    let distance_km = check_field(obj, "distance_km", parse_float, &mut errs);
    let pending_orders = check_field(obj, "pending_orders", parse_int, &mut errs);

    match (distance_km, pending_orders) {
        (Some(distance_km), Some(pending_orders)) if errs.is_empty() => Ok(EtaRequest { distance_km, pending_orders }),
        _ => Err(errs),
    }
}

fn check_field(
    obj: &Map<String, Value>,
    field: &str,
    parse: fn(&Value) -> Result<f64, FieldError>,
    errs: &mut Vec<ValidationError>,
) -> Option<f64> {
    let loc = vec![json!("body"), json!(field)];
    let Some(v) = obj.get(field) else {
        errs.push(err(loc, "Field required", "missing", None));
        return None;
    };
    match parse(v) {
        Err(e) => {
            errs.push(err(loc, e.msg, e.typ, Some(v.clone())));
            None
        }
        Ok(f) if f < 0.0 => {
            errs.push(err(loc, "Input should be greater than or equal to 0", "greater_than_equal", Some(v.clone())));
            None
        }
        Ok(f) => Some(f),
    }
}

fn finite(f: f64) -> Result<f64, FieldError> {
    if f.is_finite() { Ok(f) } else { Err(FINITE_NUMBER) }
}

fn parse_float(v: &Value) -> Result<f64, FieldError> {
    match v {
        // 1e400 처럼 f64 범위를 넘는 값은 inf 로 파싱되어 finite_number 가 된다.
        Value::Number(n) => finite(number_text(n).parse::<f64>().map_err(|_| FINITE_NUMBER)?),
        Value::String(s) => finite(s.trim().parse::<f64>().map_err(|_| FLOAT_PARSING)?),
        Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
        _ => Err(FLOAT_TYPE), // null, 배열, 객체
    }
}

/// 정수 값을 돌려준다. 큰 정수(10**30)도 받아들이므로 f64 로 돌려준다.
fn parse_int(v: &Value) -> Result<f64, FieldError> {
    match v {
        Value::Number(n) => {
            let s = number_text(n);
            if !s.contains(['.', 'e', 'E']) {
                return int_text_to_f64(&s).ok_or(INT_TYPE);
            }
            let f = s.parse::<f64>().map_err(|_| FINITE_NUMBER)?;
            let f = finite(f)?;
            if f != f.trunc() {
                return Err(INT_FRACTION);
            }
            Ok(f)
        }
        Value::String(s) => int_text_to_f64(s.trim()).ok_or(INT_PARSING),
        Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
        _ => Err(INT_TYPE),
    }
}

/// arbitrary_precision 기능 덕분에 JSON 원문 그대로의 숫자 표기를 얻는다.
fn number_text(n: &Number) -> String {
    n.to_string()
}

/// 부호(선택) + 10진 숫자만으로 된 문자열을 f64 로 바꾼다. 아니면 None.
fn int_text_to_f64(s: &str) -> Option<f64> {
    let digits = s.strip_prefix(['+', '-']).unwrap_or(s);
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let f = s.parse::<f64>().ok()?;
    Some(if f == 0.0 { 0.0 } else { f }) // -0 → 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(body: &str) -> Result<EtaRequest, Vec<ValidationError>> {
        parse_eta_request(Some("application/json"), body.as_bytes())
    }

    fn types(body: &str) -> Vec<String> {
        parse(body).unwrap_err().into_iter().map(|e| e.typ).collect()
    }

    #[test]
    fn accepts_valid_body() {
        let r = parse(r#"{"distance_km": 2.5, "pending_orders": 3, "extra": 1}"#).unwrap();
        assert_eq!(r, EtaRequest { distance_km: 2.5, pending_orders: 3.0 });
    }

    #[test]
    fn accepts_lax_coercions() {
        let r = parse(r#"{"distance_km": " 1.5 ", "pending_orders": "4"}"#).unwrap();
        assert_eq!(r, EtaRequest { distance_km: 1.5, pending_orders: 4.0 });
        let r = parse(r#"{"distance_km": true, "pending_orders": 2.0}"#).unwrap();
        assert_eq!(r, EtaRequest { distance_km: 1.0, pending_orders: 2.0 });
    }

    #[test]
    fn accepts_zero_and_large_values() {
        let r = parse(r#"{"distance_km": 0, "pending_orders": 0}"#).unwrap();
        assert_eq!(r, EtaRequest { distance_km: 0.0, pending_orders: 0.0 });
        let r = parse(r#"{"distance_km": 1e300, "pending_orders": 1000000000000000000000000000000}"#).unwrap();
        assert_eq!(r.pending_orders, 1e30);
    }

    #[test]
    fn rejects_negative() {
        assert_eq!(types(r#"{"distance_km": -1, "pending_orders": -1}"#), ["greater_than_equal", "greater_than_equal"]);
    }

    #[test]
    fn rejects_wrong_types() {
        assert_eq!(types(r#"{"distance_km": "abc", "pending_orders": "x"}"#), ["float_parsing", "int_parsing"]);
        assert_eq!(types(r#"{"distance_km": null, "pending_orders": [1]}"#), ["float_type", "int_type"]);
        assert_eq!(types(r#"{"distance_km": 1e400, "pending_orders": 1.5}"#), ["finite_number", "int_from_float"]);
        assert_eq!(types(r#"{"distance_km": "inf", "pending_orders": 1e400}"#), ["finite_number", "finite_number"]);
    }

    #[test]
    fn rejects_missing_and_malformed() {
        assert_eq!(types(r#"{}"#), ["missing", "missing"]);
        assert_eq!(types(r#"{"distance_km": 1,"#), ["json_invalid"]);
        assert_eq!(types(r#"{"distance_km": 1, "pending_orders": 1} x"#), ["json_invalid"]);
        assert_eq!(types(""), ["json_invalid"]);
        assert_eq!(types("[1, 2]"), ["model_attributes_type"]);
    }

    #[test]
    fn content_type_rules() {
        let body = br#"{"distance_km": 1, "pending_orders": 1}"#;
        assert!(parse_eta_request(None, body).is_ok());
        assert!(parse_eta_request(Some("application/json; charset=utf-8"), body).is_ok());
        assert!(parse_eta_request(Some("application/merge-patch+json"), body).is_ok());
        let e = parse_eta_request(Some("text/plain"), body).unwrap_err();
        assert_eq!(e[0].typ, "model_attributes_type");
    }
}
