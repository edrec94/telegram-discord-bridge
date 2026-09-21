import pytest

from config import ConfigError, load_config

REQUIRED_VARS = [
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_CHANNEL",
    "DISCORD_WEBHOOK_URL",
]


def _set_all(monkeypatch, **overrides):
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "abc123hash",
        "TELEGRAM_CHANNEL": "somechannel",
        "DISCORD_WEBHOOK_URL": "https://example.com/webhook",
    }
    values.update(overrides)
    for key, val in values.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)


def test_load_config_success(monkeypatch):
    _set_all(monkeypatch)
    config = load_config()
    assert config.telegram_api_id == 123456
    assert config.telegram_api_hash == "abc123hash"
    assert config.telegram_channel == "somechannel"
    assert config.discord_webhook_url == "https://example.com/webhook"


@pytest.mark.parametrize("missing", REQUIRED_VARS)
def test_load_config_missing_var_raises(monkeypatch, missing):
    _set_all(monkeypatch, **{missing: None})
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_non_integer_api_id_raises(monkeypatch):
    _set_all(monkeypatch, TELEGRAM_API_ID="not-a-number")
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_blank_var_raises(monkeypatch):
    _set_all(monkeypatch, TELEGRAM_CHANNEL="   ")
    with pytest.raises(ConfigError):
        load_config()
