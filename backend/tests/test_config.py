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


def test_cost_prices_are_opt_in_environment_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("MODEL_INPUT_PRICE_CNY_PER_MILLION", raising=False)
    monkeypatch.delenv("MODEL_OUTPUT_PRICE_CNY_PER_MILLION", raising=False)
    assert config.Settings.from_env().input_price_cny_per_million is None
    monkeypatch.setenv("MODEL_INPUT_PRICE_CNY_PER_MILLION", "2")
    monkeypatch.setenv("MODEL_OUTPUT_PRICE_CNY_PER_MILLION", "8")
    settings = config.Settings.from_env()
    assert settings.input_price_cny_per_million == "2"
    assert settings.output_price_cny_per_million == "8"
