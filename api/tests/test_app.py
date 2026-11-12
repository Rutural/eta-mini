import pytest
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


# ---------- /health ----------

def test_health_returns_ok_and_model_name():
    """/health 는 200 과 status=ok, 문자열 model 필드를 돌려준다."""
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert isinstance(body["model"], str) and body["model"]


# ---------- /eta 정상 입력 ----------

def test_eta_response_shape():
    """/eta 응답은 minutes(숫자)와 model(문자열) 두 필드만 가진다."""
    res = client.post("/eta", json={"distance_km": 2.0, "pending_orders": 1})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"minutes", "model"}
    assert isinstance(body["minutes"], (int, float))
    assert isinstance(body["model"], str)


def test_eta_model_matches_health():
    """/eta 의 model 값은 /health 가 알려 주는 구현체 이름과 같다."""
    health_model = client.get("/health").json()["model"]
    res = client.post("/eta", json={"distance_km": 1.0, "pending_orders": 0})
    assert res.json()["model"] == health_model


@pytest.mark.parametrize(
    ("distance_km", "pending_orders", "expected"),
    [
        (2.0, 1, 18.0),    # 10 + 3*2 + 2*1
        (5.0, 3, 31.0),    # 10 + 15 + 6
        (1.5, 0, 14.5),    # 소수 거리
    ],
)
def test_eta_known_values(distance_km, pending_orders, expected):
    """알려진 입력에 대해 rule 구현체의 예상값(10 + 3*km + 2*주문)을 돌려준다."""
    res = client.post(
        "/eta", json={"distance_km": distance_km, "pending_orders": pending_orders}
    )
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(expected)


def test_eta_integer_distance_accepted():
    """distance_km 에 정수를 보내도 받아들인다."""
    res = client.post("/eta", json={"distance_km": 3, "pending_orders": 0})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(19.0)


# ---------- /eta 경계값 ----------

def test_eta_zero_inputs_returns_base_time():
    """거리 0, 주문 0 이면 기본 시간 10분을 돌려준다."""
    res = client.post("/eta", json={"distance_km": 0, "pending_orders": 0})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(10.0)


def test_eta_large_values():
    """큰 값도 422 없이 처리하고 공식대로 계산한다."""
    res = client.post("/eta", json={"distance_km": 1000.0, "pending_orders": 10000})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(10.0 + 3000.0 + 20000.0)


def test_eta_increases_with_distance_and_orders():
    """거리나 대기 주문이 늘면 예상 시간도 늘어난다."""
    def minutes(d, p):
        return client.post("/eta", json={"distance_km": d, "pending_orders": p}).json()["minutes"]

    assert minutes(2.0, 0) > minutes(1.0, 0)
    assert minutes(1.0, 5) > minutes(1.0, 0)


# ---------- /eta 잘못된 입력 → 422 ----------

@pytest.mark.parametrize(
    "payload",
    [
        {"distance_km": -1.0, "pending_orders": 0},        # 음수 거리
        {"distance_km": 1.0, "pending_orders": -1},        # 음수 주문
        {"distance_km": "abc", "pending_orders": 0},       # 숫자가 아닌 거리
        {"distance_km": 1.0, "pending_orders": "many"},    # 숫자가 아닌 주문
        {"distance_km": 1.0, "pending_orders": 1.5},       # 정수가 아닌 주문
        {"distance_km": None, "pending_orders": 0},        # null
        {"pending_orders": 0},                             # distance_km 누락
        {"distance_km": 1.0},                              # pending_orders 누락
        {},                                                # 빈 본문
    ],
)
def test_eta_invalid_input_returns_422(payload):
    """음수·숫자 아님·누락 등 잘못된 입력은 422 를 돌려준다."""
    res = client.post("/eta", json=payload)
    assert res.status_code == 422


def test_eta_get_not_allowed():
    """/eta 는 POST 전용이라 GET 은 405 를 돌려준다."""
    res = client.get("/eta")
    assert res.status_code == 405
