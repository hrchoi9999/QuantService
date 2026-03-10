import importlib

from service_platform.web.app import app


def test_home_endpoint_returns_service_metadata() -> None:
    client = app.test_client()
    response = client.get("/")

    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Under Construction" in body
    assert "QuantService" in body


def test_health_endpoint_returns_ok() -> None:
    client = app.test_client()
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "app_env": "development"}


def test_port_env_overrides_web_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("WEB_PORT", "8000")

    config_module = importlib.import_module("service_platform.shared.config")
    config_module = importlib.reload(config_module)

    assert config_module.get_settings().web_port == 9090
