//! delivery-eta 의 Rust 구현. api/app.py 와 같은 계약(GET /health, POST /eta)을 따른다.
//!
//! 예측은 ONNX 모델(입력 "X" [1, 2] float32 → 출력 "variable")을 ONNX Runtime 으로 실행한다.
//! 정규화는 모델 안에 있으므로 원래 단위의 값을 그대로 넣는다.
//!
//! 환경 변수
//!   PORT        듣는 포트 (기본 8080)
//!   MODEL_PATH  ONNX 모델 경로 (기본 artifacts/model_sklearn.onnx)
//!   ORT_LIB     libonnxruntime 공유 라이브러리 경로 (기본 /usr/local/lib/libonnxruntime.so)
//!   MODEL_IMPL  /health, /eta 의 model 필드 값 (기본 onnx)

mod predictor;
mod validate;

use std::sync::Arc;

use axum::{
    Json, Router,
    body::{Body, to_bytes},
    extract::State,
    http::{StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use serde_json::json;

use predictor::Predictor;
use validate::{ValidationError, parse_eta_request};

const MAX_BODY: usize = 1 << 20;

/// 테스트에서 가짜 구현으로 바꿀 수 있게 예측 함수를 추상화한다.
pub trait Estimator: Send + Sync + 'static {
    fn estimate(&self, distance_km: f64, pending_orders: f64) -> Result<f64, String>;
}

struct AppState {
    est: Box<dyn Estimator>,
    model_name: String,
}

fn getenv(key: &str, default: &str) -> String {
    std::env::var(key).ok().filter(|v| !v.is_empty()).unwrap_or_else(|| default.to_string())
}

#[tokio::main]
async fn main() {
    let model_name = getenv("MODEL_IMPL", "onnx");
    let pred = match Predictor::new(
        &getenv("ORT_LIB", "/usr/local/lib/libonnxruntime.so"),
        &getenv("MODEL_PATH", "artifacts/model_sklearn.onnx"),
    ) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("모델 로드 실패: {e}");
            std::process::exit(1);
        }
    };

    let addr = format!("0.0.0.0:{}", getenv("PORT", "8080"));
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("포트를 열 수 없다");
    eprintln!("delivery-eta (rust, model={model_name}) listening on {addr}");
    axum::serve(listener, app(Box::new(pred), model_name))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .expect("서버 오류");
}

fn app(est: Box<dyn Estimator>, model_name: String) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/health", get(health))
        .route("/eta", post(eta))
        .with_state(Arc::new(AppState { est, model_name }))
}

async fn index(State(s): State<Arc<AppState>>) -> Html<String> {
    Html(INDEX_HTML.replace("{model}", &s.model_name))
}

async fn health(State(s): State<Arc<AppState>>) -> Response {
    Json(json!({"status": "ok", "model": s.model_name})).into_response()
}

fn unprocessable(errs: Vec<ValidationError>) -> Response {
    (StatusCode::UNPROCESSABLE_ENTITY, Json(json!({ "detail": errs }))).into_response()
}

async fn eta(State(s): State<Arc<AppState>>, req: axum::extract::Request) -> Response {
    let content_type = req
        .headers()
        .get(header::CONTENT_TYPE)
        .map(|v| String::from_utf8_lossy(v.as_bytes()).into_owned());
    let body = match to_bytes(Body::new(req.into_body()), MAX_BODY).await {
        Ok(b) => b,
        Err(_) => {
            return unprocessable(vec![ValidationError {
                loc: vec![json!("body")],
                msg: "Could not read body".into(),
                typ: "body_read_error".into(),
                input: None,
            }]);
        }
    };

    let r = match parse_eta_request(content_type.as_deref(), &body) {
        Ok(r) => r,
        Err(errs) => return unprocessable(errs),
    };

    match s.est.estimate(r.distance_km, r.pending_orders) {
        Err(e) => {
            eprintln!("예측 실패: {e}");
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"detail": "prediction failed"}))).into_response()
        }
        // float32 범위를 넘는 입력은 모델 출력이 inf 가 된다. null/500 대신 422 로 거부한다.
        Ok(m) if !m.is_finite() => unprocessable(vec![ValidationError {
            loc: vec![json!("body")],
            msg: "Input values are too large to compute a finite estimate".into(),
            typ: "value_error".into(),
            input: None,
        }]),
        Ok(m) => Json(json!({"minutes": m, "model": s.model_name})).into_response(),
    }
}

const INDEX_HTML: &str = r#"<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>delivery-eta API</title>
</head>
<body>
  <h1>delivery-eta API (Rust)</h1>
  <p>거리와 밀린 주문 수로 배달 예상 시간(분)을 계산하는 API입니다.</p>
  <p>현재 구현체: <code>{model}</code></p>
  <ul>
    <li>GET <a href="/health">/health</a> — 서비스 상태와 구현체 이름</li>
    <li>POST /eta — <code>{"distance_km": 2.0, "pending_orders": 1}</code> → <code>{"minutes": ..., "model": "{model}"}</code></li>
  </ul>
</body>
</html>
"#;

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::Request;
    use tower::ServiceExt;

    /// minutes = 10 * distance + pending (계약 검증용 가짜 모델)
    struct Fake;
    impl Estimator for Fake {
        fn estimate(&self, d: f64, o: f64) -> Result<f64, String> {
            Ok(10.0 * d + o)
        }
    }

    async fn call(method: &str, uri: &str, ct: Option<&str>, body: &str) -> (StatusCode, serde_json::Value) {
        let mut b = Request::builder().method(method).uri(uri);
        if let Some(ct) = ct {
            b = b.header(header::CONTENT_TYPE, ct);
        }
        let resp = app(Box::new(Fake), "onnx".into())
            .oneshot(b.body(Body::from(body.to_string())).unwrap())
            .await
            .unwrap();
        let status = resp.status();
        let bytes = to_bytes(resp.into_body(), MAX_BODY).await.unwrap();
        (status, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
    }

    #[tokio::test]
    async fn health_ok() {
        let (st, v) = call("GET", "/health", None, "").await;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(v, json!({"status": "ok", "model": "onnx"}));
    }

    #[tokio::test]
    async fn eta_ok() {
        let (st, v) = call("POST", "/eta", Some("application/json"), r#"{"distance_km": 2, "pending_orders": 1}"#).await;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(v["minutes"].as_f64(), Some(21.0));
        assert_eq!(v["model"], "onnx");
    }

    #[tokio::test]
    async fn input_errors_are_422() {
        for (ct, body) in [
            (Some("application/json"), "{bad"),
            (Some("text/plain"), r#"{"distance_km": 1, "pending_orders": 1}"#),
            (None, r#"{"distance_km": -1, "pending_orders": 1}"#),
            (Some("application/json"), r#"{"distance_km": "x", "pending_orders": 1}"#),
            (Some("application/json"), ""),
        ] {
            let (st, v) = call("POST", "/eta", ct, body).await;
            assert_eq!(st, StatusCode::UNPROCESSABLE_ENTITY, "body={body}");
            assert!(v["detail"].is_array());
        }
    }

    #[tokio::test]
    async fn infinite_estimate_is_422() {
        let (st, _) = call("POST", "/eta", None, r#"{"distance_km": 1e308, "pending_orders": 1}"#).await;
        assert_eq!(st, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn wrong_method_is_405() {
        let (st, _) = call("GET", "/eta", None, "").await;
        assert_eq!(st, StatusCode::METHOD_NOT_ALLOWED);
    }
}
