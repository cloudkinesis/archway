from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from typing import Callable, Literal
from uuid import uuid4

from app.core.config import get_settings
from app.core.logging import AuditLogger
from app.models.domain import JobRun, JobStatus, utc_now


JobOperation = Literal["research", "architecture", "diagrams", "export"]
JobCallable = Callable[[str], str | None]

# A job is terminal once it has reached one of these states; it no longer runs.
TERMINAL_STATUSES = {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}


class JobManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="archway-job")
        self._jobs: dict[str, JobRun] = {}
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit(self, session_id: str, operation: JobOperation, work: JobCallable, message: str) -> JobRun:
        # Opportunistic, lock-safe cleanup so terminal jobs do not accumulate.
        self.cleanup_expired_jobs()
        job = JobRun(
            id=f"job_{uuid4().hex[:12]}",
            session_id=session_id,
            operation=operation,
            status=JobStatus.queued,
            progress=0,
            message=message,
        )
        with self._lock:
            self._jobs[job.id] = job
        future = self._executor.submit(self._run, job.id, work)
        with self._lock:
            self._futures[job.id] = future
        AuditLogger(session_id).event(operation, "job_submitted", job_id=job.id)
        return self.get(job.id)

    def get(self, job_id: str) -> JobRun:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            self._refresh_duration(job)
            return job.model_copy(deep=True)

    def latest_for_session(self, session_id: str, operation: JobOperation) -> JobRun | None:
        self.cleanup_expired_jobs()
        with self._lock:
            matches = [
                job for job in self._jobs.values()
                if job.session_id == session_id and job.operation == operation
            ]
            matches.sort(key=lambda item: item.created_at, reverse=True)
            if matches:
                self._refresh_duration(matches[0])
            return matches[0].model_copy(deep=True) if matches else None

    def update(self, job_id: str, *, progress: int | None = None, message: str | None = None, result_path: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                # Never mutate progress/message of a terminal (or evicted) job.
                return
            if progress is not None:
                job.progress = max(0, min(100, progress))
            if message is not None:
                job.message = message
            if result_path is not None:
                job.result_path = result_path
            job.updated_at = utc_now()
            self._refresh_duration(job)

    def cancel(self, job_id: str) -> JobRun:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in TERMINAL_STATUSES:
                # Already terminal: honest no-op, do not flip to cancelled.
                job.cancellation_status = "already_terminal"
                job.updated_at = utc_now()
                return job.model_copy(deep=True)
            future = self._futures.get(job_id)
            job.cancellation_requested = True
            if job.cancellation_requested_at is None:
                job.cancellation_requested_at = utc_now()
            job.updated_at = utc_now()

        cancelled_before_start = future.cancel() if future is not None else False

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in TERMINAL_STATUSES:
                # The task finished between our checks; report honestly.
                pass
            elif cancelled_before_start:
                # The future had not started; cancellation is real and complete.
                job.status = JobStatus.cancelled
                job.cancellation_status = "accepted"
                job.message = "Cancelled before execution started."
                job.completed_at = utc_now()
                self._set_expiry(job)
            else:
                # The task is already running; we can only request cooperative stop.
                job.status = JobStatus.cancel_requested
                job.cancellation_status = "requested"
                job.message = "Cancellation requested; the task may continue until the next safe boundary."
            job.updated_at = utc_now()
            self._refresh_duration(job)
        return self.get(job_id)

    def is_cancellation_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return False
            return job.cancellation_requested or job.status == JobStatus.cancel_requested

    # Backwards-compatible alias used by long-running phase workers (e.g. diagrams).
    def should_cancel(self, job_id: str) -> bool:
        return self.is_cancellation_requested(job_id)

    def cleanup_expired_jobs(self, now: datetime | None = None) -> int:
        now = now or utc_now()
        removed = 0
        with self._lock:
            # 1) TTL eviction of terminal, expired jobs.
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in TERMINAL_STATUSES and job.expires_at is not None and job.expires_at <= now
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
                self._futures.pop(job_id, None)
                removed += 1

            # 2) Cap retained jobs: drop oldest terminal jobs first; never drop active ones.
            max_retained = max(1, get_settings().job_max_retained)
            if len(self._jobs) > max_retained:
                terminal = [
                    (job_id, job)
                    for job_id, job in self._jobs.items()
                    if job.status in TERMINAL_STATUSES
                ]
                terminal.sort(key=lambda item: item[1].completed_at or item[1].created_at)
                overflow = len(self._jobs) - max_retained
                for job_id, _job in terminal[:overflow]:
                    self._jobs.pop(job_id, None)
                    self._futures.pop(job_id, None)
                    removed += 1
        return removed

    def _run(self, job_id: str, work: JobCallable) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.status in TERMINAL_STATUSES:
                # Cancelled/cleaned up before we started; do not run.
                return
            if job.cancellation_requested:
                # Cancellation arrived before execution started: honor it cooperatively.
                job.status = JobStatus.cancelled
                job.cancellation_status = "completed"
                job.message = "Cancelled before execution started."
                job.completed_at = utc_now()
                job.updated_at = job.completed_at
                self._set_expiry(job)
                self._refresh_duration(job)
                session_id, operation = job.session_id, job.operation
                AuditLogger(session_id).event(operation, "job_cancelled", job_id=job_id)
                return
            job.status = JobStatus.running
            job.started_at = utc_now()
            job.updated_at = job.started_at
            session_id = job.session_id
            operation = job.operation
        AuditLogger(session_id).event(operation, "job_started", job_id=job_id)
        try:
            result_path = work(job_id)
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                if job.cancellation_requested:
                    # A cancellation was requested while running; the worker has now
                    # returned, so the job stops here rather than reporting success.
                    job.status = JobStatus.cancelled
                    job.cancellation_status = "completed"
                    job.message = "Cancelled before completion."
                else:
                    job.status = JobStatus.succeeded
                    job.progress = 100
                    job.message = "Complete."
                    job.result_path = result_path
                job.completed_at = utc_now()
                job.updated_at = job.completed_at
                self._set_expiry(job)
                self._refresh_duration(job)
            AuditLogger(session_id).event(operation, "job_completed", job_id=job_id, result_path=result_path)
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.status = JobStatus.failed
                job.error = str(exc)
                job.message = "Archway hit an error while running this job. Diagnostics were recorded."
                job.completed_at = utc_now()
                job.updated_at = job.completed_at
                self._set_expiry(job)
                self._refresh_duration(job)
            AuditLogger(session_id).event(operation, "job_failed", job_id=job_id, error_type=type(exc).__name__)

    def _set_expiry(self, job: JobRun) -> None:
        settings = get_settings()
        ttl = settings.job_completed_ttl_seconds if job.status == JobStatus.succeeded else settings.job_failed_ttl_seconds
        base = job.completed_at or utc_now()
        job.expires_at = base + timedelta(seconds=max(0, ttl))

    def _refresh_duration(self, job: JobRun) -> None:
        if job.started_at is None:
            job.duration_seconds = None
            return
        end = job.completed_at or utc_now()
        job.duration_seconds = max(0.0, round((end - job.started_at).total_seconds(), 3))


job_manager = JobManager()
