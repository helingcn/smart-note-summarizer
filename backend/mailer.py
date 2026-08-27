"""Hesap doğrulama ve şifre sıfırlama e-postaları."""

from email.message import EmailMessage
import smtplib

from config import (
    APP_ENV, PUBLIC_APP_URL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT,
    SMTP_USERNAME, SMTP_USE_TLS,
)


def smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def _send(to_email: str, subject: str, body: str) -> None:
    if not smtp_configured():
        if APP_ENV == "production":
            raise RuntimeError("Production ortamında SMTP yapılandırması zorunludur.")
        return
    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def send_verification_email(email: str, token: str) -> None:
    link = f"{PUBLIC_APP_URL}/?verify_token={token}"
    _send(
        email,
        "SmartDigest e-posta doğrulama",
        f"E-posta adresinizi doğrulamak için bağlantıyı açın:\n\n{link}\n\n"
        "Bu bağlantı 24 saat geçerlidir.",
    )


def send_password_reset_email(email: str, token: str) -> None:
    link = f"{PUBLIC_APP_URL}/?reset_token={token}"
    _send(
        email,
        "SmartDigest şifre sıfırlama",
        f"Şifrenizi sıfırlamak için bağlantıyı açın:\n\n{link}\n\n"
        "Bu bağlantı 30 dakika geçerlidir. İsteği siz yapmadıysanız dikkate almayın.",
    )
