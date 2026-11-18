import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import get_settings


def test_roundtrip_and_ciphertext_hides_plaintext():
    token = "vercel_pat_abc123XYZ"
    ciphertext = crypto.encrypt(token)
    assert token not in ciphertext
    assert crypto.decrypt(ciphertext) == token
    assert crypto.encrypt(token) != ciphertext  # fresh IV every time


def test_wrong_key_cannot_decrypt(env):
    ciphertext = crypto.encrypt("secret")
    env.setenv("OPSCEND_SECRET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    crypto._fernet.cache_clear()
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(ciphertext)


def test_passphrase_is_accepted_as_key(env):
    env.setenv("OPSCEND_SECRET_KEY", "not a fernet key, just a long passphrase")
    get_settings.cache_clear()
    crypto._fernet.cache_clear()
    assert crypto.decrypt(crypto.encrypt("secret")) == "secret"


def test_missing_key_falls_back_to_a_persisted_dev_key_with_a_warning(env, tmp_path, caplog):
    env.setenv("OPSCEND_SECRET_KEY", "")
    env.setattr(crypto, "DEV_KEY_FILE", tmp_path / "dev.key")
    get_settings.cache_clear()
    crypto._fernet.cache_clear()
    with caplog.at_level("WARNING"):
        ciphertext = crypto.encrypt("secret")
    assert "OPSCEND_SECRET_KEY is not set" in caplog.text
    crypto._fernet.cache_clear()
    assert crypto.decrypt(ciphertext) == "secret"  # same key read back from the file


def test_token_hint_shows_only_the_last_four():
    assert crypto.token_hint("vercel_pat_abc123XYZ") == "3XYZ"
    assert crypto.token_hint("short") == "****"
