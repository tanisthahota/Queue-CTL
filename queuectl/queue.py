"""Job queue management."""

from datetime import datetime, timedelta
from typing import Optional, List
from .models import Job, JobState
from .storage import Storage


class JobQueue:
    """Manages job queue operations."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def enqueue(self, job: Job) -> None:
        """Add a job to the queue."""
        job.state = JobState.PENDING
        job.created_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        self.storage.add_job(job)

    def get_next_job(self) -> Optional[Job]:
        """Get the next pending job ready to process."""
        pending_jobs = self.storage.get_jobs_by_state(JobState.PENDING)

        for job in pending_jobs:
            # Check if job is ready (no retry delay or delay has passed)
            if job.next_retry_at is None or job.next_retry_at <= datetime.utcnow():
                return job

        return None

    def mark_processing(self, job: Job) -> None:
        """Mark a job as currently processing."""
        job.state = JobState.PROCESSING
        job.updated_at = datetime.utcnow()
        self.storage.update_job(job)

    def mark_completed(self, job: Job) -> None:
        """Mark a job as successfully completed."""
        job.state = JobState.COMPLETED
        job.updated_at = datetime.utcnow()
        job.error_message = None
        self.storage.update_job(job)

    def mark_failed(self, job: Job, error_message: str) -> None:
        """Mark a job as failed and schedule retry if possible."""
        config = self.storage.get_config()
        job.attempts += 1
        job.error_message = error_message
        job.updated_at = datetime.utcnow()

        if job.attempts >= job.max_retries:
            # Move to DLQ
            self.storage.move_to_dlq(job)
        else:
            # Schedule retry with exponential backoff
            delay_seconds = min(
                config.backoff_base ** (job.attempts - 1),
                config.backoff_max_delay,
            )
            job.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
            job.state = JobState.PENDING
            self.storage.update_job(job)

    def retry_dlq_job(self, job_id: str) -> bool:
        """Retry a job from the DLQ."""
        job = self.storage.get_dlq_job(job_id)
        if not job:
            return False

        # Reset job for retry
        job.state = JobState.PENDING
        job.attempts = 0
        job.next_retry_at = None
        job.error_message = None
        job.updated_at = datetime.utcnow()

        # Remove from DLQ and add back to main queue
        self.storage.remove_from_dlq(job_id)
        self.storage.add_job(job)
        return True

    def get_jobs_by_state(self, state: JobState) -> List[Job]:
        """Get all jobs in a specific state."""
        return self.storage.get_jobs_by_state(state)

    def get_all_jobs(self) -> List[Job]:
        """Get all jobs."""
        return self.storage.get_all_jobs()

    def get_dlq_jobs(self) -> List[Job]:
        """Get all DLQ jobs."""
        return self.storage.get_dlq_jobs()
