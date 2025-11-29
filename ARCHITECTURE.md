# QueueCTL Architecture

## System Overview

QueueCTL is a single-machine, file-based background job queue system designed for simplicity and reliability. It manages job execution with automatic retries, exponential backoff, and a Dead Letter Queue for permanently failed jobs.

## Core Components

### 1. Data Models (`models.py`)

#### `JobState` Enum
Defines the five states a job can be in:
- **PENDING** — Waiting for a worker to pick it up
- **PROCESSING** — Currently being executed by a worker
- **COMPLETED** — Successfully executed
- **FAILED** — Failed but retryable (intermediate state)
- **DEAD** — Permanently failed, moved to DLQ

#### `Job` Model
Represents a background job with validation:
```python
{
  "id": str,                    # Unique identifier
  "command": str,               # Shell command to execute
  "state": JobState,            # Current state
  "attempts": int,              # Number of execution attempts
  "max_retries": int,           # Max retry attempts (default: 3)
  "created_at": datetime,       # Creation timestamp
  "updated_at": datetime,       # Last update timestamp
  "next_retry_at": datetime,    # Scheduled retry time (exponential backoff)
  "error_message": str          # Last error message
}
```

#### `Config` Model
System configuration:
```python
{
  "max_retries": int,           # Default max retries (default: 3)
  "backoff_base": float,        # Exponential backoff base (default: 2.0)
  "backoff_max_delay": int      # Max delay between retries (default: 3600s)
}
```

### 2. Storage Layer (`storage.py`)

**Responsibility:** Persistent job storage with file-based locking.

#### Key Features
- **JSON-based persistence** — All data stored in JSON files for simplicity
- **Atomic writes** — Temporary file + rename pattern prevents corruption
- **File-based locking** — Uses `fcntl` for process-safe locks
- **Isolation** — Each job has its own lock file

#### Storage Structure
```
.queuectl/
├── jobs.json          # Main job queue (list of Job objects)
├── dlq.json           # Dead Letter Queue (list of failed Job objects)
├── config.json        # System configuration
└── locks/             # Process locks directory
    ├── job1.lock      # Lock for job1
    ├── job2.lock      # Lock for job2
    └── ...
```

#### Critical Methods
- `add_job(job)` — Add job to queue
- `update_job(job)` — Update existing job
- `get_job(job_id)` — Retrieve job by ID
- `get_jobs_by_state(state)` — Filter jobs by state
- `move_to_dlq(job)` — Move job from queue to DLQ
- `acquire_lock(job_id)` — Acquire exclusive lock (returns fd or None)
- `release_lock(fd)` — Release lock

### 3. Queue Management (`queue.py`)

**Responsibility:** Job lifecycle and state transitions.

#### Key Features
- **State machine** — Manages valid state transitions
- **Retry scheduling** — Calculates exponential backoff delays
- **DLQ management** — Moves permanently failed jobs

#### State Transitions
```
PENDING → PROCESSING → COMPLETED (success)
       ↓
       FAILED (if attempts < max_retries)
       ↓
       PENDING (with next_retry_at set)
       ↓
       PROCESSING → COMPLETED or FAILED
       ↓
       If attempts >= max_retries: DEAD (moved to DLQ)
```

#### Exponential Backoff Algorithm
```python
delay = min(backoff_base ^ (attempts - 1), backoff_max_delay)

Example (backoff_base=2.0, backoff_max_delay=3600):
- Attempt 1 fails: delay = 2^0 = 1 second
- Attempt 2 fails: delay = 2^1 = 2 seconds
- Attempt 3 fails: delay = 2^2 = 4 seconds
- Attempt 4 fails: delay = 2^3 = 8 seconds
- ...
- Attempt 12 fails: delay = 2^11 = 2048 seconds (capped at 3600)
```

### 4. Worker Process (`worker.py`)

**Responsibility:** Execute jobs from the queue.

#### Key Features
- **Process-based** — Each worker runs in its own process
- **Locking** — Acquires lock before processing to prevent duplicates
- **Timeout handling** — 5-minute timeout per job
- **Graceful shutdown** — Finishes current job before exiting
- **Signal handling** — Responds to SIGTERM and SIGINT

#### Execution Flow
```
1. Worker polls for next job (1s interval)
2. If job found:
   a. Acquire lock (fail if already locked)
   b. Mark job as PROCESSING
   c. Execute command via subprocess.run()
   d. Check exit code:
      - 0: Mark COMPLETED
      - Non-zero: Mark FAILED, schedule retry
   e. Release lock
3. Repeat
```

#### Error Handling
- **Command not found** — Caught as exception, treated as failure
- **Timeout** — Subprocess timeout after 5 minutes
- **Lock acquisition failure** — Job skipped (already being processed)

### 5. CLI Interface (`cli.py`)

**Responsibility:** User-facing commands via Click framework.

#### Command Groups

**`enqueue`** — Add jobs
```bash
queuectl enqueue '{"id":"job1","command":"echo hello"}'
```

**`worker`** — Manage workers
```bash
queuectl worker start --count 3
```

**`status`** — Show statistics
```bash
queuectl status
```

**`list`** — Query jobs
```bash
queuectl list --state pending --limit 10
```

**`dlq`** — Dead Letter Queue management
```bash
queuectl dlq list
queuectl dlq retry job1
```

**`config`** — Configuration management
```bash
queuectl config show
queuectl config set max-retries 5
```

## Concurrency & Safety

