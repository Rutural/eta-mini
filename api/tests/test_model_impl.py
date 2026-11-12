import importlib

import pytest
from fastapi.testclient import TestClient

import api.app as app_module


@pytest.fixture
def reload_app(monkeypatch):
    """MODEL_IMPL 을 바꿔 api.app 을 다시 import 하고, 끝나면 원래 설정으로 되돌린다."""
    def _reload(impl):
        monkeypatch.setenv("MODEL_IMPL", impl)
        return importlib.reload(app_module)

    yield _reload
    monkeypatch.undo()
    importlib.reload(app_module)


def test_model_impl_selects_implementation(reload_app):
    """MODEL_IMPL=rule 이면 /health 와 /eta 가 model=rule 을 알린다."""
    module = reload_app("rule")
    client = TestClient(module.app)
    assert client.get("/health").json()["model"] == "rule"
    res = client.post("/eta", json={"distance_km": 2.0, "pending_orders": 1})
    assert res.json() == {"minutes": 18.0, "model": "rule"}


def test_model_impl_unknown_module_fails_at_import(reload_app):
    """존재하지 않는 MODEL_IMPL 이면 시작(import) 시점에 바로 실패한다."""
    with pytest.raises(ModuleNotFoundError):
        reload_app("no_such_model")
