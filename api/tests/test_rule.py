import pytest

from api.predictors.rule import estimate_delivery_minutes


@pytest.mark.parametrize(
    ("distance_km", "pending_orders", "expected"),
    [
        (0, 0, 10.0),
        (2.0, 1, 18.0),
        (5.0, 3, 31.0),
        (1.5, 0, 14.5),
    ],
)
def test_rule_known_values(distance_km, pending_orders, expected):
    """rule 구현체를 직접 호출하면 10 + 3*km + 2*주문 을 돌려준다."""
    assert estimate_delivery_minutes(distance_km, pending_orders) == pytest.approx(expected)


def test_rule_returns_float():
    """정수 입력이어도 float 을 돌려준다."""
    assert isinstance(estimate_delivery_minutes(1, 1), float)
