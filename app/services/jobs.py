from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable, Literal
from uuid import uuid4

from app.core.logging import AuditLogger
from app.models.domain import JobRun, JobStatus, utc_now


JobOperation = Literal["research", "architecture", "diagrams", "export"]
JobCallable = Callable[[str], str | None]


class JobManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="archway-job")
        self._jobs: dict[str, JobRun] = {}
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit(self, session_id: str, operation: JobOperation, work: JobCallable, message: str) -> JobRun:
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
            job = self._jobs[job_id]
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
            job = self._jobs[job_id]
            if job.status in {JobStatus.succeeded, JobStatus.failed}:
                return job.model_copy(deep=True)
            job.status = JobStatus.cancel_requested
            job.message = "Cancellation requested. Archway will stop before the next safe boundary."
            job.updated_at = utc_now()
            self._refresh_duration(job)
            future = self._futures.get(job_id)
        if future is not None:
            future.cancel()
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs[job_id].status == JobStatus.cancel_requested

    def _run(self, job_id: str, work: JobCallable) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.running
            job.started_at = utc_now()
            job.updated_at = job.started_at
            session_id = job.session_id
            operation = job.operation
        AuditLogger(session_id).event(operation, "job_started", job_id=job_id)
        try:
            result_path = work(job_id)
            with self._lock:
                job = self._jobs[job_id]
                if job.status == JobStatus.cancel_requested:
                    job.message = "Cancelled before completion."
                else:
                    job.status = JobStatus.succeeded
                    job.progress = 100
                    job.message = "Complete."
                    job.result_path = result_path
                job.completed_at = utc_now()
                job.updated_at = job.completed_at
                self._refresh_duration(job)
            AuditLogger(session_id).event(operation, "job_completed", job_id=job_id, result_path=result_path)
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.status = JobStatus.failed
                job.error = str(exc)
                job.message = "Archway hit an error while running this job. Diagnostics were recorded."
                job.completed_at = utc_now()
                job.updated_at = job.completed_at
                self._refresh_duration(job)
            AuditLogger(session_id).event(operation, "job_failed", job_id=job_id, error_type=type(exc).__name__)

    def _refresh_duration(self, job: JobRun) -> None:
        if job.started_at is None:
            job.duration_seconds = None
            return
        end = job.completed_at or utc_now()
        job.duration_seconds = max(0.0, round((end - job.started_at).total_seconds(), 3))


job_manager = JobManager()
