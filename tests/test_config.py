import pytest

from app import config
from app.config import Settings


def _settings(**overrides):
    return Settings(_env_file=None, **overrides)


def test_live_feed_requires_credentials():
    with pytest.raises(ValueError, match="Live feed enabled"):
        _settings(
            use_live_feed=True,
            live_exchange="binance",
            live_symbol="BTC/USDT",
            live_api_key=None,
            live_api_secret="secret",
        )


def test_live_feed_passes_with_credentials():
    settings = _settings(
        use_live_feed=True,
        live_exchange="binance",
        live_symbol="BTC/USDT",
        live_api_key="abc",
        live_api_secret="def",
    )
    assert settings.use_live_feed is True


def test_ice_live_requires_all_fields():
    with pytest.raises(ValueError, match="Missing ICE config"):
        _settings(use_ice_live=True, ice_api_url=None)


def test_web3_loan_requires_credentials():
    with pytest.raises(ValueError, match="USE_WEB3_LOAN=1"):
        _settings(
            use_web3_loan=True,
            flash_loan_contract=None,
            receiver_address="0xabc",
            lender_private_key=None,
        )


def test_secret_backend_populates_missing_fields(monkeypatch):
    def fake_vault(addr, token, path):
        return {
            "LIVE_API_KEY": "vault-key",
            "LIVE_API_SECRET": "vault-secret",
        }

    monkeypatch.setattr(config, "_load_vault_secret", fake_vault)

    settings = _settings(
        use_live_feed=True,
        live_exchange="binance",
        live_symbol="BTC/USDT",
        live_api_key=None,
        live_api_secret=None,
        secrets_backend="vault",
        secrets_vault_addr="http://vault.local",
        secrets_vault_token="s.x",
        secrets_vault_path="secret/data/flash-green",
    )

    assert settings.live_api_key == "vault-key"
    assert settings.live_api_secret == "vault-secret"


def test_secret_backend_requires_config():
    with pytest.raises(ValueError, match="SECRETS_BACKEND=vault"):
        _settings(secrets_backend="vault")
