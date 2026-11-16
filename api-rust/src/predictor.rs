//! ONNX 모델 실행. ort 의 load-dynamic 기능으로 ONNX Runtime 공유 라이브러리를 실행 중에 연다.

use std::sync::Mutex;

use ort::{environment::Environment, session::Session, value::Tensor};

use crate::Estimator;

pub struct Predictor {
    // Session::run 이 &mut self 를 요구하므로 Mutex 로 감싼다. 모델이 작아 경합 비용은 무시할 만하다.
    // 필드는 선언 순서대로 해제되므로 세션이 환경보다 먼저 해제된다.
    session: Mutex<Session>,
    _env: Environment,
}

impl Predictor {
    pub fn new(lib_path: &str, model_path: &str) -> Result<Self, String> {
        let env = ort::init_from(lib_path)
            .map_err(|e| format!("ONNX Runtime 로드 ({lib_path}): {e}"))?
            .with_name("delivery-eta")
            .build()
            .map_err(|e| format!("ONNX Runtime 환경 생성: {e}"))?;
        let session = Session::builder(&env)
            .and_then(|mut b| b.commit_from_file(model_path))
            .map_err(|e| format!("세션 생성 ({model_path}): {e}"))?;
        Ok(Self { session: Mutex::new(session), _env: env })
    }
}

impl Estimator for Predictor {
    /// 배달 예상 시간(분)을 계산한다. 입력은 Python 구현과 같이 float32 로 바꿔 넣는다.
    fn estimate(&self, distance_km: f64, pending_orders: f64) -> Result<f64, String> {
        let input = Tensor::from_array(([1usize, 2], vec![distance_km as f32, pending_orders as f32]))
            .map_err(|e| e.to_string())?;
        let mut session = self.session.lock().map_err(|e| e.to_string())?;
        let outputs = session.run(ort::inputs!["X" => input]).map_err(|e| e.to_string())?;
        let (_, data) = outputs["variable"].try_extract_tensor::<f32>().map_err(|e| e.to_string())?;
        data.first().map(|&v| v as f64).ok_or_else(|| "빈 출력".to_string())
    }
}
