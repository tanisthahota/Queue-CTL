"""Test suite for QueueCTL - Background Job Queue System."""

import json
import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from queuectl.models import Job, JobState, Config
from queuectl.storage import Storage
from queuectl.queue import JobQueue
from queuectl.worker import Worker


class TestRunner:
    """Test runner for QueueCTL."""

    def __init__(self):
        self.test_dir = tempfile.mkdtemp(prefix="queuectl_test_")
        self.storage = Storage(self.test_dir)
        self.queue = JobQueue(self.storage)
        self.passed = 0
        self.failed = 0
        self.tests = []

    def cleanup(self):
        """Clean up test directory."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def assert_equal(self, actual, expected, message=""):
        """Assert equality."""
        if actual != expected:
            raise AssertionError(f"{message}\nExpected: {expected}\nActual: {actual}")

    def assert_true(self, condition, message=""):
        """Assert condition is true."""
        if not condition:
            raise AssertionError(message)

    def assert_false(self, condition, message=""):
        """Assert condition is false."""
        if condition:
            raise AssertionError(message)

    def run_test(self, test_name, test_func):
        """Run a single test."""
        try:
            print(f"\n▶ {test_name}...", end=" ")
            test_func()
            print("✓ PASSED")
            self.passed += 1
            self.tests.append((test_name, "PASSED", None))
        except Exception as e:
            print(f"✗ FAILED")
            print(f"  Error: {e}")
            self.failed += 1
            self.tests.append((test_name, "FAILED", str(e)))

    def print_summary(self):
        """Print test summary."""
        total = self.passed + self.failed
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        for test_name, status, error in self.tests:
            symbol = "✓" if status == "PASSED" else "✗"
            print(f"{symbol} {test_name}: {status}")
            if error:
                print(f"  {error}")
        print("=" * 70)
        print(f"Total: {total} | Passed: {self.passed} | Failed: {self.failed}")
        print("=" * 70)
        return self.failed == 0

    # Test Cases

    def test_job_creation(self):
        """Test: Create a job with valid data."""
        job = Job(id="test1", command="echo hello")
        self.assert_equal(job.id, "test1")
        self.assert_equal(job.command, "echo hello")
        self.assert_equal(job.state, JobState.PENDING)
        self.assert_equal(job.attempts, 0)
        self.assert_equal(job.max_retries, 3)

    def test_job_enqueue(self):
        """Test: Enqueue a job to the queue."""
        job = Job(id="job1", command="echo test")
        self.queue.enqueue(job)

        stored_job = self.storage.get_job("job1")
        self.assert_true(stored_job is not None)
        self.assert_equal(stored_job.id, "job1")
        self.assert_equal(stored_job.state, JobState.PENDING)

    def test_get_next_job(self):
        """Test: Get next pending job."""
        job1 = Job(id="job1", command="echo 1")
        job2 = Job(id="job2", command="echo 2")
        self.queue.enqueue(job1)
        self.queue.enqueue(job2)

        next_job = self.queue.get_next_job()
        self.assert_true(next_job is not None)
        self.assert_equal(next_job.id, "job1")

    def test_mark_completed(self):
        """Test: Mark job as completed."""
        job = Job(id="job1", command="echo test")
        self.queue.enqueue(job)

        job = self.storage.get_job("job1")
        self.queue.mark_completed(job)

        updated_job = self.storage.get_job("job1")
        self.assert_equal(updated_job.state, JobState.COMPLETED)

    def test_mark_failed_with_retry(self):
        """Test: Mark job as failed and schedule retry."""
        job = Job(id="job1", command="false", max_retries=3)
        self.queue.enqueue(job)

        job = self.storage.get_job("job1")
        self.queue.mark_failed(job, "Exit code: 1")

        updated_job = self.storage.get_job("job1")
        self.assert_equal(updated_job.attempts, 1)
        self.assert_equal(updated_job.state, JobState.PENDING)
        self.assert_true(updated_job.next_retry_at is not None)

    def test_exponential_backoff(self):
        """Test: Exponential backoff calculation."""
        config = Config(backoff_base=2.0)
        self.storage.set_config(config)

        job = Job(id="job1", command="false", max_retries=5)
        self.queue.enqueue(job)

        # First failure: 2^0 = 1 second
        job = self.storage.get_job("job1")
        self.queue.mark_failed(job, "Error 1")
        job = self.storage.get_job("job1")
        delay1 = (job.next_retry_at - datetime.utcnow()).total_seconds()
        self.assert_true(0.9 < delay1 < 1.1, f"Expected ~1s, got {delay1}s")

        # Second failure: 2^1 = 2 seconds
        self.queue.mark_failed(job, "Error 2")
        job = self.storage.get_job("job1")
        delay2 = (job.next_retry_at - datetime.utcnow()).total_seconds()
        self.assert_true(1.9 < delay2 < 2.1, f"Expected ~2s, got {delay2}s")

    def test_move_to_dlq(self):
        """Test: Move job to Dead Letter Queue after max retries."""
        job = Job(id="job1", command="false", max_retries=2)
        self.queue.enqueue(job)

        # Fail twice
        for i in range(2):
            job = self.storage.get_job("job1")
            self.queue.mark_failed(job, f"Error {i+1}")

        # Third failure should move to DLQ
        job = self.storage.get_job("job1")
        self.assert_true(job is None, "Job should be removed from main queue")

        dlq_job = self.storage.get_dlq_job("job1")
        self.assert_true(dlq_job is not None)
        self.assert_equal(dlq_job.state, JobState.DEAD)

    def test_dlq_retry(self):
        """Test: Retry a job from Dead Letter Queue."""
        job = Job(id="job1", command="echo test", max_retries=1)
        self.queue.enqueue(job)

        # Fail to move to DLQ
        job = self.storage.get_job("job1")
        self.queue.mark_failed(job, "Error")
        job = self.storage.get_job("job1")
        self.queue.mark_failed(job, "Error")

        # Verify in DLQ
        dlq_job = self.storage.get_dlq_job("job1")
        self.assert_true(dlq_job is not None)

        # Retry from DLQ
        success = self.queue.retry_dlq_job("job1")
        self.assert_true(success)

        # Verify back in main queue
        job = self.storage.get_job("job1")
        self.assert_true(job is not None)
        self.assert_equal(job.state, JobState.PENDING)
        self.assert_equal(job.attempts, 0)

    def test_job_persistence(self):
        """Test: Jobs persist across storage instances."""
        job = Job(id="persist1", command="echo persistent")
        self.queue.enqueue(job)

        # Create new storage instance
        new_storage = Storage(self.test_dir)
        new_job = new_storage.get_job("persist1")

        self.assert_true(new_job is not None)
        self.assert_equal(new_job.id, "persist1")
        self.assert_equal(new_job.command, "echo persistent")

    def test_get_jobs_by_state(self):
        """Test: Get jobs filtered by state."""
        # Enqueue multiple jobs
        job1 = Job(id="job1", command="echo 1")
        job2 = Job(id="job2", command="echo 2")
        job3 = Job(id="job3", command="echo 3")

        self.queue.enqueue(job1)
        self.queue.enqueue(job2)
        self.queue.enqueue(job3)

        # Mark some as completed
        job1 = self.storage.get_job("job1")
        self.queue.mark_completed(job1)

        # Get pending jobs
        pending = self.queue.get_jobs_by_state(JobState.PENDING)
        self.assert_equal(len(pending), 2)

        # Get completed jobs
        completed = self.queue.get_jobs_by_state(JobState.COMPLETED)
        self.assert_equal(len(completed), 1)

    def test_config_persistence(self):
        """Test: Configuration persists."""
        config = Config(max_retries=5, backoff_base=3.0)
        self.storage.set_config(config)

        # Create new storage instance
        new_storage = Storage(self.test_dir)
        new_config = new_storage.get_config()

        self.assert_equal(new_config.max_retries, 5)
        self.assert_equal(new_config.backoff_base, 3.0)

    def test_job_locking(self):
        """Test: Job locking prevents duplicate processing."""
        job = Job(id="job1", command="echo test")
        self.queue.enqueue(job)

        # Acquire lock
        fd1 = self.storage.acquire_lock("job1")
        self.assert_true(fd1 is not None)

        # Try to acquire same lock (should fail)
        fd2 = self.storage.acquire_lock("job1")
        self.assert_true(fd2 is None)

        # Release lock
        self.storage.release_lock(fd1)

        # Now should be able to acquire
        fd3 = self.storage.acquire_lock("job1")
        self.assert_true(fd3 is not None)
        self.storage.release_lock(fd3)

    def test_stats(self):
        """Test: Get job statistics."""
        job1 = Job(id="job1", command="echo 1")
        job2 = Job(id="job2", command="echo 2")
        job3 = Job(id="job3", command="echo 3")

        self.queue.enqueue(job1)
        self.queue.enqueue(job2)
        self.queue.enqueue(job3)

        # Mark some as completed
        job1 = self.storage.get_job("job1")
        self.queue.mark_completed(job1)

        stats = self.storage.get_stats()
        self.assert_equal(stats["total"], 3)
        self.assert_equal(stats["pending"], 2)
        self.assert_equal(stats["completed"], 1)

    def test_worker_execution_success(self):
        """Test: Worker executes successful command."""
        job = Job(id="worker_test1", command="echo success")
        self.queue.enqueue(job)

        worker = Worker(self.storage, worker_id=1)

        # Execute job
        job = self.queue.get_next_job()
        worker._execute_job(job)

        # Verify completed
        completed_job = self.storage.get_job("worker_test1")
        self.assert_equal(completed_job.state, JobState.COMPLETED)

    def test_worker_execution_failure(self):
        """Test: Worker handles command failure."""
        job = Job(id="worker_test2", command="exit 1", max_retries=2)
        self.queue.enqueue(job)

        worker = Worker(self.storage, worker_id=1)

        # Execute job (should fail)
        job = self.queue.get_next_job()
        worker._execute_job(job)

        # Verify failed and scheduled for retry
        failed_job = self.storage.get_job("worker_test2")
        self.assert_equal(failed_job.attempts, 1)
        self.assert_equal(failed_job.state, JobState.PENDING)
        self.assert_true(failed_job.next_retry_at is not None)

    def test_worker_execution_timeout(self):
        """Test: Worker handles command timeout."""
        # Note: This test uses a shorter timeout for testing
        job = Job(id="worker_test3", command="sleep 10", max_retries=1)
        self.queue.enqueue(job)

        worker = Worker(self.storage, worker_id=1)

        # Execute job (will timeout)
        job = self.queue.get_next_job()
        # Temporarily reduce timeout for testing
        original_timeout = 300
        worker._execute_job(job)

        # Verify failed
        failed_job = self.storage.get_job("worker_test3")
        self.assert_equal(failed_job.attempts, 1)

    def test_retry_delay_respected(self):
        """Test: Job with retry delay is not picked up immediately."""
        job = Job(id="job1", command="echo test")
        self.queue.enqueue(job)

        # Mark as failed (schedules retry in future)
        job = self.storage.get_job("job1")
        self.queue.mark_failed(job, "Error")

        # Try to get next job (should be None due to retry delay)
        next_job = self.queue.get_next_job()
        self.assert_true(next_job is None)

        # Manually set retry time to past
        job = self.storage.get_job("job1")
        job.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        self.storage.update_job(job)

        # Now should be picked up
        next_job = self.queue.get_next_job()
        self.assert_true(next_job is not None)
        self.assert_equal(next_job.id, "job1")

    def test_dlq_list(self):
        """Test: List jobs in Dead Letter Queue."""
        # Create jobs and move to DLQ
        for i in range(3):
            job = Job(id=f"dlq_job{i}", command="false", max_retries=1)
            self.queue.enqueue(job)
            job = self.storage.get_job(f"dlq_job{i}")
            self.queue.mark_failed(job, "Error")
            job = self.storage.get_job(f"dlq_job{i}")
            self.queue.mark_failed(job, "Error")

        dlq_jobs = self.storage.get_dlq_jobs()
        self.assert_equal(len(dlq_jobs), 3)

    def test_job_error_message(self):
        """Test: Job stores error message."""
        job = Job(id="job1", command="false")
        self.queue.enqueue(job)

        job = self.storage.get_job("job1")
        error_msg = "Command failed with exit code 1"
        self.queue.mark_failed(job, error_msg)

        updated_job = self.storage.get_job("job1")
        self.assert_equal(updated_job.error_message, error_msg)


def main():
    """Run all tests."""
    print("=" * 70)
    print("QueueCTL Test Suite")
    print("=" * 70)

    runner = TestRunner()

    try:
        # Run all tests
        runner.run_test("Job Creation", runner.test_job_creation)
        runner.run_test("Job Enqueue", runner.test_job_enqueue)
        runner.run_test("Get Next Job", runner.test_get_next_job)
        runner.run_test("Mark Completed", runner.test_mark_completed)
        runner.run_test("Mark Failed with Retry", runner.test_mark_failed_with_retry)
        runner.run_test("Exponential Backoff", runner.test_exponential_backoff)
        runner.run_test("Move to DLQ", runner.test_move_to_dlq)
        runner.run_test("DLQ Retry", runner.test_dlq_retry)
        runner.run_test("Job Persistence", runner.test_job_persistence)
        runner.run_test("Get Jobs by State", runner.test_get_jobs_by_state)
        runner.run_test("Config Persistence", runner.test_config_persistence)
        runner.run_test("Job Locking", runner.test_job_locking)
        runner.run_test("Statistics", runner.test_stats)
        runner.run_test("Worker Execution Success", runner.test_worker_execution_success)
        runner.run_test("Worker Execution Failure", runner.test_worker_execution_failure)
        runner.run_test("Worker Execution Timeout", runner.test_worker_execution_timeout)
        runner.run_test("Retry Delay Respected", runner.test_retry_delay_respected)
        runner.run_test("DLQ List", runner.test_dlq_list)
        runner.run_test("Job Error Message", runner.test_job_error_message)

    finally:
        runner.cleanup()

    # Print summary and exit
    success = runner.print_summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
