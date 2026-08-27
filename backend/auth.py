import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from config import (
    APP_ENV,
    AUTH_IP_LIMIT_PER_5_MINUTES,
    BASE_DIR,
    GLOBAL_IP_LIMIT_PER_MINUTE,
    JWT_SECRET_PATH,
    RATE_LIMIT_PER_MINUTE,
    REDIS_URL,
    REQUIRE_EMAIL_VERIFICATION,
    TRUST_PROXY_HEADERS,
)
from fastapi import Depends, Header, HTTPException, Request, status

JWT_ALGORITHM = "HS256"
JWT_EXPIRES_HOURS = 24 * 7
PBKDF2_ITERATIONS = 210_000
HASH_ALGORITHM_LABEL = "pbkdf2_sha256"


def _load_or_create_jwt_secret() -> str:
    """Fernet anahtarıyla aynı desen: env'de yoksa diskte sakla, yoksa üret.
    Bu sayede her süreç yeniden başlatıldığında farklı bir anahtar üretilip
    var olan tüm oturumların (JWT'lerin) geçersiz kalması engellenir."""
    configured = os.getenv("SMARTDIGEST_JWT_SECRET")
    if configured:
        return configured
    if JWT_SECRET_PATH.exists():
        return JWT_SECRET_PATH.read_text().strip()
    legacy_path = BASE_DIR / ".smartdigest.jwt_secret"
    if legacy_path.exists() and legacy_path != JWT_SECRET_PATH:
        JWT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        secret = legacy_path.read_text().strip()
        JWT_SECRET_PATH.write_text(secret)
        JWT_SECRET_PATH.chmod(0o600)
        return secret
    JWT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32).hex()
    JWT_SECRET_PATH.write_text(secret)
    JWT_SECRET_PATH.chmod(0o600)
    return secret


JWT_SECRET = _load_or_create_jwt_secret()