### Process Locking
- **Problem:** Multiple workers might pick up the same job
- **Solution:** File-based exclusive locks using `fcntl.flock()`
- **Implementation:** Each job has a lock file in `.queuectl/locks/`
- **Atomicity:** Lock acquisition is atomic; only one process succeeds

### Data Consistency
- **Problem:** Concurrent writes to JSON files could corrupt data
- **Solution:** Atomic writes using temporary files
- **Implementation:** Write to `.tmp` file, then rename (atomic on most filesystems)

### Job State Guarantees
- **Processing state** — Prevents duplicate processing via locking
- **Retry scheduling** — `next_retry_at` ensures jobs aren't retried too early
- **DLQ transition** — Jobs atomically moved from queue to DLQ

## Data Flow Diagrams

### Job Lifecycle
```
┌──────────────┐
│   ENQUEUE    │ → Job created in PENDING state
└──────────────┘
       ↓
┌──────────────────────────────┐
│ WORKER POLLS FOR NEXT JOB    │ → Checks PENDING jobs with no retry delay
└──────────────────────────────┘
       ↓
┌──────────────────────────────┐
│ ACQUIRE LOCK                 │ → Exclusive lock prevents duplicates
└──────────────────────────────┘
       ↓
┌──────────────────────────────┐
│ MARK PROCESSING              │ → Update job state
└──────────────────────────────┘
       ↓
┌──────────────────────────────┐
│ EXECUTE COMMAND              │ → Run shell command
└──────────────────────────────┘
       ↓
    ┌──────────────────────────────────────┐
    │ CHECK EXIT CODE                      │
    └──────────────────────────────────────┘
       ↓                              ↓
   SUCCESS (0)                   FAILURE (non-0)
       ↓                              ↓
┌──────────────────┐        ┌──────────────────────────┐
│ MARK COMPLETED   │        │ INCREMENT ATTEMPTS      │
└──────────────────┘        └──────────────────────────┘
       ↓                              ↓
   JOB DONE              ┌────────────────────────────┐
                         │ attempts < max_retries?    │
                         └────────────────────────────┘
                              ↓              ↓
                            YES             NO
                             ↓              ↓
                    ┌──────────────┐  ┌──────────────┐
                    │ SCHEDULE     │  │ MOVE TO DLQ  │
                    │ RETRY        │  │ (DEAD state) │
                    │ (exponential │  └──────────────┘
                    │  backoff)    │
                    └──────────────┘
                             ↓
                    ┌──────────────┐
                    │ MARK PENDING │
                    │ with delay   │
                    └──────────────┘
                             ↓
                    Back to WORKER POLLS
```

### Multi-Worker Coordination
```
Worker 1                    Worker 2                    Worker 3
   │                           │                           │
   ├─ Poll for job ────────────┼─ Poll for job ────────────┼─ Poll for job
   │                           │                           │
   ├─ Find job1 ───────────────┼─ Find job1 ───────────────┼─ Find job2
   │                           │                           │
   ├─ Try lock job1 ───────────┼─ Try lock job1 ───────────┼─ Try lock job2
   │  (SUCCESS)                │  (FAIL - locked)          │  (SUCCESS)
   │                           │                           │
   ├─ Execute job1 ────────────┼─ Skip, poll again ────────┼─ Execute job2
   │                           │                           │
   └─ Release lock ────────────┼─ Find job3 ───────────────┼─ Release lock
                               │                           │
                               ├─ Try lock job3 ───────────┼─ Poll again
                               │  (SUCCESS)                │
                               │                           │
                               ├─ Execute job3 ────────────┼─ Find job4
                               │                           │
                               └─ Release lock ────────────┼─ Try lock job4
                                                           │  (SUCCESS)
                                                           │
                                                           └─ Execute job4
```

## Scalability Considerations

### Current Limitations
- **Single machine only** — No distributed support
- **JSON storage** — Suitable for ~10k jobs; consider SQLite for larger scale
- **File-based locking** — Less efficient than database locks
- **Process-based workers** — Higher memory overhead than async workers

### Optimization Opportunities
1. **SQLite backend** — Replace JSON with SQLite for better performance
2. **Async workers** — Use asyncio instead of multiprocessing
3. **Distributed queue** — Add Redis/RabbitMQ support
4. **Batch processing** — Process multiple jobs per worker
5. **Job priorities** — Add priority queue support

## Testing Strategy

### Unit Tests
- Job creation and validation
- State transitions
- Exponential backoff calculation
- Storage persistence
- Job locking

### Integration Tests
- Worker execution (success/failure)
- Retry logic
- DLQ transitions
- Multi-worker coordination

### Manual Test Scenarios
1. Basic job success
2. Job failure and retry
3. Multiple workers processing in parallel
4. Job persistence across restarts
5. DLQ management and retry

## Security Considerations

### Current Approach
- **Shell execution** — Commands run with `shell=True`
- **No authentication** — Single-machine, local use
- **File permissions** — Relies on OS file permissions

### Recommendations
1. **Input validation** — Sanitize job commands before execution
2. **Sandboxing** — Consider containerization for untrusted commands
3. **Audit logging** — Log all job executions
4. **Access control** — Add authentication if exposing via API

## Performance Metrics

### Typical Performance
- **Job enqueue** — < 10ms
- **Job retrieval** — < 10ms
- **Lock acquisition** — < 1ms
- **Worker polling** — 1s interval (configurable)
- **Throughput** — Depends on job execution time and worker count

### Monitoring
- Job statistics (pending, processing, completed, failed, dead)
- Worker status
- Retry attempts and backoff delays
- Error messages and failure reasons

---

**Last Updated:** November 2025
