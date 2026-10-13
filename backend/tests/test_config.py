import backend.config as config


def test_root_dotenv_is_loaded_without_overriding_process_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=fixture-key\nOPENAI_BASE_URL=https://fixture.invalid/v1\nOPENAI_MODEL=fixture-model\n"
    )
    monkeypatch.setenv("OPENAI_MODEL", "process-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    settings = config.Settings.from_env()
    assert settings.api_key == "fixture-key"
    assert settings.base_url == "https://fixture.invalid/v1"
    assert settings.model == "process-model"
    assert settings.max_model_calls == 24
    assert settings.task_timeout == 300
    assert settings.request_timeout == 90
