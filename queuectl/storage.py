"""Persistent job storage using JSON files."""

import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from .models import Job, JobState, Config

# Handle platform-specific locking
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class Storage:
    """File-based storage for jobs with locking."""

    def __init__(self, data_dir: str = ".queuectl"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.jobs_file = self.data_dir / "jobs.json"
        self.dlq_file = self.data_dir / "dlq.json"
        self.config_file = self.data_dir / "config.json"
        self.locks_dir = self.data_dir / "locks"
        self.locks_dir.mkdir(exist_ok=True)

        # Initialize files if they don't exist
        if not self.jobs_file.exists():
            self._write_json(self.jobs_file, [])
        if not self.dlq_file.exists():
            self._write_json(self.dlq_file, [])
        if not self.config_file.exists():
            default_config = Config()
            self._write_json(self.config_file, default_config.model_dump())

    def _write_json(self, file_path: Path, data: Any) -> None:
        """Write data to JSON file with atomic write."""
        temp_file = file_path.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
        temp_file.replace(file_path)

    def _read_json(self, file_path: Path) -> Any:
        """Read JSON file safely."""
        if not file_path.exists():
            return [] if file_path.name.endswith("s.json") else {}
        with open(file_path, "r") as f:
            return json.load(f)

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        jobs = self._read_json(self.jobs_file)
        for job_data in jobs:
            if job_data["id"] == job_id:
                return Job(**job_data)
        return None

    def add_job(self, job: Job) -> None:
        """Add a new job to the queue."""
        jobs = self._read_json(self.jobs_file)
        job_dict = job.model_dump(mode="json")
        jobs.append(job_dict)
        self._write_json(self.jobs_file, jobs)

    def update_job(self, job: Job) -> None:
        """Update an existing job."""
        jobs = self._read_json(self.jobs_file)
        for i, job_data in enumerate(jobs):
            if job_data["id"] == job.id:
                jobs[i] = job.model_dump(mode="json")
                self._write_json(self.jobs_file, jobs)
                return
        raise ValueError(f"Job {job.id} not found")

    def get_jobs_by_state(self, state: JobState) -> List[Job]:
        """Get all jobs in a specific state."""
        jobs = self._read_json(self.jobs_file)
        result = []
        for job_data in jobs:
            if job_data["state"] == state.value:
                result.append(Job(**job_data))
        return result

    def get_all_jobs(self) -> List[Job]:
        """Get all jobs."""
        jobs = self._read_json(self.jobs_file)
        return [Job(**job_data) for job_data in jobs]

    def move_to_dlq(self, job: Job) -> None:
        """Move a job to the Dead Letter Queue."""
        job.state = JobState.DEAD
        job.updated_at = datetime.utcnow()

        # Remove from main queue
        jobs = self._read_json(self.jobs_file)
        jobs = [j for j in jobs if j["id"] != job.id]
        self._write_json(self.jobs_file, jobs)

        # Add to DLQ
        dlq = self._read_json(self.dlq_file)
        dlq.append(job.model_dump(mode="json"))
        self._write_json(self.dlq_file, dlq)

    def get_dlq_jobs(self) -> List[Job]:
        """Get all jobs in the Dead Letter Queue."""
        dlq = self._read_json(self.dlq_file)
        return [Job(**job_data) for job_data in dlq]

    def get_dlq_job(self, job_id: str) -> Optional[Job]:
        """Get a specific DLQ job."""
        dlq = self._read_json(self.dlq_file)
        for job_data in dlq:
            if job_data["id"] == job_id:
                return Job(**job_data)
        return None

    def remove_from_dlq(self, job_id: str) -> None:
        """Remove a job from DLQ."""
        dlq = self._read_json(self.dlq_file)
        dlq = [j for j in dlq if j["id"] != job_id]
        self._write_json(self.dlq_file, dlq)

    def acquire_lock(self, job_id: str) -> Optional[int]:
        """Acquire a lock for a job. Returns lock file descriptor or None if locked."""
        lock_file = self.locks_dir / f"{job_id}.lock"
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_WRONLY, 0o644)
            if sys.platform == "win32":
                # Windows locking
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError:
                    os.close(fd)
                    return None
            else:
                # Unix locking
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except (IOError, OSError):
            return None

    def release_lock(self, fd: int) -> None:
        """Release a lock."""
        try:
            if sys.platform == "win32":
                # Windows unlocking
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                # Unix unlocking
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except (IOError, OSError):
            pass

    def get_config(self) -> Config:
        """Get current configuration."""
        config_data = self._read_json(self.config_file)
        return Config(**config_data)

    def set_config(self, config: Config) -> None:
        """Update configuration."""
        self._write_json(self.config_file, config.model_dump())

    def get_stats(self) -> Dict[str, int]:
        """Get job statistics."""
        jobs = self._read_json(self.jobs_file)
        dlq = self._read_json(self.dlq_file)

        stats = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "dead": 0,
            "total": len(jobs) + len(dlq),
        }

        for job in jobs:
            state = job.get("state", "pending")
            if state in stats:
                stats[state] += 1

        stats["dead"] = len(dlq)
        return stats
