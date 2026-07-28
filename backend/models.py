from pydantic import BaseModel

class SummarizeRequest(BaseModel):
    text: str

class SummarizeResponse(BaseModel):
    summary: str

class HistoryItem(BaseModel):
    id: int
    original_text: str
    summary: str
    created_at: str