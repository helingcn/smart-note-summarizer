import os
import tempfile

from auth import (
    DUMMY_PASSWORD_HASH,
    Principal,
    auth_rate_limiter,
    create_access_token,
    distributed_rate_limiter,
    hash_password,
    rate_limiter,
    require_admin,
    require_principal,
    verify_password,
)
from config import ADMIN_EMAILS, APP_ENV, REQUIRE_EMAIL_VERIFICATION, logger
from database import (
    clear_history,
    create_account_token,
    create_user,
    delete_summary,
    delete_user_account,
    get_history,
    get_summary_source,
    get_user_by_email,
    list_users,
    reset_password_with_token,
    revoke_all_sessions,
    set_user_disabled,
    update_password,
    verify_email_token,
)
from extractor import PDFValidationError, extract_pdf, ocr_available
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from google.genai.errors import ClientError
from job_manager import QueueFullError, job_manager
from mailer import send_password_reset_email, send_verification_email, smtp_configured
from models import (
    AdminUserStatusRequest,
    ChangePasswordRequest,
    ChatRequest,
    ChatResponse,
    DeleteAccountRequest,
    EmailRequest,
    HistoryItem,
    JobCreatedResponse,
    JobStatusResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SourceResponse,
    SummarizeRequest,
    TokenResponse,
    VerifyTokenRequest,
)
from pydantic import EmailStr, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from summarizer import answer_question

GEMINI_QUOTA_MESSAGE = (
    "Gemini API günlük/dakikalık kullanım sınırına ulaşıldı. Birkaç dakika sonra tekrar deneyin."
)
MAX_SUMMARY_INPUT_CHARS = 100_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MIN_PASSWORD_LENGTH = 8
_EMAIL_ADAPTER = TypeAdapter(EmailStr)

app = FastAPI(title="SmartDigest API", version="2.0.0")


@app.middleware("http")
async def global_rate_limit(request: Request, call_next):
    if request.url.path != "/health":
        await run_in_threadpool(distributed_rate_limiter.check_global_ip, request)
    return await call_next(request)


def _is_quota_error(error: Exception) -> bool:
    return isinstance(error, ClientError) and getattr(error, "code", None) == 429


def _validate_summary(request: SummarizeRequest) -> None:
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Özetlenecek metin boş olamaz.")
    if len(request.text) > MAX_SUMMARY_INPUT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Metin çok uzun (maks. {MAX_SUMMARY_INPUT_CHARS:,} karakter).",
        )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_email_format(email: str) -> None:
    # Elle yazılmış "@" not in email gibi zayıf bir kontrol yerine, Pydantic'in
    # RFC uyumlu EmailStr doğrulayıcısını kullanıyoruz; hatayı burada yakalayıp
    # projenin geri kalanıyla tutarlı, temiz bir 400 + Türkçe mesaja çeviriyoruz
    # (pydantic'in kendi ValidationError'ı FastAPI'de otomatik 422 üretirdi).
    try:
        _EMAIL_ADAPTER.validate_python(email)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail="Geçerli bir e-posta adresi girin.") from error


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request):
    email = _normalize_email(payload.email)
    # Kayıt, pahalı bir PBKDF2 hash hesaplatıyor; giriş denemeleriyle aynı sıkı
    # limiti uygulamazsak, kimliği doğrulanmamış biri sınırsız kayıt isteğiyle
    # sunucuya bedava CPU işi yaptırabilir (login'deki korumanın simetriği).
    auth_rate_limiter.check(Principal(user_id=email), "register")
    distributed_rate_limiter.check_auth(request, email, "register")
    _validate_email_format(email)
    if len(payload.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı."
        )
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Bu e-posta adresi zaten kayıtlı.")
    try:
        user_id = create_user(
            email,
            hash_password(payload.password),
            email_verified=not REQUIRE_EMAIL_VERIFICATION,
            role="admin" if email in ADMIN_EMAILS else "user",
        )
    except ValueError as error:
        # get_user_by_email kontrolüyle create_user arasında aynı e-postayla
        # yarışan ikinci bir istek olursa (TOCTOU), UNIQUE kısıtı burada patlar;
        # bunu çirkin bir 500 yerine aynı temiz 409 mesajına çeviriyoruz.
        raise HTTPException(status_code=409, detail=str(error)) from error
    role = "admin" if email in ADMIN_EMAILS else "user"
    email_verified = not REQUIRE_EMAIL_VERIFICATION
    development_token = None
    if REQUIRE_EMAIL_VERIFICATION:
        verification_token = create_account_token(user_id, "verify_email", 24 * 60)
        send_verification_email(email, verification_token)
        if APP_ENV != "production" and not smtp_configured():
            development_token = verification_token
    logger.info("Yeni kullanıcı kaydı: %s", email)
    return TokenResponse(
        access_token=create_access_token(email, 0, role),
        email=email,
        email_verified=email_verified,
        verification_required=REQUIRE_EMAIL_VERIFICATION and not email_verified,
        development_token=development_token,
        role=role,
    )


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request):
    email = _normalize_email(payload.email)
    auth_rate_limiter.check(Principal(user_id=email), "login")
    distributed_rate_limiter.check_auth(request, email, "login")
    user = get_user_by_email(email)
    # Kullanıcı bulunamasa bile aynı maliyetli hesaplamayı çalıştırıyoruz; aksi
    # hâlde yanıt süresi farkı hangi e-postaların kayıtlı olduğunu sızdırır.
    password_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
    password_ok = verify_password(payload.password, password_hash)
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı.")
    if user["disabled"]:
        raise HTTPException(status_code=403, detail="Hesap devre dışı bırakılmış.")
    if REQUIRE_EMAIL_VERIFICATION and not user["email_verified"]:
        raise HTTPException(status_code=403, detail="E-posta adresinizi doğrulamanız gerekiyor.")
    return TokenResponse(
        access_token=create_access_token(email, user["token_version"], user["role"]),
        email=email,
        email_verified=bool(user["email_verified"]),
        role=user["role"],
    )


