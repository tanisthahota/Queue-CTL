"""CLI interface for queuectl."""

import click
import json
import os
import sys
from datetime import datetime
from typing import Optional
from pathlib import Path
from .models import Job, JobState, Config
from .storage import Storage
from .queue import JobQueue
from .worker import Worker
import multiprocessing


# Global storage instance
_storage: Optional[Storage] = None


def get_storage() -> Storage:
    """Get or create storage instance."""
    global _storage
    if _storage is None:
        data_dir = os.environ.get("QUEUECTL_DATA_DIR", ".queuectl")
        _storage = Storage(data_dir)
    return _storage


@click.group()
def cli():
    """QueueCTL - Background Job Queue System"""
    pass


@cli.command()
@click.argument("job_json")
def enqueue(job_json: str):
    """Enqueue a new job.

    Example:
        queuectl enqueue '{"id":"job1","command":"echo hello"}'
    """
    try:
        job_data = json.loads(job_json)
        job = Job(**job_data)
        storage = get_storage()
        queue = JobQueue(storage)
        queue.enqueue(job)
        click.echo(f"✓ Job {job.id} enqueued successfully")
    except json.JSONDecodeError as e:
        click.echo(f"✗ Invalid JSON: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cli.group()
def worker():
    """Manage worker processes"""
    pass


def _worker_process(worker_id: int):
    """Run a single worker process."""
    storage = get_storage()
    w = Worker(storage, worker_id)
    w.run()


@worker.command()
@click.option("--count", default=1, help="Number of workers to start")
def start(count: int):
    """Start one or more workers.

    Example:
        queuectl worker start --count 3
    """
    if count < 1:
        click.echo("✗ Count must be at least 1", err=True)
        sys.exit(1)

    click.echo(f"Starting {count} worker(s)...")

    processes = []
    try:
        for i in range(count):
            p = multiprocessing.Process(target=_worker_process, args=(i + 1,))
            p.start()
            processes.append(p)

        # Wait for all processes
        for p in processes:
            p.join()

    except KeyboardInterrupt:
        click.echo("\nShutting down workers...")
        for p in processes:
            if p.is_alive():
                p.terminate()
        for p in processes:
            p.join(timeout=5)
            if p.is_alive():
                p.kill()
        click.echo("Workers stopped")


@cli.command()
def status():
    """Show job queue status and statistics.

    Example:
        queuectl status
    """
    storage = get_storage()
    stats = storage.get_stats()
    config = storage.get_config()

    click.echo("\n" + "=" * 50)
    click.echo("QueueCTL Status")
    click.echo("=" * 50)
    click.echo(f"Total Jobs:     {stats['total']}")
    click.echo(f"  Pending:      {stats['pending']}")
    click.echo(f"  Processing:   {stats['processing']}")
    click.echo(f"  Completed:    {stats['completed']}")
    click.echo(f"  Failed:       {stats['failed']}")
    click.echo(f"  Dead (DLQ):   {stats['dead']}")
    click.echo("\nConfiguration:")
    click.echo(f"  Max Retries:  {config.max_retries}")
    click.echo(f"  Backoff Base: {config.backoff_base}")
    click.echo("=" * 50 + "\n")


@cli.command()
@click.option("--state", type=click.Choice(["pending", "processing", "completed", "failed"]), help="Filter by state")
@click.option("--limit", default=10, help="Maximum jobs to display")
def list(state: Optional[str], limit: int):
    """List jobs by state.

    Example:
        queuectl list --state pending
        queuectl list --state completed --limit 20
    """
    storage = get_storage()

    if state:
        jobs = storage.get_jobs_by_state(JobState(state))
    else:
        jobs = storage.get_all_jobs()

    jobs = jobs[:limit]

    if not jobs:
        click.echo("No jobs found")
        return

    click.echo(f"\n{'ID':<20} {'State':<12} {'Attempts':<10} {'Created':<20}")
    click.echo("-" * 62)
    for job in jobs:
        created = job.created_at.strftime("%Y-%m-%d %H:%M:%S") if isinstance(job.created_at, datetime) else str(job.created_at)
        click.echo(f"{job.id:<20} {job.state.value:<12} {job.attempts:<10} {created:<20}")
    click.echo()


@cli.group()
def dlq():
    """Manage Dead Letter Queue"""
    pass


@dlq.command()
@click.option("--limit", default=10, help="Maximum jobs to display")
def list(limit: int):
    """List jobs in the Dead Letter Queue.

    Example:
        queuectl dlq list
    """
    storage = get_storage()
    jobs = storage.get_dlq_jobs()[:limit]

    if not jobs:
        click.echo("Dead Letter Queue is empty")
        return

    click.echo(f"\n{'ID':<20} {'Command':<30} {'Attempts':<10} {'Error':<30}")
    click.echo("-" * 90)
    for job in jobs:
        error = (job.error_message or "")[:30]
        cmd = (job.command or "")[:30]
        click.echo(f"{job.id:<20} {cmd:<30} {job.attempts:<10} {error:<30}")
    click.echo()


@dlq.command()
@click.argument("job_id")
def retry(job_id: str):
    """Retry a job from the Dead Letter Queue.

    Example:
        queuectl dlq retry job1
    """
    storage = get_storage()
    queue = JobQueue(storage)

    if queue.retry_dlq_job(job_id):
        click.echo(f"✓ Job {job_id} moved back to queue for retry")
    else:
        click.echo(f"✗ Job {job_id} not found in Dead Letter Queue", err=True)
        sys.exit(1)


@cli.group()
def config():
    """Manage configuration"""
    pass


@config.command()
def show():
    """Show current configuration.

    Example:
        queuectl config show
    """
    storage = get_storage()
    cfg = storage.get_config()

    click.echo("\nCurrent Configuration:")
    click.echo(f"  max-retries:   {cfg.max_retries}")
    click.echo(f"  backoff-base:  {cfg.backoff_base}")
    click.echo(f"  backoff-max-delay: {cfg.backoff_max_delay} seconds")
    click.echo()


@config.command()
@click.argument("key")
@click.argument("value")
def set(key: str, value: str):
    """Set a configuration value.

    Example:
        queuectl config set max-retries 5
        queuectl config set backoff-base 3.0
    """
    storage = get_storage()
    cfg = storage.get_config()

    try:
        if key == "max-retries":
            cfg.max_retries = int(value)
        elif key == "backoff-base":
            cfg.backoff_base = float(value)
        elif key == "backoff-max-delay":
            cfg.backoff_max_delay = int(value)
        else:
            click.echo(f"✗ Unknown config key: {key}", err=True)
            sys.exit(1)

        storage.set_config(cfg)
        click.echo(f"✓ Configuration updated: {key} = {value}")
    except ValueError as e:
        click.echo(f"✗ Invalid value: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
