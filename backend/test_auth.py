import database
from auth import hash_password, verify_password


def test_hash_password_roundtrips_with_verify():
    stored = hash_password("dogru-sifre-123")
    assert verify_password("dogru-sifre-123", stored) is True


def test_verify_password_rejects_wrong_password():
    stored = hash_password("dogru-sifre-123")
    assert verify_password("yanlis-sifre", stored) is False


def test_hash_password_encodes_iteration_count():
    stored = hash_password("sifre", iterations=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")


def test_verify_password_uses_encoded_iteration_count_not_current_default():
    # Hash'in kendi taşıdığı iterasyon sayısıyla doğrulanabildiğini kanıtlar;
    # PBKDF2_ITERATIONS ileride değişse bile eski hash'ler bozulmaz.
    stored = hash_password("sifre", iterations=1000)
    assert verify_password("sifre", stored) is True


def test_verify_password_accepts_legacy_colon_format():
    # Sürüm alanı eklenmeden önceki format (salt:hash); geriye dönük uyumluluk.
    legacy = hash_password("eski-sifre")
    salt_hex, digest_hex = legacy.split("$")[2], legacy.split("$")[3]
    legacy_stored = f"{salt_hex}:{digest_hex}"
    assert verify_password("eski-sifre", legacy_stored) is True
    assert verify_password("yanlis", legacy_stored) is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("herhangi", "bozuk-veri") is False
    assert verify_password("herhangi", "") is False


def test_account_token_is_single_use(tmp_path):
    db_path = tmp_path / "tokens.db"
    database.init_db(db_path)
    user_id = database.create_user(
        "token@example.com", hash_password("test1234"), db_path=db_path
    )
    token = database.create_account_token(user_id, "reset_password", 30, db_path)
    assert database.consume_account_token(token, "reset_password", db_path)["id"] == user_id
    assert database.consume_account_token(token, "reset_password", db_path) is None


def test_session_version_increments_when_password_changes(tmp_path):
    db_path = tmp_path / "sessions.db"
    database.init_db(db_path)
    user_id = database.create_user(
        "session@example.com", hash_password("test1234"), db_path=db_path
    )
    database.update_password(user_id, hash_password("yenisifre1"), db_path)
    assert database.get_user_by_email("session@example.com", db_path)["token_version"] == 1
