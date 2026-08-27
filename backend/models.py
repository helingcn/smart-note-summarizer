from typing import Literal

from pydantic import BaseModel, Field

class SummarizeRequest(BaseModel):
    text: str = Field(max_length=100_000)
    mode: Literal["fast", "verified"] = "fast"
    length: Literal["balanced", "detailed"] = "balanced"
    retain_source: bool = False
    retention_days: Literal[1, 7, 30] = 7

class SummarizeResponse(BaseModel):
    summary: str


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str


class SummaryEvidence(BaseModel):
    claim: str
    page: int
    paragraph: int
    quote: str
    support: int
    status: Literal["supported", "review", "weak"]
    verification: Literal["lexical", "semantic"] = "lexical"
    confidence: float | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: int
    message: str
    summary: str | None = None
    evidence: list[SummaryEvidence] = Field(default_factory=list)
    error: str | None = None


class ChatRequest(BaseModel):
    text: str = Field(max_length=100_000)
    question: str = Field(max_length=2_000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

class HistoryItem(BaseModel):
    id: int
    summary: str
    created_at: str
    has_source: bool = False
    source_expires_at: str | None = None


class SourceResponse(BaseModel):
    text: str


class RegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    email_verified: bool = True
    verification_required: bool = False
    development_token: str | None = None
    role: str = "user"


class VerifyTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class EmailRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    password: str = Field(max_length=128)


class AdminUserStatusRequest(BaseModel):
    disabled: bool
