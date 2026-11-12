import pytest
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app, raise_server_exceptions=False)
JSON = {"Content-Type": "application/json"}

# ---------- / ----------

def test_index_returns_html():
    """/ 는 200 과 HTML 소개 페이지를 돌려준다."""
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "/eta" in res.text

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


# ---------- /health 구조 ----------

def test_health_has_exact_keys():
    """/health 응답 키는 정확히 status, model 두 개다."""
    assert set(client.get("/health").json()) == {"status", "model"}


def test_unknown_endpoint_returns_404():
    """없는 경로는 404 를 돌려준다."""
    assert client.get("/no-such-path").status_code == 404


# ---------- /eta 경계값·정밀도 ----------

def test_eta_just_below_zero_distance_returns_422():
    """0 바로 아래 거리(-0.0001)도 422 로 거부한다."""
    res = client.post("/eta", json={"distance_km": -0.0001, "pending_orders": 0})
    assert res.status_code == 422


def test_eta_negative_zero_distance_treated_as_zero():
    """-0.0 은 0 으로 취급되어 기본 시간 10분을 돌려준다."""
    res = client.post(
        "/eta", content='{"distance_km": -0.0, "pending_orders": 0}', headers=JSON
    )
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(10.0)


def test_eta_tiny_distance():
    """아주 작은 거리(1e-9)도 정밀도를 잃지 않고 계산한다."""
    res = client.post("/eta", json={"distance_km": 1e-9, "pending_orders": 0})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(10.0 + 3e-9, rel=1e-12)


def test_eta_huge_integer_orders():
    """거대한 정수 주문 수(10**30)도 거부하지 않고 공식대로 계산한다."""
    res = client.post("/eta", json={"distance_km": 0, "pending_orders": 10**30})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(2e30)


# ---------- /eta 비유한 값 (알려진 버그) ----------
# Python JSON 파서는 표준 밖의 NaN/Infinity 리터럴을 받아들인다.
# 계약상 minutes 는 숫자이므로 이런 입력은 422 여야 한다.
# 현재 앱은 500 또는 minutes=null 을 돌려주므로 xfail 로 기록한다.
# 앱이 고쳐지면 strict=True 때문에 XPASS → 실패하니, 그때 xfail 을 지운다.

@pytest.mark.xfail(strict=True, reason="버그: NaN 이 ge=0 검사를 통과해 응답 직렬화에서 500")
def test_eta_nan_distance_returns_422():
    """distance_km 가 NaN 이면 422 를 돌려준다."""
    res = client.post(
        "/eta", content='{"distance_km": NaN, "pending_orders": 0}', headers=JSON
    )
    assert res.status_code == 422


@pytest.mark.xfail(strict=True, reason="버그: Infinity 입력 시 200 + minutes=null")
def test_eta_infinite_distance_returns_422():
    """distance_km 가 Infinity 면 422 를 돌려준다."""
    res = client.post(
        "/eta", content='{"distance_km": Infinity, "pending_orders": 0}', headers=JSON
    )
    assert res.status_code == 422


@pytest.mark.xfail(strict=True, reason="버그: 3*1e308 이 inf 로 넘쳐 minutes=null")
def test_eta_overflowing_distance_never_returns_null_minutes():
    """계산이 넘칠 만큼 큰 거리여도 minutes 가 null 인 200 응답은 내지 않는다."""
    res = client.post("/eta", json={"distance_km": 1e308, "pending_orders": 0})
    assert not (res.status_code == 200 and res.json()["minutes"] is None)


# ---------- /eta 입력 타입 관대함 (현재 동작 고정) ----------
# 스펙이 아직 정해지지 않아 Pydantic 기본(lax) 동작을 그대로 기록한다.
# 스펙이 정해지면 기대값을 바꾼다.

def test_eta_numeric_strings_are_coerced():
    """[현재 동작] 숫자 문자열("2", "1")은 숫자로 변환되어 받아들여진다."""
    res = client.post("/eta", json={"distance_km": "2", "pending_orders": "1"})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(18.0)


def test_eta_booleans_are_coerced():
    """[현재 동작] true 는 1 로 변환되어 받아들여진다."""
    res = client.post("/eta", json={"distance_km": True, "pending_orders": True})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(15.0)


def test_eta_whole_float_orders_accepted():
    """[현재 동작] pending_orders 1.0 은 정수 1 로 받아들여진다."""
    res = client.post("/eta", json={"distance_km": 1, "pending_orders": 1.0})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(15.0)


def test_eta_extra_fields_ignored():
    """[현재 동작] 정의되지 않은 필드는 무시된다."""
    res = client.post("/eta", json={"distance_km": 1, "pending_orders": 0, "x": 1})
    assert res.status_code == 200
    assert res.json()["minutes"] == pytest.approx(13.0)


# ---------- /eta 요청 형식 ----------

@pytest.mark.parametrize(
    ("content", "headers"),
    [
        ('{"distance_km": 1,', JSON),                                   # 깨진 JSON
        ("[1, 2]", JSON),                                               # 객체가 아닌 본문
        ('{"distance_km": 1, "pending_orders": 0}', {"Content-Type": "text/plain"}),
    ],
    ids=["malformed-json", "array-body", "text-plain"],
)
def test_eta_bad_request_format_returns_422(content, headers):
    """깨진 JSON, 객체가 아닌 본문, JSON 이 아닌 Content-Type 은 422 를 돌려준다."""
    assert client.post("/eta", content=content, headers=headers).status_code == 422


def test_eta_422_body_points_to_missing_field():
    """422 응답 본문은 detail 목록이며, 누락된 필드 위치를 loc 로 알려 준다."""
    res = client.post("/eta", json={"pending_orders": 0})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, list) and detail
    assert all({"loc", "msg", "type"} <= set(err) for err in detail)
    assert ["body", "distance_km"] in [err["loc"] for err in detail]
