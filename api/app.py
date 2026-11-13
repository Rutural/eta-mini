import importlib
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# 어떤 방식의 API를 쓸 것인지를 외부에서 환경변수를 통해 주입
MODEL_IMPL = os.getenv("MODEL_IMPL", "rule")
estimate_delivery_minutes = importlib.import_module(f"api.predictors.{MODEL_IMPL}").estimate_delivery_minutes

class EtaRequest(BaseModel):
    """배달 예상 시간 요청"""
    # 모델이 더 많은 정보를 원하면 여기에 필드를 추가
    # 아래 ge=0 와 같은 조건들을 유효성 검사 룰을 지정 (validation rule)
    distance_km: float = Field(ge=0, description="가게에서 배달지까지 거리(km)")
    pending_orders: int = Field(ge=0, description="지금 밀려 있는 주문 수")

class EtaResponse(BaseModel):
    """배달 예상 시간 응답"""
    minutes: float
    model: str  # 어떤 구현체가 낸 예측인지 (장애 추적용)

app = FastAPI(title="delivery-eta")

INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>delivery-eta API</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; line-height: 1.6; color: #222; }
    code, pre { background: #f4f4f4; border-radius: 6px; }
    code { padding: 2px 6px; }
    pre { padding: 12px; overflow-x: auto; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
  </style>
</head>
<body>
  <h1>🛵 delivery-eta API</h1>
  <p>거리와 밀린 주문 수로 배달 예상 시간(분)을 계산하는 API입니다.</p>
  <p>현재 구현체: <code>{model}</code></p>

  <h2>엔드포인트</h2>
  <table>
    <tr><th>메서드</th><th>경로</th><th>설명</th></tr>
    <tr><td>GET</td><td><a href="/health">/health</a></td><td>서비스 상태와 구현체 이름</td></tr>
    <tr><td>POST</td><td>/eta</td><td>배달 예상 시간 계산</td></tr>
    <tr><td>GET</td><td><a href="/docs">/docs</a></td><td>Swagger 문서 (직접 호출해 보기)</td></tr>
  </table>

  <h2>요청 예시</h2>
<pre>POST /eta
{"distance_km": 2.0, "pending_orders": 1}

→ {"minutes": 18.0, "model": "{model}"}</pre>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """API 소개 페이지(HTML)를 돌려준다."""
    return INDEX_HTML.replace("{model}", MODEL_IMPL)

@app.get("/health")
def health() -> dict[str, str]:
    """서비스 상태와 현재 구현체 이름을 돌려준다."""
    return {"status": "ok", "model": MODEL_IMPL}

@app.post("/eta", response_model=EtaResponse)
def eta(req: EtaRequest) -> EtaResponse:
    """배달 예상 시간을 계산"""
    minutes = estimate_delivery_minutes(req.distance_km, req.pending_orders)
    return EtaResponse(minutes=minutes, model=MODEL_IMPL)

