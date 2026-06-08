from time import sleep

from app.services.jobs import JobManager


def test_job_manager_runs_work_and_records_result():
    manager = JobManager()

    def work(job_id: str) -> str:
        manager.update(job_id, progress=50, message="Halfway")
        return "research/report.json"

    job = manager.submit("sess_test", "research", work, "Queued")

    for _ in range(30):
        current = manager.get(job.id)
        if current.status == "succeeded":
            break
        sleep(0.05)

    current = manager.get(job.id)
    assert current.status == "succeeded"
    assert current.progress == 100
    assert current.result_path == "research/report.json"
    assert current.duration_seconds is not None


def test_job_manager_records_failures():
    manager = JobManager()

    def work(_job_id: str) -> str:
        raise RuntimeError("boom")

    job = manager.submit("sess_test", "diagrams", work, "Queued")

    for _ in range(30):
        current = manager.get(job.id)
        if current.status == "failed":
            break
        sleep(0.05)

    current = manager.get(job.id)
    assert current.status == "failed"
    assert current.error == "boom"
    assert current.duration_seconds is not None
