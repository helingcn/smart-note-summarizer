from fastapi import FastAPI, UploadFile, File
import shutil
import os
from models import SummarizeRequest, SummarizeResponse, HistoryItem
from summarizer import summarize_long_text
from database import init_db, save_summary, get_history
from extractor import get_text

app = FastAPI()

init_db()

@app.post("/summarize")
def summarize(request: SummarizeRequest):
    summary = summarize_long_text(request.text)
    save_summary(request.text, summary)
    return SummarizeResponse(summary=summary)

@app.post("/extract")
def extract(file: UploadFile = File(...)):
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = get_text(file_path=file_path)
    os.remove(file_path)

    return {"text": text}

@app.get("/history")
def history():
    rows = get_history()
    return [
        HistoryItem(id=row[0], original_text=row[1], summary=row[2], created_at=row[3])
        for row in rows
    ]