from fastapi import FastAPI, UploadFile, File, HTTPException
import shutil
import os
from models import SummarizeRequest, SummarizeResponse, HistoryItem
from summarizer import summarize_long_text
from extractor import get_text
from database import init_db, save_summary, get_history, delete_summary
from config import logger

app = FastAPI()

init_db()

@app.post("/summarize")
def summarize(request: SummarizeRequest):
    if not request.text or not request.text.strip():
        logger.warning("Boş metin ile özetleme denendi.")
        raise HTTPException(status_code=400, detail="Özetlenecek metin boş olamaz.")

    try:
        summary = summarize_long_text(request.text)
        save_summary(request.text, summary)
        logger.info(f"Özetleme başarılı: {len(request.text)} karakter işlendi.")
        return SummarizeResponse(summary=summary)
    except Exception as e:
        logger.error(f"Özetleme sırasında hata: {e}")
        raise HTTPException(status_code=500, detail="Özetleme sırasında bir hata oluştu.")


@app.post("/extract")
def extract(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        logger.warning(f"Geçersiz dosya türü yüklendi: {file.filename}")
        raise HTTPException(status_code=400, detail="Sadece PDF dosyaları desteklenir.")

    file_path = f"temp_{file.filename}"

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        text = get_text(file_path=file_path)

        if not text or not text.strip():
            logger.warning(f"{file.filename} dosyasından metin çıkarılamadı.")
            raise HTTPException(status_code=422, detail="PDF'ten metin çıkarılamadı. Dosya taranmış bir görüntü olabilir.")

        logger.info(f"{file.filename} dosyasından {len(text)} karakter çıkarıldı.")
        return {"text": text}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PDF işleme sırasında hata: {e}")
        raise HTTPException(status_code=500, detail="PDF işlenirken bir hata oluştu.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.get("/history")
def history():
    try:
        rows = get_history()
        return [
            HistoryItem(id=row[0], original_text=row[1], summary=row[2], created_at=row[3])
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Geçmiş getirilirken hata: {e}")
        raise HTTPException(status_code=500, detail="Geçmiş getirilirken bir hata oluştu.")


@app.delete("/history/{item_id}")
def delete_history_item(item_id: int):
    try:
        delete_summary(item_id)
        logger.info(f"Kayıt silindi: id={item_id}")
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Kayıt silinirken hata: {e}")
        raise HTTPException(status_code=500, detail="Kayıt silinirken bir hata oluştu.")