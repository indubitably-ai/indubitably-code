import pytest

from config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, load_anthropic_config


def test_load_config_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MAX_TOKENS", raising=False)

    cfg = load_anthropic_config()

    assert cfg.model == DEFAULT_MODEL
    assert cfg.max_tokens == DEFAULT_MAX_TOKENS


def test_load_config_honours_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "2048")

    cfg = load_anthropic_config()

    assert cfg.model == "claude-test"
    assert cfg.max_tokens == 2048


def test_load_config_invalid_tokens_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", " ")
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "not-an-int")

    cfg = load_anthropic_config()

    assert cfg.model == DEFAULT_MODEL
    assert cfg.max_tokens == DEFAULT_MAX_TOKENS
