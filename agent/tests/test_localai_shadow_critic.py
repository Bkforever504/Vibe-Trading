import pytest

from agent.src.providers.localai_shadow_critic import validate_localai_base_url


def test_localai_endpoint_is_loopback_only():
    assert validate_localai_base_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    for value in ("https://127.0.0.1:8080", "http://example.com:8080", "http://127.0.0.1:11434", "http://localhost:8080"):
        with pytest.raises(ValueError):
            validate_localai_base_url(value)