@app.post("/auth/verify-email")
def verify_email(payload: VerifyTokenRequest):
    if not verify_email_token(payload.token):
        raise HTTPException(
            status_code=400, detail="Doğrulama bağlantısı geçersiz veya süresi dolmuş."
        )
    return {"status": "verified"}


@app.post("/auth/resend-verification")
def resend_verification(payload: EmailRequest, request: Request):
    email = _normalize_email(payload.email)
    distributed_rate_limiter.check_auth(request, email, "resend-verification")
    user = get_user_by_email(email)
    development_token = None
    if user and not user["email_verified"] and not user["disabled"]:
        token = create_account_token(user["id"], "verify_email", 24 * 60)
        send_verification_email(email, token)
        if APP_ENV != "production" and not smtp_configured():
            development_token = token
    return {
        "message": "Hesap uygunsa doğrulama e-postası gönderildi.",
        "development_token": development_token,
    }


@app.post("/auth/forgot-password")
def forgot_password(payload: EmailRequest, request: Request):
    email = _normalize_email(payload.email)
    distributed_rate_limiter.check_auth(request, email, "forgot-password")
    user = get_user_by_email(email)
    development_token = None
    if user and not user["disabled"]:
        token = create_account_token(user["id"], "reset_password", 30)
        send_password_reset_email(email, token)
        if APP_ENV != "production" and not smtp_configured():
            development_token = token
    return {
        "message": "Hesap uygunsa şifre sıfırlama e-postası gönderildi.",
        "development_token": development_token,
    }


@app.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest):
    if not reset_password_with_token(payload.token, hash_password(payload.new_password)):
        raise HTTPException(
            status_code=400, detail="Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş."
        )
    return {"status": "password-reset"}


@app.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    principal: Principal = Depends(require_principal),
):
    user = get_user_by_email(principal.user_id)
    if not user or not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Mevcut şifre hatalı.")
    update_password(user["id"], hash_password(payload.new_password))
    return {"status": "password-changed", "reauthenticate": True}


@app.post("/auth/logout-all")
def logout_all(principal: Principal = Depends(require_principal)):
    revoke_all_sessions(principal.database_id)
    return {"status": "sessions-revoked"}


@app.delete("/auth/account")
def delete_account(
    payload: DeleteAccountRequest,
    principal: Principal = Depends(require_principal),
):
    user = get_user_by_email(principal.user_id)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Şifre hatalı.")
    delete_user_account(user["id"])
    return {"status": "account-deleted"}


@app.get("/admin/users")
def admin_users(
    limit: int = Query(100, ge=1, le=500),
    principal: Principal = Depends(require_admin),
):
    return list_users(limit)


@app.patch("/admin/users/{user_id}")
def admin_set_user_status(
    user_id: int,
    payload: AdminUserStatusRequest,
    principal: Principal = Depends(require_admin),
):
    if principal.database_id == user_id and payload.disabled:
        raise HTTPException(
            status_code=400, detail="Kendi yönetici hesabınızı devre dışı bırakamazsınız."
        )
    if not set_user_disabled(user_id, payload.disabled):
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    return {"status": "updated"}


@app.get("/auth/me")
def me(principal: Principal = Depends(require_principal)):
    return {"email": principal.user_id, "role": principal.role}


@app.post("/jobs", response_model=JobCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: SummarizeRequest,
    principal: Principal = Depends(require_principal),
):
    rate_limiter.check(principal, "summarize")
    _validate_summary(request)
    try:
        job = job_manager.submit(principal.user_id, request)
    except QueueFullError as error:
        raise HTTPException(
            status_code=503,
            detail="Özetleme kuyruğu şu anda dolu. Lütfen daha sonra tekrar deneyin.",
            headers={"Retry-After": "30"},
        ) from error
    logger.info("Özetleme işi oluşturuldu: %s kullanıcı=%s", job["job_id"], principal.user_id)
    return JobCreatedResponse(**job)


