"""JobManager lifecycle hardening: TTL eviction, honest cancellation, and a
cancellation-check API. Deterministic unit tests using events/stubs.
"""

import threading
import time
from datetime import timedelta

from app.models.domain import JobRun, JobStatus, utc_now
from app.services.jobs import JobManager, TERMINAL_STATUSES


def _register(manager: JobManager, *, status: JobStatus, expires_in: float | None) -> JobRun:
    """Insert a synthetic job directly (white-box) for deterministic TTL tests."""
    now = utc_now()
    job = JobRun(
        id=f"job_{status.value}_{int(now.timestamp()*1000)%100000}",
        session_id="sess_test",
        operation="research",
        status=status,
        progress=100 if status == JobStatus.succeeded else 40,
        message="synthetic",
        started_at=now - timedelta(seconds=10),
        completed_at=now if status in TERMINAL_STATUSES else None,
        expires_at=(now + timedelta(seconds=expires_in)) if expires_in is not None else None,
    )
    with manager._lock:
        manager._jobs[job.id] = job
    return job


def _wait_terminal(manager: JobManager, job_id: str, timeout: float = 5.0) -> JobRun:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        time.sleep(0.02)
    return manager.get(job_id)


# Test 1 — completed jobs expire
def test_completed_jobs_expire_and_future_removed():
    manager = JobManager()
    job = _register(manager, status=JobStatus.succeeded, expires_in=-1)  # already expired
    manager._futures[job.id] = manager._executor.submit(lambda: None)
    removed = manager.cleanup_expired_jobs()
    assert removed == 1
    assert job.id not in manager._jobs
    assert job.id not in manager._futures


# Test 2 — running jobs do not expire
def test_running_jobs_do_not_expire():
    manager = JobManager()
    job = _register(manager, status=JobStatus.running, expires_in=None)
    # Force ancient timestamps; running jobs have no expires_at so must survive.
    with manager._lock:
        manager._jobs[job.id].updated_at = utc_now() - timedelta(days=2)
    assert manager.cleanup_expired_jobs() == 0
    assert job.id in manager._jobs


# Test 3 — failed/cancelled jobs expire
def test_failed_and_cancelled_jobs_expire():
    manager = JobManager()
    failed = _register(manager, status=JobStatus.failed, expires_in=-5)
    cancelled = _register(manager, status=JobStatus.cancelled, expires_in=-5)
    removed = manager.cleanup_expired_jobs()
    assert removed == 2
    assert failed.id not in manager._jobs
    assert cancelled.id not in manager._jobs


# Test 4 — cancellation requested for an already-running future is honest
def test_cancel_running_future_reports_cancel_requested_not_cancelled():
    manager = JobManager()
    started = threading.Event()
    release = threading.Event()

    def work(_job_id: str) -> str:
        started.set()
        release.wait(timeout=5)
        return "research/report.json"

    job = manager.submit("sess_test", "research", work, "Queued")
    assert started.wait(timeout=5), "work did not start"

    result = manager.cancel(job.id)
    # Future is already running: we must not claim hard cancellation.
    assert result.status == JobStatus.cancel_requested
    assert result.cancellation_requested is True
    assert result.cancellation_status == "requested"

    release.set()
    final = _wait_terminal(manager, job.id)
    # Once the worker returns, the job stops as cancelled (not succeeded).
    assert final.status == JobStatus.cancelled
    assert final.cancellation_status == "completed"


# Test 5 — future cancellation before start
def test_cancel_pending_future_before_start_marks_cancelled():
    manager = JobManager()
    release = threading.Event()
    started = [threading.Event(), threading.Event()]

    def blocker(index: int):
        def work(_job_id: str) -> str:
            started[index].set()
            release.wait(timeout=5)
            return "x"
        return work

    manager.submit("sess_test", "research", blocker(0), "Queued")
    manager.submit("sess_test", "research", blocker(1), "Queued")
    assert started[0].wait(timeout=5) and started[1].wait(timeout=5), "pool not saturated"

    pending = manager.submit("sess_test", "research", lambda _job_id: "y", "Queued")
    result = manager.cancel(pending.id)
    try:
        assert result.status == JobStatus.cancelled
        assert result.cancellation_status == "accepted"
    finally:
        release.set()


# Test 6 — terminal job cancel is an honest no-op
def test_cancel_terminal_job_is_already_terminal_noop():
    manager = JobManager()
    job = _register(manager, status=JobStatus.succeeded, expires_in=3600)
    result = manager.cancel(job.id)
    assert result.status == JobStatus.succeeded  # not flipped to cancelled
    assert result.cancellation_status == "already_terminal"
    assert result.cancellation_requested is False


# Test 7 — cancellation-check API
def test_is_cancellation_requested_api():
    manager = JobManager()
    requested = _register(manager, status=JobStatus.cancel_requested, expires_in=None)
    with manager._lock:
        manager._jobs[requested.id].cancellation_requested = True
    running = _register(manager, status=JobStatus.running, expires_in=None)
    terminal = _register(manager, status=JobStatus.cancelled, expires_in=3600)

    assert manager.is_cancellation_requested(requested.id) is True
    assert manager.should_cancel(requested.id) is True  # alias
    assert manager.is_cancellation_requested(running.id) is False
    assert manager.is_cancellation_requested(terminal.id) is False
    assert manager.is_cancellation_requested("does_not_exist") is False


# Test 8 — additive response compatibility
def test_jobrun_fields_are_additive_and_backward_compatible():
    manager = JobManager()

    def work(_job_id: str) -> str:
        return "ok"

    job = manager.submit("sess_test", "export", work, "Queued")
    final = _wait_terminal(manager, job.id)
    data = final.model_dump()
    # Existing fields remain.
    for field in ("id", "session_id", "operation", "status", "progress", "message", "duration_seconds", "error", "result_path", "created_at", "updated_at", "started_at", "completed_at"):
        assert field in data, f"missing existing field: {field}"
    # New additive fields exist.
    for field in ("expires_at", "cancellation_requested", "cancellation_requested_at", "cancellation_status"):
        assert field in data, f"missing additive field: {field}"
    assert final.status == JobStatus.succeeded
    assert final.progress == 100
    assert final.expires_at is not None


# Optional — max retained cap removes oldest terminal jobs first, keeps active ones
def test_max_retained_cap_evicts_oldest_terminal_first(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("ARCHWAY_JOB_MAX_RETAINED", "3")
    get_settings.cache_clear()
    try:
        manager = JobManager()
        # 4 terminal (succeeded) jobs with increasing completion time + 1 running.
        ids = []
        base = utc_now()
        for i in range(4):
            job = JobRun(id=f"job_term_{i}", session_id="s", operation="research", status=JobStatus.succeeded, message="x", completed_at=base + timedelta(seconds=i), expires_at=base + timedelta(hours=1))
            with manager._lock:
                manager._jobs[job.id] = job
            ids.append(job.id)
        running = JobRun(id="job_running", session_id="s", operation="research", status=JobStatus.running, message="x")
        with manager._lock:
            manager._jobs[running.id] = running

        removed = manager.cleanup_expired_jobs()
        # 5 jobs, cap 3 -> remove 2 oldest terminal; running must survive.
        assert removed == 2
        assert "job_running" in manager._jobs
        assert ids[0] not in manager._jobs and ids[1] not in manager._jobs
        assert ids[2] in manager._jobs and ids[3] in manager._jobs
    finally:
        get_settings.cache_clear()