@dataclass(frozen=True)
class Principal:
    user_id: str  # e-posta adresi
    database_id: int = 0
    role: str = "user"


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """`algoritma$iterasyon$salt$hash` biçiminde, kendi parametresini taşıyan bir
    hash üretir. PBKDF2_ITERATIONS ileride artırılırsa (ör. donanım hızlanınca),
    eski hash'ler kendi ürettikleri iterasyon sayısıyla doğrulanmaya devam eder;
    sabit bir değere gömülü olsaydı sabit değişince tüm şifreler doğrulanamaz
    hale gelirdi."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_ALGORITHM_LABEL}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = stored_hash.split("$")
    if len(parts) == 4 and parts[0] == HASH_ALGORITHM_LABEL:
        _, iterations_str, salt_hex, digest_hex = parts
        try:
            iterations = int(iterations_str)
            salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        except ValueError:
            return False
    elif ":" in stored_hash:
        # Sürüm alanı eklenmeden önce üretilmiş eski format (salt:hash); o an
        # geçerli olan sabit PBKDF2_ITERATIONS ile doğrulanır. Bu dal olmasaydı,
        # bu değişiklikten önce kayıt olmuş kullanıcılar bir daha giriş yapamazdı.
        try:
            salt_hex, digest_hex = stored_hash.split(":", 1)
            salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
            iterations = PBKDF2_ITERATIONS
        except ValueError:
            return False
    else:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


# Kullanıcı bulunamadığında bile login()'in aynı maliyetli PBKDF2 hesaplamasını
# çalıştırabilmesi için sabit bir "sahte" hash; aksi hâlde yanıt süresi farkı
# ("e-posta hiç yok" -> anında 401, "e-posta var, şifre yanlış" -> hash sonrası
# 401) hangi e-postaların kayıtlı olduğunu dışarıya sızdırırdı.
DUMMY_PASSWORD_HASH = hash_password("smartdigest-dummy-password-for-timing-safety")


def create_access_token(email: str, token_version: int = 0, role: str = "user") -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": email,
        "ver": token_version,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def require_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum açmanız gerekiyor."
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum süresi doldu, tekrar giriş yapın.",
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz oturum."
        ) from None
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz oturum.")
    from database import get_user_by_email

    user = get_user_by_email(email)
    if user is None or user["disabled"]:
        raise HTTPException(status_code=401, detail="Hesap kullanılamıyor.")
    if REQUIRE_EMAIL_VERIFICATION and not user["email_verified"]:
        raise HTTPException(status_code=403, detail="E-posta adresinizi doğrulamanız gerekiyor.")
    if int(payload.get("ver", -1)) != int(user["token_version"]):
        raise HTTPException(status_code=401, detail="Oturum geçersiz kılındı.")
    return Principal(user_id=email, database_id=int(user["id"]), role=str(user["role"]))


def require_admin(principal: Principal = Depends(require_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Yönetici yetkisi gerekiyor.")
    return principal


class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT_PER_MINUTE, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, principal: Principal, scope: str = "default") -> None:
        now = time.monotonic()
        key = f"{principal.user_id}:{scope}"
        with self._lock:
            timestamps = self._requests[key]
            while timestamps and now - timestamps[0] >= self.window_seconds:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - timestamps[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Çok fazla istek gönderildi. {retry_after} saniye sonra tekrar deneyin.",
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(now)


rate_limiter = RateLimiter()
# Genel API limitinden (dakikada RATE_LIMIT_PER_MINUTE) ayrı, çok daha sıkı bir
# limiter: hem giriş kaba kuvvetine hem de kayıt spam'ine karşı (ikisi de pahalı
# bir PBKDF2 hash hesaplatıyor), e-posta başına 5 dk'da 5 deneme. login/register
# "scope" parametresiyle ayrı sayaçlar tutuyor, aynı limiter paylaşılabiliyor.
auth_rate_limiter = RateLimiter(limit=5, window_seconds=300)


def client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


class DistributedRateLimiter:
    """Redis varsa süreçler arası, geliştirmede ise bellek içi sabit pencere limiti."""

    def __init__(self) -> None:
        self._local: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._redis = None
        if REDIS_URL:
            try:
                import redis

                self._redis = redis.Redis.from_url(
                    REDIS_URL, decode_responses=True, socket_connect_timeout=2
                )
                self._redis.ping()
            except Exception as error:
                if APP_ENV == "production":
                    raise RuntimeError(
                        "Production ortamında Redis bağlantısı zorunludur."
                    ) from error

    def check_key(self, key: str, limit: int, window_seconds: int) -> None:
        if self._redis is not None:
            bucket = int(time.time() // window_seconds)
            redis_key = f"smartdigest:rate:{key}:{bucket}"
            pipeline = self._redis.pipeline()
            pipeline.incr(redis_key)
            pipeline.expire(redis_key, window_seconds + 2)
            count, _ = pipeline.execute()
            if int(count) > limit:
                raise HTTPException(
                    status_code=429,
                    detail="Çok fazla istek gönderildi. Lütfen daha sonra tekrar deneyin.",
                    headers={"Retry-After": str(window_seconds)},
                )
            return
        now = time.monotonic()
        with self._lock:
            timestamps = self._local[key]
            while timestamps and now - timestamps[0] >= window_seconds:
                timestamps.popleft()
            if len(timestamps) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Çok fazla istek gönderildi. Lütfen daha sonra tekrar deneyin.",
                    headers={"Retry-After": str(window_seconds)},
                )
            timestamps.append(now)

    def check_global_ip(self, request: Request) -> None:
        self.check_key(f"global-ip:{client_ip(request)}", GLOBAL_IP_LIMIT_PER_MINUTE, 60)

    def check_auth(self, request: Request, account: str, scope: str) -> None:
        ip = client_ip(request)
        self.check_key(f"auth-ip:{scope}:{ip}", AUTH_IP_LIMIT_PER_5_MINUTES, 300)
        self.check_key(f"auth-account:{scope}:{account}", 5, 300)
        self.check_key(f"auth-global:{scope}", 300, 300)


distributed_rate_limiter = DistributedRateLimiter()