@app.post(
    "/summarize",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
)
def summarize_alias(
    request: SummarizeRequest,
    principal: Principal = Depends(require_principal),
):
    """Geriye uyumlu yol; artık beklemek yerine bir arka plan işi oluşturur."""
    return create_job(request, principal)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str, principal: Principal = Depends(require_principal)):
    job = job_manager.get(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="İş bulunamadı.")
    if job["status"] == "failed" and job.get("error"):
        # Dahili hata ayrıntısını API tüketicisine sızdırmayalım.
        if "429" in job["error"] or "RESOURCE_EXHAUSTED" in job["error"]:
            job["error"] = GEMINI_QUOTA_MESSAGE
        else:
            job["error"] = "Özetleme sırasında bir hata oluştu."
    return JobStatusResponse(**job)


@app.delete("/jobs/{job_id}")
def cancel_job(job_id: str, principal: Principal = Depends(require_principal)):
    rate_limiter.check(principal, "job-cancel")
    if not job_manager.cancel(principal.user_id, job_id):
        raise HTTPException(status_code=404, detail="İptal edilebilir iş bulunamadı.")
    return {"status": "cancellation-requested"}


@app.post("/chat", response_model=ChatResponse)
def chat_with_document(
    request: ChatRequest,
    principal: Principal = Depends(require_principal),
):
    rate_limiter.check(principal, "chat")
    if not request.text.strip() or not request.question.strip():
        raise HTTPException(status_code=400, detail="Belge ve soru boş olamaz.")
    try:
        answer, sources = answer_question(request.text, request.question)
        return ChatResponse(answer=answer, sources=sources)
    except Exception as error:
        logger.error("Belge sohbeti sırasında hata: %s", error)
        if _is_quota_error(error):
            raise HTTPException(status_code=429, detail=GEMINI_QUOTA_MESSAGE) from error
        raise HTTPException(
            status_code=500, detail="Belge sorusu yanıtlanırken bir hata oluştu."
        ) from error


@app.post("/extract")
def extract(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_principal),
):
    rate_limiter.check(principal, "extract")
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sadece PDF dosyaları desteklenir.")
    if file.content_type not in {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=400, detail="Dosyanın MIME türü PDF değil.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file_path = tmp.name
        total = 0
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                tmp.close()
                os.remove(file_path)
                raise HTTPException(status_code=413, detail="PDF en fazla 20 MB olabilir.")
            tmp.write(chunk)

    try:
        document = extract_pdf(file_path)
        if not document.text.strip():
            ocr_note = "" if ocr_available() else " OCR için Tesseract bileşeni kurulu değil."
            raise HTTPException(
                status_code=422,
                detail="PDF'ten metin çıkarılamadı. Dosya taranmış bir görüntü olabilir."
                + ocr_note,
            )
        return {
            "text": document.text,
            "pages": [
                {"page": page.page, "text": page.text, "method": page.method}
                for page in document.pages
            ],
            "page_count": document.page_count,
            "ocr_used": document.ocr_used,
        }
    except HTTPException:
        raise
    except (PDFValidationError, TimeoutError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.error("PDF işleme sırasında hata: %s", error)
        raise HTTPException(status_code=500, detail="PDF işlenirken bir hata oluştu.") from error
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.get("/history", response_model=list[HistoryItem])
def history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_principal),
):
    rate_limiter.check(principal, "history")
    return [HistoryItem(**row) for row in get_history(principal.user_id, limit, offset)]


@app.get("/history/{item_id}/source", response_model=SourceResponse)
def history_source(item_id: int, principal: Principal = Depends(require_principal)):
    rate_limiter.check(principal, "history-source")
    source = get_summary_source(principal.user_id, item_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Kaynak metin bulunamadı veya süresi doldu.")
    return SourceResponse(text=source)


@app.delete("/history/{item_id}")
def delete_history_item(item_id: int, principal: Principal = Depends(require_principal)):
    rate_limiter.check(principal, "history-delete")
    if not delete_summary(principal.user_id, item_id):
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")
    logger.info("Kayıt silindi: id=%s kullanıcı=%s", item_id, principal.user_id)
    return {"status": "deleted"}


@app.delete("/history")
def clear_user_history(principal: Principal = Depends(require_principal)):
    rate_limiter.check(principal, "history-clear")
    deleted = clear_history(principal.user_id)
    logger.info("Kullanıcı geçmişi temizlendi: kullanıcı=%s adet=%s", principal.user_id, deleted)
    return {"status": "cleared", "deleted": deleted}
