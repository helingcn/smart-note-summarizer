import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from config import BASE_DIR, FERNET_KEY_PATH


def _load_or_create_key(key_path: Path = FERNET_KEY_PATH) -> bytes:
    configured_key = os.getenv("SMARTDIGEST_FERNET_KEY")
    if configured_key:
        return configured_key.encode("utf-8")
    if key_path.exists():
        return key_path.read_bytes().strip()
    legacy_path = BASE_DIR / ".smartdigest.key"
    if legacy_path.exists() and legacy_path != key_path:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = legacy_path.read_bytes().strip()
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        return key
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_source(text: str) -> bytes:
    return _fernet.encrypt(text.encode("utf-8"))


def decrypt_source(payload: bytes) -> str:
    try:
        return _fernet.decrypt(payload).decode("utf-8")
    except InvalidToken as error:
        raise ValueError("Saklanan kaynak metnin şifresi çözülemedi.") from error
