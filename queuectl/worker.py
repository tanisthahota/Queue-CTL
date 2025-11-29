"""Worker process for executing jobs."""

import subprocess
import signal
import time
import sys
from typing import Optional
from .models import Job
from .queue import JobQueue
from .storage import Storage


class Worker:
    """Executes jobs from the queue."""

    def __init__(self, storage: Storage, worker_id: int = 1):
        self.storage = storage
        self.queue = JobQueue(storage)
        self.worker_id = worker_id
        self.running = True
        self.current_job: Optional[Job] = None

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal gracefully."""
        self.running = False
        if self.current_job:
            print(f"\n[Worker {self.worker_id}] Finishing current job {self.current_job.id}...")

    def run(self, poll_interval: float = 1.0) -> None:
        """Run the worker loop."""
        print(f"[Worker {self.worker_id}] Started")
        while self.running:
            try:
                job = self.queue.get_next_job()
                if job:
                    self._execute_job(job)
                else:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                self.running = False
            except Exception as e:
                print(f"[Worker {self.worker_id}] Error: {e}", file=sys.stderr)
                time.sleep(poll_interval)

        print(f"[Worker {self.worker_id}] Stopped")

    def _execute_job(self, job: Job) -> None:
        """Execute a single job."""
        lock_fd = self.storage.acquire_lock(job.id)
        if lock_fd is None:
            # Job is already being processed by another worker
            return

        try:
            self.current_job = job
            self.queue.mark_processing(job)
            print(f"[Worker {self.worker_id}] Processing job {job.id}: {job.command}")

            # Execute the command
            try:
                result = subprocess.run(
                    job.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                )

                if result.returncode == 0:
                    self.queue.mark_completed(job)
                    print(f"[Worker {self.worker_id}] Job {job.id} completed successfully")
                else:
                    error_msg = result.stderr or f"Exit code: {result.returncode}"
                    self.queue.mark_failed(job, error_msg)
                    print(
                        f"[Worker {self.worker_id}] Job {job.id} failed (attempt {job.attempts}): {error_msg}"
                    )

            except subprocess.TimeoutExpired:
                error_msg = "Command timeout (5 minutes)"
                self.queue.mark_failed(job, error_msg)
                print(f"[Worker {self.worker_id}] Job {job.id} timeout")
            except Exception as e:
                error_msg = str(e)
                self.queue.mark_failed(job, error_msg)
                print(f"[Worker {self.worker_id}] Job {job.id} error: {error_msg}")

        finally:
            self.current_job = None
            self.storage.release_lock(lock_fd)
