from __future__ import annotations

from pathlib import Path

import pytest

from consenttrace.config import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMSettings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # setenv first so monkeypatch remembers the original state and also undoes
    # whatever load_dotenv writes into os.environ during the test
    for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "JUDGE_MODEL"):
        monkeypatch.setenv(var, "placeholder")
        monkeypatch.delenv(var)


def test_no_key_means_offline(tmp_path: Path) -> None:
    assert LLMSettings.from_env(tmp_path / "missing.env") is None


def test_reads_env_file_with_defaults(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=sk-from-file\n", encoding="utf-8")
    settings = LLMSettings.from_env(env)
    assert settings is not None
    assert (settings.base_url, settings.model, settings.api_key) == (DEFAULT_BASE_URL, DEFAULT_MODEL, "sk-from-file")


def test_process_env_wins_and_model_var_is_selectable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=sk-file\nLLM_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "sk-process")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")

    agent = LLMSettings.from_env(env)
    judge = LLMSettings.from_env(None, model_var="JUDGE_MODEL")

    assert agent is not None and agent.api_key == "sk-process" and agent.model == "from-file"
    assert judge is not None and judge.model == "judge-model" and judge.base_url == "https://example.invalid/v1"


def test_api_key_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret")
    settings = LLMSettings.from_env(None)
    assert settings is not None and "sk-super-secret" not in repr(settings)
