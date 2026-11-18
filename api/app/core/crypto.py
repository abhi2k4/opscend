"""Fernet encryption for provider tokens at rest.

The key comes from `OPSCEND_SECRET_KEY`. A proper Fernet key is used as is; any
other passphrase is stretched to one with SHA-256. With no key at all (local
development only) a random key is generated once and kept in a gitignored file,
with a loud warning, so a fresh checkout still boots.
"""

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import API_DIR, get_settings

log = logging.getLogger(__name__)

DEV_KEY_FILE = API_DIR / ".opscend_secret_key"


class DecryptionError(Exception):
    """The ciphertext was not produced with the current secret key."""


def _dev_key() -> str:
    if DEV_KEY_FILE.exists():
        return DEV_KEY_FILE.read_text().strip()
    key = Fernet.generate_key().decode()
    DEV_KEY_FILE.write_text(key)
    DEV_KEY_FILE.chmod(0o600)
    return key


def resolve_secret_key() -> str:
    """Return the configured secret, or a persisted development key with a warning."""
    configured = get_settings().secret_key
    if configured and configured.strip():
        return configured.strip()
    log.warning(
        "OPSCEND_SECRET_KEY is not set: using a generated development key stored in %s. "
        "Set OPSCEND_SECRET_KEY before storing real provider tokens.",
        DEV_KEY_FILE,
    )
    return _dev_key()


def _as_fernet_key(secret: str) -> bytes:
    try:
        Fernet(secret.encode())
        return secret.encode()
    except ValueError:
        return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


@lru_cache
def _fernet() -> Fernet:
    return Fernet(_as_fernet_key(resolve_secret_key()))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("stored secret cannot be decrypted with the current key") from exc


def token_hint(token: str) -> str:
    """Last four characters, the only part of a token the API ever returns."""
    return token[-4:] if len(token) >= 8 else "****"


def signing_key() -> bytes:
    """Key for session JWTs, derived so it differs from the encryption key."""
    return hashlib.sha256(b"opscend-session:" + resolve_secret_key().encode()).digest()
