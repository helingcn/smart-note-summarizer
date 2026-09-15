"""SQLite üzerinde kalıcı, birden fazla süreççe güvenle tüketilebilen iş kuyruğu."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import JOB_QUEUE_LIMIT, JOB_TTL_HOURS, JOB_WORKERS, logger
from database import (
    cancel_job_record,
    claim_next_job,
    connection,
    create_job_record,
    get_job_record,
    heartbeat_job,
    job_cancel_requested,
    purge_old_jobs_if_due,
    recover_interrupted_jobs,
    save_summary,
    update_job_record,
)
from models import SummarizeRequest
from semantic_verifier import verify_evidence_batch
from summarizer import build_summary_evidence, summarize_long_text


class QueueFullError(RuntimeError):
    pass


class JobCancelled(RuntimeError):
    pass


class JobManager:
    def __init__(self) -> None:
        self.worker_id = uuid.uuid4().hex
        self._executor = ThreadPoolExecutor(
            max_workers=JOB_WORKERS, thread_name_prefix="smartdigest-summary"
        )
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._slots = threading.BoundedSemaphore(JOB_WORKERS)
        recover_interrupted_jobs()
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="smartdigest-dispatcher", daemon=True
        )
        self._dispatcher.start()

    def submit(self, user_id: str, request: SummarizeRequest) -> dict:
        job_id = uuid.uuid4().hex
        try:
            create_job_record(job_id, user_id, request.model_dump_json(), JOB_QUEUE_LIMIT)
        except OverflowError as error:
            raise QueueFullError(str(error)) from error
        self._wake.set()
        return {"job_id": job_id, "status": "queued"}

    def _dispatch_loop(self) -> None:
        while not self._stopped.is_set():
            purge_old_jobs_if_due(JOB_TTL_HOURS)
            dispatched = False
            while self._slots.acquire(blocking=False):
                claimed = claim_next_job(self.worker_id)
                if claimed is None:
                    self._slots.release()
                    break
                job_id, payload = claimed
                try:
                    request = SummarizeRequest.model_validate_json(payload)
                except Exception as error:
                    update_job_record(
                        job_id,
                        status="failed",
                        progress=100,
                        message="İş kaydı okunamadı.",
                        error=str(error),
                        encrypted_request=None,
                    )
                    self._slots.release()
                    continue
                future = self._executor.submit(self._run, job_id, request)
                future.add_done_callback(self._worker_finished)
                dispatched = True
            if not dispatched:
                self._wake.wait(timeout=1)
                self._wake.clear()

    def _worker_finished(self, _future) -> None:
        self._slots.release()
        self._wake.set()

    def _run(self, job_id: str, request: SummarizeRequest) -> None:
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, heartbeat_stop),
            name=f"smartdigest-heartbeat-{job_id[:8]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            summary = summarize_long_text(
                request.text,
                verified=request.mode == "verified",
                length=request.length,
                on_progress=lambda percent, message: self._progress(job_id, percent, message),
            )
            update_job_record(job_id, progress=87, message="Kaynak kanıtları eşleştiriliyor…")
            evidence = build_summary_evidence(summary, request.text)
            if request.mode == "verified" and evidence:
                update_job_record(
                    job_id, progress=89, message="Kanıtlar anlamsal olarak doğrulanıyor…"
                )
                evidence = verify_evidence_batch(evidence, request.text)
            if job_cancel_requested(job_id):
                update_job_record(
                    job_id,
                    status="cancelled",
                    progress=100,
                    message="İşlem iptal edildi; sonuç kaydedilmedi.",
                    encrypted_request=None,
                )
                return
            update_job_record(job_id, progress=92, message="Sonuç güvenli biçimde kaydediliyor.")
            with connection() as conn:
                row = conn.execute(
                    "SELECT user_id FROM summary_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
            if row is None:
                raise RuntimeError("İş kaydı bulunamadı.")
            save_summary(
                user_id=row["user_id"],
                summary=summary,
                source_text=request.text if request.retain_source else None,
                retention_days=request.retention_days if request.retain_source else None,
            )
            update_job_record(
                job_id,
                status="succeeded",
                progress=100,
                message="Özet hazır.",
                summary=summary,
                evidence=evidence,
                encrypted_request=None,
            )
        except JobCancelled:
            update_job_record(
                job_id,
                status="cancelled",
                progress=100,
                message="İşlem iptal edildi; sonuç kaydedilmedi.",
                encrypted_request=None,
            )
        except Exception as error:
            logger.exception("Özetleme işi başarısız oldu: %s", job_id)
            update_job_record(
                job_id,
                status="failed",
                progress=100,
                message="Özetleme tamamlanamadı.",
                error=str(error),
                encrypted_request=None,
            )
        finally:
            heartbeat_stop.set()

    def _progress(self, job_id: str, percent: int, message: str) -> None:
        if job_cancel_requested(job_id):
            raise JobCancelled()
        update_job_record(job_id, progress=percent, message=message)

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(30):
            if not heartbeat_job(job_id, self.worker_id):
                return

    def get(self, user_id: str, job_id: str) -> dict | None:
        purge_old_jobs_if_due(JOB_TTL_HOURS)
        return get_job_record(user_id, job_id)

    def cancel(self, user_id: str, job_id: str) -> bool:
        cancelled = cancel_job_record(user_id, job_id)
        if cancelled:
            self._wake.set()
        return cancelled


job_manager = JobManager()
