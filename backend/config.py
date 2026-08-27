import logging
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
load_dotenv(PROJECT_DIR / ".env")

DATA_DIR = (
    Path(os.getenv("SMARTDIGEST_DATA_DIR", str(PROJECT_DIR / ".smartdigest-data")))
    .expanduser()
    .resolve()
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = (
    Path(os.getenv("SMARTDIGEST_DB_PATH", str(DATA_DIR / "smartdigest.db"))).expanduser().resolve()
)
LOG_PATH = (
    Path(os.getenv("SMARTDIGEST_LOG_PATH", str(DATA_DIR / "smartdigest.log")))
    .expanduser()
    .resolve()
)
FERNET_KEY_PATH = (
    Path(os.getenv("SMARTDIGEST_FERNET_KEY_PATH", str(DATA_DIR / ".smartdigest.key")))
    .expanduser()
    .resolve()
)
JWT_SECRET_PATH = (
    Path(os.getenv("SMARTDIGEST_JWT_SECRET_PATH", str(DATA_DIR / ".smartdigest.jwt_secret")))
    .expanduser()
    .resolve()
)
RATE_LIMIT_PER_MINUTE = int(os.getenv("SMARTDIGEST_RATE_LIMIT_PER_MINUTE", "30"))
APP_ENV = os.getenv("SMARTDIGEST_ENV", "development").strip().lower()
REDIS_URL = os.getenv("SMARTDIGEST_REDIS_URL", "").strip()
TRUST_PROXY_HEADERS = os.getenv("SMARTDIGEST_TRUST_PROXY_HEADERS", "false").lower() == "true"
AUTH_IP_LIMIT_PER_5_MINUTES = int(os.getenv("SMARTDIGEST_AUTH_IP_LIMIT_PER_5_MINUTES", "30"))
GLOBAL_IP_LIMIT_PER_MINUTE = int(os.getenv("SMARTDIGEST_GLOBAL_IP_LIMIT_PER_MINUTE", "120"))
REQUIRE_EMAIL_VERIFICATION = (
    os.getenv(
        "SMARTDIGEST_REQUIRE_EMAIL_VERIFICATION",
        "true" if APP_ENV == "production" else "false",
    ).lower()
    == "true"
)
SMTP_HOST = os.getenv("SMARTDIGEST_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMARTDIGEST_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMARTDIGEST_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMARTDIGEST_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMARTDIGEST_SMTP_FROM", SMTP_USERNAME).strip()
SMTP_USE_TLS = os.getenv("SMARTDIGEST_SMTP_USE_TLS", "true").lower() == "true"
PUBLIC_APP_URL = os.getenv("SMARTDIGEST_PUBLIC_APP_URL", "http://127.0.0.1:8501").rstrip("/")
ADMIN_EMAILS = {
    value.strip().lower()
    for value in os.getenv("SMARTDIGEST_ADMIN_EMAILS", "").split(",")
    if value.strip()
}
if APP_ENV == "production":
    if not REDIS_URL:
        raise RuntimeError("Production ortamında SMARTDIGEST_REDIS_URL zorunludur.")
    if REQUIRE_EMAIL_VERIFICATION and not (SMTP_HOST and SMTP_FROM):
        raise RuntimeError(
            "E-posta doğrulaması açık production ortamında SMTP_HOST ve SMTP_FROM zorunludur."
        )
JOB_WORKERS = max(1, int(os.getenv("SMARTDIGEST_JOB_WORKERS", "2")))
JOB_TTL_HOURS = max(1, int(os.getenv("SMARTDIGEST_JOB_TTL_HOURS", "24")))
JOB_QUEUE_LIMIT = max(JOB_WORKERS, int(os.getenv("SMARTDIGEST_JOB_QUEUE_LIMIT", "50")))

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("smartdigest")
